"""Memory policy and recall orchestration.

This module keeps the runtime rules for chat context, vector recall, and
turn-based memory condensation in one place so the UI/API can change those
knobs later without touching the agent prompt assembly.
"""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from ..config import settings
from .chat_history import read_chat_history
from .compressor import compress_conversation, estimate_tokens
from .context import load_conversation_summary, load_long_term, save_conversation_summary
from .memory_v3 import filter_recalled_memories, should_recall_vector_memory
from .vector_store import MAX_VECTORS, VectorStore

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_SETTINGS = {
    "condensation_days": 1,
    "retention_days": 30,
    "turns_per_condense": 15,
    "vector_recall_enabled": True,
    "vector_top_k": 5,
    "vector_max_distance": 0.55,
}


def load_settings_json() -> dict:
    path = settings.settings_file
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def memory_settings() -> dict:
    raw = load_settings_json().get("memory", {})
    return {**DEFAULT_MEMORY_SETTINGS, **(raw or {})}


def context_settings() -> dict:
    raw = load_settings_json().get("context", {})
    return {
        "max_tokens": int(raw.get("max_tokens", 8000) or 8000),
        "compress_at": float(raw.get("compress_at", 0.9) or 0.9),
    }


def runtime_state_path(character: str) -> Path:
    return settings.get_memory_dir(character) / "memory_runtime.json"


def load_runtime_state(character: str) -> dict:
    path = runtime_state_path(character)
    if not path.exists():
        return {"turns_since_condense": 0, "compressed_message_count": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {"turns_since_condense": 0, "compressed_message_count": 0, **data}
    except Exception:
        return {"turns_since_condense": 0, "compressed_message_count": 0}


def save_runtime_state(character: str, data: dict):
    path = runtime_state_path(character)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def bump_turn_and_should_condense(character: str) -> bool:
    cfg = memory_settings()
    interval = int(cfg.get("turns_per_condense") or 0)
    if interval <= 0:
        return False
    state = load_runtime_state(character)
    state["turns_since_condense"] = int(state.get("turns_since_condense") or 0) + 1
    state["last_turn_at"] = datetime.now(timezone.utc).isoformat()
    should = state["turns_since_condense"] >= interval
    if should:
        state["turns_since_condense"] = 0
        state["last_condense_trigger"] = "turn_interval"
        state["last_condense_at"] = state["last_turn_at"]
    save_runtime_state(character, state)
    return should


def reset_condense_counter(character: str, trigger: str = "manual"):
    state = load_runtime_state(character)
    state["turns_since_condense"] = 0
    state["last_condense_trigger"] = trigger
    state["last_condense_at"] = datetime.now(timezone.utc).isoformat()
    save_runtime_state(character, state)


def vector_store(character: str) -> VectorStore:
    return VectorStore(settings.get_vector_dir(character))


def index_chat_pair(character: str, user_text: str, assistant_text: str):
    """Persist one completed text turn into the per-character vector store."""
    if not user_text.strip() and not assistant_text.strip():
        return
    store = vector_store(character)
    today = datetime.now().date().isoformat()
    doc = f"用户：{user_text.strip()}\n角色：{assistant_text.strip()}"
    store.add(
        [doc],
        [{
            "source": "chat_history",
            "date": today,
            "type": "dialogue_turn",
            "importance": 1,
            "character": character,
            "tags": ["chat"],
        }],
    )
    cfg = memory_settings()
    store.cleanup_old(
        max_count=MAX_VECTORS,
        retention_days=int(cfg.get("retention_days") or 0),
    )


def recall_vector_context(character: str, user_message: str) -> str:
    """Return formatted vector recall only when the user asks for old details."""
    cfg = memory_settings()
    if not cfg.get("vector_recall_enabled", True):
        return ""
    if not should_recall_vector_memory(user_message):
        return ""
    if _long_term_likely_answers(character, user_message):
        return ""

    top_k = int(cfg.get("vector_top_k") or 5)
    max_distance = float(cfg.get("vector_max_distance") or 0.55)
    items = filter_recalled_memories(
        vector_store(character).query(user_message, top_k=top_k),
        max_distance=max_distance,
    )
    if not items:
        return ""

    lines = []
    for item in items:
        meta = item.get("metadata") or {}
        date = meta.get("date") or "unknown-date"
        distance = item.get("distance")
        suffix = f" distance={distance:.3f}" if isinstance(distance, (int, float)) else ""
        lines.append(f"- [{date}{suffix}] {item.get('content', '').strip()}")
    return "\n".join(lines)


def _long_term_likely_answers(character: str, user_message: str) -> bool:
    long_term = load_long_term(character)
    if not long_term.strip():
        return False
    keywords = _keywords(user_message)
    if not keywords:
        return False
    hits = sum(1 for word in keywords if word in long_term)
    return hits >= min(2, len(keywords))


def _keywords(text: str) -> list[str]:
    cleaned = re.sub(
        r"(还记得|记得|之前|以前|上次|那天|昨天|前天|吗|么|呢|什么|哪个|哪些|怎么|是不是)",
        " ",
        text or "",
    )
    words = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{3,}", cleaned)
    return [w for w in words if len(w.strip()) >= 2][:8]


def format_chat_messages(messages: list[dict], char_name: str, user_label: str) -> str:
    lines = []
    for msg in messages:
        if msg.get("type") not in (None, "text"):
            continue
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        if msg.get("role") == "user":
            lines.append(f"{user_label}: {content}")
        elif msg.get("role") == "assistant":
            lines.append(f"{char_name}: {content}")
    return "\n".join(lines)


async def build_context_window(
    llm_client,
    character: str,
    char_name: str,
    user_label: str,
    base_prompt: str,
    system_prompt: str,
) -> tuple[str, str]:
    """Build summary + recent chat, compressing older turns at the configured limit."""
    cfg = context_settings()
    max_tokens = cfg["max_tokens"]
    threshold = cfg["compress_at"]
    limit_tokens = int(max_tokens * threshold)

    all_messages = [
        m for m in read_chat_history(character)
        if m.get("type") in (None, "text") and (m.get("content") or "").strip()
    ]
    state = load_runtime_state(character)
    compressed_count = min(
        int(state.get("compressed_message_count") or 0),
        len(all_messages),
    )
    messages = all_messages[compressed_count:]
    if not messages:
        return load_conversation_summary(character), ""

    summary = load_conversation_summary(character)
    recent: list[dict] = []
    for msg in reversed(messages):
        candidate = [msg] + recent
        chat_history = format_chat_messages(candidate, char_name, user_label)
        total = estimate_tokens(system_prompt + base_prompt + (summary or "") + chat_history)
        if total > limit_tokens and recent:
            break
        recent = candidate

    old_count = max(0, len(messages) - len(recent))
    if old_count <= 0:
        return summary, format_chat_messages(recent, char_name, user_label)

    old_text = format_chat_messages(messages[:old_count], char_name, user_label)
    if old_text.strip():
        new_summary = await compress_conversation(llm_client, summary, old_text)
        if new_summary and new_summary.strip() != (summary or "").strip():
            save_conversation_summary(character, new_summary)
            summary = new_summary
            state["compressed_message_count"] = compressed_count + old_count
            state["last_compressed_at"] = datetime.now(timezone.utc).isoformat()
            save_runtime_state(character, state)
            logger.info("Conversation summary compressed for %s (%s old messages)", character, old_count)

    return summary, format_chat_messages(recent, char_name, user_label)
