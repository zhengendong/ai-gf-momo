"""Agent runtime orchestration."""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Protocol

import httpx

from ..agents.image import ImagePipeline
from ..agents.memory import MemoryAgent
from ..agents.momo import MomoAgent
from ..config import settings
from ..core.chat_history import append_chat_pair, read_chat_history
from ..core.context import (
    append_daily_memory,
    assemble_momo_prompt,
    get_character_name,
    get_user_pet_name,
)
from ..core.memory_policy import (
    build_context_window,
    bump_turn_and_due_targets,
    index_chat_pair,
    mark_condense_failed,
    memory_settings,
    recall_vector_context,
    reset_condense_counter,
)
from ..core.business_knowledge import load_relevant_knowledge
from ..core.image_job import build_image_job
from ..core.orchestrator import bg_tasks
from ..core.output_monitor import (
    check_output_consistency,
)
from ..core.state import apply_state_updates, state_updates_from_effects
from ..core.time_system import write_last_chat
from ..models.schemas import StreamChunk
from ..services.prompt_builder import sanitize_dynamic_photo_prompt

logger = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 20
DEFAULT_PHOTO_PROMPT = "rating:general, looking_at_viewer, masterpiece, best quality, amazing quality"


def _sanitize_photo_prompt_without_blocking(prompt: str) -> str:
    cleaned = sanitize_dynamic_photo_prompt(prompt)
    if cleaned:
        return cleaned
    logger.warning("photo_prompt became empty after sanitizing; using default non-blocking prompt.")
    return DEFAULT_PHOTO_PROMPT


class ChunkSender(Protocol):
    async def send_chunk(
        self,
        session_id: str,
        chunk: StreamChunk,
        character: str | None = None,
    ):
        ...


