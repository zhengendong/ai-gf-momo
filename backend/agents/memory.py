"""
Memory Agent — 记忆沉淀
定时或手动触发，从 daily memory 提炼精华更新 soul 和 long_term
"""

import logging
import re
from pathlib import Path
from datetime import date, timedelta

from ..config import settings
from ..core.context import (
    get_character_name,
    load_identity,
    render_user_profile,
)
from ..core.compressor import strip_model_thinking
from ..core.memory_v3 import chat_messages_for_days

logger = logging.getLogger(__name__)


class MemoryAgent:
    """记忆沉淀 Agent"""

    def __init__(self, llm_client):
        self.llm = llm_client

    async def condense(self, character: str, days: int = 1, target: str = "all") -> dict:
        """
        执行记忆沉淀

        Args:
            character: 角色名
            days: 读取过去几天的 daily memory

        Returns:
            {"soul": "更新后的 soul.md 内容", "long_term": "更新后的 long_term.md 内容"}
        """
        target = self._normalize_target(target)
        memory_dir = settings.get_memory_dir(character)
        char_name = get_character_name(character)
        identity = load_identity(character)
        user_profile = render_user_profile(character)

        # 1. 读取最近对话原料。days=1 表示今天，而不是昨天。
        source_texts = []
        chat_source = chat_messages_for_days(character, days)
        if chat_source.strip():
            source_texts.append(f"## 最近 {days} 天 chat_history.json\n{chat_source}")

        daily_texts = []
        for i in range(days):
            d = date.today() - timedelta(days=i)
            path = memory_dir / f"{d.isoformat()}.md"
            if path.exists():
                raw_daily = path.read_text(encoding="utf-8")
                daily_texts.append(f"## {d.isoformat()}\n{self._filter_daily_pollution(character, raw_daily)}")
        if daily_texts:
            source_texts.append("## daily memory\n" + "\n\n".join(daily_texts))

        if not source_texts:
            logger.info(f"角色 {character} 没有需要沉淀的对话材料")
            return {}

        source_content = "\n\n".join(source_texts)

        # 2. 读取当前 soul 和 long_term
        soul_path = memory_dir / "soul.md"
        long_term_path = memory_dir / "long_term.md"
        current_soul = soul_path.read_text(encoding="utf-8") if soul_path.exists() else ""
        current_long = long_term_path.read_text(encoding="utf-8") if long_term_path.exists() else ""

        output_schema = self._output_schema(target)
        target_rule = self._target_rule(target)

        # 3. 调用 LLM 分析
        system = f"""你是记忆沉淀助手。你的任务是从当前角色的对话日记中提炼精华。

当前角色是：{char_name}

规则：
- identity.md 是固定身份，只能作为判断依据，绝不能改写，也不能被日记覆盖。
- user.json 只描述用户，不描述角色身份。
- 如果日记中出现“当前角色自称为另一个名字/另一个角色”的内容，把它视为污染，不要沉淀。
- soul.md：只记录当前角色的自我认知、情感倾向、底线、执念等慢变化人格。不要写流水账，不要写用户偏好。
- long_term.md：只记录用户偏好、纪念日、重要事件、关系约定、稳定事实。不要写“当前角色是谁”。
- {target_rule}
- 输出必须短，合并同类项，删除无意义或污染内容。

输出 JSON：
{output_schema}"""

        user = f"""## 当前角色 identity.md（固定身份，只读）
{identity or "（空）"}

## 当前用户 user.json（只描述用户）
{user_profile or "（空）"}

## 对话材料（原料，可能含污染）
{source_content}

## 当前 soul.md
{current_soul or "（空）"}

## 当前 long_term.md
{current_long or "（空）"}

请分析提炼，输出 JSON。"""

        try:
            import json
            raw = await self.llm.chat_prompt(system=system, user=user)

            # 解析 JSON
            text = strip_model_thinking(raw)
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
            text = self._extract_json_object(text)

            data = self._filter_target(json.loads(text), target)
            data = self._sanitize_output(character, char_name, data)

            # 4. 写回文件
            soul_path.parent.mkdir(parents=True, exist_ok=True)
            long_term_path.parent.mkdir(parents=True, exist_ok=True)
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

    def _normalize_target(self, target: str | None) -> str:
        value = (target or "all").strip()
        if value in ("memory", "long-term", "longterm"):
            return "long_term"
        if value in ("long_term", "soul", "all"):
            return value
        return "all"

    def _target_rule(self, target: str) -> str:
        if target == "long_term":
            return "本次只允许更新 long_term.md；soul.md 只能作为参考，输出 JSON 中不要包含 soul。"
        if target == "soul":
            return "本次只允许更新 soul.md；long_term.md 只能作为参考，输出 JSON 中不要包含 long_term。"
        return "本次同时更新 soul.md 和 long_term.md。"

    def _output_schema(self, target: str) -> str:
        if target == "long_term":
            return '{\n  "long_term": "更新后的 long_term.md 完整内容"\n}'
        if target == "soul":
            return '{\n  "soul": "更新后的 soul.md 完整内容"\n}'
        return '{\n  "soul": "更新后的 soul.md 完整内容",\n  "long_term": "更新后的 long_term.md 完整内容"\n}'

    def _filter_target(self, data: dict, target: str) -> dict:
        if not isinstance(data, dict):
            return {}
        if target == "long_term":
            return {"long_term": data.get("long_term", "")}
        if target == "soul":
            return {"soul": data.get("soul", "")}
        return data

    def _extract_json_object(self, text: str) -> str:
        text = (text or "").strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return text[start:end + 1]
        return text

    def _sanitize_output(self, character: str, char_name: str, data: dict) -> dict:
        """Drop obvious identity-conflict lines before writing memory files."""
        known_names = set()
        chars_dir = settings.characters_dir
        if chars_dir.exists():
            for item in chars_dir.iterdir():
                if not item.is_dir():
                    continue
                try:
                    known_names.add(get_character_name(item.name))
                except Exception:
                    known_names.add(item.name)
        known_names.discard(char_name)
        known_names.discard(character)

        cleaned = dict(data or {})
        for key in ("soul", "long_term"):
            text = str(cleaned.get(key) or "")
            if not text:
                continue
            lines = []
            for line in text.splitlines():
                if self._is_identity_conflict(line, known_names):
                    logger.warning("沉淀输出疑似身份污染，已丢弃: %s", line)
                    continue
                lines.append(line)
            cleaned[key] = "\n".join(lines).strip() + "\n"
        return cleaned

    def _is_identity_conflict(self, line: str, other_names: set[str]) -> bool:
        if not other_names:
            return False
        text = line.strip()
        if not text:
            return False
        identity_markers = ("我是", "我叫", "你是", "她是", "角色是", "名字是")
        if not any(marker in text for marker in identity_markers):
            return False
        return any(name and name in text for name in other_names)

    def _filter_daily_pollution(self, character: str, text: str) -> str:
        """Remove obvious identity-conflict lines from daily logs before condensation."""
        from ..core.memory_v3 import is_identity_conflict_memory
        kept = []
        for line in (text or "").splitlines():
            if is_identity_conflict_memory(character, line):
                logger.warning("沉淀输入疑似身份污染，已过滤: %s", line)
                continue
            kept.append(line)
        return "\n".join(kept)
