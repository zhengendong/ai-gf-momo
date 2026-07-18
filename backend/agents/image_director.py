"""Always-on visual continuity and conditional shot-direction agent."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..config import settings
from ..core.state import merge_continuity_patch, validate_initial_state_patch
from ..core.wardrobe import wardrobe_agent_view, wardrobe_visible_prompt_tags, wardrobe_visible_tags
from ..models.schemas import ContinuityOutput
from ..services.prompt_builder import expand_prompt_tags, get_visual_anchor_tags

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
        interaction_mode: str = "chat",
    ) -> ContinuityOutput:
        """Resolve every turn; retry once when JSON or state structure is invalid."""
        visual_anchor = get_visual_anchor_tags(character)
        payload = {
            "character": character,
            "user_message": user_message,
            "character_reply": reply,
            "image_goal": image_goal,
            "interaction_mode": interaction_mode,
            "recent_dialogue": list(recent_dialogue or [])[-16:],
            "previous_state": {
                "version": int(previous_state.get("version") or 0),
                "initialized": bool(previous_state.get("initialized", True)),
                "wardrobe": wardrobe_agent_view(previous_state.get("wardrobe") or {}),
                "scene_tags": list(previous_state.get("scene_tags") or []),
            },
            "applicable_business_knowledge": business_knowledge,
            "prompt_inputs": {
                "role_tags": expand_prompt_tags(visual_anchor.get("role_tags")),
                "body_tags": expand_prompt_tags(visual_anchor.get("body_tags")),
                "appearance_tags": expand_prompt_tags(visual_anchor.get("appearance_tags")),
                "instruction": (
                    "role_tags、body_tags、appearance_tags 必须按原顺序完整保留；"
                    "服饰与场景标签按本图重点筛选；动作和环境关系可用精简英文短语补充。"
                ),
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
                if interaction_mode.startswith("initial_scene"):
                    validate_initial_state_patch(result.state_patch)
                # Dry-run the exact patch before any user-visible reply or file write.
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

        raw_shot = data.get("shot_spec")
        if image_goal:
            # Prompt planning is outside the state transaction's safety
            # boundary. Missing old-format fields degrade gracefully instead
            # of cancelling the character reply and committed state.
            shot_spec = _parse_shot(raw_shot if isinstance(raw_shot, dict) else {})
        else:
            shot_spec = None
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
        """Normalize prompt facts without turning editorial errors into turn errors.

        Character anchors and committed wardrobe/exposure facts are immutable.
        Scene selection may only project committed facts. There is deliberately
        no length budget.
        """
        completed = dict(shot)
        for field in ("role_tags", "body_tags", "appearance_tags"):
            required = expand_prompt_tags(visual_anchor.get(field))
            completed[field] = required

        wardrobe_candidates = wardrobe_visible_prompt_tags(merged_state.get("wardrobe") or {})
        scene_candidates = list(merged_state.get("scene_tags") or [])
        # Clothing and exposure are visual continuity facts, not optional
        # camera decoration. A foot or facial close-up must not silently make
        # a topless/nude character appear dressed again.
        completed["wardrobe_tags"] = wardrobe_candidates
        completed["scene_tags"] = _keep_committed_tags(
            completed.get("scene_tags"),
            scene_candidates,
        )
        if scene_candidates and not completed["scene_tags"]:
            completed["scene_tags"] = scene_candidates[:2]
        return completed

    @staticmethod
    def fallback_shot(
        character: str,
        image_goal: dict[str, Any],
        committed_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a local image fallback without another model request.

        This only runs after the director has already exhausted its one repair.
        It intentionally preserves the last committed visual facts rather than
        guessing unverified state changes from prose.
        """
        shot = {
            "generate": True,
            "reason": "local continuity fallback",
            "role_tags": [],
            "body_tags": [],
            "appearance_tags": [],
            "wardrobe_tags": [],
            "scene_tags": [],
            "action_tags": [],
            "action_text": None,
            "environment_text": None,
            "pose": [],
            "expression": [],
            "camera": {"shot": "medium_shot", "angle": None, "focus": None, "pov": False},
            "lighting": [],
            "rating": str(image_goal.get("rating") or "general").removeprefix("rating:"),
        }
        return VisualContinuityAgent.normalize_prompt_plan(
            shot,
            get_visual_anchor_tags(character),
            committed_state,
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
    shot = _optional_string(camera.get("shot"))
    focus = _optional_string(camera.get("focus"))
    if focus:
        shot = None
    elif not shot:
        shot = "medium_shot"
    rating = str(data.get("rating") or "general").removeprefix("rating:")
    if rating not in {"general", "sensitive", "nsfw"}:
        rating = "general"
    action_tags = _string_list(data.get("action_tags"))
    action_text = _optional_phrase(data.get("action_text"), max_words=25)
    environment_text = _optional_phrase(data.get("environment_text"), max_words=18)
    return {
        "generate": True,
        "reason": str(data.get("reason") or "").strip(),
        "role_tags": _string_list(data.get("role_tags")),
        "body_tags": _string_list(data.get("body_tags")),
        "appearance_tags": _string_list(data.get("appearance_tags")),
        "wardrobe_tags": _string_list(data.get("wardrobe_tags")),
        "scene_tags": _string_list(data.get("scene_tags")),
        "action_tags": action_tags,
        "action_text": action_text,
        "environment_text": environment_text,
        "pose": _string_list(data.get("pose")),
        "expression": _string_list(data.get("expression")),
        "camera": {
            "shot": shot,
            "angle": _optional_string(camera.get("angle")),
            "focus": focus,
            "pov": bool(camera.get("pov", False)),
        },
        "lighting": _string_list(data.get("lighting")),
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


def _keep_committed_tags(selected: Any, candidates: list[str]) -> list[str]:
    by_norm = {_norm_tag(tag): tag for tag in candidates}
    return [
        by_norm[_norm_tag(tag)]
        for tag in _string_list(selected)
        if _norm_tag(tag) in by_norm
    ]


# Compatibility import for code outside the runtime that still uses the old name.
ImageDirectorAgent = VisualContinuityAgent
