"""Deterministic consistency checks for runtime state writeback."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..models.schemas import AgentOutput
from .outfit_state import (
    has_internal_conflict,
    normalize_outfit_tags,
    parse_outfit_tags,
    persistent_prompt_tags,
)
from .state import read_status

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


async def check_output_consistency(
    character: str,
    output: AgentOutput,
) -> MonitorResult:
    """Check whether an AgentOutput is consistent with status writeback."""
    local_issues = _local_consistency_issues(character, output)
    if local_issues:
        return MonitorResult(valid=False, issues=local_issues)
    return MonitorResult(valid=True, issues=[])


def _local_consistency_issues(character: str, output: AgentOutput) -> list[str]:
    """Deterministic checks for tool/status divergence that must never pass."""
    issues: list[str] = []
    status_md = read_status(character)
    current_outfit = normalize_outfit_tags(_status_section_tags(status_md, "穿着"))
    updates_outfit = _state_update_section(output.state_updates, "穿着")
    updated_outfit = normalize_outfit_tags(parse_outfit_tags(updates_outfit)) if updates_outfit else []
    final_outfit = updated_outfit or current_outfit

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

    if _reply_commits_state_change(output.reply) and not _has_status_updates(output):
        issues.append(
            "reply says a real outfit/scene/body state change has already happened, but state_updates.status "
            "is missing. Either add complete state_updates.status or rewrite reply so it does not claim the "
            "state has changed."
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
