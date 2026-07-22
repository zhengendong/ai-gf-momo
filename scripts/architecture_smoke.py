"""Offline checks for knowledge routing, state effects and frozen image jobs."""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import settings
from backend.agents.momo import MomoAgent
from backend.agents.image_director import VisualContinuityAgent, _parse_shot
from backend.core.business_knowledge import route_domains
from backend.core.context import assemble_momo_prompt
from backend.core.chat_history import read_chat_history, replace_chat_image_url, write_chat_history
from backend.core.characters import create_character, get_profile, list_characters
from backend.core.memory_v3 import load_user_profile
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
    legacy_main_output = MomoAgent(None)._parse_output(json.dumps({
        "reply": "旁白。\n\n“台词。”",
        "image_goal": {"purpose": "旧字段不应再控制生图"},
        "memory_candidate": None,
        "persist_context": True,
    }, ensure_ascii=False))
    assert legacy_main_output.image_goal is None
    assert "\n\n" in legacy_main_output.reply
    director_decision = VisualContinuityAgent(None)._parse(json.dumps({
        "reason": "本轮值得表现",
        "state_patch": {"wardrobe": {}, "scene": None},
        "shot": {
            "camera": {"view": "medium_shot", "angle": "front_view", "pov": False},
            "action": {"tags": ["waving"], "text": None},
            "environment": "classroom, soft light",
        },
    }, ensure_ascii=False))
    assert director_decision.shot_spec is not None
    director_skip = VisualContinuityAgent(None)._parse(json.dumps({
        "reason": "普通对话没有新视觉信息",
        "state_patch": {"wardrobe": {}, "scene": None},
        "shot": None,
    }, ensure_ascii=False))
    assert director_skip.shot_spec is None
    director_protocol = (ROOT / "config" / "image_director.md").read_text(encoding="utf-8")
    assert '"upper": ["white_lace_bra", "white_blouse"]' in director_protocol
    assert '"scene": ["classroom", "after_school"]' in director_protocol
    assert '"view": "medium_shot"' in director_protocol
    assert '角色主动表现出有画面价值的剧情瞬间' not in director_protocol
    assert '接吻或拥抱场景不生图' in director_protocol
    assert '"role_tags"' not in director_protocol
    visual_prompting = (ROOT / "config" / "knowledge" / "visual_prompting.md").read_text(encoding="utf-8")
    assert '亲密或性爱画面必须写出实际发生的一个核心双方行为' in visual_prompting
    assert '玩家 POV' in visual_prompting
    assert '省略 `she/he`' in visual_prompting

    normalized_camera = _parse_shot({
        "action": {"tags": ["presenting_foot"], "text": None},
        "environment": "bedroom",
        "camera": {"shot": "close-up", "angle": "front_view", "focus": "foot_focus"},
    })
    assert normalized_camera["camera"]["view"] == "foot_focus"
    natural_only = _parse_shot({
        "action": {"tags": [], "text": "reaching for the door handle with her right hand"},
        "environment": "half-open door leading into a quiet hallway",
        "camera": {"view": "medium_shot", "angle": "from_side", "pov": False},
    })
    assert not natural_only["action"]["tags"]
    assert natural_only["action"]["text"].startswith("reaching for")
    assert natural_only["environment"].startswith("half-open door")
    assert len(_compact_natural_phrase("word " * 30, 25).split()) == 25
    forced_wardrobe = VisualContinuityAgent.normalize_prompt_plan(
        {
            "camera": {"view": "medium_shot", "angle": None, "pov": False},
            "action": {"tags": [], "text": None},
            "environment": "",
        },
        {"gender": "female", "role_tags": [], "body_tags": [], "appearance_tags": []},
        {"wardrobe": wardrobe_from_tags(["topless", "blue_skirt", "barefoot"]), "scene_tags": []},
    )
    assert "role_tags" not in forced_wardrobe
    assert "wardrobe_tags" not in forced_wardrobe
    assert forced_wardrobe["environment"] == "current setting"
    compact_state = merge_continuity_patch(
        {
            "version": 1,
            "initialized": True,
            "wardrobe": wardrobe_from_tags(["white_shirt", "blue_skirt"]),
            "scene_tags": ["bedroom"],
        },
        {
            "wardrobe": {"upper": ["black_tank_top"]},
            "scene": ["classroom", "after_school"],
        },
    )
    assert "black_tank_top" in compact_state["outfit_tags"]
    assert compact_state["scene_tags"] == ["classroom", "after_school"]
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
                "gender": "male",
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

            reference_data = root / "data" / "sex_tag"
            reference_data.mkdir(parents=True)
            (reference_data / "NSFW_sex_acts.csv").write_text("tag_en\nfellatio\n", encoding="utf-8")
            assert list_characters() == [char]
            assert reference_data.exists()
            assert not (root / "characters" / "sex_tag").exists()

            create_character("gender_probe", {
                "name": "Gender Probe",
                "gender": "male",
                "identity": "test only",
                "user_profile": {"gender": "female"},
            })
            assert get_profile("gender_probe")["gender"] == "male"
            assert load_user_profile("gender_probe")["gender"] == "female"

            frozen = capture_state_snapshot(char)
            directed = build_image_prompt(char, "unused", state_snapshot=frozen, shot_spec={
                "camera": {"view": "chest_focus", "angle": "front_view", "pov": False},
                "action": {
                    "tags": ["presenting_breasts", "blushing"],
                    "text": "presenting his chest clearly toward the viewer",
                },
                "environment": "living room, soft light, sofa beside him",
            })
            assert all(tag in directed for tag in ("1boy", "solo", "petite", "black_hair", "brown_eyes"))
            assert "1girl" not in directed
            assert "rating:" not in directed
            assert directed.index("1boy") < directed.index("solo")
            assert "white shirt" in directed and "blue skirt" in directed
            assert "presenting his chest clearly" in directed
            assert "sofa beside him" in directed

            long_prompt = build_image_prompt(char, "unused", state_snapshot=frozen, shot_spec={
                "role_tags": ["ignored_director_role"],
                "appearance_tags": [f"ignored_feature_{index}" for index in range(30)],
                "camera": {"view": "medium_shot", "angle": "front_view", "pov": False},
                "action": {
                    "tags": ["standing", "posing", "smile"],
                    "text": "interacting naturally with the furniture while facing the viewer",
                },
                "environment": "living room, sofa and window, soft light",
            })
            assert "ignored_feature_29" not in long_prompt
            assert "ignored_director_role" not in long_prompt

            compacted = build_image_prompt(char, "unused", state_snapshot=frozen, shot_spec={
                "camera": {"view": "medium_shot", "angle": "front_view", "pov": False},
                "action": {"tags": ["standing", "posing", "smile"], "text": "word " * 30},
                "environment": "place " * 25,
            })
            # Prose is compacted softly and never blocks image generation.
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
            assert "角色性别：male" in momo_prompt
            assert "玩家性别：未设置" in momo_prompt
            assert momo_prompt.count("玩家性别：") == 1
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
            assert "rating:" not in manual_prompt
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
