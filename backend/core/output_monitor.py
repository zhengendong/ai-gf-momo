"""LLM-based output consistency checks for runtime state and plan writeback."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from ..models.schemas import AgentOutput
from .context import get_character_name, get_user_pet_name
from .outfit_state import (
    has_internal_conflict,
    normalize_outfit_tags,
    parse_outfit_tags,
    persistent_prompt_tags,
)
from .state import read_plans, read_status

logger = logging.getLogger(__name__)


@dataclass
class MonitorResult:
    valid: bool
    issues: list[str]
    needs_repair: bool = False


MONITOR_SYSTEM = """你是 AgentRuntime 的输出一致性监察器。
你的职责不是替角色做决定，也不是根据用户命令改状态。
你只检查角色本轮输出是否自洽：
- 用户请求本身不是状态事实。
- 角色拒绝、犹豫、询问、承诺稍后去做，不要求更新最终状态。
- 角色回复如果声称现实状态已经成立或已经发生，必须有相应 state_updates。
- 角色回复如果形成待执行目标、承诺稍后行动、等待用户选择，应有相应 plan_updates。
- photo_prompt 如果存在，必须与回复和最终状态意图一致。
- photo_prompt 中的持久穿着/身体状态 tag（barefoot/topless/bottomless/nude 等）必须存在于最终 status.穿着。
- 穿着和场景细节的状态更新必须是当前完整状态，而不是只写变化项。
只输出 JSON，不要输出解释文本。"""


REPAIR_SYSTEM = """你是 AgentRuntime 的输出修复器。
你要修复主 Agent 的 JSON 输出，让 reply、state_updates、plan_updates、photo_prompt 一致。
不要替角色服从用户命令；保持角色自主性。
如果原回复只是拒绝、犹豫、询问、准备稍后做，不要伪造已经完成的状态。
如果原回复声称某个现实状态已经成立或已经发生，就必须补齐对应 state_updates。
如果原回复形成待执行目标或承诺稍后行动，就必须补齐 plan_updates。
如果 photo_prompt 使用 barefoot/topless/bottomless/nude 等持久状态 tag，最终 status.穿着 必须包含这些 tag；否则修改 photo_prompt 或补齐完整 state_updates。
注意：脱鞋不等于 barefoot；仍穿袜子/过膝袜/丝袜时，不要写 barefoot。barefoot 表示脚部没有鞋也没有袜类覆盖。
如果无法安全补齐状态，可以修改 reply，让它不再声称已经完成。
只输出合法 JSON，不要输出 Markdown。"""


async def check_output_consistency(
    llm,
    character: str,
    user_message: str,
    output: AgentOutput,
) -> MonitorResult:
    """Check whether an AgentOutput is consistent with status/plans."""
    local_issues = _local_consistency_issues(character, output)
    if local_issues:
        return MonitorResult(valid=False, issues=local_issues, needs_repair=True)

    prompt = _build_monitor_prompt(character, user_message, output)
    try:
        raw = await llm.chat_prompt(
            system=MONITOR_SYSTEM,
            user=prompt,
            temperature=0.1,
            max_tokens=800,
        )
        data = _parse_json(raw)
        valid = bool(data.get("valid", True))
        issues = data.get("issues") or []
        if not isinstance(issues, list):
            issues = [str(issues)]
        return MonitorResult(
            valid=valid,
            issues=[str(i) for i in issues if str(i).strip()],
            needs_repair=bool(data.get("needs_repair", not valid)),
        )
    except Exception as e:
        logger.warning("Output monitor failed, allowing original output: %s", e)
        return MonitorResult(valid=True, issues=[], needs_repair=False)


async def repair_output_consistency(
    llm,
    character: str,
    user_message: str,
    output: AgentOutput,
    monitor_result: MonitorResult,
) -> AgentOutput:
    """Ask the LLM to repair an inconsistent output without changing autonomy."""
    prompt = _build_repair_prompt(character, user_message, output, monitor_result)
    raw = await llm.chat_prompt(
        system=REPAIR_SYSTEM,
        user=prompt,
        temperature=0.2,
        max_tokens=1800,
    )
    data = _parse_json(raw)
    return AgentOutput(
        reply=data.get("reply", output.reply),
        photo_prompt=data.get("photo_prompt"),
        state_updates=data.get("state_updates"),
        immediate_memory=data.get("immediate_memory"),
        plan_updates=data.get("plan_updates"),
        persist_context=data.get("persist_context", output.persist_context),
    )


def _build_monitor_prompt(character: str, user_message: str, output: AgentOutput) -> str:
    return "\n\n".join([
        _runtime_context(character),
        "## 用户本轮输入",
        user_message,
        "## 主 Agent 输出 JSON",
        _output_json(output),
        "## 你的输出格式",
        json.dumps({
            "valid": True,
            "needs_repair": False,
            "issues": [],
        }, ensure_ascii=False),
    ])


def _build_repair_prompt(
    character: str,
    user_message: str,
    output: AgentOutput,
    monitor_result: MonitorResult,
) -> str:
    return "\n\n".join([
        _runtime_context(character),
        "## 用户本轮输入",
        user_message,
        "## 原始 Agent 输出 JSON",
        _output_json(output),
        "## 监察器发现的问题",
        json.dumps(monitor_result.issues, ensure_ascii=False),
        "## 必须输出的 JSON 字段",
        json.dumps({
            "reply": "角色回复文本",
            "photo_prompt": None,
            "state_updates": None,
            "plan_updates": None,
            "immediate_memory": None,
            "persist_context": True,
        }, ensure_ascii=False),
    ])


def _runtime_context(character: str) -> str:
    return "\n\n".join([
        "## 当前角色",
        f"- character_id: {character}",
        f"- name: {get_character_name(character)}",
        f"- user_pet_name: {get_user_pet_name(character)}",
        "## 当前 status.md",
        read_status(character),
        "## 当前 plans.md",
        read_plans(character),
    ])


def _output_json(output: AgentOutput) -> str:
    if hasattr(output, "model_dump"):
        data = output.model_dump()
    else:
        data = output.dict()
    return json.dumps(data, ensure_ascii=False, indent=2)


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


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            text = "\n".join(lines[1:-1]).strip()
    return json.loads(text)
