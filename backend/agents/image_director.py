"""Always-on visual continuity and conditional shot-direction agent."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..config import settings
from ..core.context import get_character_name
from ..core.memory_v3 import load_user_profile
from ..core.state import merge_continuity_patch, validate_initial_state_patch
from ..core.wardrobe import wardrobe_director_view
from ..models.schemas import ContinuityOutput
from ..services.prompt_builder import get_visual_anchor_tags

logger = logging.getLogger(__name__)


class VisualContinuityError(RuntimeError):
    """Raised when continuity cannot be resolved into a valid state patch."""


class VisualContinuityAgent:
    """Interpret a role-play reply, update continuity and optionally direct a shot."""

    def __init__(self, llm_client):
        self.llm = llm_client
        self._system_prompt: str | None = None

    async def resolve(
        self,
        *,
        character: str,
        user_message: str,
        reply: str,
        previous_state: dict[str, Any],
        recent_dialogue: list[dict[str, str]] | None = None,
        business_knowledge: str = "",
        interaction_mode: str = "chat",
        image_goal: dict[str, Any] | None = None,
    ) -> ContinuityOutput:
        """Resolve every turn; retry once when JSON or state structure is invalid."""
        _ = business_knowledge, image_goal
        visual_anchor = get_visual_anchor_tags(character)
        user_profile = load_user_profile(character)
        initialized = bool(previous_state.get("initialized", True))
        payload = {
            "character": character,
            "user_message": user_message,
            "character_reply": reply,
            "interaction_mode": interaction_mode,
            "recent_dialogue": list(recent_dialogue or [])[-16:],
            "previous_state": {
                "version": int(previous_state.get("version") or 0),
                "initialized": initialized,
                "wardrobe": (
                    wardrobe_director_view(previous_state.get("wardrobe") or {})
                    if initialized
                    else None
                ),
                "scene": list(previous_state.get("scene_tags") or []),
            },
            "participants": {
                "character": {
                    "name": get_character_name(character),
                    "gender": visual_anchor.get("gender") or "unknown",
                    "primary_subject": True,
                },
                "player": {
                    "name": str(user_profile.get("user_pet_name") or "用户").strip(),
                    "gender": str(user_profile.get("gender") or "unknown").strip().lower(),
                    "pov_owner": True,
                },
            },
        }
        last_error: Exception | None = None
        last_raw = ""
        for attempt in range(2):
            request = dict(payload)
            if attempt:
                request["repair"] = {
                    "invalid_output": last_raw[:4000],
                    "error": str(last_error),
                    "instruction": "重新输出完整合法 JSON，并保持角色回复中已经发生的事实。",
                }
            try:
                raw = await self.llm.chat_prompt(
                    system=self.system_prompt(),
                    user=json.dumps(request, ensure_ascii=False, indent=2),
                    temperature=0.2 if attempt else 0.35,
                )
                last_raw = raw or ""
                result = self._parse(last_raw)
                if interaction_mode.startswith("initial_scene"):
                    validate_initial_state_patch(result.state_patch)
                merged_state = merge_continuity_patch(previous_state, result.state_patch)
                if result.shot_spec is not None:
                    result.shot_spec = self.normalize_prompt_plan(
                        result.shot_spec,
                        visual_anchor,
                        merged_state=merged_state,
                    )
                return result
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Visual continuity attempt %s failed for %s: %s",
                    attempt + 1,
                    character,
                    exc,
                )
        raise VisualContinuityError(str(last_error or "unknown continuity error"))

    def system_prompt(self) -> str:
        if self._system_prompt is None:
            protocol_path = settings.config_dir / "image_director.md"
            protocol = protocol_path.read_text(encoding="utf-8")
            knowledge_path = settings.config_dir / "knowledge" / "visual_prompting.md"
            knowledge = knowledge_path.read_text(encoding="utf-8") if knowledge_path.exists() else ""
            self._system_prompt = f"{protocol}\n\n---\n\n{knowledge}" if knowledge else protocol
        return self._system_prompt

    def reload_system_prompt(self):
        self._system_prompt = None

    def _parse(self, raw: str) -> ContinuityOutput:
        text = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.DOTALL).strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1])
        if not text.startswith("{"):
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                text = text[start:end + 1]
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("continuity output must be an object")
        state_patch = data.get("state_patch")
        if not isinstance(state_patch, dict):
            raise ValueError("continuity output requires state_patch object")

        raw_shot = data.get("shot")
        if raw_shot is None:
            raw_shot = data.get("shot_spec")
        shot_spec = _parse_shot(raw_shot) if isinstance(raw_shot, dict) else None
        return ContinuityOutput(
            state_patch=state_patch,
            shot_spec=shot_spec,
            reason=str(data.get("reason") or "").strip(),
        )

    @staticmethod
    def normalize_prompt_plan(
        shot: dict[str, Any],
        visual_anchor: dict[str, Any],
        merged_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Finish the compact shot plan without copying fixed prompt anchors."""
        _ = visual_anchor
        completed = dict(shot)
        if not str(completed.get("environment") or "").strip():
            completed["environment"] = ", ".join(
                str(tag).strip()
                for tag in list(merged_state.get("scene_tags") or [])[:2]
                if str(tag).strip()
            ) or "current setting"
        return completed

    @staticmethod
    def harmonize_shot(
        shot: dict[str, Any] | None,
        committed_state: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Apply a small deterministic action-conflict repair after state commit."""
        _ = committed_state
        if not shot:
            return None
        result = dict(shot)
        action = dict(result.get("action") or {})
        action_tags = _string_list(action.get("tags"))
        normalized = {_norm_tag(tag) for tag in action_tags}
        if normalized & {"legs_spread", "spread_legs", "spreading_legs"}:
            action_tags = [
                tag for tag in action_tags
                if _norm_tag(tag) not in {"legs_together", "knees_together"}
            ]
        action["tags"] = action_tags
        result["action"] = action
        return result


def _parse_shot(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize the compact protocol and accept the previous ShotSpec shape."""
    camera = data.get("camera") if isinstance(data.get("camera"), dict) else {}
    view = (
        _optional_string(camera.get("view"))
        or _optional_string(camera.get("focus"))
        or _optional_string(camera.get("shot"))
        or "medium_shot"
    )

    action_value = data.get("action") if isinstance(data.get("action"), dict) else None
    if action_value is not None:
        action_tags = _string_list(action_value.get("tags"))
        action_text = _optional_phrase(action_value.get("text"), max_words=25)
    else:
        action_tags = _string_list(data.get("pose"))
        for value in (*_string_list(data.get("action_tags")), *_string_list(data.get("expression"))):
            if value not in action_tags:
                action_tags.append(value)
        action_text = _optional_phrase(data.get("action_text"), max_words=25)

    if "environment" in data:
        environment = _optional_phrase(data.get("environment"), max_words=18)
        if not environment:
            raise ValueError("shot.environment must be a non-empty string")
    else:
        environment_parts = [
            *_string_list(data.get("scene_tags")),
            *([_optional_phrase(data.get("environment_text"), max_words=18)] if data.get("environment_text") else []),
            *_string_list(data.get("lighting")),
        ]
        environment = ", ".join(part for part in environment_parts if part)

    return {
        "camera": {
            "view": view,
            "angle": _optional_string(camera.get("angle")),
            "pov": bool(camera.get("pov", False)),
        },
        "action": {"tags": action_tags, "text": action_text},
        "environment": environment,
    }


def _string_list(value: Any) -> list[str]:
    raw_values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for raw in raw_values:
        if raw is None:
            continue
        for part in str(raw).split(","):
            item = part.strip()
            if item and item not in result:
                result.append(item)
    return result


def _optional_string(value: Any) -> str | None:
    item = str(value or "").strip()
    return item or None


def _optional_phrase(value: Any, *, max_words: int) -> str | None:
    if value is None:
        return None
    phrase = " ".join(str(value).split()).strip()
    if not phrase:
        return None
    phrase = re.split(r"(?<=[.!?])\s+", phrase, maxsplit=1)[0]
    words = phrase.split()
    if len(words) > max_words:
        phrase = " ".join(words[:max_words])
    return phrase[:240].strip() or None


def _norm_tag(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


# Compatibility import for code outside the runtime that still uses the old name.
ImageDirectorAgent = VisualContinuityAgent
