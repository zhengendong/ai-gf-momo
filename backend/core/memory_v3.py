"""Memory v3 helpers.

The v3 shape keeps one editable user profile and one long-term memory file.
Old files are migrated in-place but left on disk as a fallback.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import settings


USER_JSON = "user.json"
OLD_USER_JSON = "user_profile.json"
OLD_PERSONALITY_MD = "personality.md"


def default_user_profile() -> dict:
    return {
        "gender": "",
        "user_pet_name": "",
        "identity": "",
        "communication_style": "",
        "notes": "",
        "last_updated": "",
    }


def user_profile_path(character: str) -> Path:
    return settings.get_character_dir(character) / USER_JSON


def legacy_user_profile_path(character: str) -> Path:
    return settings.get_memory_dir(character) / USER_JSON


def long_term_path(character: str) -> Path:
    return settings.get_memory_dir(character) / "long_term.md"


def load_user_profile(character: str) -> dict:
    path = user_profile_path(character)
    if not path.exists():
        migrate_character_memory_v3(character)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {**default_user_profile(), **data}
        except Exception:
            return default_user_profile()
    return default_user_profile()


def save_user_profile(character: str, updates: dict) -> dict:
    profile = load_user_profile(character)
    for key in ("gender", "user_pet_name", "identity", "communication_style", "notes"):
        if key in updates and updates[key] is not None:
            profile[key] = str(updates[key]).strip()
    profile["last_updated"] = datetime.now(timezone.utc).isoformat()
    path = user_profile_path(character)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    return profile


def render_user_profile(profile: dict) -> str:
    lines = ["# 用户信息", ""]
    if profile.get("gender"):
        lines.append(f"- 用户性别：{profile['gender']}")
    if profile.get("user_pet_name"):
        lines.append(f"- 当前称呼：{profile['user_pet_name']}")
    if profile.get("identity"):
        lines.append(f"- 用户身份：{profile['identity']}")
    if profile.get("communication_style"):
        lines.append(f"- 沟通偏好：{profile['communication_style']}")
    if profile.get("notes"):
        lines.append(f"- 备注：{profile['notes']}")
    return "\n".join(lines)


def migrate_character_memory_v3(character: str) -> bool:
    """Create root user.json and merge old personality/preferences into long_term.md.

    Returns True if any file changed.
    """
    char_dir = settings.get_character_dir(character)
    char_dir.mkdir(parents=True, exist_ok=True)
    memory_dir = settings.get_memory_dir(character)
    memory_dir.mkdir(parents=True, exist_ok=True)
    changed = False

    user_path = user_profile_path(character)
    legacy_user_path = legacy_user_profile_path(character)
    old_user_path = memory_dir / OLD_USER_JSON
    old_profile = {}
    if legacy_user_path.exists():
        try:
            old_profile.update(json.loads(legacy_user_path.read_text(encoding="utf-8")))
        except Exception:
            pass
    if old_user_path.exists():
        try:
            old_profile.update(json.loads(old_user_path.read_text(encoding="utf-8")))
        except Exception:
            pass

    if not user_path.exists():
        profile = default_user_profile()
        for key in ("gender", "user_pet_name", "identity", "communication_style", "notes", "last_updated"):
            if old_profile.get(key):
                profile[key] = old_profile[key]
        user_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        changed = True

    additions = []
    prefs = old_profile.get("preferences") or {}
    pref_lines = []
    for label, key in (("喜欢", "likes"), ("不喜欢", "dislikes"), ("爱好", "hobbies")):
        items = [str(x).strip() for x in prefs.get(key, []) if str(x).strip()]
        if items:
            pref_lines.append(f"- {label}：{', '.join(items)}")
    if pref_lines:
        additions.append(("用户偏好", pref_lines))

    traits = old_profile.get("personality_traits") or {}
    if traits:
        additions.append((
            "用户偏好",
            [f"- {k}：{v}" for k, v in traits.items() if str(v).strip()],
        ))

    personality_path = memory_dir / OLD_PERSONALITY_MD
    if personality_path.exists():
        text = personality_path.read_text(encoding="utf-8").strip()
        if text:
            additions.extend(_extract_personality_sections(text))

    lt_path = long_term_path(character)
    if not lt_path.exists():
        from .context import get_character_name
        lt_path.write_text(_default_long_term_text(get_character_name(character)), encoding="utf-8")
        changed = True

    if additions:
        current = lt_path.read_text(encoding="utf-8") if lt_path.exists() else ""
        merged = ensure_long_term_sections(current, character)
        for section, lines in additions:
            merged = append_unique_section_lines(merged, section, lines)
        if merged.strip() != current.strip():
            lt_path.write_text(merged, encoding="utf-8")
            changed = True

    return changed


def ensure_long_term_sections(text: str, character: str) -> str:
    from .context import get_character_name
    char_name = get_character_name(character)
    text = (text or "").strip()
    if not text:
        return _default_long_term_text(char_name)

    if "## 用户偏好" in text and "## 角色人格" in text:
        return text.rstrip() + "\n"

    lines = text.splitlines()
    bullet_lines = [ln for ln in lines if ln.strip().startswith("- ")]
    result = [
        f"# {char_name}的长期记忆",
        "",
        "## 用户偏好",
        "- （暂无）",
        "",
        "## 重要事件",
    ]
    result.extend(bullet_lines or ["- （暂无）"])
    result.extend([
        "",
        "## 关系约定",
        "- （暂无）",
        "",
        "## 角色人格",
        "- （暂无）",
        "",
        "## 角色信念",
        "- （暂无）",
        "",
        "## 情感印记",
        "- （暂无）",
        "",
    ])
    return "\n".join(result)


def append_unique_section_lines(text: str, section: str, lines: list[str]) -> str:
    clean_lines = [ln if ln.strip().startswith("- ") else f"- {ln}" for ln in lines if str(ln).strip()]
    if not clean_lines:
        return text
    text = text.rstrip() + "\n"
    header = f"## {section}"
    if header not in text:
        return text + f"\n{header}\n" + "\n".join(clean_lines) + "\n"

    pattern = re.compile(rf"(^## {re.escape(section)}\n)(.*?)(?=^## |\Z)", re.M | re.S)
    match = pattern.search(text)
    if not match:
        return text
    body = match.group(2).strip()
    existing = {ln.strip() for ln in body.splitlines() if ln.strip()}
    kept_body = "" if body == "- （暂无）" else body
    additions = [ln for ln in clean_lines if ln.strip() not in existing]
    if not additions:
        return text
    new_body = "\n".join([x for x in [kept_body, "\n".join(additions)] if x.strip()]).strip()
    return text[:match.start(2)] + new_body + "\n\n" + text[match.end(2):]


def is_identity_conflict_memory(character: str, text: str) -> bool:
    """Return True when a memory line appears to redefine this character as another role."""
    if not text:
        return False
    from .context import get_character_name
    current_names = {character, get_character_name(character)}
    other_names = set()
    if settings.characters_dir.exists():
        for item in settings.characters_dir.iterdir():
            if not item.is_dir() or item.name == character:
                continue
            other_names.add(item.name)
            try:
                other_names.add(get_character_name(item.name))
            except Exception:
                pass
    other_names -= current_names
    if not other_names:
        return False
    markers = ("我是", "我叫", "你是", "她是", "角色是", "名字是")
    if not any(marker in text for marker in markers):
        return False
    return any(name and name in text for name in other_names)


def should_recall_vector_memory(message: str) -> bool:
    text = (message or "").strip()
    if not text:
        return False
    triggers = [
        "记得", "之前", "以前", "上次", "那天", "昨天", "前天",
        "我喜欢", "我不喜欢", "讨厌", "爱好", "偏好", "还记不记得",
    ]
    if any(t in text for t in triggers):
        return True
    return len(text) >= 40 and any(ch in text for ch in "，。！？,.!?")


def filter_recalled_memories(items: list[dict], max_distance: float = 0.55) -> list[dict]:
    result = []
    for item in items:
        distance = item.get("distance")
        if distance is None or float(distance) <= max_distance:
            result.append(item)
    return result


def chat_messages_for_days(character: str, days: int) -> str:
    from .chat_history import read_chat_history

    cutoff = datetime.now(timezone.utc) - timedelta(days=max(days, 1))
    lines = []
    for msg in read_chat_history(character):
        ts = _parse_ts(msg.get("timestamp"))
        if ts and ts < cutoff:
            continue
        if msg.get("type") not in (None, "text"):
            continue
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        role = "用户" if msg.get("role") == "user" else "角色"
        # Technical timestamps are used only to select a bounded recent
        # window. They must never be exposed to MemoryAgent as story facts.
        lines.append(f"### {role}\n{content}")
    return "\n\n".join(lines)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _extract_personality_sections(text: str) -> list[tuple[str, list[str]]]:
    mapping = {
        "自我画像": "角色人格",
        "信念": "角色信念",
        "情感印记": "情感印记",
    }
    result = []
    for old, new in mapping.items():
        m = re.search(rf"^## {re.escape(old)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
        if not m:
            continue
        lines = [
            ln.strip()
            for ln in m.group(1).splitlines()
            if ln.strip().startswith("- ") and "随经历慢慢形成" not in ln
        ]
        if lines:
            result.append((new, lines))
    return result


def _default_long_term_text(char_name: str) -> str:
    return f"""# {char_name}的长期记忆

## 用户偏好
- （暂无）

## 重要事件
- （暂无）

## 关系约定
- （暂无）

## 角色人格
- （暂无）

## 角色信念
- （暂无）

## 情感印记
- （暂无）
"""
