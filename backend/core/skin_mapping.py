"""Local character skin tag mapping search."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from ..config import settings


MAPPING_FILE = settings.data_dir / "char_skin_mapping.json"


@lru_cache(maxsize=1)
def load_skin_mappings() -> list[dict[str, Any]]:
    if not MAPPING_FILE.exists():
        return []
    data = json.loads(MAPPING_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def search_skin_mappings(query: str, limit: int = 20) -> list[dict[str, Any]]:
    q = (query or "").strip().lower()
    limit = max(1, min(limit, 50))
    if not q:
        return []

    scored: list[tuple[int, int, dict[str, Any]]] = []
    for idx, item in enumerate(load_skin_mappings()):
        name_cn = str(item.get("name_cn") or "")
        name_en = str(item.get("name_en") or "")
        series = str(item.get("series") or "")
        role_tags = str(item.get("role_tags") or "")

        haystacks = {
            "name_cn": name_cn.lower(),
            "name_en": name_en.lower(),
            "series": series.lower(),
            "role_tags": role_tags.lower(),
        }
        score = 0
        if haystacks["name_cn"] == q or haystacks["name_en"] == q:
            score += 1000
        if haystacks["name_cn"].startswith(q) or haystacks["name_en"].startswith(q):
            score += 500
        if q in haystacks["name_cn"] or q in haystacks["name_en"]:
            score += 260
        if q in haystacks["series"]:
            score += 120
        if q in haystacks["role_tags"]:
            score += 80
        if score:
            scored.append((score, idx, item))

    scored.sort(key=lambda row: (-row[0], row[1]))
    return [_public_mapping(item) for _, _, item in scored[:limit]]


def _public_mapping(item: dict[str, Any]) -> dict[str, str]:
    return {
        "name_cn": str(item.get("name_cn") or ""),
        "name_en": str(item.get("name_en") or ""),
        "series": str(item.get("series") or ""),
        "role_tags": str(item.get("role_tags") or ""),
        "body_tags": str(item.get("body_tags") or ""),
        "appearance_tags": str(item.get("appearance_tags") or ""),
    }
