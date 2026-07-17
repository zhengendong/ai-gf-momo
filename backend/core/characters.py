"""
角色管理模块
列出、切换、新增、修改角色
"""

import json
import logging
import shutil
import gc
import os
from pathlib import Path
from typing import Optional

from ..config import settings

logger = logging.getLogger(__name__)


def normalize_initial_scene(value=None) -> dict:
    raw = value if isinstance(value, dict) else {}
    concept = str(raw.get("concept") or "").strip()
    if len(concept) > 4000:
        raise ValueError("初始场景构想不能超过 4000 个字符")
    opening_mode = str(raw.get("opening_mode") or "character_first").strip().lower()
    if opening_mode not in {"character_first", "player_first"}:
        raise ValueError("初始场景开场模式无效")
    try:
        revision = max(1, int(raw.get("revision") or 1))
    except (TypeError, ValueError):
        revision = 1
    return {
        "concept": concept,
        "opening_mode": opening_mode,
        "revision": revision,
    }


def list_characters() -> list[str]:
    """列出所有角色"""
    migrate_all_character_assets()
    chars_dir = settings.characters_dir
    if not chars_dir.exists():
        return []
    return sorted(d.name for d in chars_dir.iterdir() if d.is_dir())


def get_active() -> str:
    """获取当前激活角色名"""
    settings_data = _load_settings()
    return settings_data.get("active_character", "momo")


