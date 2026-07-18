"""Exercise the real conversation runtime against isolated deterministic fakes."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import settings
from backend.core.chat_history import read_chat_history
from backend.core.characters import get_profile, reset_character_memory, update_profile
from backend.core.context import load_conversation_summary
from backend.core.orchestrator import bg_tasks
from backend.core.runtime import AgentRuntime
from backend.core.state import is_state_initialized, read_status, write_uninitialized_state
from backend.models.schemas import StreamChunk

CHARACTER = "probe"


class FakeLLM:
    def __init__(self, replies: list[dict | str]):
        self.replies = list(replies)
        self.calls: list[dict] = []

    async def chat_prompt(self, system: str, user: str, **kwargs) -> str:
        self.calls.append({
            "system_len": len(system or ""),
            "user_len": len(user or ""),
            "user": user or "",
            "user_preview": (user or "")[-1600:],
            "kwargs": kwargs,
        })
        if not self.replies:
            raise RuntimeError("FakeLLM has no more replies")
        item = self.replies.pop(0)
        return item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)


class FakeComfy:
    def build_workflow_from_template(self, **kwargs):
        return {"prompt": kwargs.get("prompt", "")}

    async def submit_and_wait(self, workflow, *args, **kwargs):
        return "fake_prompt_id", {
            "outputs": {"1": {"images": [{"filename": "probe.png", "subfolder": ""}]}}
        }

    async def get_image(self, filename, subfolder="", folder_type="output"):
        return b"\x89PNG\r\n\x1a\n"


class CapturingSender:
    def __init__(self):
        self.chunks: list[StreamChunk] = []

    async def send_chunk(self, session_id: str, chunk: StreamChunk, character: str | None = None):
        if character and not chunk.character:
            chunk.character = character
        self.chunks.append(chunk)


def write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def setup_temp_app(root: Path):
    settings.base_dir = root
    for name in ("agent.md", "image_director.md"):
        write(root / "config" / name, (ROOT / "config" / name).read_text(encoding="utf-8"))
    shutil.copytree(ROOT / "config" / "knowledge", root / "config" / "knowledge", dirs_exist_ok=True)
    write(root / "config" / "settings.json", json.dumps({
        "active_character": CHARACTER,
        "context": {"max_tokens": 16000, "compress_at": 0.85},
        "memory": {"turns_per_condense": 0, "vector_recall_enabled": False, "retention_days": 0},
    }, ensure_ascii=False, indent=2))
    char_dir = root / "characters" / CHARACTER
    if char_dir.exists():
        shutil.rmtree(char_dir, ignore_errors=True)
    write(char_dir / "profile.json", json.dumps({
        "name": "探针",
        "avatar": "T",
        "gender": "female",
        "visual_anchor": {
            "role_tags": "1girl, solo",
            "body_tags": "petite",
            "appearance_tags": "black_hair, brown_eyes",
        },
    }, ensure_ascii=False, indent=2))
    write(char_dir / "identity.md", "你叫探针，只用于运行时测试。")
    write(char_dir / "user.json", json.dumps({"user_pet_name": "测试员"}, ensure_ascii=False))
    write(char_dir / "memory" / "status.md", """# 探针的状态
## 穿着
- white_shirt
- black_pleated_skirt
- black_mary_jane_shoes
- white_thighhighs

## 场景细节
- bedroom
- indoors
- evening
- warm_lighting

