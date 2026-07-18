"""Memory policy and recall orchestration.

This module keeps the runtime rules for chat context, vector recall, and
turn-based memory condensation in one place so the UI/API can change those
knobs later without touching the agent prompt assembly.
"""

import json
import hashlib
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..config import settings
from .chat_history import read_chat_history
from .compressor import estimate_tokens
from .context import load_conversation_summary, load_long_term, save_conversation_summary
from .memory_v3 import filter_recalled_memories, should_recall_vector_memory
from .vector_store import MAX_VECTORS, VectorStore

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_SETTINGS = {
    "condensation_days": 1,
    "retention_days": 30,
    "long_term_turns_per_condense": 15,
    "soul_turns_per_condense": 15,
    "vector_recall_enabled": True,
    "vector_top_k": 5,
    "vector_max_distance": 0.55,
}

CONDENSE_TARGETS = ("long_term", "soul")

MIN_CONTEXT_TOKENS = 8000
DEFAULT_CONTEXT_TOKENS = 16000
MAX_CONTEXT_TOKENS = 1_048_576
MIN_RECENT_MESSAGES = 12
VECTOR_WRITE_BATCH_SIZE = 32
VECTOR_CLEANUP_EVERY_WRITES = 50

_runtime_state_locks: dict[str, threading.RLock] = {}
_runtime_state_locks_guard = threading.Lock()
_vector_cache_guard = threading.Lock()
_vector_stores: dict[str, VectorStore] = {}
_vector_locks: dict[str, threading.RLock] = {}
_pending_vector_writes: dict[str, list[dict]] = {}
_vector_cleanup_write_counts: dict[str, int] = {}
_settings_cache: tuple[Path, int, dict] | None = None


@dataclass(frozen=True)
class ContextCompressionPlan:
    """Frozen old-history slice that can be summarized off the live path."""

    character: str
    old_summary: str
    turns_to_compress: str
    through_fingerprint: str
    expected_cursor_fingerprint: str
    message_count: int


@dataclass(frozen=True)
class ContextWindow:
    summary: str
    chat_history: str
    compression_plan: ContextCompressionPlan | None = None


def _runtime_state_lock(character: str) -> threading.RLock:
    with _runtime_state_locks_guard:
        return _runtime_state_locks.setdefault(character, threading.RLock())


def load_settings_json() -> dict:
    global _settings_cache
    path = settings.settings_file
    try:
        modified = path.stat().st_mtime_ns
    except OSError:
        return {}
    with _runtime_state_locks_guard:
        if _settings_cache and _settings_cache[0] == path and _settings_cache[1] == modified:
            return _settings_cache[2]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        result = data if isinstance(data, dict) else {}
        with _runtime_state_locks_guard:
            _settings_cache = (path, modified, result)
        return result
    except Exception:
        return {}


def memory_settings() -> dict:
    raw = load_settings_json().get("memory", {})
    merged = {**DEFAULT_MEMORY_SETTINGS, **(raw or {})}
    legacy_interval = int(merged.get("turns_per_condense") or 0)
    if "long_term_turns_per_condense" not in (raw or {}) and legacy_interval:
        merged["long_term_turns_per_condense"] = legacy_interval
    if "soul_turns_per_condense" not in (raw or {}) and legacy_interval:
        merged["soul_turns_per_condense"] = legacy_interval
    return merged


def context_settings() -> dict:
    return normalize_context_settings(load_settings_json().get("context", {}))


def normalize_context_settings(raw: dict | None) -> dict:
    raw = raw or {}
    try:
        configured_max = int(raw.get("max_tokens", DEFAULT_CONTEXT_TOKENS) or DEFAULT_CONTEXT_TOKENS)
    except (TypeError, ValueError):
        configured_max = DEFAULT_CONTEXT_TOKENS
    try:
        compress_at = float(raw.get("compress_at", 0.85) or 0.85)
    except (TypeError, ValueError):
        compress_at = 0.85
    return {
        "max_tokens": min(MAX_CONTEXT_TOKENS, max(MIN_CONTEXT_TOKENS, configured_max)),
        "compress_at": min(0.95, max(0.5, compress_at)),
    }


def runtime_state_path(character: str) -> Path:
    return settings.get_memory_dir(character) / "memory_runtime.json"


def load_runtime_state(character: str) -> dict:
    path = runtime_state_path(character)
    base = {
        "turns_since_condense": 0,
        "compressed_message_count": 0,
        "long_term_turns_since_condense": 0,
        "soul_turns_since_condense": 0,
    }
    with _runtime_state_lock(character):
        if not path.exists():
            return base
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            state = {**base, **data}
            legacy_turns = int(state.get("turns_since_condense") or 0)
            for target in CONDENSE_TARGETS:
                key = f"{target}_turns_since_condense"
                if not state.get(key) and legacy_turns:
                    state[key] = legacy_turns
            return state
        except Exception:
            return base