def switch_character(name: str):
    """切换激活角色"""
    migrate_character_assets(name)
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

    # profile.json 是“皮肤”文件，皮肤信息只落进 visual_anchor（不重复存平铺字段）。
    skin_keys = {"name", "avatar", "gender", "visual_anchor", "initial_outfit_tags", "initial_scene"}
    default_profile = {"name": name, "avatar": "💕"}
    for k, v in profile.items():
        if k in skin_keys:
            default_profile[k] = v
    default_profile["initial_scene"] = normalize_initial_scene(profile.get("initial_scene"))

    with open(char_dir / "profile.json", "w", encoding="utf-8") as f:
        json.dump(default_profile, f, ensure_ascii=False, indent=2)

    identity = profile.get("identity", "").strip()
    if not identity:
        identity = f"# {name}\n\n## 身份\n\n待编辑...\n"
    (char_dir / "identity.md").write_text(identity, encoding="utf-8")

    # 初始化角色资产空间
    memory_dir = settings.get_memory_dir(name)
    memory_dir.mkdir(parents=True, exist_ok=True)
    settings.get_images_dir(name).mkdir(parents=True, exist_ok=True)
    settings.get_vector_dir(name).parent.mkdir(parents=True, exist_ok=True)

    # 初始化记忆文件
    from .state import write_uninitialized_state
    from .memory_v3 import default_user_profile, save_user_profile, user_profile_path
    display_name = default_profile.get("name") or name
    user_profile_path(name).write_text(
        json.dumps(default_user_profile(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if profile.get("user_profile"):
        save_user_profile(name, profile["user_profile"])
    (memory_dir / "soul.md").write_text(_default_soul(display_name), encoding="utf-8")
    (memory_dir / "long_term.md").write_text(f"# {display_name}的长期记忆\n\n（随对话自然生长）\n", encoding="utf-8")
    write_uninitialized_state(name)

    logger.info(f"角色 '{name}' 创建完成")


def _default_soul(display_name: str) -> str:
    return f"""# {display_name}的灵魂

## 自我认知
- （随长期互动慢慢形成）

## 情感倾向
- （随长期互动慢慢形成）

## 底线
- （随长期互动慢慢形成）

## 执念
- （随长期互动慢慢形成）
"""


def delete_character(name: str):
    """Delete a character's config, memory, and generated data."""
    migrate_character_assets(name)
    char_dir = settings.get_character_dir(name)
    if not char_dir.exists():
        raise ValueError(f"角色 '{name}' 不存在")

    if name == get_active():
        remaining = [c for c in list_characters() if c != name]
        if remaining:
            switch_character(remaining[0])

    _release_vector_locks()
    if char_dir.exists():
        _remove_tree(char_dir)
    for path in [
        settings.legacy_characters_dir / name,
        settings.legacy_memory_dir / name,
        settings.legacy_data_dir / name,
    ]:
        if path.exists():
            _remove_tree(path)
    logger.info("角色 '%s' 已删除", name)


def clear_character_records(name: str):
    """Clear runtime records while keeping profile and identity files."""
    migrate_character_assets(name)
    if not settings.get_character_dir(name).exists():
        raise ValueError(f"角色 '{name}' 不存在")

    reset_character_memory(name)

    logger.info("角色 '%s' 记录已清空", name)


def reset_character_memory(name: str):
    """Reset dynamic memory, chat records, generated images, and vector data."""
    char_dir = settings.get_character_dir(name)
    if not char_dir.exists():
        raise ValueError(f"角色 '{name}' 不存在")

    from .memory_v3 import migrate_character_memory_v3
    migrate_character_memory_v3(name)

    memory_dir = settings.get_memory_dir(name)
    images_dir = settings.get_images_dir(name)
    vector_dir = settings.get_vector_dir(name)

    _release_vector_locks()
    if memory_dir.exists():
        _remove_tree(memory_dir)
    if images_dir.exists():
        _remove_tree(images_dir)
    vector_root = vector_dir.parent
    if vector_root.exists():
        _remove_tree(vector_root)

    memory_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)
    vector_root.mkdir(parents=True, exist_ok=True)

    from .state import write_uninitialized_state

    display_name = get_profile(name).get("name") or name
    (memory_dir / "soul.md").write_text(_default_soul(display_name), encoding="utf-8")
    (memory_dir / "long_term.md").write_text(
        f"# {display_name}的长期记忆\n\n（随对话自然生长）\n",
        encoding="utf-8",
    )
    write_uninitialized_state(name)


def get_profile(name: str) -> dict:
    """获取角色 profile"""
    migrate_character_assets(name)
    path = settings.get_character_dir(name) / "profile.json"
    if not path.exists():
        raise ValueError(f"角色 '{name}' 不存在")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def update_profile(name: str, updates: dict):
    """修改角色 profile"""
    profile = get_profile(name)
    if "initial_scene" in updates:
        current = normalize_initial_scene(profile.get("initial_scene"))
        incoming = normalize_initial_scene(updates.get("initial_scene"))
        if (
            incoming["concept"] != current["concept"]
            or incoming["opening_mode"] != current["opening_mode"]
        ):
            incoming["revision"] = current["revision"] + 1
        updates = dict(updates)
        updates["initial_scene"] = incoming
    profile.update(updates)
    path = settings.get_character_dir(name) / "profile.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    logger.info(f"角色 '{name}' profile 已更新")


def migrate_all_character_assets():
    """Move legacy split character assets into characters/{id}/."""
    names = set()
    for base in (
        settings.legacy_characters_dir,
        settings.legacy_memory_dir,
        settings.legacy_data_dir,
        settings.characters_dir,
    ):
        if base.exists():
            names.update(d.name for d in base.iterdir() if d.is_dir())
    for name in sorted(names):
        migrate_character_assets(name)


def migrate_character_assets(name: str):
    """Migrate one character from legacy config/memory/data folders."""
    dst = settings.get_character_dir(name)
    legacy_config = settings.legacy_characters_dir / name
    legacy_memory = settings.legacy_memory_dir / name
    legacy_data = settings.legacy_data_dir / name

    dst.mkdir(parents=True, exist_ok=True)
    memory_dst = settings.get_memory_dir(name)
    images_dst = settings.get_images_dir(name)
    vector_dst = settings.get_vector_dir(name)
    memory_dst.mkdir(parents=True, exist_ok=True)
    images_dst.mkdir(parents=True, exist_ok=True)
    vector_dst.parent.mkdir(parents=True, exist_ok=True)

    if not any(p.exists() for p in (legacy_config, legacy_memory, legacy_data)):
        return

    if legacy_config.exists():
        _move_children(legacy_config, dst)
        _remove_empty_dir(legacy_config)

    if legacy_memory.exists():
        memory_dst.mkdir(parents=True, exist_ok=True)
        _move_children(legacy_memory, memory_dst)
        _remove_empty_dir(legacy_memory)

    if legacy_data.exists():
        images_src = legacy_data / "images"
        chroma_src = legacy_data / "chroma_db"
        if images_src.exists():
            images_dst.mkdir(parents=True, exist_ok=True)
            _move_children(images_src, images_dst)
            _remove_empty_dir(images_src)
        if chroma_src.exists():
            vector_dst.mkdir(parents=True, exist_ok=True)
            _move_children(chroma_src, vector_dst)
            _remove_empty_dir(chroma_src)
        _move_non_asset_children(legacy_data, dst / "data")
        _remove_empty_dir(legacy_data)


def _move_children(src: Path, dst: Path):
    dst.mkdir(parents=True, exist_ok=True)
    for item in list(src.iterdir()):
        target = dst / item.name
        if target.exists():
            if item.is_dir():
                _move_children(item, target)
                _remove_empty_dir(item)
            else:
                item.unlink(missing_ok=True)
            continue
        shutil.move(str(item), str(target))


def _move_non_asset_children(src: Path, dst: Path):
    for item in list(src.iterdir()):
        if item.name in {"images", "chroma_db"}:
            continue
        dst.mkdir(parents=True, exist_ok=True)
        target = dst / item.name
        if target.exists():
            if item.is_dir():
                _move_children(item, target)
                _remove_empty_dir(item)
            else:
                item.unlink(missing_ok=True)
        else:
            shutil.move(str(item), str(target))


def _remove_empty_dir(path: Path):
    try:
        if path.exists() and path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    except Exception:
        pass


def _release_vector_locks():
    try:
        from chromadb.api.client import SharedSystemClient
        SharedSystemClient.clear_system_cache()
    except Exception:
        pass
    gc.collect()


def _remove_tree(path: Path):
    def _onerror(func, failed_path, exc_info):
        try:
            os.chmod(failed_path, 0o700)
            func(failed_path)
        except Exception:
            raise

    shutil.rmtree(path, onerror=_onerror)


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
