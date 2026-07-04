"""Lightweight runtime diagnostics that avoid web-server dependencies.

Usage:
    python scripts/diagnose_runtime.py [character]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHARACTERS = ROOT / "characters"
SETTINGS = ROOT / "config" / "settings.json"

CLOTHING_HINTS = (
    "shirt",
    "skirt",
    "shorts",
    "pants",
    "dress",
    "bra",
    "panties",
    "shoe",
    "boot",
    "mary_jane",
    "sock",
    "thighhigh",
    "stocking",
    "barefoot",
    "topless",
    "bottomless",
    "nude",
    "naked",
    "collar",
    "necklace",
)


def estimate_tokens(text: str) -> int:
    chinese = sum(1 for c in text if "\u4e00" <= c <= "\u9fff" or "\u3400" <= c <= "\u4dbf")
    others = len(text) - chinese
    return int(chinese * 1.5 + others * 0.3)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def section(text: str, title: str) -> str:
    match = re.search(rf"## {re.escape(title)}\n(.*?)(?=## |\Z)", text, re.DOTALL)
    return match.group(1).strip() if match else ""


def tags(text: str) -> list[str]:
    result = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("-"):
            line = line[1:].strip()
        for item in line.split(","):
            item = item.strip().replace(" ", "_").lower()
            if item and item not in result:
                result.append(item)
    return result


def looks_like_clothing(tag: str) -> bool:
    return any(hint in tag for hint in CLOTHING_HINTS)


def diagnose_character(character: str) -> dict:
    char_dir = CHARACTERS / character
    memory_dir = char_dir / "memory"
    status = read_text(memory_dir / "status.md")
    chat_data = read_json(memory_dir / "chat_history.json", {"messages": []})
    messages = chat_data.get("messages", chat_data if isinstance(chat_data, list) else [])
    summary = read_text(memory_dir / "conversation_summary.md")
    long_term = read_text(memory_dir / "long_term.md")
    identity = read_text(char_dir / "identity.md")
    agent = read_text(ROOT / "config" / "agent.md")
    photo_rules = read_text(ROOT / "config" / "photo_rules.md")
    settings = read_json(SETTINGS, {})

    fixed_context = "\n\n".join([agent, identity, status, photo_rules, long_term, summary])
    outfit = tags(section(status, "穿着"))
    image_history = read_json(char_dir / "images" / "_history.json", [])
    prompt_warnings = []
    for item in image_history[-5:]:
        prompt_tags = tags(item.get("prompt", ""))
        clothing_in_prompt = [tag for tag in prompt_tags if looks_like_clothing(tag)]
        duplicate_state_tags = [tag for tag in clothing_in_prompt if tag in outfit]
        conflicting_barefoot = "barefoot" in prompt_tags and any(
            hint in tag for tag in prompt_tags for hint in ("shoe", "sock", "thighhigh", "stocking")
        )
        if duplicate_state_tags or conflicting_barefoot:
            prompt_warnings.append({
                "image_url": item.get("image_url") or item.get("imageUrl"),
                "duplicate_state_tags": duplicate_state_tags,
                "conflicting_barefoot": conflicting_barefoot,
            })

    return {
        "character": character,
        "context_settings": settings.get("context", {}),
        "fixed_context_estimated_tokens": estimate_tokens(fixed_context),
        "chat_text_messages": len([
            m for m in messages
            if m.get("type") in (None, "text") and (m.get("content") or "").strip()
        ]),
        "outfit_tags": outfit,
        "summary_has_think_block": "<think>" in summary or "</think>" in summary,
        "recent_image_prompt_warnings": prompt_warnings,
    }


def main() -> int:
    if len(sys.argv) > 1:
        characters = [sys.argv[1]]
    else:
        characters = sorted(p.name for p in CHARACTERS.iterdir() if p.is_dir())
    print(json.dumps([diagnose_character(c) for c in characters], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
