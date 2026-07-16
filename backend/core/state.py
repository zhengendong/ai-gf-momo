"""
状态管理模块
读取和写入 memory/{character}/status.md
"""

import logging
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Optional

from ..config import settings
from ..utils.helpers import read_markdown, write_markdown
from .outfit_state import normalize_outfit_markdown
from .wardrobe import (
    apply_wardrobe_patch,
    derived_absence_tags,
    normalize_wardrobe,
    reduce_wardrobe,
    wardrobe_from_tags,
    wardrobe_visible_tags,
)

logger = logging.getLogger(__name__)

def _character_name(character: str) -> str:
    from .context import get_character_name
    return get_character_name(character)


def _allowed_sections(character: str) -> set[str]:
    return {"穿着", "场景细节"}


def _section_aliases(character: str) -> dict:
    return {
        "心情状态": None,
        "表情": None,
        "小桃的心情状态": None,
        f"{_character_name(character)}的心情状态": None,
        f"{character}的心情状态": None,
        "房间": "场景细节",
        "地点": "场景细节",
        "裙子": "穿着",
        "姿势/动作": None,
        "外貌": None,
    }


def _dict_to_bullets(d: dict) -> str:
    """将嵌套 dict 转为 markdown 列表格式：- key：value"""
    lines = []
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append(f"- {k}：")
            for sk, sv in v.items():
                lines.append(f"  - {sk}：{sv}")
        else:
            lines.append(f"- {k}：{v}")
    return "\n".join(lines)


def _value_to_markdown(value) -> str:
    """将值（str / dict）转为 markdown section 内容"""
    if isinstance(value, dict):
        return _dict_to_bullets(value)
    if isinstance(value, str):
        return value
    return str(value)


def get_status_path(character: str) -> Path:
    """获取角色的 status 文件路径"""
    return settings.get_memory_dir(character) / "status.md"


def get_state_snapshot_path(character: str) -> Path:
    """获取角色结构化状态快照路径。"""
    return settings.get_memory_dir(character) / "state_snapshot.json"


def read_state_snapshot(character: str) -> dict:
    """读取角色结构化状态快照；不存在时返回空结构。"""
    path = get_state_snapshot_path(character)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"读取 state_snapshot 失败: {character}: {e}")
        return {}


def capture_state_snapshot(character: str) -> dict:
    """Return a self-contained visual state snapshot for an asynchronous job."""
    status = read_status(character)
    previous = read_state_snapshot(character)
    wardrobe = previous.get("wardrobe")
    if isinstance(wardrobe, dict):
        wardrobe = normalize_wardrobe(wardrobe)
    else:
        wardrobe = wardrobe_from_tags(_read_section_tags(status, "穿着"))
    return {
        "version": int(previous.get("version") or 0),
        "wardrobe": deepcopy(wardrobe),
        # Compatibility projection for old image and API consumers.  It is a
        # render projection, not the canonical layered wardrobe.
        "outfit_tags": wardrobe_visible_tags(wardrobe),
        "scene_tags": _read_section_tags(status, "场景细节"),
    }


def state_updates_from_effects(character: str, effects: list[dict]) -> dict | None:
    """Build legacy updates from completed effects without mutating state."""
    status_updates: dict[str, str] = {}
    for effect in effects or []:
        if not isinstance(effect, dict) or effect.get("status", "completed") != "completed":
            continue
        effect_type = effect.get("type")
        if effect_type in {"replace_outfit", "outfit_change"}:
            tags = effect.get("tags") or effect.get("outfit_tags") or effect.get("items")
            if tags:
                status_updates["穿着"] = _tags_to_markdown(tags)
        elif effect_type in {"replace_scene", "scene_change", "scene_update"}:
            tags = effect.get("tags") or effect.get("scene_tags")
            if tags:
                status_updates["场景细节"] = _tags_to_markdown(tags)
    if not status_updates:
        return None
    return {"status": status_updates}


def read_status(character: str) -> str:
    """读取角色的当前状态"""
    path = get_status_path(character)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        default = _default_status(character)
        write_markdown(path, default)
        return default
    content = read_markdown(path)
    migrated = _strip_legacy_mood_sections(content)
    if migrated != content:
        write_markdown(path, migrated)
        logger.info("已移除旧心情状态: %s/status.md", character)
    return migrated


def write_status(character: str, content: str):
    """写入角色的状态"""
    path = get_status_path(character)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_markdown(path, _strip_legacy_mood_sections(content))
    logger.info(f"状态已更新: {character}/status.md")


