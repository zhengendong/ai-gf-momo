"""
Momo Agent — 实时对话
一次 LLM 调用完成角色决策、自然回复和高层图片目标
"""

import json
import logging
from typing import Optional

from ..core.context import (
    assemble_momo_prompt,
    get_character_name,
    load_identity,
    load_soul,
    load_long_term,
)
from ..models.schemas import AgentOutput
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
        """
        构建 system prompt：
        agent.md (协议/规则/输出格式)
        + identity.md → ## 你的身份
        + soul.md     → ## 你的灵魂
        + long_term.md → ## 你的记忆
        """
        char = character or get_active()
        cache_key = f"system:{char}"
        if cache_key not in self._system_prompts:
            try:
                base = read_markdown(self._agent_path)
                base = base.replace("{name}", get_character_name(char))

                identity = load_identity(char)
                soul = load_soul(char)
                long_term = load_long_term(char)

                parts = [base.strip()]
                if identity:
                    parts.append(f"\n\n## 你的身份\n\n{identity.strip()}")
                if soul:
                    parts.append(f"\n\n## 你的灵魂\n\n{soul.strip()}")
                if long_term:
                    parts.append(f"\n\n## 你的记忆\n\n{long_term.strip()}")
                self._system_prompts[cache_key] = "\n".join(parts)
            except Exception as e:
                logger.error(f"加载 system prompt 失败: {e}")
                self._system_prompts[cache_key] = f"你是{char}，一个沉浸式AI伴侣。请用JSON格式回复。"
        return self._system_prompts[cache_key]

    @property
    def _agent_path(self):
        from ..config import settings
        return settings.agent_file

    def reload_system_prompt(self, character: str = None):
        """热重载 system prompt"""
        if character:
            self._system_prompts.pop(f"system:{character}", None)
        else:
            self._system_prompts.clear()

    async def process(
        self,
        user_message: str,
        character: str = None,
        chat_history: str = "",
        conversation_summary: str = "",
        recalled_memories: str = "",
        business_knowledge: str = "",
        interaction_mode: str = "chat",
        prepared_prompt: str | None = None,
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
        prompt = prepared_prompt or assemble_momo_prompt(
            character, user_message,
            chat_history=chat_history,
            conversation_summary=conversation_summary,
            recalled_memories=recalled_memories,
            business_knowledge=business_knowledge,
            interaction_mode=interaction_mode,
        )
        total_tokens = estimate_tokens(system_prompt + prompt)

        # 2. build_context_window already trims recent history before this point.
        # Do not run another LLM summarization in the live reply path.
        if needs_compression(total_tokens):
            logger.warning(f"上下文接近上限 ({total_tokens} tokens)，历史压缩由后台任务处理")
            if prepared_prompt is None:
                prompt = assemble_momo_prompt(
                    character, user_message,
                    chat_history="",
                    conversation_summary=conversation_summary,
                    recalled_memories=recalled_memories,
                    business_knowledge=business_knowledge,
                    interaction_mode=interaction_mode,
                )

        # 3. 调用 LLM
        try:
            raw = await self.llm.chat_prompt(system=system_prompt, user=prompt)
            output = self._parse_output(raw)
        except Exception as e:
            logger.error(f"Momo Agent 调用失败: {e}")
            raise

        return output

    async def repair_output(
        self,
        *,
        character: str,
        user_message: str,
        status: str,
        output: AgentOutput,
        issues: list[str],
    ) -> AgentOutput:
        """Repair only the character-facing JSON contract."""
        payload = {
            "current_user_message": user_message,
            "current_status": status,
            "invalid_output": output.model_dump(),
            "validation_issues": issues,
            "instruction": (
                "Return one corrected complete JSON outcome. Preserve the character's decision and voice, "
                "and return only reply, image_goal, memory_candidate and persist_context. Do not explain."
            ),
        }
        raw = await self.llm.chat_prompt(
            system=self.system_prompt(character),
            user=json.dumps(payload, ensure_ascii=False, indent=2),
            temperature=0.3,
        )
        return self._parse_output(raw)

    def _parse_output(self, raw: str) -> AgentOutput:
        """解析 LLM 输出的 JSON"""
        import re
        try:
            text = raw.strip()
            # 去掉 <think>...</think> 推理块（Minimax M3 等推理模型）
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
            # 去掉可能的 markdown 代码块标记
            if text.startswith("`"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
            # Some OpenAI-compatible endpoints prepend a short explanation even
            # when the model was instructed to return JSON only. Recover the
            # object without accepting arbitrary prose as a role reply.
            if not text.startswith("{"):
                start = text.find("{")
                end = text.rfind("}")
                if start >= 0 and end > start:
                    text = text[start:end + 1]
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError("Momo output must be a JSON object")
            reply = str(data.get("reply") or "").strip()
            if not reply:
                raise ValueError("Momo output requires a non-empty reply")
            image_goal = data.get("image_goal")
            if image_goal is not None and not isinstance(image_goal, dict):
                raise ValueError("image_goal must be an object or null")
            return AgentOutput(
                reply=reply,
                # State fields remain readable on AgentOutput for old API
                # callers, but the live MomoAgent no longer owns continuity.
                state_ops=[],
                image_goal=image_goal,
                effects=[],
                image_intent=None,
                memory_candidate=data.get("memory_candidate"),
                photo_prompt=None,
                state_updates=None,
                immediate_memory=data.get("immediate_memory"),
                persist_context=data.get("persist_context", True),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"解析 Agent 输出失败: {e}, raw={raw[:200]}")
            raise ValueError(f"invalid Momo output: {e}") from e