def save_runtime_state(character: str, data: dict):
    path = runtime_state_path(character)
    with _runtime_state_lock(character):
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, path)


def bump_turn_and_due_targets(character: str) -> list[str]:
    with _runtime_state_lock(character):
        cfg = memory_settings()
        state = load_runtime_state(character)
        state["last_turn_at"] = datetime.now(timezone.utc).isoformat()
        state["turns_since_condense"] = int(state.get("turns_since_condense") or 0) + 1

        due_targets = []
        for target in CONDENSE_TARGETS:
            interval = int(cfg.get(f"{target}_turns_per_condense") or 0)
            key = f"{target}_turns_since_condense"
            state[key] = int(state.get(key) or 0) + 1
            if interval <= 0 or state.get(f"{target}_condense_in_progress"):
                continue
            if state[key] >= interval:
                state[f"{target}_last_condense_trigger"] = "turn_interval"
                state[f"{target}_last_condense_started_at"] = state["last_turn_at"]
                state[f"{target}_condense_in_progress"] = True
                due_targets.append(target)

        if due_targets:
            state["last_condense_trigger"] = "turn_interval"
            state["last_condense_started_at"] = state["last_turn_at"]
            state["condense_in_progress"] = True
        save_runtime_state(character, state)
        return due_targets


def bump_turn_and_should_condense(character: str) -> bool:
    return bool(bump_turn_and_due_targets(character))


def normalize_condense_target(target: str | None) -> str:
    value = (target or "all").strip()
    if value in ("memory", "long-term", "longterm"):
        return "long_term"
    if value in (*CONDENSE_TARGETS, "all"):
        return value
    return "all"


def condense_targets_for(target: str | None) -> tuple[str, ...]:
    normalized = normalize_condense_target(target)
    if normalized == "all":
        return CONDENSE_TARGETS
    return (normalized,)


def reset_condense_counter(character: str, trigger: str = "manual", target: str = "all"):
    with _runtime_state_lock(character):
        state = load_runtime_state(character)
        now = datetime.now(timezone.utc).isoformat()
        for item in condense_targets_for(target):
            state[f"{item}_turns_since_condense"] = 0
            state[f"{item}_last_condense_trigger"] = trigger
            state[f"{item}_last_condense_at"] = now
            state[f"{item}_condense_in_progress"] = False
            state.pop(f"{item}_last_condense_error", None)
        if target in ("all", None):
            state["turns_since_condense"] = 0
        state["last_condense_trigger"] = trigger
        state["last_condense_at"] = now
        state["condense_in_progress"] = any(
            state.get(f"{item}_condense_in_progress") for item in CONDENSE_TARGETS
        )
        state.pop("last_condense_error", None)
        save_runtime_state(character, state)


def mark_condense_failed(character: str, trigger: str = "manual", error: str = "", target: str = "all"):
    with _runtime_state_lock(character):
        state = load_runtime_state(character)
        now = datetime.now(timezone.utc).isoformat()
        for item in condense_targets_for(target):
            state[f"{item}_last_condense_trigger"] = trigger
            state[f"{item}_last_condense_failed_at"] = now
            state[f"{item}_condense_in_progress"] = False
            if error:
                state[f"{item}_last_condense_error"] = error[:500]
        state["last_condense_trigger"] = trigger
        state["last_condense_failed_at"] = now
        state["condense_in_progress"] = any(
            state.get(f"{item}_condense_in_progress") for item in CONDENSE_TARGETS
        )
        if error:
            state["last_condense_error"] = error[:500]
        save_runtime_state(character, state)


def vector_store(character: str) -> VectorStore:
    """Return one process-local Chroma wrapper per character directory."""
    directory = settings.get_vector_dir(character)
    with _vector_cache_guard:
        store = _vector_stores.get(character)
        if store is None or store._persist_directory != directory:
            store = VectorStore(directory)
            _vector_stores[character] = store
        _vector_locks.setdefault(character, threading.RLock())
        return store


def clear_vector_store_cache(character: str | None = None):
    """Drop wrappers before a character vector directory is reset or deleted."""
    if character is not None:
        lock = _vector_lock(character)
        with lock:
            with _vector_cache_guard:
                _vector_stores.pop(character, None)
                _vector_locks.pop(character, None)
                _pending_vector_writes.pop(character, None)
                _vector_cleanup_write_counts.pop(character, None)
        return
    with _vector_cache_guard:
        _vector_stores.clear()
        _vector_locks.clear()
        _pending_vector_writes.clear()
        _vector_cleanup_write_counts.clear()


def _vector_lock(character: str) -> threading.RLock:
    with _vector_cache_guard:
        return _vector_locks.setdefault(character, threading.RLock())


