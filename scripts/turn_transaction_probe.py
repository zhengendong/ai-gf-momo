"""Offline V2 turn probe: state operation, frozen snapshot and image director."""

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
from backend.core.output_monitor import check_output_consistency
from backend.core.state import read_state_snapshot, read_status
from backend.models.schemas import AgentOutput
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
                    "state_ops": [{
                        "domain": "wardrobe",
                        "operation": "remove",
                        "slot": "footwear",
                        "target": "outermost",
                    }],
                    "image_goal": {
                        "required": True,
                        "purpose": "展示本轮完成的变化",
                        "subject": "feet",
                        "visibility": "clear",
                        "rating": "general",
                    },
                    "memory_candidate": None,
                    "persist_context": True,
                },
                {
                    "reason": "清楚展示已完成的变化",
                    "action_tags": ["showing_feet"],
                    "pose": ["sitting_on_bed"],
                    "expression": ["looking_at_viewer"],
                    "camera": {
                        "shot": "close-up",
                        "angle": "front_view",
                        "focus": "feet_focus",
                        "pov": False,
                    },
                    "lighting": ["warm_lighting"],
                    "rating": "general",
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
            assert len(llm.calls) == 2, "one main call plus one conditional image-director call"

            statuses = [chunk.content for chunk in sender.chunks if chunk.type == "image_status"]
            assert "directing" in statuses and "generating" in statuses
            assert any(chunk.type == "image" for chunk in sender.chunks)

            history_path = root / "characters" / CHARACTER / "images" / "_history.json"
            history = json.loads(history_path.read_text(encoding="utf-8"))
            prompt = history[-1]["prompt"]
            assert "black_mary_jane_shoes" not in prompt
            assert "white_thighhighs" in prompt
            assert "barefoot" not in prompt
            assert "feet_focus" in prompt

            # A pure visual follow-up may restate the already committed
            # footwear state without pretending to remove it a second time.
            followup = AgentOutput(
                reply="鞋已经脱掉了，现在给你看看。",
                state_ops=[],
                image_goal={
                    "required": True,
                    "purpose": "展示当前已经脱鞋的状态",
                    "subject": "当前双脚",
                    "visibility": "clear",
                    "mood": "shy",
                    "rating": "general",
                },
            )
            followup_result = await check_output_consistency(CHARACTER, followup, "看一下")
            assert followup_result.valid, followup_result.issues

            # Combining a new state change with a visual request still
            # requires a real operation; the visual exemption must not hide it.
            missing_operation = await check_output_consistency(
                CHARACTER,
                followup,
                "把裙子脱掉给我看看",
            )
            assert not missing_operation.valid

            refusal_llm = FakeLLM([{
                "reply": "现在还没准备好，不能给你看。",
                "state_ops": [],
                "image_goal": None,
                "memory_candidate": None,
                "persist_context": True,
            }])
            refusal_sender = CapturingSender()
            refusal_runtime = AgentRuntime(refusal_llm, FakeComfy(), refusal_sender)
            await refusal_runtime.handle_message("refusal_session", CHARACTER, "现在给我看看")
            if bg_tasks.active_count:
                await asyncio.gather(*list(bg_tasks._tasks), return_exceptions=False)
            assert len(refusal_llm.calls) == 1, "a refusal must not trigger repair or image direction"
            assert not any(chunk.type == "image" for chunk in refusal_sender.chunks)
            print("turn transaction probe: ok")
    finally:
        settings.base_dir = original_base


if __name__ == "__main__":
    asyncio.run(main())
