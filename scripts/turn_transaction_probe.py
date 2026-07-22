"""Offline turn probe: role reply, continuity patch and frozen image job."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import settings
from backend.core.orchestrator import bg_tasks
from backend.core.runtime import AgentRuntime
from backend.core.state import read_state_snapshot, read_status
from scripts.runtime_conversation_probe import (
    CHARACTER,
    CapturingSender,
    FakeComfy,
    FakeLLM,
    setup_temp_app,
)


async def main():
    original_base = settings.base_dir
    try:
        with tempfile.TemporaryDirectory(prefix="ai_gf_turn_v2_") as tmp:
            root = Path(tmp)
            setup_temp_app(root)
            # The image director prompt is intentionally separate from agent.md.
            (root / "config" / "image_director.md").write_text(
                (ROOT / "config" / "image_director.md").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            llm = FakeLLM([
                {
                    "reply": "我已经完成了本轮变化，现在给你看。",
                    "memory_candidate": None,
                    "persist_context": True,
                },
                {
                    "reason": "回复明确完成了脱鞋，更新 footwear 并设计画面。",
                    "state_patch": {
                        "wardrobe": {
                            "footwear": [],
                        },
                        "scene": None,
                    },
                    "shot": {
                        "reason": "清楚展示已完成的变化",
                        "action": {
                            "tags": ["sitting_on_bed", "showing_feet", "looking_at_viewer"],
                            "text": "extending both feet toward the viewer after removing her shoes",
                        },
                        "camera": {
                            "view": "foot_focus",
                            "angle": "front_view",
                            "pov": False,
                        },
                        "environment": "bedroom, warm light, bed edge and floor below",
                    },
                },
            ])
            sender = CapturingSender()
            runtime = AgentRuntime(llm, FakeComfy(), sender)
            await runtime.handle_message("v2_session", CHARACTER, "完成变化并给我看看")
            if bg_tasks.active_count:
                await asyncio.gather(*list(bg_tasks._tasks), return_exceptions=False)

            snapshot = read_state_snapshot(CHARACTER)
            wardrobe = snapshot["wardrobe"]
            assert not wardrobe["layers"]["footwear"]
            assert wardrobe["layers"]["legwear"]
            assert "black_mary_jane_shoes" not in read_status(CHARACTER)
            assert len(llm.calls) == 2, "one role call plus one always-on continuity call"
            director_payload = json.loads(llm.calls[1]["user"])
            assert "image_goal" not in director_payload
            assert "prompt_inputs" not in director_payload
            assert director_payload["previous_state"]["wardrobe"]["footwear"] == ["black_mary_jane_shoes"]
            assert director_payload["participants"]["character"]["gender"] == "female"
            assert director_payload["participants"]["character"]["primary_subject"] is True
            assert director_payload["participants"]["player"]["gender"] == "male"
            assert director_payload["participants"]["player"]["pov_owner"] is True

            statuses = [chunk.content for chunk in sender.chunks if chunk.type == "image_status"]
            assert "generating" in statuses
            assert any(chunk.type == "image" for chunk in sender.chunks)

            history_path = root / "characters" / CHARACTER / "images" / "_history.json"
            history = json.loads(history_path.read_text(encoding="utf-8"))
            prompt = history[-1]["prompt"]
            assert "black_mary_jane_shoes" not in prompt
            assert "white thighhighs" in prompt
            assert "barefoot" not in prompt
            assert "white shirt" in prompt and "black pleated skirt" in prompt
            assert "petite" in prompt and "black_hair" in prompt and "brown_eyes" in prompt
            assert "extending both feet toward the viewer" in prompt
            assert "bed edge and floor below" in prompt
            assert ":0.9" not in prompt and ":1.1" not in prompt

            refusal_llm = FakeLLM([
                {
                    "reply": "现在还没准备好，不能给你看。",
                    "memory_candidate": None,
                    "persist_context": True,
                },
                {
                    "reason": "角色拒绝，状态不变。",
                    "state_patch": {"wardrobe": {}, "scene": None},
                    "shot": None,
                },
            ])
            refusal_sender = CapturingSender()
            refusal_runtime = AgentRuntime(refusal_llm, FakeComfy(), refusal_sender)
            await refusal_runtime.handle_message("refusal_session", CHARACTER, "现在给我看看")
            if bg_tasks.active_count:
                await asyncio.gather(*list(bg_tasks._tasks), return_exceptions=False)
            assert len(refusal_llm.calls) == 2, "continuity runs even when no image is requested"
            assert not any(chunk.type == "image" for chunk in refusal_sender.chunks)

            # A fully invalid director response must not add another model
            # call or block delivery of the character reply.
            before_failure = read_state_snapshot(CHARACTER)
            failure_llm = FakeLLM([
                {
                    "reply": "我站到你面前，让你看清楚。",
                    "memory_candidate": None,
                    "persist_context": True,
                },
                "not-json",
                "still-not-json",
            ])
            failure_sender = CapturingSender()
            failure_runtime = AgentRuntime(failure_llm, FakeComfy(), failure_sender)
            await failure_runtime.handle_message("failure_session", CHARACTER, "换好了吗")
            assert read_state_snapshot(CHARACTER) == before_failure
            if bg_tasks.active_count:
                await asyncio.gather(*list(bg_tasks._tasks), return_exceptions=False)
            assert any(chunk.type == "text" for chunk in failure_sender.chunks)
            assert not any(chunk.type == "image" for chunk in failure_sender.chunks)
            assert len(failure_llm.calls) == 3, "one role call plus one director attempt and one repair"
            assert not any(
                chunk.type == "status_update" and "状态同步失败" in (chunk.content or "")
                for chunk in failure_sender.chunks
            )
            print("turn transaction probe: ok")
    finally:
        settings.base_dir = original_base


if __name__ == "__main__":
    asyncio.run(main())