def apply_state_updates(character: str, updates: dict):
    """
    将 Agent 输出的 state_updates 应用到文件

    Args:
        character: 角色名
        updates: {"status": "新的完整内容"} 或 {"status": {...}}
    """
    if not updates:
        return

    if "status" in updates:
        status_val = updates["status"]
        wardrobe_changed = isinstance(status_val, str)
        if isinstance(status_val, str):
            write_status(character, status_val)
        elif isinstance(status_val, dict):
            # 深度合并模式：读当前 → 合并 → 写回
            current = read_status(character)
            merged = _deep_merge_markdown(character, current, status_val)
            write_status(character, merged)
            aliases = _section_aliases(character)
            wardrobe_changed = any(
                aliases.get(section, section) == "穿着" for section in status_val
            )
        _write_state_snapshot(character, rebuild_wardrobe=wardrobe_changed)


def apply_state_operations(character: str, operations: list[dict]) -> dict:
    """Validate and atomically project completed V2 state operations.

    Wardrobe operations are reduced against the canonical layered snapshot.
    Scene operations reuse the existing Markdown compatibility projection.
    No file is changed until every operation validates.
    """
    operations = operations or []
    current_status = read_status(character)
    previous = read_state_snapshot(character)
    raw_wardrobe = previous.get("wardrobe")
    wardrobe = (
        normalize_wardrobe(raw_wardrobe)
        if isinstance(raw_wardrobe, dict)
        else wardrobe_from_tags(_read_section_tags(current_status, "穿着"))
    )
    wardrobe_ops = [
        operation for operation in operations
        if isinstance(operation, dict)
        and str(operation.get("domain") or "").strip().lower() == "wardrobe"
    ]
    next_wardrobe = reduce_wardrobe(wardrobe, wardrobe_ops)

    status_updates: dict[str, str] = {}
    if wardrobe_ops:
        status_updates["穿着"] = _wardrobe_to_status_markdown(next_wardrobe)

    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("state operation must be an object")
        domain = str(operation.get("domain") or "").strip().lower()
        action = str(operation.get("operation") or operation.get("type") or "").strip().lower()
        action = action.removeprefix(f"{domain}.") if domain else action
        if domain == "wardrobe":
            continue
        if domain == "scene" and action in {"replace", "update", "change"}:
            tags = operation.get("tags") or operation.get("scene_tags")
            if not tags:
                raise ValueError("scene operation requires complete tags")
            status_updates["场景细节"] = _tags_to_markdown(tags)
        elif domain == "mood":
            logger.info("忽略兼容输入中的旧 mood 状态操作")
            continue
        else:
            raise ValueError(f"unsupported state operation: {domain}.{action}")

    if status_updates:
        merged = _deep_merge_markdown(character, current_status, status_updates)
        write_status(character, merged)
        _write_state_snapshot(character, wardrobe=next_wardrobe)
    return capture_state_snapshot(character)


def merge_continuity_patch(state_snapshot: dict, state_patch: dict | None) -> dict:
    """Validate and merge a VisualContinuityAgent patch without file writes."""
    if state_patch is None:
        state_patch = {}
    if not isinstance(state_patch, dict):
        raise ValueError("state_patch must be an object")
    unknown = set(state_patch) - {"wardrobe", "scene"}
    if unknown:
        raise ValueError(f"state_patch contains unsupported fields: {', '.join(sorted(unknown))}")

    previous = deepcopy(state_snapshot or {})
    wardrobe = normalize_wardrobe(previous.get("wardrobe"))
    next_wardrobe = apply_wardrobe_patch(wardrobe, state_patch.get("wardrobe"))

    scene_tags = list(previous.get("scene_tags") or [])
    scene_patch = state_patch.get("scene")
    if scene_patch is not None:
        if not isinstance(scene_patch, dict):
            raise ValueError("scene patch must be an object or null")
        mode = str(scene_patch.get("mode") or "replace").strip().lower()
        if mode != "replace":
            raise ValueError(f"unsupported scene patch mode: {mode}")
        raw_tags = scene_patch.get("tags")
        if not isinstance(raw_tags, list):
            raise ValueError("scene replace patch requires a tags array")
        scene_tags = _normalize_state_tags(raw_tags)
        if len(scene_tags) > 4:
            raise ValueError("scene replace patch exceeds the 4-tag budget")

    return {
        "version": int(previous.get("version") or 0),
        "wardrobe": next_wardrobe,
        "outfit_tags": wardrobe_visible_tags(next_wardrobe),
        "scene_tags": scene_tags,
    }