def _vector_record(character: str, user_text: str, assistant_text: str) -> dict | None:
    if not user_text.strip() and not assistant_text.strip():
        return None
    today = datetime.now().date().isoformat()
    return {
        "document": f"用户：{user_text.strip()}\n角色：{assistant_text.strip()}",
        "metadata": {
            "source": "chat_history",
            "date": today,
            "type": "dialogue_turn",
            "importance": 1,
            "character": character,
            "tags": ["chat"],
        },
    }


def queue_vector_chat_pair(character: str, user_text: str, assistant_text: str) -> bool:
    """Append a completed turn to the in-memory vector write queue."""
    record = _vector_record(character, user_text, assistant_text)
    if record is None:
        return False
    with _vector_lock(character):
        _pending_vector_writes.setdefault(character, []).append(record)
    return True


def has_pending_vector_writes(character: str) -> bool:
    with _vector_lock(character):
        return bool(_pending_vector_writes.get(character))


def flush_pending_vector_writes(character: str) -> int:
    """Persist one bounded queue batch; returns the number written."""
    with _vector_lock(character):
        pending = _pending_vector_writes.get(character) or []
        if not pending:
            return 0
        batch = pending[:VECTOR_WRITE_BATCH_SIZE]
        del pending[:len(batch)]
        if not pending:
            _pending_vector_writes.pop(character, None)

        store = vector_store(character)
        written = store.add(
            [item["document"] for item in batch],
            [item["metadata"] for item in batch],
        )
        if not written:
            _pending_vector_writes.setdefault(character, [])[:0] = batch
            return -1

        write_count = _vector_cleanup_write_counts.get(character, 0) + len(batch)
        if write_count >= VECTOR_CLEANUP_EVERY_WRITES:
            cfg = memory_settings()
            store.cleanup_old(
                max_count=MAX_VECTORS,
                retention_days=int(cfg.get("retention_days") or 0),
            )
            write_count = 0
        _vector_cleanup_write_counts[character] = write_count
        return len(batch)


def _pending_vector_items(character: str, user_message: str, top_k: int) -> list[dict]:
    """Expose queued turns immediately when recall is requested before flush."""
    with _vector_lock(character):
        pending = list(_pending_vector_writes.get(character) or [])
    if not pending:
        return []
    keywords = _keywords(user_message)
    scored = []
    for index, item in enumerate(pending):
        text = item["document"]
        score = sum(1 for word in keywords if word and word in text)
        scored.append((score, index, item))
    scored.sort(key=lambda value: (value[0], value[1]), reverse=True)
    return [
        {"content": item["document"], "metadata": item["metadata"], "distance": None}
        for _score, _index, item in scored[:top_k]
    ]


def index_chat_pair(character: str, user_text: str, assistant_text: str):
    """Compatibility entry point for callers that require a synchronous flush."""
    if queue_vector_chat_pair(character, user_text, assistant_text):
        while flush_pending_vector_writes(character):
            pass


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
    with _vector_lock(character):
        persisted = vector_store(character).query(user_message, top_k=top_k)
    items = filter_recalled_memories(
        _pending_vector_items(character, user_message, top_k) + persisted,
        max_distance=max_distance,
    )[:top_k]
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


def _message_fingerprint(message: dict) -> str:
    payload = "\x1f".join((
        str(message.get("id") or ""),
        str(message.get("role") or ""),
        str(message.get("content") or ""),
    ))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _context_summary(character: str, state: dict | None = None) -> str:
    """Prefer the summary stored atomically beside its cursor."""
    current_state = state if state is not None else load_runtime_state(character)
    if "conversation_summary" in current_state:
        return str(current_state.get("conversation_summary") or "")
    return load_conversation_summary(character)


def _uncompressed_start(messages: list[dict], state: dict) -> int:
    cursor = str(state.get("compressed_through_fingerprint") or "")
    if cursor:
        for index, message in enumerate(messages):
            if _message_fingerprint(message) == cursor:
                return index + 1
        # The chat log keeps a bounded tail. If the cursor has fallen out of
        # that tail, every remaining message is newer than the summary.
        return 0
    return min(int(state.get("compressed_message_count") or 0), len(messages))


