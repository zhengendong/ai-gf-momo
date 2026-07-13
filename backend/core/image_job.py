"""Immutable image jobs built from one committed conversation turn."""

from __future__ import annotations

from dataclasses import dataclass
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


def build_image_job(
    character: str,
    reply: str,
    image_intent: dict[str, Any] | None = None,
    legacy_prompt: str | None = None,
) -> ImageJob | None:
    """Freeze state and compile the main Agent's shot brief into one job."""
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
        state_snapshot=capture_state_snapshot(character),
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

    return ", ".join(_dedupe(tags))


def _extend(target: list[str], value: Any):
    if isinstance(value, str):
        target.extend(part.strip() for part in value.split(",") if part.strip())
    elif isinstance(value, list):
        target.extend(str(part).strip() for part in value if str(part).strip())


def _dedupe(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        key = tag.lower().replace(" ", "_")
        if key not in seen:
            seen.add(key)
            result.append(tag)
    return result