def commit_continuity_patch(character: str, state_patch: dict | None) -> tuple[dict, bool]:
    """Persist one validated continuity patch and return its frozen snapshot."""
    previous = capture_state_snapshot(character)
    merged = merge_continuity_patch(previous, state_patch)
    changed = (
        merged["wardrobe"] != previous.get("wardrobe")
        or merged["scene_tags"] != list(previous.get("scene_tags") or [])
    )
    if not changed:
        return previous, False

    current_status = read_status(character)
    status_updates = {
        "穿着": _wardrobe_to_status_markdown(merged["wardrobe"]),
        "场景细节": _tags_to_markdown(merged["scene_tags"]),
    }
    next_status = _deep_merge_markdown(character, current_status, status_updates)
    write_status(character, next_status)

    merged["version"] = int(previous.get("version") or 0) + 1
    path = get_state_snapshot_path(character)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)
    return deepcopy(merged), True


def _write_state_snapshot(
    character: str,
    wardrobe: dict | None = None,
    rebuild_wardrobe: bool = False,
):
    """Persist the machine-readable source alongside the Markdown projection."""
    path = get_state_snapshot_path(character)
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = read_state_snapshot(character)
    snapshot = capture_state_snapshot(character)
    if rebuild_wardrobe and wardrobe is None:
        wardrobe = wardrobe_from_tags(_read_section_tags(read_status(character), "穿着"))
    if wardrobe is not None:
        normalized = normalize_wardrobe(wardrobe)
        snapshot["wardrobe"] = normalized
        snapshot["outfit_tags"] = wardrobe_visible_tags(normalized)
        # Keep the Markdown file as a projection of the same canonical
        # wardrobe. Never write the legacy flat garment tags back to it.
        current_status = read_status(character)
        projected = _deep_merge_markdown(
            character,
            current_status,
            {"穿着": _wardrobe_to_status_markdown(normalized)},
        )
        write_status(character, projected)
    snapshot["version"] = int(previous.get("version") or 0) + 1
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_section_tags(status: str, section: str) -> list[str]:
    match = re.search(rf"## {re.escape(section)}\n(.*?)(?=## |\Z)", status, re.DOTALL)
    if not match:
        return []
    result = []
    for line in match.group(1).splitlines():
        value = line.strip().removeprefix("-").strip()
        if section == "穿着" and "：" in value:
            _, value = value.split("：", 1)
            value = value.split("（", 1)[0].strip()
            if value == "无":
                continue
            value = value.replace("、", "\n")
        if "\n" in value:
            result.extend(v.strip().replace(" ", "_") for v in value.splitlines() if v.strip())
            continue
        if value:
            result.append(value.replace(" ", "_"))
    return result


def _tags_to_markdown(value) -> str:
    values = value if isinstance(value, list) else str(value).replace(",", "\n").splitlines()
    return "\n".join(f"- {str(tag).strip().removeprefix('-').strip()}" for tag in values if str(tag).strip())


def _wardrobe_to_status_markdown(wardrobe: dict) -> str:
    """Render the canonical layered wardrobe as a readable Markdown projection.

    This deliberately avoids the legacy flat ``white``/``lace``/``panties``
    list.  The JSON snapshot remains the machine source; this is only its
    human/model-facing projection.
    """
    value = normalize_wardrobe(wardrobe)
    absence_tags = set(derived_absence_tags(value))
    if "completely_nude" in absence_tags:
        accessories = []
        for item_id in value.get("layers", {}).get("accessories", []):
            item = value.get("items", {}).get(item_id, {})
            phrase = " ".join(str(tag).replace("_", " ") for tag in item.get("tags", []))
            if phrase and phrase not in accessories:
                accessories.append(phrase)
        lines = ["- 状态：completely_nude"]
        if accessories:
            lines.append(f"- 配饰：{'、'.join(accessories)}")
        return "\n".join(lines)

    lines = []
    labels = {
        "upper": "上身",
        "lower": "下身",
        "legwear": "腿部",
        "footwear": "鞋子",
        "accessories": "配饰",
    }
    for slot in ("upper", "lower", "legwear", "footwear", "accessories"):
        phrases = []
        for item_id in value.get("layers", {}).get(slot, []):
            item = value.get("items", {}).get(item_id, {})
            phrase = " ".join(str(tag).replace("_", " ") for tag in item.get("tags", []))
            if phrase and phrase not in phrases:
                phrases.append(phrase)
        text = "、".join(phrases) if phrases else "无"
        lines.append(f"- {labels[slot]}：{text}")
    if not value.get("layers", {}).get("upper"):
        lines[0] = "- 上身：topless"
    if not value.get("layers", {}).get("lower"):
        lines[1] = "- 下身：bottomless"
    if not value.get("layers", {}).get("legwear") and not value.get("layers", {}).get("footwear"):
        lines[3] = "- 鞋子：barefoot"
    return "\n".join(lines)