class AgentRuntime:
    """Coordinate one websocket message through chat, state, memory and tools."""

    def __init__(self, llm_service, comfyui_service, sender: ChunkSender):
        self.sender = sender
        self.momo_agent = MomoAgent(llm_service)
        self.memory_agent = MemoryAgent(llm_service)
        self.image_pipeline = ImagePipeline(comfyui_service, sender)
        self.chat_history_buffer: dict[tuple[str, str], list[str]] = {}
        self._character_locks: dict[str, asyncio.Lock] = {}
        self._memory_locks: dict[str, asyncio.Lock] = {}

    def clear_session(self, session_id: str):
        for key in list(self.chat_history_buffer):
            if key[0] == session_id:
                self.chat_history_buffer.pop(key, None)

    def clear_character_cache(self, character: str):
        for key in list(self.chat_history_buffer):
            if key[1] == character:
                self.chat_history_buffer.pop(key, None)

    async def handle_message(self, session_id: str, character: str, content: str):
        """Serialize decisions and state commits for the same character."""
        lock = self._character_locks.setdefault(character, asyncio.Lock())
        async with lock:
            await self._handle_message(session_id, character, content)

    async def _handle_message(self, session_id: str, character: str, content: str):
        started_at = time.perf_counter()
        char = character
        char_name = get_character_name(char)
        user_label = get_user_pet_name(char) or "用户"
        buffer_key = (session_id, char)

        try:
            history = self.chat_history_buffer.get(buffer_key, [])
            recent_context = "\n".join(history[-6:])
            if not recent_context:
                persisted = read_chat_history(char)[-6:]
                recent_context = "\n".join(
                    str(item.get("content") or "") for item in persisted
                )
            business_knowledge = load_relevant_knowledge(
                content,
                recent_context,
            )
            base_prompt = assemble_momo_prompt(
                char,
                content,
                business_knowledge=business_knowledge,
            )
            context_started = time.perf_counter()
            summary, chat_history = await build_context_window(
                self.momo_agent.llm,
                char,
                char_name,
                user_label,
                base_prompt,
                self.momo_agent.system_prompt(char),
            )
            if not chat_history and history:
                chat_history = "\n".join(history[-MAX_HISTORY_TURNS:])
            recalled_memories = recall_vector_context(char, content)
            logger.info(
                "Runtime context ready: character=%s elapsed=%.3fs history_chars=%s",
                char,
                time.perf_counter() - context_started,
                len(chat_history or ""),
            )

            llm_started = time.perf_counter()
            output = await self.momo_agent.process(
                character=char,
                user_message=content,
                chat_history=chat_history,
                conversation_summary=summary,
                recalled_memories=recalled_memories,
                business_knowledge=business_knowledge,
            )
            logger.info(
                "Runtime main LLM done: character=%s elapsed=%.3fs",
                char,
                time.perf_counter() - llm_started,
            )
            if output.photo_prompt:
                output.photo_prompt = _sanitize_photo_prompt_without_blocking(output.photo_prompt)
            if output.effects and not output.state_updates:
                output.state_updates = state_updates_from_effects(char, output.effects)

            consistency_started = time.perf_counter()
            output = await self._ensure_consistent_output(char, output)
            logger.info(
                "Runtime consistency done: character=%s elapsed=%.3fs",
                char,
                time.perf_counter() - consistency_started,
            )

            if not output.persist_context:
                await self.sender.send_chunk(
                    session_id,
                    StreamChunk(type="text", content=output.reply),
                    character=char,
                )
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

            wrote_runtime_state = False
            if output.state_updates:
                await self._async_update_state(char, output.state_updates)
                wrote_runtime_state = True

            image_job = build_image_job(
                char,
                output.reply,
                image_intent=output.image_intent,
                legacy_prompt=output.photo_prompt,
            )

            if wrote_runtime_state:
                await self.push_current_state(session_id, char)

            await self.sender.send_chunk(
                session_id,
                StreamChunk(type="text", content=output.reply),
                character=char,
            )

            memory_candidate = output.memory_candidate or output.immediate_memory
            if memory_candidate:
                bg_tasks.schedule(
                    self._async_evaluate_memory_candidate(
                        char,
                        memory_candidate,
                        content,
                        output.reply,
                    )
                )

            bg_tasks.schedule(self._async_append_daily(
                char,
                content,
                output.reply,
                image_job.dynamic_prompt if image_job else None,
            ))
            bg_tasks.schedule(
                self._async_append_chat_history(char, content, output.reply)
            )
            if memory_settings().get("vector_recall_enabled", True):
                bg_tasks.schedule(
                    self._async_index_vector_memory(char, content, output.reply)
                )
            due_condense_targets = bump_turn_and_due_targets(char)
            if due_condense_targets:
                target = "all" if len(due_condense_targets) > 1 else due_condense_targets[0]
                bg_tasks.schedule(
                    self._async_condense_memory(char, trigger="turn_interval", target=target)
                )

            if image_job:
                bg_tasks.schedule(
                    self.image_pipeline.generate_job(session_id, image_job)
                )
            else:
                await self.sender.send_chunk(
                    session_id,
                    StreamChunk(type="image_status", content="done"),
                    character=char,
                )

            try:
                write_last_chat(char)
            except Exception as e:
                logger.debug("write_last_chat failed: %s", e)

            history.append(f"{user_label}：{content}")
            history.append(f"{char_name}：{output.reply}")
            self.chat_history_buffer[buffer_key] = history[-MAX_HISTORY_TURNS:]

            await self.sender.send_chunk(
                session_id,
                StreamChunk(type="done", done=True),
                character=char,
            )
            logger.info(
                "Runtime turn done: character=%s total=%.3fs",
                char,
                time.perf_counter() - started_at,
            )

        except Exception as e:
            content = self._format_user_facing_error(char_name, e)
            logger.error("Message handling failed for %s: %s", char, e, exc_info=True)
            await self.sender.send_chunk(
                session_id,
                StreamChunk(type="text", content=content),
                character=char,
            )

    async def refresh_memory(self, session_id: str, character: str, target: str = "all"):
        label = self._condense_target_label(target)
        await self.sender.send_chunk(
            session_id,
            StreamChunk(type="status_update", content=f"正在沉淀{label}..."),
            character=character,
        )
        result = await self._condense_memory(character, trigger="manual", target=target)
        if result:
            changed = []
            if result.get("soul"):
                changed.append("soul")
            if result.get("long_term"):
                changed.append("long_term")
            changed_label = "、".join(changed) if changed else label
            content = f"{label}沉淀完成：已更新 {changed_label}。"
        else:
            content = f"没有可沉淀的新{label}，或沉淀失败。"
        await self.sender.send_chunk(
            session_id,
            StreamChunk(type="status_update", content=content),
            character=character,
        )
        await self.sender.send_chunk(
            session_id,
            StreamChunk(type="text", content=content),
            character=character,
        )

    async def push_current_state(self, session_id: str, character: str):
        try:
            from ..core.state import read_status

            status_content = read_status(character)
            await self.sender.send_chunk(
                session_id,
                StreamChunk(
                    type="state_update",
                    content=json.dumps({
                        "character": character,
                        "status": self._parse_status_sections(status_content, character),
                    }, ensure_ascii=False),
                ),
                character=character,
            )
        except Exception as e:
            logger.error("Push state failed for %s: %s", character, e)

    def reload_system_prompt(self, character: str | None = None):
        self.momo_agent.reload_system_prompt(character)

    async def _ensure_consistent_output(
        self,
        character: str,
        output,
    ):
        result = await check_output_consistency(
            character,
            output,
        )
        if result.valid:
            return output

        logger.warning("Output consistency issue for %s: %s", character, result.issues)
        # A repair model adds latency and may invent a different decision. Keep
        # the conversational result, but never generate a picture from a turn
        # whose state relationship is inconsistent.
        output.state_updates = None
        output.effects = []
        output.photo_prompt = None
        output.image_intent = None
        return output

    def _format_user_facing_error(self, char_name: str, error: Exception) -> str:
        if isinstance(error, httpx.HTTPStatusError):
            body = error.response.text[:200]
            return f"（{char_name}走神了...等一下哦）\nLLM API {error.response.status_code}: {body}"
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

    async def _async_evaluate_memory_candidate(
        self,
        character: str,
        candidate: str,
        user_message: str,
        reply: str,
    ):
        try:
            lock = self._memory_locks.setdefault(character, asyncio.Lock())
            async with lock:
                result = await self.memory_agent.evaluate_candidate(
                    character,
                    candidate,
                    user_message,
                    reply,
                )
            logger.info("Memory candidate processed for %s: %s", character, result)
        except Exception as e:
            logger.error("Memory candidate processing failed for %s: %s", character, e)

    async def _async_append_daily(
        self,
        character: str,
        user_msg: str,
        reply: str,
        photo_prompt: str | None = None,
    ):
        try:
            now = datetime.now().strftime("%H:%M")
            user_label = get_user_pet_name(character)
            char_name = get_character_name(character)
            content = f"### {now} {user_label}说：\n{user_msg}\n\n### {char_name}说：\n{reply}"
            if photo_prompt:
                content += f"\n\n📷 {photo_prompt}"
            append_daily_memory(character, content)
        except Exception as e:
            logger.error("Append daily memory failed for %s: %s", character, e)

    async def _async_append_chat_history(self, character: str, user_msg: str, reply: str):
        try:
            append_chat_pair(character, user_msg, reply)
        except Exception as e:
            logger.error("Append chat_history failed for %s: %s", character, e)

    async def _async_index_vector_memory(self, character: str, user_msg: str, reply: str):
        try:
            index_chat_pair(character, user_msg, reply)
        except Exception as e:
            logger.error("Index vector memory failed for %s: %s", character, e)

    async def _async_condense_memory(self, character: str, trigger: str = "manual", target: str = "all"):
        await self._condense_memory(character, trigger=trigger, target=target)

    async def _condense_memory(self, character: str, trigger: str = "manual", target: str = "all"):
        try:
            days = int(memory_settings().get("condensation_days") or 1)
            lock = self._memory_locks.setdefault(character, asyncio.Lock())
            async with lock:
                result = await self.memory_agent.condense(character, days=days, target=target)
            if self._condense_result_has_update(result, target=target):
                reset_condense_counter(character, trigger=trigger, target=target)
            else:
                mark_condense_failed(character, trigger=trigger, error="empty_result", target=target)
            return result
        except Exception as e:
            mark_condense_failed(character, trigger=trigger, error=str(e), target=target)
            logger.error("Memory condensation failed for %s: %s", character, e)
            return {}

    def _condense_result_has_update(self, result: dict | None, target: str = "all") -> bool:
        if not isinstance(result, dict):
            return False
        if target in ("memory", "long-term", "longterm"):
            target = "long_term"
        if target == "long_term":
            return bool((result.get("long_term") or "").strip())
        if target == "soul":
            return bool((result.get("soul") or "").strip())
        return bool((result.get("soul") or "").strip() or (result.get("long_term") or "").strip())

    def _condense_target_label(self, target: str = "all") -> str:
        if target in ("long_term", "memory", "long-term", "longterm"):
            return "长期记忆"
        if target == "soul":
            return "灵魂"
        return "记忆"

    def _parse_status_sections(self, content: str, character: str | None = None) -> dict:
        sections = self._parse_markdown_sections(content)

        if character:
            from ..core.state import _allowed_sections as _state_allowed
            allowed = _state_allowed(character)
        else:
            allowed = {"穿着", "场景细节"}
        return {k: v for k, v in sections.items() if k in allowed}

    def _parse_markdown_sections(self, content: str) -> dict:
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
        return sections


