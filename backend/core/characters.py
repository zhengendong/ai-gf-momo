"""
角色管理模块
列出、切换、新增、修改角色
"""

import json
import logging
import shutil
from pathlib import Path
from typing import Optional

from ..config import settings

logger = logging.getLogger(__name__)


def list_characters() -> list[str]:
    """列出所有角色"""
    chars_dir = settings.characters_dir
    if not chars_dir.exists():
        return []
    return [d.name for d in chars_dir.iterdir() if d.is_dir()]


def get_active() -> str:
    """获取当前激活角色名"""
    settings_data = _load_settings()
    return settings_data.get("active_character", "momo")


def switch_character(name: str):
    """切换激活角色"""
    chars_dir = settings.characters_dir
    char_dir = chars_dir / name
    if not char_dir.exists():
        raise ValueError(f"角色 '{name}' 不存在")

    settings_data = _load_settings()
    settings_data["active_character"] = name
    _save_settings(settings_data)
    logger.info(f"已切换到角色: {name}")


def create_character(name: str, profile: dict):
    """创建新角色"""
    chars_dir = settings.characters_dir
    char_dir = chars_dir / name
    if char_dir.exists():
        raise ValueError(f"角色 '{name}' 已存在")

    char_dir.mkdir(parents=True, exist_ok=True)

    default_profile = {
        "name": name,
        "avatar": "💕",
        "avatar_role": "",
        "body_type": "",
        "appearance": ""
    }
    default_profile.update(profile)

    with open(char_dir / "profile.json", "w", encoding="utf-8") as f:
        json.dump(default_profile, f, ensure_ascii=False, indent=2)

    identity = profile.get("identity", "").strip()
    if not identity:
        identity = f"# {name}\n\n## 身份\n\n待编辑...\n"
    (char_dir / "identity.md").write_text(identity, encoding="utf-8")

    # 初始化记忆空间
    memory_dir = settings.memory_dir / name
    memory_dir.mkdir(parents=True, exist_ok=True)

    # 初始化记忆文件
    from .state import _default_status, _default_plans
    (memory_dir / "soul.md").write_text(f"# {name}的灵魂\n\n## 核心\n\n待编辑...\n", encoding="utf-8")
    (memory_dir / "long_term.md").write_text(f"# {name}的长期记忆\n\n（随对话自然生长）\n", encoding="utf-8")
    (memory_dir / "status.md").write_text(_default_status().replace("小桃", name), encoding="utf-8")
    (memory_dir / "plans.md").write_text(_default_plans().replace("小桃", name), encoding="utf-8")

    logger.info(f"角色 '{name}' 创建完成")


def delete_character(name: str):
    """Delete a character's config, memory, and generated data."""
    char_dir = settings.get_character_dir(name)
    if not char_dir.exists():
        raise ValueError(f"角色 '{name}' 不存在")

    if name == get_active():
        remaining = [c for c in list_characters() if c != name]
        if remaining:
            switch_character(remaining[0])

    for path in [char_dir, settings.get_memory_dir(name), settings.data_dir / name]:
        if path.exists():
            shutil.rmtree(path)
    logger.info("角色 '%s' 已删除", name)


def clear_character_records(name: str):
    """Clear runtime records while keeping profile and identity files."""
    if not settings.get_character_dir(name).exists():
        raise ValueError(f"角色 '{name}' 不存在")

    memory_dir = settings.get_memory_dir(name)
    if memory_dir.exists():
        for item in list(memory_dir.iterdir()):
            if item.name in {"chat_history.json", "conversation_summary.md"}:
                item.unlink(missing_ok=True)
            elif item.suffix == ".md" and item.stem[:4].isdigit():
                item.unlink(missing_ok=True)

    images_dir = settings.get_images_dir(name)
    if images_dir.exists():
        shutil.rmtree(images_dir)

    memory_dir.mkdir(parents=True, exist_ok=True)
    logger.info("角色 '%s' 记录已清空", name)


def get_profile(name: str) -> dict:
    """获取角色 profile"""
    path = settings.get_character_dir(name) / "profile.json"
    if not path.exists():
        raise ValueError(f"角色 '{name}' 不存在")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def update_profile(name: str, updates: dict):
    """修改角色 profile"""
    profile = get_profile(name)
    profile.update(updates)
    path = settings.get_character_dir(name) / "profile.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    logger.info(f"角色 '{name}' profile 已更新")


def _load_settings() -> dict:
    path = settings.settings_file
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"active_character": "momo"}


def _save_settings(data: dict):
    path = settings.settings_file
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