def _normalize_state_tags(value: list) -> list[str]:
    result: list[str] = []
    for raw in value:
        tag = str(raw or "").strip().removeprefix("-").strip().lower().replace(" ", "_")
        if tag and tag not in result:
            result.append(tag)
    return result


def _deep_merge_markdown(character: str, current_text: str, updates: dict) -> str:
    """
    将字典更新合并到 Markdown 文本。
    - 非白名单 key 通过别名映射路由，无匹配则跳过并记 warning
    - dict 值自动转为 `- key：value` 列表格式
    - str 值直接作为 section 内容
    """
    result = current_text
    aliases = _section_aliases(character)
    allowed = _allowed_sections(character)
    for section, content in updates.items():
        canonical = aliases.get(section, section)
        if canonical is None:
            logger.warning(f"状态更新丢弃非白名单 key: {section!r}")
            continue
        if canonical not in allowed:
            logger.warning(f"状态更新跳过未识别 key: {section!r}")
            continue

        md_content = _value_to_markdown(content)
        if canonical == "穿着" and "- 上身：" not in md_content:
            md_content = normalize_outfit_markdown(md_content)

        # 穿着防呆：dict 只有 1-2 项但旧内容有 4+ 行 → 可能是 LLM 只发了变更项，拒绝
        if canonical == "穿着" and isinstance(content, dict):
            old_lines = 0
            if f"## {canonical}" in result:
                old_section = result.split(f"## {canonical}")[1].split("## ")[0]
                old_lines = old_section.count("\n- ")
            if len(content) <= 2 and old_lines >= 4:
                logger.warning(f"穿着更新疑似不完整: 新 {len(content)} 项 vs 旧 {old_lines} 项，已拒绝")
                continue

        header = f"## {canonical}"

        if header in result:
            parts = result.split(header)
            before = parts[0]
            after_parts = parts[1].split("## ", 1)
            replacement = f"{header}\n{md_content}\n\n"
            if len(after_parts) > 1:
                result = before + replacement + "## " + after_parts[1]
            else:
                result = before + replacement
        else:
            result += f"\n{header}\n{md_content}\n"
    return result


def _coerce_outfit_tags(outfit_tags=None) -> str:
    if outfit_tags is None:
        tags = [
            "white_shirt",
            "black_pleated_skirt",
            "black_mary_jane_shoes",
            "white_thighhighs",
            "silver_heart_necklace",
            "black_bell_collar",
        ]
    elif isinstance(outfit_tags, str):
        tags = []
        for line in outfit_tags.replace(",", "\n").splitlines():
            tag = line.strip()
            if tag.startswith("-"):
                tag = tag[1:].strip()
            if tag:
                tags.append(tag)
    else:
        tags = [str(tag).strip() for tag in outfit_tags if str(tag).strip()]
    return normalize_outfit_markdown(tags)


def _default_status(character: str = "momo", outfit_tags=None) -> str:
    """默认状态"""
    char_name = _character_name(character)
    outfit = _wardrobe_to_status_markdown(wardrobe_from_tags(
        [line.removeprefix("-").strip() for line in _coerce_outfit_tags(outfit_tags).splitlines() if line.strip()]
    ))
    return f"""# {char_name}的状态

## 穿着
{outfit}

## 场景细节
- bedroom
- indoors
- evening
- warm_lighting
"""


def _strip_legacy_mood_sections(content: str) -> str:
    """Remove obsolete mood sections while preserving all visual facts."""
    cleaned = re.sub(
        r"(?ms)\n*^##[ \t]+[^\n]*心情状态[ \t]*\n.*?(?=^##[ \t]+|\Z)",
        "\n",
        str(content or ""),
    )
    return cleaned.rstrip() + "\n"
