"""
Momo Agent — 实时对话
一次 LLM 调用完成意图判断、对话生成、生图 prompt、状态更新
"""

import json
import logging
from typing import Optional

from ..models.schemas import AgentOutput
from ..core.context import assemble_momo_prompt, get_character_name
from ..core.compressor import estimate_tokens, needs_compression
from ..core.characters import get_active
from ..utils.helpers import read_markdown

logger = logging.getLogger(__name__)


class MomoAgent:
    """实时对话 Agent"""

    def __init__(self, llm_client):
        """
        Args:
            llm_client: LLM 客户端，需支持 chat(system, user) → str
        """
        self.llm = llm_client
        self._system_prompts: dict[str, str] = {}

    def system_prompt(self, character: str = None) -> str:
        """加载 agent.md 作为 system prompt"""
        char = character or get_active()
        if char not in self._system_prompts:
            try:
                content = read_markdown(self._agent_path)
                # 替换 {name} 占位符
                content = content.replace("{name}", get_character_name(char))
                self._system_prompts[char] = content
            except Exception as e:
                logger.error(f"加载 agent.md 失败: {e}")
                self._system_prompts[char] = f"你是{char}，一个沉浸式AI伴侣。请用JSON格式回复。"
        return self._system_prompts[char]

    @property
    def _agent_path(self):
        from ..config import settings
        return settings.agent_file

    def reload_system_prompt(self, character: str = None):
        """热重载 agent.md"""
        if character:
            self._system_prompts.pop(character, None)
        else:
            self._system_prompts.clear()

    async def process(
        self,
        user_message: str,
        character: str = None,
        chat_history: str = "",
        conversation_summary: str = "",
        recalled_memories: str = "",
    ) -> AgentOutput:
        """
        处理用户消息

        Args:
            user_message: 用户输入
            chat_history: 最近对话历史
            conversation_summary: 旧对话摘要
            recalled_memories: 向量库召回的相关历史片段

        Returns:
            AgentOutput
        """
        character = character or get_active()
        system_prompt = self.system_prompt(character)

        # 1. 检查上下文窗口
        prompt = assemble_momo_prompt(
            character, user_message,
            chat_history=chat_history,
            conversation_summary=conversation_summary,
            recalled_memories=recalled_memories,
        )
        total_tokens = estimate_tokens(system_prompt + prompt)

        # 2. build_context_window already trims recent history before this point.
        # Do not run another LLM summarization in the live reply path.
        if needs_compression(total_tokens):
            logger.warning(f"上下文接近上限 ({total_tokens} tokens)，本轮裁掉最近对话以避免同步压缩")
            prompt = assemble_momo_prompt(
                character, user_message,
                chat_history="",
                conversation_summary=conversation_summary,
                recalled_memories=recalled_memories,
            )

        # 3. 调用 LLM
        try:
            raw = await self.llm.chat_prompt(system=system_prompt, user=prompt)
            output = self._parse_output(raw)
        except Exception as e:
            logger.error(f"Momo Agent 调用失败: {e}")
            char_name = get_character_name(character)
            output = AgentOutput(reply=f"（{char_name}走神了…等一下哦～）\n错误: {e}")

        return output

    def _parse_output(self, raw: str) -> AgentOutput:
        """解析 LLM 输出的 JSON"""
        import re
        try:
            text = raw.strip()
            # 去掉 <think>...</think> 推理块（Minimax M3 等推理模型）
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
            # 去掉可能的 markdown 代码块标记
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
            data = json.loads(text)
            return AgentOutput(
                reply=data.get("reply", ""),
                photo_prompt=data.get("photo_prompt"),
                state_updates=data.get("state_updates"),
                immediate_memory=data.get("immediate_memory"),
                persist_context=data.get("persist_context", True),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"解析 Agent 输出失败: {e}, raw={raw[:200]}")
            return AgentOutput(reply=raw.strip())
