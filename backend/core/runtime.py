"""Agent runtime orchestration."""

import asyncio
import json
import logging
from typing import Protocol

import httpx

from ..agents.image import ImagePipeline
from ..agents.memory import MemoryAgent
from ..agents.momo import MomoAgent
from ..config import settings
from ..core.chat_history import append_chat_pair, format_recent_chat_for_prompt
from ..core.context import (
    get_character_name,
    get_user_pet_name,
    load_conversation_summary,
)
from ..core.orchestrator import bg_tasks
from ..core.plan_manager import (
    PLAN_FIELDS,
    add_plan as _add_plan,
    close_plan as _close_plan,
    update_plan as _update_plan,
)
from ..core.state import apply_state_updates
from ..core.time_system import write_last_chat
from ..models.schemas import StreamChunk
from ..services.llm import LLMContentRejectedError, content_rejection_reason

logger = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 20


class ChunkSender(Protocol):
    async def send_chunk(
        self,
        session_id: str,
        chunk: StreamChunk,
        character: str | None = None,
    ):
        ...


class AgentRuntime:
    """Coordinates one websocket message through chat, state, memory and image flows."""

    def __init__(self, llm_service, comfyui_service, sender: ChunkSender):
        self.sender = sender
        self.momo_agent = MomoAgent(llm_service)
        self.memory_agent = MemoryAgent(llm_service)
        self.image_pipeline = ImagePipeline(comfyui_service, sender)
        self.chat_history_buffer: dict[tuple[str, str], list[str]] = {}

    def clear_session(self, session_id: str):
        for key in list(self.chat_history_buffer):
            if key[0] == session_id:
                self.chat_history_buffer.pop(key, None)

    def clear_character_cache(self, character: str):
        for key in list(self.chat_history_buffer):
            if key[1] == character:
                self.chat_history_buffer.pop(key, None)

    async def handle_message(self, session_id: str, character: str, content: str):
        char = character
        char_name = get_character_name(char)
        user_pet = get_user_pet_name(char)
        user_label = user_pet or "用户"
        buffer_key = (session_id, char)

        try:
            history = self.chat_history_buffer.get(buffer_key, [])
            if history:
                chat_history = "\n".join(history[-MAX_HISTORY_TURNS:])
            else:
                chat_history = format_recent_chat_for_prompt(
                    char,
                    char_name,
                    user_label,
                    max_messages=MAX_HISTORY_TURNS * 2,
                )
            summary = load_conversation_summary(char)

            output = await self.momo_agent.process(
                character=char,
                user_message=content,
                chat_history=chat_history,
                conversation_summary=summary,
            )

            await self.sender.send_chunk(
                session_id,
                StreamChunk(type="text", content=output.reply),
                character=char,
            )

            if not output.persist_context:
                await self.sender.send_chunk(
                    session_id,
                    StreamChunk(type="image_status", content="done"),
                    character=char,
                )
                await self.sender.send_chunk(
                    session_id,
                    StreamChunk(type="done", done=True),
                    character=char,
                )
                return

            tasks = []

            if output.state_updates:
                tasks.append(asyncio.create_task(
                    self._async_update_state(char, output.state_updates, session_id)
                ))

            if output.photo_prompt:
                tasks.append(asyncio.create_task(
                    self.image_pipeline.generate(session_id, output.photo_prompt, char)
                ))
            else:
                await self.sender.send_chunk(
                    session_id,
                    StreamChunk(type="image_status", content="done"),
                    character=char,
                )

            if output.immediate_memory:
                tasks.append(asyncio.create_task(
                    self._async_append_long_term(char, output.immediate_memory)
                ))

            if output.plan_updates:
                tasks.append(asyncio.create_task(
                    self._async_apply_plan_updates(char, output.plan_updates)
                ))

            tasks.append(asyncio.create_task(
                self._async_append_chat_history(char, content, output.reply)
            ))

            try:
                write_last_chat(char)
            except Exception as e:
                logger.debug("write_last_chat failed: %s", e)

            history.append(f"{user_label}: {content}")
            history.append(f"{char_name}: {output.reply}")
            self.chat_history_buffer[buffer_key] = history[-MAX_HISTORY_TURNS:]

            await self.sender.send_chunk(
                session_id,
                StreamChunk(type="done", done=True),
                character=char,
            )

        except Exception as e:
            content = self._format_user_facing_error(char_name, e)
            logger.error("Message handling failed for %s: %s", char, e, exc_info=True)
            await self.sender.send_chunk(
                session_id,
                StreamChunk(
                    type="text",
                    content=content,
                ),
                character=char,
            )

    async def refresh_memory(self, session_id: str, character: str):
        bg_tasks.schedule(self.memory_agent.condense(character))
        await self.sender.send_chunk(
            session_id,
            StreamChunk(type="text", content="记忆刷新已触发～"),
            character=character,
        )

    async def push_current_state(self, session_id: str, character: str):
        try:
            from ..core.state import read_plans, read_status

            status_content = read_status(character)
            plans_content = read_plans(character)
            await self.sender.send_chunk(
                session_id,
                StreamChunk(
                    type="state_update",
                    content=json.dumps({
                        "character": character,
                        "status": self._parse_status_sections(status_content, character),
                        "plans": self._parse_status_sections(plans_content, character),
                    }, ensure_ascii=False),
                ),
                character=character,
            )
        except Exception as e:
            logger.error("Push state failed for %s: %s", character, e)

    def reload_system_prompt(self, character: str | None = None):
        self.momo_agent.reload_system_prompt(character)

    def _format_user_facing_error(self, char_name: str, error: Exception) -> str:
        if isinstance(error, LLMContentRejectedError):
            return str(error)
        if isinstance(error, httpx.HTTPStatusError):
            reason = content_rejection_reason(error.response.status_code, error.response.text)
            if reason:
                return reason
        return f"（{char_name}走神了...等一下哦）\n错误: {error}"

    async def _async_update_state(
        self,
        character: str,
        state_updates: dict,
        session_id: str | None = None,
    ):
        try:
            apply_state_updates(character, state_updates)
            if session_id:
                await self.push_current_state(session_id, character)
        except Exception as e:
            logger.error("State update failed for %s: %s", character, e)

    async def _async_apply_plan_updates(self, character: str, plan_updates: dict):
        try:
            for p in plan_updates.get("add", []) or []:
                _add_plan(
                    character,
                    name=p.get("name", "").strip(),
                    plan_type=p.get("type", "short"),
                    target=p.get("target", ""),
                    complete_when=p.get("complete_when", ""),
                )
            for p in plan_updates.get("update", []) or []:
                name = p.get("name", "").strip()
                if not name:
                    continue
                kwargs = {
                    k: v
                    for k, v in p.items()
                    if k in PLAN_FIELDS and k != "name"
                }
                _update_plan(character, name, **kwargs)
            for p in plan_updates.get("close", []) or []:
                name = p.get("name", "").strip()
                reason = p.get("reason", "completed")
                if name:
                    _close_plan(character, name, reason)
            logger.info("Plan updates applied: %s", character)
        except Exception as e:
            logger.error("Plan updates failed for %s: %s", character, e)

    async def _async_append_long_term(self, character: str, memory: str):
        try:
            path = settings.get_memory_dir(character) / "long_term.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            from ..core.memory_v3 import append_unique_section_lines, ensure_long_term_sections
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            existing = ensure_long_term_sections(existing, character)
            updated = append_unique_section_lines(existing, "重要事件", [memory])
            path.write_text(updated, encoding="utf-8")
        except Exception as e:
            logger.error("Append long_term failed for %s: %s", character, e)

    async def _async_append_chat_history(self, character: str, user_msg: str, reply: str):
        try:
            append_chat_pair(character, user_msg, reply)
        except Exception as e:
            logger.error("Append chat_history failed for %s: %s", character, e)

    def _parse_status_sections(self, content: str, character: str | None = None) -> dict:
        sections = {}
        current_title = None
        current_lines = []
        for line in content.split("\n"):
            if line.startswith("## "):
                if current_title:
                    sections[current_title] = "\n".join(current_lines).strip()
                current_title = line[3:].strip()
                current_lines = []
            elif line.startswith("# "):
                continue
            elif current_title:
                current_lines.append(line)
        if current_title:
            sections[current_title] = "\n".join(current_lines).strip()

        if character:
            from ..core.state import _allowed_sections as _state_allowed
            allowed = _state_allowed(character)
        else:
            allowed = {"穿着", "场景细节"}
        return {k: v for k, v in sections.items() if k in allowed}
