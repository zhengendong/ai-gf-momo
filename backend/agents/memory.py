"""
Memory Agent — 记忆沉淀
定时或手动触发，从 daily memory 提炼精华更新 soul 和 long_term
"""

import logging
from pathlib import Path
from datetime import date, timedelta

from ..config import settings

logger = logging.getLogger(__name__)


class MemoryAgent:
    """记忆沉淀 Agent"""

    def __init__(self, llm_client):
        self.llm = llm_client

    async def condense(self, character: str, days: int = 1) -> dict:
        """
        执行记忆沉淀

        Args:
            character: 角色名
            days: 读取过去几天的 daily memory

        Returns:
            {"soul": "更新后的 soul.md 内容", "long_term": "更新后的 long_term.md 内容"}
        """
        memory_dir = settings.get_memory_dir(character)

        # 1. 读取 daily memory
        daily_texts = []
        for i in range(days):
            d = date.today() - timedelta(days=i + 1)
            path = memory_dir / f"{d.isoformat()}.md"
            if path.exists():
                daily_texts.append(f"## {d.isoformat()}\n{path.read_text(encoding='utf-8')}")

        if not daily_texts:
            logger.info(f"角色 {character} 没有需要沉淀的日记")
            return {}

        daily_content = "\n\n".join(daily_texts)

        # 2. 读取当前 soul 和 long_term
        soul_path = memory_dir / "soul.md"
        long_term_path = memory_dir / "long_term.md"
        current_soul = soul_path.read_text(encoding="utf-8") if soul_path.exists() else ""
        current_long = long_term_path.read_text(encoding="utf-8") if long_term_path.exists() else ""

        # 3. 调用 LLM 分析
        system = """你是记忆沉淀助手。你的任务是从对话日记中提炼精华，更新灵魂(soul)和长期记忆(long_term)。

规则：
- soul.md：只记录感情观、自我认知、核心欲望、底线变化。是"她变成了什么样的人"，不是流水账。必须短。过时的内容替换而非追加。
- long_term.md：记录主人偏好、纪念日、重要事件。同类合并、无意义删除。必须短。

输出 JSON：
{
  "soul": "更新后的 soul.md 完整内容",
  "long_term": "更新后的 long_term.md 完整内容"
}"""

        user = f"""## 对话日记
{daily_content}

## 当前 soul.md
{current_soul or "（空）"}

## 当前 long_term.md
{current_long or "（空）"}

请分析提炼，输出 JSON。"""

        try:
            import json
            raw = await self.llm.chat_prompt(system=system, user=user)

            # 解析 JSON
            text = raw.strip()
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

            data = json.loads(text)

            # 4. 写回文件
            if "soul" in data and data["soul"]:
                soul_path.write_text(data["soul"], encoding="utf-8")
                logger.info(f"soul.md 已更新 ({character})")

            if "long_term" in data and data["long_term"]:
                long_term_path.write_text(data["long_term"], encoding="utf-8")
                logger.info(f"long_term.md 已更新 ({character})")

            return data

        except Exception as e:
            logger.error(f"记忆沉淀失败: {e}")
            return {}
