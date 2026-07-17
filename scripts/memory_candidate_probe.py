"""Offline check: only MemoryAgent can accept a main-Agent memory candidate."""

import asyncio
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents.memory import MemoryAgent
from backend.config import settings
from backend.core.chat_history import write_chat_history
from backend.core.memory_v3 import chat_messages_for_days


class FakeMemoryLLM:
    def __init__(self, should_write: bool):
        self.should_write = should_write

    async def chat_prompt(self, **kwargs):
        if not self.should_write:
            return json.dumps({"should_write": False}, ensure_ascii=False)
        return json.dumps({
            "should_write": True,
            "long_term": "# 探针的长期记忆\n\n## 用户偏好\n- 测试员明确喜欢蓝莓。\n",
        }, ensure_ascii=False)


class CaptureCondenseLLM:
    def __init__(self):
        self.user = ""

    async def chat_prompt(self, **kwargs):
        self.user = kwargs.get("user") or ""
        return json.dumps({
            "long_term": "# 探针的长期记忆\n\n## 重要事件\n- 故事中随后在书店重逢。\n",
        }, ensure_ascii=False)


async def main():
    original_base = settings.base_dir
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        settings.base_dir = root
        try:
            char_dir = root / "characters" / "probe"
            (char_dir / "memory").mkdir(parents=True)
            (char_dir / "profile.json").write_text(json.dumps({"name": "探针"}, ensure_ascii=False), encoding="utf-8")
            (char_dir / "identity.md").write_text("你叫探针。", encoding="utf-8")
            (char_dir / "user.json").write_text(json.dumps({"user_pet_name": "测试员"}, ensure_ascii=False), encoding="utf-8")
            long_term = char_dir / "memory" / "long_term.md"
            long_term.write_text("# 探针的长期记忆\n", encoding="utf-8")

            rejected = await MemoryAgent(FakeMemoryLLM(False)).evaluate_candidate(
                "probe", "测试员今天心情不错", "我今天心情不错", "那就好。",
            )
            assert not rejected["written"]
            assert long_term.read_text(encoding="utf-8") == "# 探针的长期记忆\n"

            accepted = await MemoryAgent(FakeMemoryLLM(True)).evaluate_candidate(
                "probe", "测试员明确表示长期喜欢蓝莓", "我一直最喜欢蓝莓", "我记住了。",
            )
            assert accepted["written"]
            assert "喜欢蓝莓" in long_term.read_text(encoding="utf-8")

            write_chat_history("probe", [
                {
                    "role": "user", "type": "text", "content": "几天后我们在书店重逢。",
                    "timestamp": "2037-08-09T10:11:12+00:00",
                },
                {
                    "role": "assistant", "type": "text", "content": "她在书架前向你招手。",
                    "timestamp": "2037-08-09T10:12:12+00:00",
                },
            ])
            source = chat_messages_for_days("probe", 1)
            assert "2037" not in source and "10:11" not in source
            assert "### 用户" in source and "### 角色" in source

            (char_dir / "memory" / f"{date.today().isoformat()}.md").write_text(
                "### 19:55 场景切换：\n几天后我们在书店重逢。\n\n### 新场景：\n她在书架前向你招手。\n",
                encoding="utf-8",
            )
            capture = CaptureCondenseLLM()
            await MemoryAgent(capture).condense("probe", days=1, target="long_term")
            assert "2037" not in capture.user
            assert date.today().isoformat() not in capture.user
            assert "19:55" not in capture.user
            print("memory candidate probe: ok")
        finally:
            settings.base_dir = original_base


if __name__ == "__main__":
    asyncio.run(main())
