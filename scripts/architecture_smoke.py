"""Offline checks for knowledge routing, state effects and frozen image jobs."""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import settings
from backend.core.business_knowledge import route_domains
from backend.core.image_job import build_image_job
from backend.core.state import (
    apply_state_operations,
    apply_state_updates,
    state_updates_from_effects,
)
from backend.services.prompt_builder import build_image_prompt, normalize_camera_action_tags


def main():
    assert route_domains("换套舒服的睡衣给我看看") == ["wardrobe", "photography"]
    assert route_domains("看一下") == ["photography"]
    assert route_domains("你还记得上次吗") == ["recall"]
    assert route_domains("今天吃了什么") == []
    focused = normalize_camera_action_tags(
        "sitting_on_bed, legs_together, spreading_legs, covering_self, pussy_focus"
    )
    assert "legs_together" not in focused
    assert "covering_self" not in focused
    assert "sitting_on_bed" in focused and "lying_down" not in focused

    original_base = settings.base_dir
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        settings.base_dir = root
        try:
            char = "probe"
            char_dir = root / "characters" / char
            (char_dir / "memory").mkdir(parents=True)
            (char_dir / "profile.json").write_text(json.dumps({
                "name": "Probe",
                "visual_anchor": {
                    "role_tags": "1girl, solo",
                    "body_tags": "petite",
                    "appearance_tags": "black_hair, brown_eyes",
                },
            }), encoding="utf-8")
            (char_dir / "memory" / "status.md").write_text("""# state

## 穿着
- white_shirt
- blue_skirt

## 场景细节
- living_room
- daytime

## Probe的心情状态
- calm
""", encoding="utf-8")

            updates = state_updates_from_effects(char, [{
                "type": "replace_outfit",
                "status": "completed",
                "tags": ["pink_pajamas", "barefoot"],
            }])
            assert updates
            apply_state_updates(char, updates)
            job = build_image_job(char, "换好了。", image_intent={
                "generate": True,
                "pose": ["sitting"],
                "camera": {"shot": "medium_shot", "angle": "front_view"},
                "rating": "general",
            })
            assert job and job.state_snapshot["outfit_tags"] == ["pink_pajamas", "barefoot"]

            # A later turn must not alter an already queued image.
            apply_state_updates(char, {"status": {"穿着": "- black_dress\n- high_heels"}})
            prompt = build_image_prompt(
                char,
                job.dynamic_prompt,
                state_snapshot=job.state_snapshot,
            )
            assert "pink_pajamas" in prompt and "black_dress" not in prompt

            # V2 state operations preserve untouched layers and make the next
            # inner layer visible after removing the outer layer.
            apply_state_operations(char, [{
                "domain": "wardrobe",
                "operation": "replace",
                "garments": [
                    {"id": "inner", "slots": ["lower"], "tags": ["white_panties"]},
                    {"id": "outer", "slots": ["lower"], "tags": ["blue_skirt"]},
                    {"id": "top", "slots": ["upper"], "tags": ["white_blouse"]},
                ],
            }])
            apply_state_operations(char, [{
                "domain": "wardrobe",
                "operation": "remove",
                "slot": "lower",
                "target": "outermost",
            }])
            v2_job = build_image_job(char, "完成。", image_intent={
                "generate": True,
                "camera": {"shot": "medium_shot", "angle": "front_view"},
                "rating": "sensitive",
            })
            assert v2_job
            assert "white_panties" in v2_job.state_snapshot["outfit_tags"]
            assert "blue_skirt" not in v2_job.state_snapshot["outfit_tags"]
            print("architecture smoke: ok")
        finally:
            settings.base_dir = original_base


if __name__ == "__main__":
    main()
