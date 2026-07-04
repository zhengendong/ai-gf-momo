"""Smoke-test the runtime state/plan contract without calling an LLM."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.output_monitor import (  # noqa: E402
    check_output_consistency,
    infer_missing_plan_updates,
)
from backend.models.schemas import AgentOutput  # noqa: E402


async def main() -> int:
    pending = AgentOutput(
        reply="呜呜别凶嘛，我这就去换，等我一下下。",
        state_updates=None,
        plan_updates=None,
    )
    fallback = infer_missing_plan_updates("sakura", "你到底换不换", pending)
    print("fallback_plan:", fallback)
    pending_result = await check_output_consistency(None, "sakura", "你到底换不换", pending)
    print("pending_without_plan:", pending_result)

    pending.plan_updates = fallback
    pending_ok = await check_output_consistency(None, "sakura", "你到底换不换", pending)
    print("pending_with_fallback:", pending_ok)

    completed_without_state = AgentOutput(
        reply="主人～换好啦！小樱又穿回吊带小背心和热裤了哦～是不是又变得清爽啦？",
        state_updates=None,
        plan_updates=None,
    )
    completed_result = await check_output_consistency(
        None,
        "sakura",
        "好呀",
        completed_without_state,
    )
    print("completed_without_state:", completed_result)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
