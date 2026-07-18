"""Offline checks for knowledge routing, state effects and frozen image jobs."""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import settings
from backend.agents.image_director import VisualContinuityAgent, _parse_shot
from backend.core.business_knowledge import route_domains
from backend.core.context import assemble_momo_prompt
from backend.core.chat_history import read_chat_history, replace_chat_image_url, write_chat_history
from backend.core.image_job import build_image_job
from backend.core.runtime import build_scene_transition_instruction
from backend.core.state import (
    apply_state_operations,
    apply_state_updates,
    capture_state_snapshot,
    merge_continuity_patch,
    read_status,
    state_updates_from_effects,
)
from backend.core.wardrobe import wardrobe_from_tags
from backend.services.prompt_builder import (
    _compact_natural_phrase,
    build_image_prompt,
    expand_prompt_tags,
    normalize_camera_action_tags,
    parse_clothing_status,
)


def main():
    normalized_camera = _parse_shot({
        "action_tags": ["presenting_foot"],
        "camera": {"shot": "close-up", "angle": "front_view", "focus": "foot_focus"},
    })
    assert normalized_camera["camera"]["shot"] is None
    assert normalized_camera["camera"]["focus"] == "foot_focus"
    natural_only = _parse_shot({
        "action_tags": [],
        "action_text": "She reaches for the door handle with her right hand.",
        "environment_text": "The half-open door leads into a quiet hallway.",
        "camera": {"shot": "medium_shot", "angle": "from_side", "focus": None},
    })
    assert not natural_only["action_tags"]
    assert natural_only["action_text"].startswith("She reaches")
    assert natural_only["environment_text"].startswith("The half-open door")
    assert len(_compact_natural_phrase("word " * 30, 25).split()) == 25
    forced_wardrobe = VisualContinuityAgent.normalize_prompt_plan(
        {
            "role_tags": [], "body_tags": [], "appearance_tags": [],
            "wardrobe_tags": [], "scene_tags": [], "action_tags": [],
            "action_text": None, "environment_text": None, "pose": [],
            "expression": [],
            "camera": {"shot": "medium_shot", "angle": None, "focus": None, "pov": False},
            "lighting": [], "rating": "general",
        },
        {"role_tags": ["1girl"], "body_tags": [], "appearance_tags": []},
        {"wardrobe": wardrobe_from_tags(["topless", "blue_skirt", "barefoot"]), "scene_tags": []},
    )
    assert forced_wardrobe["wardrobe_tags"] == ["blue skirt", "topless", "barefoot"]
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
    assert expand_prompt_tags("(black hair, white shirt:0.9)") == ["black hair", "white shirt"]
    assert parse_clothing_status("""## 穿着
- 上身：上身：light blue pajamas、下身：light blue pajamas
- 下身：上身：light blue pajamas、下身：light blue pajamas
- 配饰：配饰：silver heart necklace、black bell collar
""") == ["light_blue_pajamas", "silver_heart_necklace", "black_bell_collar"]

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

            directed = build_image_prompt(char, "unused", shot_spec={
                "role_tags": ["1girl", "solo"],
                "body_tags": ["petite"],
                "appearance_tags": ["black_hair", "brown_eyes"],
                "wardrobe_tags": [],
                "scene_tags": ["living_room"],
                "action_tags": ["presenting_breasts"],
                "action_text": "She presents her chest clearly while facing the viewer.",
                "pose": [],
                "expression": ["blushing"],
                "camera": {"shot": None, "angle": "front_view", "focus": "chest_focus"},
                "environment_text": "She stands beside a sofa in the living room.",
                "lighting": ["soft_lighting"],
                "rating": "sensitive",
            })
            assert all(tag in directed for tag in ("1girl", "solo", "petite", "black_hair", "brown_eyes"))
            assert "white shirt" not in directed and "blue skirt" not in directed
            assert "She presents her chest clearly" in directed
            assert "She stands beside a sofa" in directed

            long_prompt = build_image_prompt(char, "unused", shot_spec={
                "role_tags": ["1girl", "solo"],
                "body_tags": ["petite"],
                "appearance_tags": [f"stable_feature_{index}" for index in range(30)],
                "wardrobe_tags": ["white shirt", "blue skirt"],
                "scene_tags": ["living_room", "daytime"],
                "action_tags": ["posing"],
                "action_text": "She interacts naturally with the furniture while facing the viewer.",
                "pose": ["standing"],
                "expression": ["smile"],
                "camera": {"shot": "medium_shot", "angle": "front_view", "focus": None},
                "environment_text": "A sofa and window establish the occupied living space around her.",
                "lighting": ["soft_lighting"],
                "rating": "general",
            })
            assert "stable_feature_29" in long_prompt
            assert len([unit for unit in long_prompt.split(",") if unit.strip()]) > 25

            compacted = build_image_prompt(char, "unused", shot_spec={
                "role_tags": ["1girl"], "body_tags": [], "appearance_tags": [],
                "wardrobe_tags": ["white shirt"],
                "scene_tags": [f"scene_detail_{index}" for index in range(45)],
                "action_tags": ["posing"],
                "action_text": "word " * 30,
                "pose": ["standing"], "expression": ["smile"],
                "camera": {"shot": "medium_shot", "angle": "front_view", "focus": None},
                "environment_text": "place " * 25,
                "lighting": ["soft_lighting"], "rating": "general",
            })
            compacted_units = [unit.strip() for unit in compacted.split(",") if unit.strip()]
            # The director owns overall concision. Backend only keeps prose
            # clauses bounded and must never truncate tags or reject a job.
            assert len(compacted_units) > 40
            assert "scene_detail_44" in compacted
            assert "word word word word word" in compacted
            assert "word " * 26 not in compacted
            assert "place " * 19 not in compacted

            write_chat_history(char, [{
                "role": "assistant",
                "type": "image",
                "imageUrl": "/static/probe/images/original.png",
                "content": "",
            }])
            assert replace_chat_image_url(
                char,
                "/static/probe/images/original.png",
                "/static/probe/images/replacement.png",
            ) == 1
            assert read_chat_history(char)[0]["imageUrl"] == "/static/probe/images/replacement.png"

            momo_prompt = assemble_momo_prompt(char, "你现在穿着什么？")
            assert "本轮开始时的客观视觉事实" in momo_prompt
            assert "历史对话与 status.md" in momo_prompt
            assert "心情状态" not in momo_prompt
            assert "心情状态" not in read_status(char)
            assert "用户对下一幕的构想：几天后在学校重逢" in build_scene_transition_instruction(
                "manual", "几天后在学校重逢"
            )

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
            assert "pink pajamas" in prompt and "black dress" not in prompt

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
            apply_state_operations(char, [{
                "domain": "wardrobe",
                "operation": "remove",
                "slot": "upper",
                "target": "outermost",
            }])
            manual_prompt = build_image_prompt(char, "rating:sensitive, medium_shot")
            assert "white panties" in manual_prompt and "topless" in manual_prompt
            try:
                merge_continuity_patch(capture_state_snapshot(char), {
                    "wardrobe": {},
                    "scene": {"mode": "replace", "tags": ["a", "b", "c", "d", "e"]},
                })
            except ValueError:
                pass
            else:
                raise AssertionError("scene patches must obey the four-tag budget")
            print("architecture smoke: ok")
        finally:
            settings.base_dir = original_base


if __name__ == "__main__":
    main()
