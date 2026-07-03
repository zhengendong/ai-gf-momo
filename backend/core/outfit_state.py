"""Outfit tag parsing and normalization.

This module does not decide what a character should do. It only keeps the
outfit state internally consistent once the Agent has produced tags.
"""

from __future__ import annotations

from typing import Any

FOOTWEAR_HINTS = (
    "shoe",
    "shoes",
    "boot",
    "boots",
    "sneaker",
    "sneakers",
    "sandal",
    "sandals",
    "mary_jane",
    "loafers",
    "heels",
)

LEGWEAR_HINTS = (
    "sock",
    "socks",
    "thighhigh",
    "thighhighs",
    "stocking",
    "stockings",
    "pantyhose",
    "tights",
)

TOP_HINTS = (
    "shirt",
    "blouse",
    "sweater",
    "hoodie",
    "jacket",
    "bra",
    "bikini_top",
    "sailor_uniform",
)

BOTTOM_HINTS = (
    "skirt",
    "pants",
    "shorts",
    "jeans",
    "panties",
    "bikini_bottom",
)

ACCESSORY_HINTS = (
    "necklace",
    "collar",
    "choker",
    "ring",
    "earrings",
    "bracelet",
    "ribbon",
    "hair_ornament",
    "glasses",
)

FULL_NUDE_TAGS = {"completely_nude", "nude", "naked", "bare_body"}
PERSISTENT_OUTFIT_STATE_TAGS = FULL_NUDE_TAGS | {
    "barefoot",
    "topless",
    "bottomless",
    "no_bra",
    "no_panties",
    "naked_apron",
}


def normalize_outfit_tags(tags: list[str]) -> list[str]:
    """Return a conflict-free outfit tag list while preserving input order."""
    normalized = _dedupe([_norm_tag(tag) for tag in tags if _norm_tag(tag)])
    tag_set = set(normalized)

    if tag_set & FULL_NUDE_TAGS:
        result = [tag for tag in normalized if tag in FULL_NUDE_TAGS or _is_accessory(tag)]
        if "completely_nude" in tag_set:
            for extra in ("nude", "bare_body"):
                if extra not in result:
                    result.append(extra)
        return _dedupe(result)

    result = normalized

    if "barefoot" in tag_set:
        result = [
            tag for tag in result
            if tag == "barefoot" or not (_has_hint(tag, FOOTWEAR_HINTS) or _has_hint(tag, LEGWEAR_HINTS))
        ]

    if "topless" in tag_set:
        result = [
            tag for tag in result
            if tag == "topless" or not _has_hint(tag, TOP_HINTS)
        ]

    if "bottomless" in tag_set:
        result = [
            tag for tag in result
            if tag == "bottomless" or not _has_hint(tag, BOTTOM_HINTS)
        ]

    return _dedupe(result)


def parse_outfit_tags(value: Any) -> list[str]:
    """Parse markdown-ish outfit section content into tags."""
    if value is None:
        return []
    if isinstance(value, dict):
        raw_lines = [str(v) for v in value.values()]
    elif isinstance(value, list):
        raw_lines = [str(v) for v in value]
    else:
        raw_lines = str(value).splitlines()

    tags: list[str] = []
    for raw_line in raw_lines:
        line = raw_line.strip()
        if line.startswith("-"):
            line = line[1:].strip()
        for item in line.split(","):
            tag = _norm_tag(item)
            if tag and tag not in tags:
                tags.append(tag)
    return tags


def format_outfit_tags(tags: list[str]) -> str:
    return "\n".join(f"- {tag}" for tag in tags)


def normalize_outfit_markdown(value: Any) -> str:
    return format_outfit_tags(normalize_outfit_tags(parse_outfit_tags(value)))


def persistent_prompt_tags(prompt: str) -> set[str]:
    tags = {_norm_tag(tag) for tag in (prompt or "").split(",") if _norm_tag(tag)}
    return tags & PERSISTENT_OUTFIT_STATE_TAGS


def has_internal_conflict(tags: list[str]) -> bool:
    tag_set = set(tags)
    if "barefoot" in tag_set and any(
        _has_hint(tag, FOOTWEAR_HINTS) or _has_hint(tag, LEGWEAR_HINTS)
        for tag in tags
    ):
        return True
    if tag_set & FULL_NUDE_TAGS and any(
        not _is_accessory(tag) and tag not in FULL_NUDE_TAGS
        for tag in tags
    ):
        return True
    return False


def _is_accessory(tag: str) -> bool:
    return _has_hint(tag, ACCESSORY_HINTS)


def _has_hint(tag: str, hints: tuple[str, ...]) -> bool:
    return any(hint in tag for hint in hints)


def _norm_tag(tag: str) -> str:
    return str(tag).strip().lower().replace(" ", "_")


def _dedupe(tags: list[str]) -> list[str]:
    seen = set()
    result = []
    for tag in tags:
        if tag and tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result
