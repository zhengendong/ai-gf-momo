"""Persistent per-character chat history.

This is the tavern-style conversation log used by the UI and by new runtime
sessions to continue a conversation after restart.
"""

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import settings

MAX_CHAT_MESSAGES = 1000
PHOTO_PROMPT_RE = re.compile(
    r"\n*\s*(?:\U0001f4f7|馃摲)\s*[\s\S]*$",
    re.IGNORECASE,
)
BARE_RATING_PROMPT_RE = re.compile(
    r"\n+\s*rating:(?:general|sensitive|nsfw|explicit)\b[\s\S]*$",
    re.IGNORECASE,
)
DAILY_HEADER_RE = re.compile(
    r"^###\s+(?:(\d{2}:\d{2})\s+)?(.+?)(?:说|璇.).*$",
    re.MULTILINE,
)


def get_chat_history_path(character: str) -> Path:
    return settings.get_memory_dir(character) / "chat_history.json"


def read_chat_history(character: str, limit: int | None = None) -> list[dict]:
    path = get_chat_history_path(character)
    if not path.exists():
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []

    messages = data.get("messages", data if isinstance(data, list) else [])
    if not isinstance(messages, list):
        return []

    repaired = repair_chat_history(character, messages)
    if repaired != messages:
        write_chat_history(character, repaired)
        messages = repaired
    return messages[-limit:] if limit else messages


def write_chat_history(character: str, messages: list[dict]):
    path = get_chat_history_path(character)
    path.parent.mkdir(parents=True, exist_ok=True)
    trimmed = messages[-MAX_CHAT_MESSAGES:]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"messages": trimmed}, f, ensure_ascii=False, indent=2)


def append_chat_message(character: str, message: dict):
    messages = read_chat_history(character)
    messages.append(normalize_message(message))
    write_chat_history(character, messages)


def replace_chat_image_url(character: str, old_url: str, new_url: str) -> int:
    """Replace a generated image reference without creating a new chat turn."""
    old_url = str(old_url or "").strip()
    new_url = str(new_url or "").strip()
    if not old_url or not new_url:
        return 0
    messages = read_chat_history(character)
    replaced = 0
    for message in messages:
        current_url = message.get("imageUrl") or message.get("image_url")
        if current_url != old_url:
            continue
        message["imageUrl"] = new_url
        message.pop("image_url", None)
        replaced += 1
    if replaced:
        write_chat_history(character, messages)
    return replaced


def append_chat_pair(character: str, user_text: str, assistant_text: str):
    append_chat_message(character, {
        "role": "user",
        "type": "text",
        "content": user_text,
    })
    append_chat_message(character, {
        "role": "assistant",
        "type": "text",
        "content": strip_photo_prompt_block(assistant_text),
        "completed": True,
    })


def append_scene_transition(character: str, assistant_text: str, label: str = "新场景"):
    """Persist a scene boundary and its narration without a synthetic user bubble."""
    messages = read_chat_history(character)
    messages.append(normalize_message({
        "role": "system",
        "type": "scene_divider",
        "content": label,
    }))
    messages.append(normalize_message({
        "role": "assistant",
        "type": "text",
        "content": strip_photo_prompt_block(assistant_text),
        "completed": True,
    }))
    write_chat_history(character, messages)


def append_initial_scene(
    character: str,
    assistant_text: str,
    user_text: str = "",
    label: str = "故事开始",
):
    """Persist an opening boundary, optional first user line, and opening reply."""
    messages = read_chat_history(character)
    messages.append(normalize_message({
        "role": "system",
        "type": "scene_divider",
        "content": label,
    }))
    if str(user_text or "").strip():
        messages.append(normalize_message({
            "role": "user",
            "type": "text",
            "content": str(user_text).strip(),
        }))
    messages.append(normalize_message({
        "role": "assistant",
        "type": "text",
        "content": strip_photo_prompt_block(assistant_text),
        "completed": True,
    }))
    write_chat_history(character, messages)


def clear_chat_history(character: str):
    write_chat_history(character, [])


def normalize_message(message: dict) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    msg = dict(message or {})
    msg.setdefault("id", int(time.time() * 1000))
    msg.setdefault("role", "assistant")
    msg.setdefault("type", "text")
    msg.setdefault("content", "")
    msg.setdefault("timestamp", now)
    msg.setdefault("completed", True)
    return msg


def strip_photo_prompt_block(content: str) -> str:
    """Remove legacy image prompt text that leaked into chat bubbles."""
    if not content:
        return ""
    cleaned = PHOTO_PROMPT_RE.sub("", content).rstrip()
    return BARE_RATING_PROMPT_RE.sub("", cleaned).rstrip()


