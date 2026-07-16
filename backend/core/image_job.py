"""Immutable image jobs built from one committed conversation turn."""

from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from typing import Any
from uuid import uuid4

from .state import capture_state_snapshot


@dataclass(frozen=True)
class ImageJob:
    job_id: str
    character: str
    reply: str
    dynamic_prompt: str
    state_snapshot: dict[str, Any]
    image_goal: dict[str, Any] | None = None
    shot_spec: dict[str, Any] | None = None


def build_image_job(
    character: str,
    reply: str,
    image_intent: dict[str, Any] | None = None,
    legacy_prompt: str | None = None,
    state_snapshot: dict[str, Any] | None = None,
    image_goal: dict[str, Any] | None = None,
) -> ImageJob | None:
    """Freeze committed state and compile a continuity ShotSpec into one job."""
    if not image_intent and not legacy_prompt:
        return None
    if image_intent and image_intent.get("generate") is False:
        return None

    dynamic_prompt = legacy_prompt or compile_image_intent(image_intent or {})
    if not dynamic_prompt.strip():
        return None
    return ImageJob(
        job_id=uuid4().hex,
        character=character,
        reply=reply,
        dynamic_prompt=dynamic_prompt,
        state_snapshot=deepcopy(state_snapshot) if state_snapshot is not None else capture_state_snapshot(character),
        image_goal=deepcopy(image_goal) if image_goal is not None else None,
        shot_spec=deepcopy(image_intent) if image_intent is not None else None,
    )


def compile_image_intent(intent: dict[str, Any]) -> str:
    """Compile a semantic shot brief; persistent state is injected later."""
    tags: list[str] = []
    rating = str(intent.get("rating") or "general").removeprefix("rating:")
    tags.append(f"rating:{rating}")

    for key in ("pose", "action_tags", "expression", "lighting"):
        _extend(tags, intent.get(key))

    camera = intent.get("camera") or {}
    if isinstance(camera, dict):
        for key in ("shot", "angle", "focus"):
            _extend(tags, camera.get(key))
        if camera.get("pov"):
            tags.append("pov")

    emphasis = intent.get("emphasis")
    if isinstance(emphasis, dict):
        emphasis_tags = _as_tags(emphasis.get("tags"))[:3]
        try:
            weight = float(emphasis.get("weight") or 0)
        except (TypeError, ValueError):
            weight = 0
        if emphasis_tags and 1.05 <= weight <= 1.20:
            emphasized_norms = {_norm_tag(tag) for tag in emphasis_tags}
            tags = [tag for tag in tags if _norm_tag(tag) not in emphasized_norms]
            rendered_weight = f"{weight:.2f}".rstrip("0").rstrip(".")
            tags.append(f"({', '.join(emphasis_tags)}:{rendered_weight})")

    return ", ".join(_dedupe(tags))


def _extend(target: list[str], value: Any):
    if isinstance(value, str):
        target.extend(part.strip() for part in value.split(",") if part.strip())
    elif isinstance(value, list):
        target.extend(str(part).strip() for part in value if str(part).strip())


def _as_tags(value: Any) -> list[str]:
    result: list[str] = []
    _extend(result, value)
    return result


def _norm_tag(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _dedupe(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        key = tag.lower().replace(" ", "_")
        if key not in seen:
            seen.add(key)
            result.append(tag)
    return result
