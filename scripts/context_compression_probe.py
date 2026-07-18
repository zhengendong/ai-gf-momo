"""Offline probe for rolling context-summary selection and cursor commits."""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import settings
from backend.core.chat_history import read_chat_history, write_chat_history
from backend.core.context import load_conversation_summary
from backend.core.memory_policy import (
    commit_context_compression,
    load_runtime_state,
    prepare_context_window,
)
from backend.core.orchestrator import bg_tasks
from backend.core.runtime import AgentRuntime


class SummaryLLM:
    def __init__(self):
        self.calls = []

    async def chat_prompt(self, **kwargs):
        self.calls.append(kwargs)
        return "旧剧情已经压缩；人物关系和事件顺序得到保留。"


class NullSender:
    async def send_chunk(self, *args, **kwargs):
        return None


def make_messages(count: int, repeats: int = 25) -> list[dict]:
    messages = []
    for index in range(count):
        role = "user" if index % 2 == 0 else "assistant"
        messages.append({
            "id": f"message-{index}",
            "role": role,
            "type": "text",
            "content": f"第{index}段剧情：" + ("连续剧情内容" * repeats),
        })
    return messages


async def main():
    original_base = settings.base_dir
    with tempfile.TemporaryDirectory() as temp:
        settings.base_dir = Path(temp)
        try:
            settings.config_dir.mkdir(parents=True)
            settings.settings_file.write_text(
                json.dumps({"context": {"max_tokens": 8000, "compress_at": 0.5}}),
                encoding="utf-8",
            )
            settings.get_memory_dir("probe").mkdir(parents=True)
            # This history is above the 50% compression threshold but still
            # below the hard model window, so the current turn must keep it.
            write_chat_history("probe", make_messages(20))

            window = await prepare_context_window(
                None,
                "probe",
                "角色",
                "用户",
                "当前消息",
                "系统提示",
                all_messages=read_chat_history("probe", repair=False),
            )
            assert window.compression_plan is not None
            assert window.compression_plan.message_count > 0
            assert window.compression_plan.turns_to_compress
            assert window.chat_history
            assert "第0段剧情" in window.chat_history

            llm = SummaryLLM()
            # Exercise the real non-blocking runtime scheduler, not only the
            # lower-level commit helper.
            runtime = AgentRuntime(llm, None, NullSender())
            runtime._schedule_context_compression(window.compression_plan)
            assert "probe" in runtime._context_compression_pending
            await asyncio.gather(*list(bg_tasks._tasks), return_exceptions=False)
            assert "probe" not in runtime._context_compression_pending

            state = load_runtime_state("probe")
            assert state["conversation_summary"].startswith("旧剧情已经压缩")
            assert state["compressed_message_count"] == window.compression_plan.message_count
            assert state["compressed_through_fingerprint"] == window.compression_plan.through_fingerprint
            assert "旧剧情已经压缩" in load_conversation_summary("probe")

            next_window = await prepare_context_window(
                None,
                "probe",
                "角色",
                "用户",
                "下一条消息",
                "系统提示",
                all_messages=read_chat_history("probe", repair=False),
            )
            assert next_window.summary.startswith("旧剧情已经压缩")
            assert "第0段剧情" not in next_window.chat_history
            assert not commit_context_compression(window.compression_plan, "过期任务不应覆盖新摘要")
            assert state["conversation_summary"] == load_runtime_state("probe")["conversation_summary"]
            assert len(llm.calls) == 1
            print("context compression probe: ok")
        finally:
            settings.base_dir = original_base


if __name__ == "__main__":
    asyncio.run(main())