def has_photo_prompt_block(content: str) -> bool:
    if not content:
        return False
    lowered = content.lower()
    return (
        "\U0001f4f7" in content
        or "馃摲" in content
        or "rating:" in lowered
    )


def should_rebuild_from_daily(character: str, messages: list[dict]) -> bool:
    image_messages = load_image_history_messages(character)
    if not image_messages:
        return False
    legacy_urls = {
        m.get("imageUrl") or m.get("image_url")
        for m in image_messages
        if m.get("imageUrl") or m.get("image_url")
    }
    trailing = 0
    for msg in reversed(messages):
        if (msg.get("imageUrl") or msg.get("image_url")) in legacy_urls:
            trailing += 1
        else:
            break
    if trailing >= min(5, len(legacy_urls)):
        return any((settings.get_memory_dir(character)).glob("*.md"))

    previous_text_time = None
    for msg in messages:
        image_url = msg.get("imageUrl") or msg.get("image_url")
        if image_url in legacy_urls:
            image_time = _parse_timestamp(msg.get("timestamp"))
            if previous_text_time and image_time:
                if abs(image_time - previous_text_time) > timedelta(hours=6):
                    return any((settings.get_memory_dir(character)).glob("*.md"))
            continue
        if msg.get("type") in (None, "text") and msg.get("content"):
            previous_text_time = _parse_timestamp(msg.get("timestamp")) or previous_text_time
    return False


def repair_chat_history(character: str, messages: list[dict]) -> list[dict]:
    """Clean old prompt leakage and re-place legacy image records deterministically."""
    image_messages = load_image_history_messages(character)
    legacy_urls = {
        m.get("imageUrl") or m.get("image_url")
        for m in image_messages
        if m.get("imageUrl") or m.get("image_url")
    }

    cleaned = []
    photo_indices = []
    for message in messages:
        msg = dict(message or {})
        image_url = msg.get("imageUrl") or msg.get("image_url")
        if image_url in legacy_urls:
            continue
        if not image_url and isinstance(msg.get("content"), str):
            if msg.get("_photo_anchor") or has_photo_prompt_block(msg.get("content") or ""):
                photo_indices.append((len(cleaned), msg.get("timestamp")))
            msg["content"] = strip_photo_prompt_block(msg.get("content") or "")
        msg.pop("_photo_anchor", None)
        cleaned.append(msg)
    if not photo_indices:
        cleaned = []
        for message in messages:
            msg = dict(message or {})
            image_url = msg.get("imageUrl") or msg.get("image_url")
            if not image_url and isinstance(msg.get("content"), str):
                msg["content"] = strip_photo_prompt_block(msg.get("content") or "")
            msg.pop("_photo_anchor", None)
            cleaned.append(msg)
        return merge_image_history(character, cleaned, image_messages=image_messages)
    return merge_image_history(
        character,
        cleaned,
        image_messages=image_messages,
        photo_indices=photo_indices,
    )


def format_recent_chat_for_prompt(
    character: str,
    char_name: str,
    user_pet: str,
    max_messages: int = 40,
) -> str:
    lines = []
    for msg in read_chat_history(character, limit=max_messages):
        if msg.get("type") not in (None, "text"):
            continue
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        if msg.get("role") == "user":
            lines.append(f"{user_pet}: {content}")
        elif msg.get("role") == "assistant":
            lines.append(f"{char_name}: {content}")
    return "\n".join(lines)


def merge_image_history(
    character: str,
    messages: list[dict],
    image_messages: list[dict] | None = None,
    photo_indices: list | None = None,
) -> list[dict]:
    """Merge legacy image history into chat messages without duplicates."""
    image_messages = image_messages if image_messages is not None else load_image_history_messages(character)
    if not image_messages:
        return messages

    seen_urls = {
        m.get("imageUrl") or m.get("image_url")
        for m in messages
        if m.get("imageUrl") or m.get("image_url")
    }
    merged = list(messages)
    photo_indices = photo_indices if photo_indices is not None else _photo_text_message_indices(merged)
    image_targets = _match_images_to_photo_indices(image_messages, photo_indices)
    inserted = 0
    unmatched = []
    for idx, msg in enumerate(image_messages):
        if msg.get("imageUrl") in seen_urls:
            continue
        target_index = image_targets.get(idx)
        if target_index is not None:
            insert_at = target_index + 1 + inserted
            merged.insert(insert_at, msg)
            inserted += 1
        else:
            unmatched.append(msg)
        seen_urls.add(msg.get("imageUrl"))
    for msg in sorted(unmatched, key=lambda m: str(m.get("timestamp", ""))):
        insert_at = _chronological_insert_index(merged, msg.get("timestamp"))
        merged.insert(insert_at, msg)
    return merged


