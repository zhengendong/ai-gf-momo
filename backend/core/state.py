"""
状态管理模块
读取和写入 memory/{character}/status.md
"""

import logging
import json
from pathlib import Path
from typing import Optional

from ..config import settings
from ..utils.helpers import read_markdown, write_markdown

logger = logging.getLogger(__name__)

def _character_name(character: str) -> str:
    from .context import get_character_name
    return get_character_name(character)


def _mood_section(character: str) -> str:
    return f"{_character_name(character)}的心情状态"


def _allowed_sections(character: str) -> set[str]:
    return {"穿着", "场景细节", _mood_section(character), f"{character}的心情状态", "小桃的心情状态"}


def _section_aliases(character: str) -> dict:
    mood = _mood_section(character)
    return {
        "心情状态": mood,
        "表情": mood,
        "小桃的心情状态": mood,
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


def get_plans_path(character: str) -> Path:
    """获取角色的 plans 文件路径"""
    return settings.get_memory_dir(character) / "plans.md"


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


def read_status(character: str) -> str:
    """读取角色的当前状态"""
    path = get_status_path(character)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        default = _default_status(character)
        write_markdown(path, default)
        return default
    return read_markdown(path)


def read_plans(character: str) -> str:
    """读取角色的当前计划"""
    path = get_plans_path(character)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        default = _default_plans(character)
        write_markdown(path, default)
        return default
    return read_markdown(path)


def write_status(character: str, content: str):
    """写入角色的状态"""
    path = get_status_path(character)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_markdown(path, content)
    logger.info(f"状态已更新: {character}/status.md")


def write_plans(character: str, content: str):
    """写入角色的计划"""
    path = get_plans_path(character)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_markdown(path, content)
    logger.info(f"计划已更新: {character}/plans.md")


def apply_state_updates(character: str, updates: dict):
    """
    将 Agent 输出的 state_updates 应用到文件

    Args:
        character: 角色名
        updates: {"status": "新的完整内容", "plans": "新的完整内容"}
                 或 {"status": {...}, "plans": {...}}
    """
    if not updates:
        return

    if "status" in updates:
        status_val = updates["status"]
        if isinstance(status_val, str):
            write_status(character, status_val)
        elif isinstance(status_val, dict):
            # 深度合并模式：读当前 → 合并 → 写回
            current = read_status(character)
            merged = _deep_merge_markdown(character, current, status_val)
            write_status(character, merged)

    if "plans" in updates:
        plans_val = updates["plans"]
        if isinstance(plans_val, str):
            write_plans(character, plans_val)
        elif isinstance(plans_val, dict):
            current = read_plans(character)
            merged = _deep_merge_markdown(character, current, plans_val)
            write_plans(character, merged)


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


def _default_status(character: str = "momo") -> str:
    """默认状态"""
    char_name = _character_name(character)
    return f"""# {char_name}的状态

## 穿着
- 上衣：白色衬衫
- 下衣：黑色百褶裙
- 鞋子：黑色玛丽珍鞋
- 袜子：白色过膝袜
- 配饰：银色小心形项链、黑色铃铛项圈

## 场景细节
- 地点：家里卧室
- 环境：傍晚，窗外天色渐暗，房间里开着灯
- 光线：暖色灯光
- 时间段：傍晚

## {char_name}的心情状态
- 等待开始新的对话
"""


def _default_plans(character: str = "momo") -> str:
    """默认计划"""
    char_name = _character_name(character)
    return f"""# {char_name}的计划

## 当前目标
- 陪用户聊天

## 想做的事
- 了解用户今天想聊什么
"""
