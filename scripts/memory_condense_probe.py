"""Probe MemoryAgent condensation with an isolated temporary character."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents.memory import MemoryAgent  # noqa: E402
from backend.config import settings  # noqa: E402


CHARACTER = "probe_memory"


class FakeLLM:
    def __init__(self):
        self.user_prompt = ""

    async def chat_prompt(self, system: str, user: str, **kwargs) -> str:
        self.user_prompt = user
        return json.dumps({
            "soul": "# 探针的灵魂\n\n## 自我认知\n- 会认真记住测试员的重要偏好。\n",
            "long_term": "# 探针的长期记忆\n\n## 用户偏好\n- 测试员喜欢蓝莓暗号。\n\n## 重要事件\n- 测试员要求验证长期记忆沉淀。\n",
        }, ensure_ascii=False)


def write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


async def main():
    with tempfile.TemporaryDirectory(prefix="ai_gf_memory_probe_") as tmp:
        root = Path(tmp)
        settings.base_dir = root
        char_dir = root / "characters" / CHARACTER
        write(char_dir / "profile.json", json.dumps({"name": "记忆探针"}, ensure_ascii=False))
        write(char_dir / "identity.md", "你叫记忆探针，只用于测试。")
        write(char_dir / "user.json", json.dumps({"user_pet_name": "测试员"}, ensure_ascii=False))
        write(char_dir / "memory" / "chat_history.json", json.dumps({
            "messages": [
                {"role": "user", "type": "text", "content": "请记住我喜欢蓝莓暗号。"},
                {"role": "assistant", "type": "text", "content": "我记住了，蓝莓是你的暗号。"},
            ]
        }, ensure_ascii=False, indent=2))

        llm = FakeLLM()
        result = await MemoryAgent(llm).condense(CHARACTER, days=1)
        soul = (char_dir / "memory" / "soul.md").read_text(encoding="utf-8")
        long_term = (char_dir / "memory" / "long_term.md").read_text(encoding="utf-8")
        print(json.dumps({
            "result_keys": sorted(result.keys()),
            "prompt_included_today_chat": "蓝莓" in llm.user_prompt,
            "soul_written": "认真记住" in soul,
            "long_term_written": "蓝莓暗号" in long_term,
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
