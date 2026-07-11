"""Progressive loading for a small set of global business manuals."""

from __future__ import annotations

import logging
import json
from pathlib import Path

from ..config import settings
from ..utils.helpers import read_markdown

logger = logging.getLogger(__name__)

def load_relevant_knowledge(user_message: str, recent_context: str = "") -> str:
    domains = route_domains(user_message, recent_context)
    parts: list[str] = []
    for domain in domains:
        path = knowledge_dir() / f"{domain}.md"
        if path.exists():
            parts.append(read_markdown(path).strip())
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
    path = knowledge_dir() / "router.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Failed to load business knowledge router: %s", exc)
        return {}


def knowledge_dir() -> Path:
    return settings.config_dir / "knowledge"
