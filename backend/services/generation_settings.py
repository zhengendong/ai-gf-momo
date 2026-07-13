"""Resolve the user-selected ComfyUI workflow and optional UI overrides."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import settings


DEFAULT_WORKFLOW = "waiNSFWIllustrious_v140.json"
DEFAULT_COMFYUI_ROOT = Path("D:/ComfyUI")


@dataclass(frozen=True)
class GenerationSettings:
    """One resolved global image-generation profile.

    ``None`` means inherit the selected workflow's own node value. The profile
    is loaded when a workflow is built, so saving the UI takes effect on the
    next image job without involving the main Agent.
    """

    root_dir: Path
    workflow: str
    negative_prompt: str | None = None
    sampler: str | None = None
    scheduler: str | None = None
    steps: int | None = None
    cfg: float | None = None
    width: int | None = None
    height: int | None = None

    @property
    def workflow_dir(self) -> Path:
        """ComfyUI's standard user workflow directory for this local install."""
        return self.root_dir / "ComfyUI" / "user" / "default" / "workflows"


def load_generation_settings() -> GenerationSettings:
    """Read the frontend-owned ComfyUI profile from ``config/settings.json``."""
    raw: dict[str, Any] = {}
    try:
        if settings.settings_file.exists():
            loaded = json.loads(settings.settings_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                raw = loaded
    except (OSError, json.JSONDecodeError):
        raw = {}

    configured = raw.get("comfyui")
    profile = configured if isinstance(configured, dict) else {}
    root_dir = Path(_optional_text(profile.get("root_dir")) or DEFAULT_COMFYUI_ROOT)
    workflow = _optional_text(profile.get("workflow")) or DEFAULT_WORKFLOW

    return GenerationSettings(
        root_dir=root_dir,
        workflow=workflow,
        negative_prompt=_optional_text(profile.get("negative_prompt")),
        sampler=_optional_text(profile.get("sampler")),
        scheduler=_optional_text(profile.get("scheduler")),
        steps=_optional_int(profile.get("steps")),
        cfg=_optional_float(profile.get("cfg")),
        width=_optional_int(profile.get("width")),
        height=_optional_int(profile.get("height")),
    )


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
