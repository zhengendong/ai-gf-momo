"""Deterministic consistency checks for runtime state writeback."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..models.schemas import AgentOutput
from .business_knowledge import route_domains
from .outfit_state import (
    has_internal_conflict,
    normalize_outfit_tags,
    parse_outfit_tags,
    persistent_prompt_tags,
)
from .state import read_status
from .state import read_state_snapshot
from .wardrobe import normalize_wardrobe, reduce_wardrobe, wardrobe_from_tags

@dataclass
class MonitorResult:
    valid: bool
    issues: list[str]


OUTFIT_REQUEST_PATTERNS = (
    "去换",
    "换衣",
    "换一套",
    "换套",
    "穿",
    "脱",
    "裙",
    "袜",
    "鞋",
    "衣服",
    "吊带",
    "短裤",
    "睡裙",
)

SCENE_REQUEST_PATTERNS = (
    "去",
    "到",
    "回",
    "房间",
    "浴室",
    "卧室",
    "床上",
    "沙发",
)

COMPLETED_REPLY_PATTERNS = (
    "换好了",
    "换好啦",
    "换完了",
    "换完啦",
    "换回",
    "穿好了",
    "穿好啦",
    "脱掉了",
    "脱下",
    "摘掉",
    "戴上",
    "穿上",
    "穿回",
    "穿着",
    "又穿",
    "现在穿",
    "已经换",
    "已经穿",
    "已经脱",
    "没戴",
    "没有戴",
    "光脚",
    "赤脚",
    "到了",
)

VISUAL_FULFILLMENT_PATTERNS = (
    "给你看",
    "让你看",
    "让客人看",
    "好好看看",
    "看到了吗",
    "看清",
    "这样可以吗",
    "这样…可以吗",
    "展示给",
)

VISUAL_NON_FULFILLMENT_PATTERNS = (
    "不能给你看",
    "不想给你看",
    "不给你看",
    "还不能看",
    "还没准备好",
    "以后再给你看",
    "等会再给你看",
)


async def check_output_consistency(
    character: str,
    output: AgentOutput,
    user_message: str = "",
) -> MonitorResult:
    """Check whether an AgentOutput is consistent with status writeback."""
    local_issues = _local_consistency_issues(character, output, user_message)
    if local_issues:
        return MonitorResult(valid=False, issues=local_issues)
    return MonitorResult(valid=True, issues=[])


def _local_consistency_issues(
    character: str,
    output: AgentOutput,
    user_message: str = "",
) -> list[str]:
    """Deterministic checks for tool/status divergence that must never pass."""
    issues: list[str] = []
    requested_domains = set(route_domains(user_message, ""))
    visual_requested = "photography" in requested_domains
    persistent_change_requested = bool({"wardrobe", "scene"} & requested_domains)
    status_md = read_status(character)
    current_outfit = normalize_outfit_tags(_status_section_tags(status_md, "穿着"))
    updates_outfit = _state_update_section(output.state_updates, "穿着")
    updated_outfit = normalize_outfit_tags(parse_outfit_tags(updates_outfit)) if updates_outfit else []
    final_outfit = updated_outfit or current_outfit

    if output.state_ops:
        snapshot = read_state_snapshot(character)
        raw_wardrobe = snapshot.get("wardrobe")
        wardrobe = (
            normalize_wardrobe(raw_wardrobe)
            if isinstance(raw_wardrobe, dict)
            else wardrobe_from_tags(current_outfit)
        )
        try:
            reduce_wardrobe(wardrobe, output.state_ops)
        except (TypeError, ValueError) as exc:
            issues.append(f"state_ops cannot be applied safely: {exc}")
        for operation in output.state_ops:
            if not isinstance(operation, dict):
                continue
            domain = str(operation.get("domain") or "").strip().lower()
            action = str(operation.get("operation") or operation.get("type") or "").strip().lower()
            action = action.removeprefix(f"{domain}.") if domain else action
            if domain == "wardrobe":
                continue
            if domain == "scene" and action in {"replace", "update", "change"}:
                if not (operation.get("tags") or operation.get("scene_tags")):
                    issues.append("scene state operation requires complete tags.")
            elif domain == "mood" and action in {"set", "update", "change"}:
                if not (operation.get("value") or operation.get("tags")):
                    issues.append("mood state operation requires a value.")
            else:
                issues.append(f"unsupported state operation: {domain}.{action}")

    prompt_state_tags = sorted(persistent_prompt_tags(output.photo_prompt or ""))
    if prompt_state_tags:
        missing = [tag for tag in prompt_state_tags if tag not in set(final_outfit)]
        if missing:
            issues.append(
                "photo_prompt contains persistent outfit/body state tags not present in final status.穿着 "
                f"({', '.join(missing)}). Persistent tags such as barefoot/topless/bottomless/nude must "
                "come from the final outfit state. Add a complete state_updates.status.穿着 if the state "
                "changed, or remove those tags from photo_prompt."
            )

    if updates_outfit:
        raw_updated = parse_outfit_tags(updates_outfit)
        if _looks_like_partial_outfit_update(current_outfit, raw_updated):
            issues.append(
                "state_updates.status.穿着 looks partial. It must list the complete current outfit, "
                "not only the changed item."
            )
        if has_internal_conflict(raw_updated):
            issues.append(
                "state_updates.status.穿着 contains conflicting persistent outfit tags. For example, "
                "`barefoot` conflicts with shoes/socks/stockings, and `completely_nude` conflicts with "
                "ordinary clothes while accessories may remain."
            )

    # A pure follow-up such as "看看" may naturally restate an already
    # committed fact ("裙子已经脱了"). That is not a second state change. Keep
    # requiring operations when the current turn itself asks for wardrobe or
    # scene changes, including combined requests such as "脱掉给我看看".
    pure_visual_followup = visual_requested and not persistent_change_requested
    if (
        _reply_commits_state_change(output.reply)
        and not _has_status_updates(output)
        and not pure_visual_followup
    ):
        issues.append(
            "reply says a real outfit/scene/body state change has already happened, but state_updates.status "
            "is missing. Either add complete state_updates.status or rewrite reply so it does not claim the "
            "state has changed."
        )

    if output.image_goal is not None and not isinstance(output.image_goal, dict):
        issues.append("image_goal must be an object or null.")
    elif isinstance(output.image_goal, dict):
        if not str(output.image_goal.get("purpose") or "").strip():
            issues.append("image_goal requires a purpose.")
        if not str(output.image_goal.get("subject") or "").strip():
            issues.append("image_goal requires a subject.")

    legacy_image = bool(output.image_intent or output.photo_prompt)
    accepted_visual_delivery = bool(output.state_ops or output.effects) or _reply_commits_visual_delivery(output.reply)
    if visual_requested and accepted_visual_delivery and not (output.image_goal or legacy_image):
        issues.append(
            "the user explicitly requested a visual delivery and the reply/effects indicate fulfillment, "
            "but image_goal is missing. Add a semantic image_goal or rewrite the reply as not yet fulfilled."
        )

    return issues


def _status_section_tags(status_md: str, section: str) -> list[str]:
    match = re.search(rf"## {re.escape(section)}\n(.*?)(?=## |\Z)", status_md, re.DOTALL)
    if not match:
        return []
    return parse_outfit_tags(match.group(1))


def _state_update_section(state_updates: dict | None, section: str) -> Any:
    if not isinstance(state_updates, dict):
        return None
    status = state_updates.get("status")
    if not isinstance(status, dict):
        return None
    return status.get(section)


def _looks_like_partial_outfit_update(current_tags: list[str], updated_tags: list[str]) -> bool:
    if not current_tags or not updated_tags:
        return False
    explicit_nude = {"completely_nude", "nude", "naked", "bare_body"}
    if set(updated_tags) & explicit_nude:
        return False
    return len(current_tags) >= 4 and len(updated_tags) <= 2


def _has_status_updates(output: AgentOutput) -> bool:
    if output.state_ops:
        return True
    updates = output.state_updates
    if not isinstance(updates, dict):
        return False
    status = updates.get("status")
    return isinstance(status, dict) and any(str(v).strip() for v in status.values())


def _mentions_outfit(text: str) -> bool:
    return any(word in (text or "") for word in OUTFIT_REQUEST_PATTERNS)


def _mentions_scene(text: str) -> bool:
    return any(word in (text or "") for word in SCENE_REQUEST_PATTERNS)


def _mentions_outfit_or_scene(text: str) -> bool:
    return _mentions_outfit(text) or _mentions_scene(text)


def _reply_commits_state_change(reply: str) -> bool:
    text = reply or ""
    return any(word in text for word in COMPLETED_REPLY_PATTERNS) and _mentions_outfit_or_scene(text)


def _reply_commits_visual_delivery(reply: str) -> bool:
    text = reply or ""
    if any(pattern in text for pattern in VISUAL_NON_FULFILLMENT_PATTERNS):
        return False
    return any(pattern in text for pattern in VISUAL_FULFILLMENT_PATTERNS)
