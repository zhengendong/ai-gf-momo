"""Offline check: only MemoryAgent can accept a main-Agent memory candidate."""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents.memory import MemoryAgent
from backend.config import settings


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
            print("memory candidate probe: ok")
        finally:
            settings.base_dir = original_base


if __name__ == "__main__":
    asyncio.run(main())
