"""
Plan Manager - 计划管理
解析、维护、跟踪 plans.md 中的多个 plan 实例。
"""

import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..config import settings

logger = logging.getLogger(__name__)


PLAN_FIELDS = ["type", "status", "created", "target", "progress", "complete_when"]


def _plan_path(character: str) -> Path:
    return settings.get_memory_dir(character) / "plans.md"


def _default_plans(character: str = "momo") -> str:
    from .context import get_character_name
    char_name = get_character_name(character)
    return f"# {char_name}的计划\n\n（暂无计划）\n"


def read_plans_raw(character: str) -> str:
    path = _plan_path(character)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        default_text = _default_plans(character)
        path.write_text(default_text, encoding="utf-8")
        return default_text
    return path.read_text(encoding="utf-8")


def write_plans_raw(character: str, content: str):
    path = _plan_path(character)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def parse_plans(character: str) -> list:
    """解析 plans.md，返回 plan 列表。"""
    text = read_plans_raw(character)
    plans = []
    pattern = r"### (.+?)\n((?:- .+\n?)+)"
    for m in re.finditer(pattern, text):
        name = m.group(1).strip()
        body = m.group(2)
        plan = {"name": name}
        for line in body.splitlines():
            line = line.strip()
            if not line.startswith("- "):
                continue
            kv = line[2:].split(":", 1)
            if len(kv) != 2:
                continue
            key = kv[0].strip()
            val = kv[1].strip()
            if key in PLAN_FIELDS:
                plan[key] = val
        plans.append(plan)
    return plans


def get_active_plans(character: str) -> list:
    return [p for p in parse_plans(character) if p.get("status") == "active"]


def get_all_plans(character: str) -> list:
    return parse_plans(character)


def add_plan(character, name, plan_type, target, complete_when="", progress="刚刚开始"):
    plans = parse_plans(character)
    for p in plans:
        if p["name"] == name:
            return p
    new_plan = {
        "name": name,
        "type": plan_type,
        "status": "active",
        "created": datetime.now().strftime("%Y-%m-%d"),
        "target": target,
        "progress": progress,
        "complete_when": complete_when,
    }
    plans.append(new_plan)
    write_plans_raw(character, _render_plans(plans, character))
    logger.info("plan added: " + character + "/" + name)
    return new_plan


def update_plan(character, name, **kwargs):
    plans = parse_plans(character)
    updated = None
    for p in plans:
        if p["name"] == name:
            for k, v in kwargs.items():
                if k in PLAN_FIELDS:
                    p[k] = str(v)
            updated = p
            break
    if updated:
        write_plans_raw(character, _render_plans(plans, character))
    return updated


def close_plan(character, name, reason="completed"):
    plans = parse_plans(character)
    target = None
    for p in plans:
        if p["name"] == name:
            target = p
            break
    if not target:
        return None
    target["status"] = "closed"
    target["progress"] = (target.get("progress", "") + " | closed: " + reason).strip(" |")
    write_plans_raw(character, _render_plans(plans, character))
    return target


def _render_plans(plans, character: str = "momo") -> str:
    long_plans = [p for p in plans if p.get("type") == "long"]
    short_plans = [p for p in plans if p.get("type") == "short"]
    other = [p for p in plans if p.get("type") not in ("long", "short")]

    def render_section(title, items):
        if not items:
            return "## " + title + "\n\n（暂无）\n"
        lines = ["## " + title, ""]
        for p in items:
            lines.append("### " + p["name"])
            for f in PLAN_FIELDS:
                if f in p:
                    lines.append("- " + f + ": " + p[f])
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    from .context import get_character_name
    char_name = get_character_name(character)
    parts = [f"# {char_name}的计划", ""]
    parts.append(render_section("长期计划", long_plans))
    parts.append("")
    parts.append(render_section("短期计划", short_plans))
    if other:
        parts.append("")
        parts.append(render_section("其他", other))
    return "\n".join(parts)


def format_plans_for_prompt(character: str) -> str:
    active = get_active_plans(character)
    if not active:
        return "（当前没有计划，可以主动设定一个）"
    lines = []
    for p in active:
        ptype = "长期" if p.get("type") == "long" else "短期"
        target = p.get("target", "")
        progress = p.get("progress", "")
        complete = p.get("complete_when", "")
        line = "- [" + ptype + "] " + p["name"] + " - " + target
        if progress:
            line += "\n  进度: " + progress
        if complete:
            line += "\n  闭环: " + complete
        lines.append(line)
    return "\n".join(lines)