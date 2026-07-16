"""Always-on visual continuity and conditional shot-direction agent."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..config import settings
from ..core.state import merge_continuity_patch
from ..core.wardrobe import wardrobe_agent_view, wardrobe_visible_tags
from ..models.schemas import ContinuityOutput

logger = logging.getLogger(__name__)


class VisualContinuityError(RuntimeError):
    """Raised when continuity cannot be resolved into a safe state patch."""


class VisualContinuityAgent:
    """Interpret a role-play reply into state continuity and an optional shot."""

    def __init__(self, llm_client):
        self.llm = llm_client
        self._system_prompt: str | None = None

    async def resolve(
        self,
        *,
        character: str,
        user_message: str,
        reply: str,
        image_goal: dict[str, Any] | None,
        previous_state: dict[str, Any],
        recent_dialogue: list[dict[str, str]] | None = None,
        business_knowledge: str = "",
    ) -> ContinuityOutput:
        """Resolve every turn; retry once when JSON or state structure is invalid."""
        payload = {
            "character": character,
            "user_message": user_message,
            "character_reply": reply,
            "image_goal": image_goal,
            "recent_dialogue": list(recent_dialogue or [])[-16:],
            "previous_state": {
                "version": int(previous_state.get("version") or 0),
                "wardrobe": wardrobe_agent_view(previous_state.get("wardrobe") or {}),
                "scene_tags": list(previous_state.get("scene_tags") or []),
            },
            "applicable_business_knowledge": business_knowledge,
        }
        last_error: Exception | None = None
        last_raw = ""
        for attempt in range(2):
            request = dict(payload)
            if attempt:
                request["repair"] = {
                    "invalid_output": last_raw[:4000],
                    "error": str(last_error),
                    "instruction": "重新输出完整合法 JSON；不要改变角色回复中的事实。",
                }
            try:
                raw = await self.llm.chat_prompt(
                    system=self.system_prompt(),
                    user=json.dumps(request, ensure_ascii=False, indent=2),
                    temperature=0.2 if attempt else 0.35,
                )
                last_raw = raw or ""
                result = self._parse(last_raw, image_goal)
                # Dry-run the exact patch before any user-visible reply or file write.
                merge_continuity_patch(previous_state, result.state_patch)
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
            path = settings.config_dir / "image_director.md"
            protocol = path.read_text(encoding="utf-8")
            knowledge_path = settings.config_dir / "knowledge" / "visual_prompting.md"
            knowledge = (
                knowledge_path.read_text(encoding="utf-8")
                if knowledge_path.exists()
                else ""
            )
            self._system_prompt = (
                f"{protocol}\n\n---\n\n{knowledge}" if knowledge else protocol
            )
        return self._system_prompt

    def reload_system_prompt(self):
        self._system_prompt = None

    def _parse(
        self,
        raw: str,
        image_goal: dict[str, Any] | None,
    ) -> ContinuityOutput:
        text = re.sub(r"<think>.*?</think>", "", raw or "", flags=re.DOTALL).strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1])
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("continuity output must be an object")
        state_patch = data.get("state_patch")
        if not isinstance(state_patch, dict):
            raise ValueError("continuity output requires state_patch object")

        raw_shot = data.get("shot_spec")
        if image_goal:
            if not isinstance(raw_shot, dict):
                raise ValueError("image_goal requires shot_spec object")
            shot_spec = _parse_shot(raw_shot)
        else:
            if raw_shot is not None:
                raise ValueError("shot_spec must be null when image_goal is absent")
            shot_spec = None
        return ContinuityOutput(
            state_patch=state_patch,
            shot_spec=shot_spec,
            reason=str(data.get("reason") or "").strip(),
        )

    @staticmethod
    def harmonize_shot(
        shot: dict[str, Any] | None,
        image_goal: dict[str, Any] | None,
        committed_state: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Apply small deterministic camera constraints after state commit."""
        if not image_goal:
            return None
        result = dict(shot or {})
        action_tags = _string_list(result.get("action_tags"))
        pose = _string_list(result.get("pose"))

        normalized = {_norm_tag(tag) for tag in action_tags + pose}
        spread = {"legs_spread", "spread_legs", "spreading_legs"}
        together = {"legs_together", "knees_together"}
        if normalized & spread:
            action_tags = [tag for tag in action_tags if _norm_tag(tag) not in together]
            pose = [tag for tag in pose if _norm_tag(tag) not in together]

        if str(image_goal.get("visibility") or "").strip().lower() == "clear":
            covering = {"covering_self", "hands_covering_crotch", "covering_crotch"}
            action_tags = [tag for tag in action_tags if _norm_tag(tag) not in covering]
            pose = [tag for tag in pose if _norm_tag(tag) not in covering]

        wardrobe = committed_state.get("wardrobe")
        visible = wardrobe_visible_tags(wardrobe) if isinstance(wardrobe, dict) else list(
            committed_state.get("outfit_tags") or []
        )
        explicit = {
            "completely_nude", "nude", "naked", "bare_body", "topless",
            "bottomless", "no_bra", "no_panties",
        }
        rating = str(result.get("rating") or image_goal.get("rating") or "general").removeprefix("rating:")
        if {_norm_tag(tag) for tag in visible} & explicit:
            rating = "nsfw"
        elif rating not in {"general", "sensitive", "nsfw"}:
            rating = "general"

        result["action_tags"] = action_tags
        result["pose"] = pose
        result["rating"] = rating
        result["generate"] = True
        return result


def _parse_shot(data: dict[str, Any]) -> dict[str, Any]:
    camera = data.get("camera") if isinstance(data.get("camera"), dict) else {}
    rating = str(data.get("rating") or "general").removeprefix("rating:")
    if rating not in {"general", "sensitive", "nsfw"}:
        rating = "general"
    return {
        "generate": True,
        "reason": str(data.get("reason") or "").strip(),
        "action_tags": _bounded_string_list(data.get("action_tags"), "action_tags", 3),
        "pose": _bounded_string_list(data.get("pose"), "pose", 2),
        "expression": _bounded_string_list(data.get("expression"), "expression", 2),
        "camera": {
            "shot": _optional_string(camera.get("shot")),
            "angle": _optional_string(camera.get("angle")),
            "focus": _optional_string(camera.get("focus")),
            "pov": bool(camera.get("pov", False)),
        },
        "lighting": _bounded_string_list(data.get("lighting"), "lighting", 2),
        "emphasis": _parse_emphasis(data.get("emphasis")),
        "rating": rating,
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


def _bounded_string_list(value: Any, field: str, limit: int) -> list[str]:
    result = _string_list(value)
    if len(result) > limit:
        raise ValueError(f"{field} exceeds the {limit}-tag budget")
    return result


def _parse_emphasis(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("emphasis must be an object or null")
    tags = _bounded_string_list(value.get("tags"), "emphasis.tags", 3)
    if not tags:
        raise ValueError("emphasis requires at least one tag")
    weight = float(value.get("weight") or 0)
    if not 1.05 <= weight <= 1.20:
        raise ValueError("emphasis.weight must be between 1.05 and 1.20")
    return {"tags": tags, "weight": round(weight, 2)}


def _optional_string(value: Any) -> str | None:
    item = str(value or "").strip()
    return item or None


def _norm_tag(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


# Compatibility import for code outside the runtime that still uses the old name.
ImageDirectorAgent = VisualContinuityAgent