def _photo_text_message_indices(messages: list[dict]) -> list[int]:
    indices = []
    for idx, msg in enumerate(messages):
        if msg.get("role") != "assistant" or msg.get("imageUrl"):
            continue
        content = msg.get("content") or ""
        if msg.get("_photo_anchor") or has_photo_prompt_block(content):
            indices.append(idx)
    return indices


def _match_images_to_photo_indices(
    image_messages: list[dict],
    photo_indices: list,
) -> dict[int, int]:
    if not photo_indices:
        return {}
    if not isinstance(photo_indices[0], tuple):
        return {
            idx: photo_indices[idx]
            for idx in range(min(len(image_messages), len(photo_indices)))
        }

    anchors = [
        {
            "index": index,
            "timestamp": _parse_timestamp(timestamp),
            "used": False,
        }
        for index, timestamp in photo_indices
    ]
    targets = {}
    for image_idx, image_msg in enumerate(image_messages):
        image_time = _parse_timestamp(image_msg.get("timestamp"))
        candidate = None
        if image_time:
            for anchor in anchors:
                anchor_time = anchor["timestamp"]
                if anchor["used"] or not anchor_time:
                    continue
                delta = image_time - anchor_time
                if timedelta(0) <= delta <= timedelta(hours=2):
                    if candidate is None or anchor_time > candidate["timestamp"]:
                        candidate = anchor
        if candidate is None:
            continue
        candidate["used"] = True
        targets[image_idx] = candidate["index"]
    return targets


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _chronological_insert_index(messages: list[dict], timestamp: str | None) -> int:
    target_time = _parse_timestamp(timestamp)
    if not target_time:
        return len(messages)
    for idx, message in enumerate(messages):
        message_time = _parse_timestamp(message.get("timestamp"))
        if message_time and message_time > target_time:
            return idx
    return len(messages)


def load_image_history_messages(character: str) -> list[dict]:
    path = settings.get_images_dir(character) / "_history.json"
    if not path.exists():
        return []
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(items, list):
        return []

    result = []
    for index, item in enumerate(items):
        image_url = item.get("image_url") or item.get("imageUrl")
        if not image_url:
            continue
        image_path = item.get("image_path") or ""
        timestamp = _image_timestamp(image_path)
        result.append(normalize_message({
            "id": f"image_{character}_{Path(image_url).stem}_{index}",
            "role": "assistant",
            "type": "image",
            "content": "",
            "imageUrl": image_url,
            "prompt": item.get("prompt", ""),
            "timestamp": timestamp,
            "completed": True,
        }))
    return sorted(result, key=lambda m: str(m.get("timestamp", "")))


def _image_timestamp(image_path: str) -> str:
    try:
        path = Path(image_path)
        if path.exists():
            return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except Exception:
        pass
    return datetime.now(timezone.utc).isoformat()


def migrate_daily_memory_to_chat_history(character: str) -> list[dict]:
    """Best-effort migration from YYYY-MM-DD.md daily logs."""
    memory_dir = settings.get_memory_dir(character)
    if not memory_dir.exists():
        return []

    try:
        from .context import get_character_name
        char_name = get_character_name(character)
    except Exception:
        char_name = character

    messages = []
    for path in sorted(memory_dir.glob("*.md")):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        messages.extend(_parse_daily_markdown(path.stem, text, char_name))
    return messages[-MAX_CHAT_MESSAGES:]


def _parse_daily_markdown(date_str: str, text: str, char_name: str) -> list[dict]:
    matches = list(DAILY_HEADER_RE.finditer(text))
    result = []
    last_time = "00:00"
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        raw_content = text[start:end].strip()
        content = strip_photo_prompt_block(raw_content)
        if not content:
            continue
        speaker = match.group(2).strip()
        role = "assistant" if speaker == char_name else "user"
        time_part = match.group(1) or last_time
        last_time = time_part
        timestamp = f"{date_str}T{time_part}:00+08:00"
        result.append(normalize_message({
            "id": f"{date_str}_{time_part}_{index}",
            "role": role,
            "type": "text",
            "content": content,
            "_photo_anchor": has_photo_prompt_block(raw_content),
            "timestamp": timestamp,
            "completed": True,
        }))
    return result
