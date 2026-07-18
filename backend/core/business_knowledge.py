"""Progressive loading for a small set of global business manuals."""

from __future__ import annotations

import logging
import json
from pathlib import Path
import threading

from ..config import settings
from ..utils.helpers import read_markdown

logger = logging.getLogger(__name__)

_cache_lock = threading.RLock()
_router_cache: tuple[Path, int, dict] | None = None
_markdown_cache: dict[Path, tuple[int, str]] = {}


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return -1


def _read_cached_markdown(path: Path) -> str:
    modified = _mtime_ns(path)
    if modified < 0:
        return ""
    with _cache_lock:
        cached = _markdown_cache.get(path)
        if cached and cached[0] == modified:
            return cached[1]
    try:
        content = read_markdown(path).strip()
    except Exception as exc:
        logger.warning("Failed to load business knowledge %s: %s", path.name, exc)
        return ""
    with _cache_lock:
        _markdown_cache[path] = (modified, content)
    return content

def load_relevant_knowledge(user_message: str, recent_context: str = "") -> str:
    domains = route_domains(user_message, recent_context)
    parts: list[str] = []
    for domain in domains:
        path = knowledge_dir() / f"{domain}.md"
        if path.exists():
            parts.append(_read_cached_markdown(path))
    if parts:
        logger.info("Loaded business knowledge domains: %s", ", ".join(domains))
    return "\n\n".join(part for part in parts if part)


def route_domains(user_message: str, recent_context: str = "") -> list[str]:
    current = (user_message or "").lower()
    # Recent context only carries an unfinished topic forward for vague turns;
    # explicit current input remains the primary signal.
    vague = len(current.strip()) <= 12 or current.strip() in {"继续", "那继续吧", "然后呢", "好", "可以"}
    searchable = current + (("\n" + (recent_context or "")[-800:]) if vague else "")
    config = load_router_config()
    return [domain for domain, item in config.items() if any(
        str(signal).lower() in searchable for signal in item.get("signals", [])
    )]


def load_router_config() -> dict:
    """Load editable domain signals; no Python change is needed to tune routing."""
    global _router_cache
    path = knowledge_dir() / "router.json"
    modified = _mtime_ns(path)
    if modified < 0:
        return {}
    with _cache_lock:
        if _router_cache and _router_cache[0] == path and _router_cache[1] == modified:
            return _router_cache[2]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        result = data if isinstance(data, dict) else {}
        with _cache_lock:
            _router_cache = (path, modified, result)
        return result
    except Exception as exc:
        logger.warning("Failed to load business knowledge router: %s", exc)
        return {}


def knowledge_dir() -> Path:
    return settings.config_dir / "knowledge"