async def prepare_context_window(
    llm_client,
    character: str,
    char_name: str,
    user_label: str,
    base_prompt: str,
    system_prompt: str,
    all_messages: list[dict] | None = None,
) -> ContextWindow:
    """Select recent dialogue linearly and freeze any history to compress."""
    del llm_client  # Kept in the signature for caller/API compatibility.
    cfg = context_settings()
    max_tokens = cfg["max_tokens"]
    limit_tokens = int(max_tokens * cfg["compress_at"])

    source_messages = all_messages if all_messages is not None else read_chat_history(character)
    text_messages = [
        message for message in source_messages
        if message.get("type") in (None, "text")
        and (message.get("content") or "").strip()
        and message.get("role") in ("user", "assistant")
    ]
    state = load_runtime_state(character)
    summary = _context_summary(character, state)
    start = _uncompressed_start(text_messages, state)
    uncompressed = text_messages[start:]
    if not uncompressed:
        return ContextWindow(summary=summary, chat_history="")

    # Format and count each message once. The compression threshold starts an
    # early background job; it is deliberately separate from the model's hard
    # context budget, so history is not hidden merely because compression has
    # started but not yet finished.
    fixed_tokens = estimate_tokens(system_prompt + base_prompt + summary)
    message_tokens = [
        estimate_tokens(format_chat_messages([message], char_name, user_label)) + 1
        for message in uncompressed
    ]

    def select_recent(budget: int) -> list[dict]:
        used_tokens = fixed_tokens
        selected = 0
        for token_count in reversed(message_tokens):
            if used_tokens + token_count > budget and selected >= MIN_RECENT_MESSAGES:
                break
            used_tokens += token_count
            selected += 1
        return uncompressed[len(uncompressed) - selected:]

    compression_recent = select_recent(limit_tokens)
    old_count = len(uncompressed) - len(compression_recent)

    # Keep a user message together with its following assistant response. It
    # is better to retain one extra message than summarize half a turn.
    if old_count > 0 and uncompressed[old_count - 1].get("role") == "user":
        old_count -= 1
        compression_recent = uncompressed[old_count:]

    live_recent = select_recent(max_tokens)
    live_old_count = len(uncompressed) - len(live_recent)
    if live_old_count > 0 and uncompressed[live_old_count - 1].get("role") == "user":
        live_old_count -= 1
        live_recent = uncompressed[live_old_count:]

    plan = None
    if old_count > 0:
        old_messages = uncompressed[:old_count]
        turns = format_chat_messages(old_messages, char_name, user_label)
        if turns.strip():
            plan = ContextCompressionPlan(
                character=character,
                old_summary=summary,
                turns_to_compress=turns,
                through_fingerprint=_message_fingerprint(old_messages[-1]),
                expected_cursor_fingerprint=str(state.get("compressed_through_fingerprint") or ""),
                message_count=len(old_messages),
            )
        logger.info(
            "Context compression planned for %s: recent=%s old=%s max_tokens=%s",
            character,
            len(compression_recent),
            old_count,
            max_tokens,
        )

    return ContextWindow(
        summary=summary,
        chat_history=format_chat_messages(live_recent, char_name, user_label),
        compression_plan=plan,
    )


def commit_context_compression(plan: ContextCompressionPlan, new_summary: str) -> bool:
    """Atomically advance the authoritative summary and its history cursor."""
    summary = str(new_summary or "").strip()
    if not summary or summary == plan.old_summary.strip():
        return False

    character = plan.character
    with _runtime_state_lock(character):
        state = load_runtime_state(character)
        if _context_summary(character, state).strip() != plan.old_summary.strip():
            logger.info("Discarded stale context summary for %s (summary advanced)", character)
            return False
        current_cursor = str(state.get("compressed_through_fingerprint") or "")
        if current_cursor != plan.expected_cursor_fingerprint:
            logger.info("Discarded stale context summary for %s (cursor advanced)", character)
            return False

        messages = [
            message for message in read_chat_history(character, repair=False)
            if message.get("type") in (None, "text")
            and (message.get("content") or "").strip()
            and message.get("role") in ("user", "assistant")
        ]
        through_index = next(
            (
                index for index, message in enumerate(messages)
                if _message_fingerprint(message) == plan.through_fingerprint
            ),
            None,
        )
        if through_index is None:
            logger.warning("Context compression cursor disappeared for %s; summary not committed", character)
            return False

        now = datetime.now(timezone.utc).isoformat()
        state["conversation_summary"] = summary
        state["compressed_through_fingerprint"] = plan.through_fingerprint
        state["compressed_message_count"] = through_index + 1
        state["last_context_compressed_at"] = now
        state["last_context_compressed_messages"] = plan.message_count
        save_runtime_state(character, state)

    # memory_runtime.json is authoritative and commits summary + cursor in one
    # replace. Markdown remains a readable projection for diagnostics/UI.
    try:
        save_conversation_summary(character, summary + "\n")
    except Exception as exc:
        logger.warning("Conversation summary projection failed for %s: %s", character, exc)
    return True


async def build_context_window(
    llm_client,
    character: str,
    char_name: str,
    user_label: str,
    base_prompt: str,
    system_prompt: str,
    all_messages: list[dict] | None = None,
) -> tuple[str, str]:
    """Compatibility wrapper returning only summary and recent chat."""
    window = await prepare_context_window(
        llm_client,
        character,
        char_name,
        user_label,
        base_prompt,
        system_prompt,
        all_messages=all_messages,
    )
    return window.summary, window.chat_history
