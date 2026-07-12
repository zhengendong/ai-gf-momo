"""Probe AgentRuntime with isolated fake conversations.

This script does not read or write real character history. It points the global
settings object at a temporary app tree, creates one probe character, and drives
the real runtime with a deterministic fake LLM.
"""

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
from backend.core.orchestrator import bg_tasks
from backend.core.state import read_status
from backend.core.chat_history import read_chat_history
from backend.core.context import load_conversation_summary
from backend.core.runtime import AgentRuntime
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
            "user_preview": (user or "")[-1600:],
            "kwargs": kwargs,
        })
        if not self.replies:
            raise RuntimeError("FakeLLM has no more replies")
        item = self.replies.pop(0)
        if isinstance(item, str):
            return item
        return json.dumps(item, ensure_ascii=False)


class FakeComfy:
    def build_workflow_from_template(self, **kwargs):
        return {"prompt": kwargs.get("prompt", "")}

    async def queue_prompt(self, workflow):
        return "fake_prompt_id"

    async def wait_for_completion(self, prompt_id, *args, **kwargs):
        return {"outputs": {"1": {"images": [{"filename": "probe.png", "subfolder": ""}]}}}

    async def get_image(self, filename, subfolder=""):
        # Minimal PNG header payload is enough for file IO tests here.
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
    write(root / "config" / "agent.md", (Path(__file__).resolve().parents[1] / "config" / "agent.md").read_text(encoding="utf-8"))
    shutil.copytree(
        Path(__file__).resolve().parents[1] / "config" / "knowledge",
        root / "config" / "knowledge",
        dirs_exist_ok=True,
    )
    write(root / "config" / "settings.json", json.dumps({
        "active_character": CHARACTER,
        "context": {"max_tokens": 16000, "compress_at": 0.85},
        "memory": {
            "turns_per_condense": 0,
            "vector_recall_enabled": False,
            "retention_days": 0,
        },
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
    write(char_dir / "user.json", json.dumps({"user_pet_name": "测试员"}, ensure_ascii=False, indent=2))
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
    write(char_dir / "memory" / "chat_history.json", json.dumps({"messages": []}, ensure_ascii=False, indent=2))


def seed_chat_history(root: Path, pairs: int):
    messages = []
    for idx in range(pairs):
        messages.append({
            "role": "user",
            "type": "text",
            "content": f"历史用户消息 {idx}",
            "completed": True,
        })
        messages.append({
            "role": "assistant",
            "type": "text",
            "content": f"历史助手回复 {idx}",
            "completed": True,
        })
    write(
        root / "characters" / CHARACTER / "memory" / "chat_history.json",
        json.dumps({"messages": messages}, ensure_ascii=False, indent=2),
    )


async def run_case(name: str, messages: list[str], llm_outputs: list[dict | str]):
    sender = CapturingSender()
    llm = FakeLLM(llm_outputs)
    runtime = AgentRuntime(llm, FakeComfy(), sender)
    durations = []
    for idx, message in enumerate(messages):
        start = time.perf_counter()
        await runtime.handle_message(f"{name}_session", CHARACTER, message)
        durations.append(time.perf_counter() - start)
        await asyncio.sleep(0)
    # Allow lightweight background tasks to finish or fail visibly.
    if bg_tasks.active_count:
        await asyncio.gather(*list(bg_tasks._tasks), return_exceptions=True)
    status = read_status(CHARACTER)
    chat_history = read_chat_history(CHARACTER)
    previews = [call["user_preview"] for call in llm.calls]
    result = {
        "case": name,
        "llm_calls": len(llm.calls),
        "llm_user_lengths": [call["user_len"] for call in llm.calls],
        "durations_ms": [round(d * 1000, 1) for d in durations],
        "checks": {
            "status_has_new_outfit": (
                ("black_tank_top" in status and "black_short_shorts" in status)
                or ("white_cami_top" in status and "black_shorts" in status)
            ),
            "history_role_order": [m.get("role") for m in chat_history[:4]],
            "chunk_type_order": [c.type for c in sender.chunks],
            "memory_update_notified": any(c.type == "memory_updated" for c in sender.chunks),
            "second_prompt_has_first_turn": len(previews) >= 2 and "蓝莓" in previews[1],
            "summary_empty": not load_conversation_summary(CHARACTER).strip(),
        },
    }
    if "--verbose" in sys.argv:
        result.update({
            "llm_user_previews": previews,
            "text_chunks": [c.content for c in sender.chunks if c.type == "text"],
            "state_chunks": [json.loads(c.content) for c in sender.chunks if c.type == "state_update"],
            "status": status,
            "chat_history": chat_history,
            "summary": load_conversation_summary(CHARACTER),
        })
    return result


async def main():
    with tempfile.TemporaryDirectory(prefix="ai_gf_probe_") as tmp:
        setup_temp_app(Path(tmp))
        results = []

        results.append(await run_case(
            "complete_state_update",
            ["换成吊带小背心和短裤，直接换好给我看"],
            [{
                "reply": "换好了，我现在穿着黑色吊带小背心和黑色短裤站在你面前。",
                "effects": [{
                    "type": "replace_outfit",
                    "status": "completed",
                    "tags": ["black_tank_top", "black_short_shorts", "black_mary_jane_shoes", "white_thighhighs"],
                }],
                "image_intent": {
                    "generate": True,
                    "pose": ["standing"],
                    "expression": ["smile", "looking_at_viewer"],
                    "camera": {"shot": "full_body", "angle": "front_view"},
                    "rating": "general",
                },
                "immediate_memory": None,
                "persist_context": True,
            }],
        ))

        # Reset state for missing-state repair case.
        setup_temp_app(Path(tmp))
        results.append(await run_case(
            "missing_state_repair",
            ["好呀"],
            [
                {
                    "reply": "我换好了，现在穿着黑色吊带小背心和黑色短裤站在你面前。",
                    "photo_prompt": None,
                    "state_updates": None,
                    "immediate_memory": None,
                    "persist_context": True,
                },
                {
                    "reply": "我换好了，现在穿着黑色吊带小背心和黑色短裤站在你面前。",
                    "photo_prompt": None,
                    "state_updates": {
                        "status": {
                            "穿着": "- black_tank_top\n- black_short_shorts\n- black_mary_jane_shoes\n- white_thighhighs",
                            "心情状态": "- 换装完成",
                        }
                    },
                    "immediate_memory": None,
                    "persist_context": True,
                },
            ],
        ))

        setup_temp_app(Path(tmp))
        results.append(await run_case(
            "colloquial_completed_outfit_repair",
            ["换回吧"],
            [
                {
                    "reply": "主人～换好啦！小樱又穿回吊带小背心和热裤了哦～是不是又变得清爽啦？",
                    "photo_prompt": None,
                    "state_updates": None,
                    "immediate_memory": None,
                    "persist_context": True,
                },
                {
                    "reply": "主人～换好啦！小樱又穿回吊带小背心和热裤了哦～是不是又变得清爽啦？",
                    "photo_prompt": None,
                    "state_updates": {
                        "status": {
                            "穿着": "- white_cami_top\n- black_shorts\n- barefoot",
                            "心情状态": "- 换回清凉服饰，等待主人确认",
                        }
                    },
                    "immediate_memory": None,
                    "persist_context": True,
                },
            ],
        ))

        setup_temp_app(Path(tmp))
        results.append(await run_case(
            "memory_candidate_refresh",
            ["我一直最喜欢蓝莓"],
            [
                {
                    "reply": "蓝莓啊，我记住了。",
                    "effects": [],
                    "image_intent": None,
                    "memory_candidate": "用户明确表示长期喜欢蓝莓。",
                    "persist_context": True,
                },
                {
                    "should_write": True,
                    "long_term": "# 探针的长期记忆\n\n## 用户偏好\n- 测试员明确喜欢蓝莓。\n",
                },
            ],
        ))

        setup_temp_app(Path(tmp))
        results.append(await run_case(
            "two_turn_memory",
            ["记住暗号是蓝莓", "刚才暗号是什么"],
            [
                {
                    "reply": "我记住了，暗号是蓝莓。",
                    "photo_prompt": None,
                    "state_updates": None,
                    "immediate_memory": None,
                    "persist_context": True,
                },
                {
                    "reply": "刚才暗号是蓝莓。",
                    "photo_prompt": None,
                    "state_updates": None,
                    "immediate_memory": None,
                    "persist_context": True,
                },
            ],
        ))

        setup_temp_app(Path(tmp))
        seed_chat_history(Path(tmp), pairs=40)
        results.append(await run_case(
            "large_history_latency",
            ["现在正常回复一句"],
            [{
                "reply": "收到，我正常回复一句。",
                "photo_prompt": None,
                "state_updates": None,
                "immediate_memory": None,
                "persist_context": True,
            }],
        ))

        print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
