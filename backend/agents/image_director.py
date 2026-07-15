"""Conditional background image-direction agent."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..config import settings
from ..core.wardrobe import wardrobe_visible_tags

logger = logging.getLogger(__name__)


class ImageDirectorAgent:
    """Turn one semantic image goal and frozen state into a shot specification."""

    def __init__(self, llm_client):
        self.llm = llm_client
        self._system_prompt: str | None = None

    async def design(
        self,
        *,
        character: str,
        user_message: str,
        reply: str,
        image_goal: dict[str, Any],
        state_snapshot: dict[str, Any],
        business_knowledge: str = "",
    ) -> dict[str, Any]:
        payload = {
            "character": character,
            "user_message": user_message,
            "reply": reply,
            "image_goal": image_goal,
            "frozen_state": state_snapshot,
            "applicable_business_knowledge": business_knowledge,
        }
        try:
            raw = await self.llm.chat_prompt(
                system=self.system_prompt(),
                user=json.dumps(payload, ensure_ascii=False, indent=2),
                temperature=0.4,
            )
            return self._harmonize(self._parse(raw), image_goal, state_snapshot)
        except Exception as exc:
            logger.warning("Image director failed for %s; using minimal shot: %s", character, exc)
            return self._harmonize(self.minimal_shot(image_goal), image_goal, state_snapshot)

    def system_prompt(self) -> str:
        if self._system_prompt is None:
            path = settings.config_dir / "image_director.md"
            self._system_prompt = path.read_text(encoding="utf-8")
        return self._system_prompt

    def _parse(self, raw: str) -> dict[str, Any]:
        text = re.sub(r"<think>.*?</think>", "", (raw or ""), flags=re.DOTALL).strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1])
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("image director output must be an object")
        camera = data.get("camera") if isinstance(data.get("camera"), dict) else {}
        rating = str(data.get("rating") or "general").removeprefix("rating:")
        if rating not in {"general", "sensitive", "nsfw"}:
            rating = "general"
        return {
            "generate": True,
            "reason": str(data.get("reason") or "").strip(),
            "action_tags": _string_list(data.get("action_tags")),
            "pose": _string_list(data.get("pose")),
            "expression": _string_list(data.get("expression")),
            "camera": {
                "shot": _optional_string(camera.get("shot")),
                "angle": _optional_string(camera.get("angle")),
                "focus": _optional_string(camera.get("focus")),
                "pov": bool(camera.get("pov", False)),
            },
            "lighting": _string_list(data.get("lighting")),
            "rating": rating,
        }

    @staticmethod
    def minimal_shot(image_goal: dict[str, Any] | None) -> dict[str, Any]:
        goal = image_goal or {}
        rating = str(goal.get("rating") or "general").removeprefix("rating:")
        if rating not in {"general", "sensitive", "nsfw"}:
            rating = "general"
        focus = goal.get("focus") if isinstance(goal.get("focus"), str) else None
        return {
            "generate": True,
            "reason": "deterministic fallback for a required image delivery",
            "action_tags": [],
            "pose": [],
            "expression": ["looking_at_viewer"],
            "camera": {
                "shot": "medium_shot" if not focus else "close-up",
                "angle": "front_view",
                "focus": focus,
                "pov": False,
            },
            "lighting": [],
            "rating": rating,
        }

    @staticmethod
    def _harmonize(
        shot: dict[str, Any],
        image_goal: dict[str, Any] | None,
        state_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply deterministic delivery constraints without inventing a shot."""
        goal = image_goal or {}
        result = dict(shot)
        action_tags = _string_list(result.get("action_tags"))
        pose = _string_list(result.get("pose"))

        normalized = {_norm_tag(tag) for tag in action_tags + pose}
        spread = {"legs_spread", "spread_legs", "spreading_legs"}
        together = {"legs_together", "knees_together"}
        if normalized & spread:
            action_tags = [tag for tag in action_tags if _norm_tag(tag) not in together]
            pose = [tag for tag in pose if _norm_tag(tag) not in together]

        if str(goal.get("visibility") or "").strip().lower() == "clear":
            covering = {"covering_self", "hands_covering_crotch", "covering_crotch"}
            action_tags = [tag for tag in action_tags if _norm_tag(tag) not in covering]
            pose = [tag for tag in pose if _norm_tag(tag) not in covering]

        wardrobe = state_snapshot.get("wardrobe")
        visible = wardrobe_visible_tags(wardrobe) if isinstance(wardrobe, dict) else list(
            state_snapshot.get("outfit_tags") or []
        )
        explicit = {
            "completely_nude", "nude", "naked", "bare_body", "topless",
            "bottomless", "no_bra", "no_panties",
        }
        rating = str(result.get("rating") or goal.get("rating") or "general").removeprefix("rating:")
        if {_norm_tag(tag) for tag in visible} & explicit:
            rating = "nsfw"
        elif rating not in {"general", "sensitive", "nsfw"}:
            rating = "general"

        result["action_tags"] = action_tags
        result["pose"] = pose
        result["rating"] = rating
        result["generate"] = True
        return result


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


def _norm_tag(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")