## 探针的心情状态
- 等待测试
""")
    write(char_dir / "memory" / "chat_history.json", json.dumps({"messages": []}, ensure_ascii=False))


def seed_chat_history(root: Path, pairs: int):
    messages = []
    for idx in range(pairs):
        messages.extend([
            {"role": "user", "type": "text", "content": f"历史用户消息 {idx}", "completed": True},
            {"role": "assistant", "type": "text", "content": f"历史助手回复 {idx}", "completed": True},
        ])
    write(
        root / "characters" / CHARACTER / "memory" / "chat_history.json",
        json.dumps({"messages": messages}, ensure_ascii=False, indent=2),
    )


def no_change(reason: str = "无视觉状态变化。") -> dict:
    return {
        "reason": reason,
        "state_patch": {"wardrobe": {}, "scene": None},
        "shot_spec": None,
    }


def initial_state_patch() -> dict:
    return {
        "reason": "开场已明确建立时间、地点和完整穿着。",
        "state_patch": {
            "wardrobe": {
                "upper": {"mode": "replace", "layers": [{
                    "id": "cardigan_1", "slots": ["upper"],
                    "category": "outerwear", "tags": ["cream_knit_cardigan"],
                }]},
                "lower": {"mode": "replace", "layers": [{
                    "id": "long_skirt_1", "slots": ["lower"],
                    "category": "outerwear", "tags": ["brown_long_skirt"],
                }]},
                "legwear": {"mode": "replace", "layers": [{
                    "id": "ankle_socks_1", "slots": ["legwear"],
                    "category": "legwear", "tags": ["white_ankle_socks"],
                }]},
                "footwear": {"mode": "replace", "layers": [{
                    "id": "canvas_shoes_1", "slots": ["footwear"],
                    "category": "footwear", "tags": ["beige_canvas_shoes"],
                }]},
            },
            "scene": {"mode": "replace", "tags": ["bookstore", "rainy_afternoon"]},
        },
        "shot_spec": None,
    }


async def run_case(name: str, messages: list[str], llm_outputs: list[dict | str]):
    sender = CapturingSender()
    llm = FakeLLM(llm_outputs)
    runtime = AgentRuntime(llm, FakeComfy(), sender)
    durations = []
    for message in messages:
        start = time.perf_counter()
        await runtime.handle_message(f"{name}_session", CHARACTER, message)
        durations.append(time.perf_counter() - start)
        await asyncio.sleep(0)
    if bg_tasks.active_count:
        await asyncio.gather(*list(bg_tasks._tasks), return_exceptions=True)

    status = read_status(CHARACTER)
    history = read_chat_history(CHARACTER)
    previews = [call["user_preview"] for call in llm.calls]
    visual_payloads = []
    for call in llm.calls:
        try:
            payload = json.loads(call["user"])
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and "previous_state" in payload:
            visual_payloads.append(payload)
    result = {
        "case": name,
        "llm_calls": len(llm.calls),
        "llm_user_lengths": [call["user_len"] for call in llm.calls],
        "durations_ms": [round(item * 1000, 1) for item in durations],
        "checks": {
            "status_has_new_outfit": "black_tank_top" in status and "black_short_shorts" in status,
            "legwear_removed": "white_thighhighs" not in status,
            "footwear_removed": "black_mary_jane_shoes" not in status,
            "history_role_order": [item.get("role") for item in history[:4]],
            "chunk_type_order": [chunk.type for chunk in sender.chunks],
            "memory_update_notified": any(chunk.type == "memory_updated" for chunk in sender.chunks),
            "second_main_prompt_has_first_turn": len(previews) >= 3 and "蓝莓" in previews[2],
            "main_prompt_marks_status_objective": bool(llm.calls) and "本轮开始时的客观视觉事实" in llm.calls[0]["user"],
            "visual_history_messages": [len(payload.get("recent_dialogue") or []) for payload in visual_payloads],
            "visual_history_within_limit": all(len(payload.get("recent_dialogue") or []) <= 16 for payload in visual_payloads),
            "summary_empty": not load_conversation_summary(CHARACTER).strip(),
            "all_fake_outputs_consumed": not llm.replies,
        },
    }
    if "--verbose" in sys.argv:
        result.update({
            "llm_user_previews": previews,
            "text_chunks": [chunk.content for chunk in sender.chunks if chunk.type == "text"],
            "state_chunks": [json.loads(chunk.content) for chunk in sender.chunks if chunk.type == "state_update"],
            "status": status,
            "chat_history": history,
        })
    return result


async def run_scene_transition_case():
    sender = CapturingSender()
    llm = FakeLLM([
        {
            "reply": "几天后的午后，她穿着校服站在教学楼走廊，朝你挥了挥手。",
            "image_goal": None,
            "memory_candidate": None,
            "persist_context": True,
        },
        {
            "reason": "下一幕已明确建立学校走廊和校服。",
            "state_patch": {
                "wardrobe": {
                    "upper": {"mode": "replace", "layers": [{
                        "id": "school_blazer_1", "slots": ["upper"],
                        "category": "outerwear", "tags": ["navy_school_blazer"],
                    }]},
                    "lower": {"mode": "replace", "layers": [{
                        "id": "school_skirt_1", "slots": ["lower"],
                        "category": "outerwear", "tags": ["plaid_school_skirt"],
                    }]},
                    "legwear": {"mode": "replace", "layers": [{
                        "id": "knee_socks_1", "slots": ["legwear"],
                        "category": "legwear", "tags": ["black_knee_socks"],
                    }]},
                    "footwear": {"mode": "replace", "layers": [{
                        "id": "loafers_1", "slots": ["footwear"],
                        "category": "footwear", "tags": ["brown_loafers"],
                    }]},
                },
                "scene": {"mode": "replace", "tags": ["school_hallway", "afternoon"]},
            },
            "shot_spec": None,
        },
    ])
    runtime = AgentRuntime(llm, FakeComfy(), sender)
    await runtime.handle_scene_transition(
        "scene_session", CHARACTER, mode="manual", concept="几天后在学校重逢"
    )
    if bg_tasks.active_count:
        await asyncio.gather(*list(bg_tasks._tasks), return_exceptions=True)

    history = read_chat_history(CHARACTER)
    chunk_types = [chunk.type for chunk in sender.chunks]
    visual_payload = json.loads(llm.calls[1]["user"])
    assert visual_payload["interaction_mode"] == "scene_transition"
    assert "界面触发的剧情推进任务" in llm.calls[0]["user"]
    assert [item["type"] for item in history[-2:]] == ["scene_divider", "text"]
    assert all("用户对下一幕的构想" not in item.get("content", "") for item in history)
    assert chunk_types.index("state_update") < chunk_types.index("scene_divider") < chunk_types.index("text")
    assert "school_hallway" in read_status(CHARACTER)
    return {
        "case": "scene_transition",
        "llm_calls": len(llm.calls),
        "checks": {
            "chunk_type_order": chunk_types,
            "history_tail_types": [item["type"] for item in history[-2:]],
            "hidden_instruction_not_persisted": True,
            "interaction_mode_forwarded": True,
        },
    }


async def run_initial_scene_case():
    write_uninitialized_state(CHARACTER)
    update_profile(CHARACTER, {
        "initial_scene": {
            "concept": "雨日下午在旧书店初次见面，她穿适合逛书店的日常服装。",
            "opening_mode": "character_first",
        }
    })
    sender = CapturingSender()
    llm = FakeLLM([
        {
            "reply": "雨声落在旧书店的玻璃窗上。她穿着米色针织开衫和棕色长裙，抱着书朝你笑了笑：‘你也喜欢这本吗？’",
            "image_goal": None,
            "memory_candidate": None,
            "persist_context": True,
        },
        initial_state_patch(),
    ])
    runtime = AgentRuntime(llm, FakeComfy(), sender)
    await runtime.handle_initial_scene("initial_session", CHARACTER)
    if bg_tasks.active_count:
        await asyncio.gather(*list(bg_tasks._tasks), return_exceptions=True)

    history = read_chat_history(CHARACTER)
    chunk_types = [chunk.type for chunk in sender.chunks]
    assert is_state_initialized(CHARACTER)
    assert [item["type"] for item in history] == ["scene_divider", "text"]
    assert chunk_types.index("state_update") < chunk_types.index("scene_divider") < chunk_types.index("text")
    assert "初始场景事实构想" in llm.calls[0]["user"]
    assert "不要机械复刻" in llm.calls[0]["user"]
    assert all("玩家保存的初始场景" not in item.get("content", "") for item in history)
    return {
        "case": "initial_scene_character_first",
        "checks": {
            "initialized": True,
            "history_types": [item["type"] for item in history],
            "chunk_type_order": chunk_types,
            "template_is_hidden": True,
        },
    }


async def run_initial_scene_with_first_message_case():
    update_profile(CHARACTER, {
        "initial_scene": {
            "concept": "雨日下午在旧书店初次见面。",
            "opening_mode": "player_first",
        }
    })
    saved = get_profile(CHARACTER)["initial_scene"]
    reset_character_memory(CHARACTER)
    assert not is_state_initialized(CHARACTER)
    assert get_profile(CHARACTER)["initial_scene"] == saved

    sender = CapturingSender()
    llm = FakeLLM([
        {
            "reply": "雨日下午，旧书店里很安静。她穿着米色针织开衫和棕色长裙，从书架后抬起头：‘你好。’",
            "image_goal": None,
            "memory_candidate": None,
            "persist_context": True,
        },
        initial_state_patch(),
    ])
    runtime = AgentRuntime(llm, FakeComfy(), sender)
    await runtime.handle_message("initial_user_session", CHARACTER, "你好，请问这本书放在哪里？")
    if bg_tasks.active_count:
        await asyncio.gather(*list(bg_tasks._tasks), return_exceptions=True)

    history = read_chat_history(CHARACTER)
    assert is_state_initialized(CHARACTER)
    assert [item["type"] for item in history] == ["scene_divider", "text", "text"]
    assert [item["role"] for item in history] == ["system", "user", "assistant"]
    assert history[1]["content"] == "你好，请问这本书放在哪里？"
    assert "玩家第一条消息：你好，请问这本书放在哪里？" in llm.calls[0]["user"]
    assert all("根据角色身份" not in item.get("content", "") for item in history)
    return {
        "case": "initial_scene_with_first_message",
        "checks": {
            "template_survives_reset": True,
            "initialized": True,
            "history_types": [item["type"] for item in history],
            "history_roles": [item["role"] for item in history],
            "first_message_persisted_verbatim": True,
        },
    }


async def main():
    with tempfile.TemporaryDirectory(prefix="ai_gf_probe_") as tmp:
        root = Path(tmp)
        results = []

        setup_temp_app(root)
        results.append(await run_case("complete_state_update", ["换装后直接给我看"], [
            {
                "reply": "换好了，我穿着黑色吊带背心和黑色短裤站在你面前。",
                "image_goal": {"purpose": "展示换装结果", "visibility": "clear"},
                "memory_candidate": None,
                "persist_context": True,
            },
            {
                "reason": "角色明确完成换装。",
                "state_patch": {
                    "wardrobe": {
                        "upper": {"mode": "replace", "layers": [{
                            "id": "black_tank_top_1", "slots": ["upper"],
                            "category": "outerwear", "tags": ["black_tank_top"],
                        }]},
                        "lower": {"mode": "replace", "layers": [{
                            "id": "black_short_shorts_1", "slots": ["lower"],
                            "category": "outerwear", "tags": ["black_short_shorts"],
                        }]},
                    },
                    "scene": None,
                },
                "shot_spec": {
                    "reason": "展示换装结果",
                    "role_tags": ["1girl", "solo"],
                    "body_tags": ["petite"],
                    "appearance_tags": ["black_hair", "brown_eyes"],
                    "wardrobe_tags": ["black tank top", "black short shorts"],
                    "scene_tags": ["bedroom"],
                    "action_tags": ["showing_outfit"],
                    "action_text": "She displays her changed outfit while standing in front of the viewer.",
                    "pose": ["standing"],
                    "expression": ["smile"],
                    "camera": {"shot": "full_body", "angle": "front_view", "focus": None, "pov": False},
                    "environment_text": "She stands near the bed in a quiet bedroom.",
                    "lighting": [], "rating": "general",
                },
            },
        ]))

        setup_temp_app(root)
        results.append(await run_case("continuity_state_parse", ["脱掉丝袜"], [
            {"reply": "她把丝袜褪下，放到床边。", "image_goal": None, "memory_candidate": None, "persist_context": True},
            {
                "reason": "丝袜已经脱下。",
                "state_patch": {"wardrobe": {"legwear": {"mode": "replace", "layers": []}}, "scene": None},
                "shot_spec": None,
            },
        ]))

        setup_temp_app(root)
        results.append(await run_case("continuity_retry", ["把鞋脱了"], [
            {"reply": "她弯腰脱下鞋，赤脚站在地毯上。", "image_goal": None, "memory_candidate": None, "persist_context": True},
            "not-json",
            {
                "reason": "修复后确认鞋已脱下。",
                "state_patch": {"wardrobe": {"footwear": {"mode": "replace", "layers": []}}, "scene": None},
                "shot_spec": None,
            },
        ]))

        setup_temp_app(root)
        results.append(await run_case("memory_candidate_refresh", ["我一直最喜欢蓝莓"], [
            {
                "reply": "蓝莓啊，我记住了。", "image_goal": None,
                "memory_candidate": "用户明确表示长期喜欢蓝莓。", "persist_context": True,
            },
            no_change(),
            {"should_write": True, "long_term": "# 探针的长期记忆\n\n## 用户偏好\n- 测试员明确喜欢蓝莓。\n"},
        ]))

        setup_temp_app(root)
        results.append(await run_case("two_turn_memory", ["记住暗号是蓝莓", "刚才暗号是什么"], [
            {"reply": "我记住了，暗号是蓝莓。", "image_goal": None, "memory_candidate": None, "persist_context": True},
            no_change(),
            {"reply": "刚才暗号是蓝莓。", "image_goal": None, "memory_candidate": None, "persist_context": True},
            no_change(),
        ]))

        setup_temp_app(root)
        seed_chat_history(root, pairs=40)
        large_history = await run_case("large_history_latency", ["现在正常回复一句"], [
            {"reply": "收到，我正常回复一句。", "image_goal": None, "memory_candidate": None, "persist_context": True},
            no_change(),
        ])
        assert large_history["checks"]["visual_history_messages"] == [16]
        assert large_history["checks"]["main_prompt_marks_status_objective"]
        results.append(large_history)

        setup_temp_app(root)
        results.append(await run_scene_transition_case())

        setup_temp_app(root)
        results.append(await run_initial_scene_case())

        setup_temp_app(root)
        results.append(await run_initial_scene_with_first_message_case())

        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
