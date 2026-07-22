"""Agent runtime orchestration."""

import asyncio
import json
import logging
import time
from typing import Protocol

from ..agents.image import ImagePipeline
from ..agents.image_director import VisualContinuityAgent, VisualContinuityError
from ..agents.memory import MemoryAgent
from ..agents.momo import MomoAgent, MomoOutputError
from ..config import settings
from ..core.chat_history import append_chat_pair, append_initial_scene, append_scene_transition, read_chat_history
from ..core.characters import get_profile, normalize_initial_scene
from ..core.context import (
    append_daily_memory,
    assemble_momo_prompt,
    get_character_name,
    get_user_pet_name,
)
from ..core.memory_policy import (
    bump_turn_and_due_targets,
    commit_context_compression,
    ContextCompressionPlan,
    flush_pending_vector_writes,
    has_pending_vector_writes,
    mark_condense_failed,
    memory_settings,
    prepare_context_window,
    queue_vector_chat_pair,
    recall_vector_context,
    reset_condense_counter,
)
from ..core.image_job import build_image_job
from ..core.orchestrator import bg_tasks
from ..services.llm import LLMServiceError
from ..core.state import (
    apply_state_operations,
    apply_state_updates,
    capture_state_snapshot,
    commit_continuity_patch,
    is_state_initialized,
)
from ..models.schemas import StreamChunk

logger = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 20
VISUAL_HISTORY_MESSAGES = 16  # Eight prior user/assistant rounds.
VISUAL_HISTORY_MESSAGE_CHARS = 800

SCENE_TRANSITION_BASE = (
    "根据当前剧情、人物关系和已经发生的事件，自然推进到合理的下一幕。"
    "选择合适的时间、地点和情境，并根据新场景决定角色是否需要换装；"
    "需要换装时自然明确本幕实际穿着，合理时也可以保持原穿着。"
    "直接输出已经发生的下一幕，可以是纯情景叙述，也可以包含角色动作和台词，"
    "不要解释设计过程。"
)

INITIAL_SCENE_BASE = (
    "根据角色身份、性格、人物关系和初始场景构想，构建故事真正开始时的第一幕。"
    "必须自然且明确地建立虚拟故事的时间或时间段、具体地点与环境、角色当前实际穿着，"
    "以及角色正在进行的动作或所处状态。穿着必须清楚到能判断上身、下身、腿部和鞋子；"
    "没有对应衣物时也要自然表达实际裸露或赤足。直接输出已经发生的故事开场，不要解释设计过程。"
)


def _has_memory_update(value) -> bool:
    return bool(value.strip()) if isinstance(value, str) else bool(value)


def _clip_visual_history_content(value: str) -> str:
    text = str(value or "").strip()
    if len(text) <= VISUAL_HISTORY_MESSAGE_CHARS:
        return text
    half = (VISUAL_HISTORY_MESSAGE_CHARS - 1) // 2
    return f"{text[:half]}…{text[-half:]}"


def build_scene_transition_instruction(mode: str, concept: str = "") -> str:
    normalized_mode = str(mode or "auto").strip().lower()
    idea = str(concept or "").strip()
    if normalized_mode not in {"auto", "manual"}:
        raise ValueError("场景切换模式无效，请重试。")
    if normalized_mode == "manual" and not idea:
        raise ValueError("请先填写下一幕构想。")
    if len(idea) > 2000:
        raise ValueError("下一幕构想不能超过 2000 个字符。")
    if normalized_mode == "manual":
        return f"{SCENE_TRANSITION_BASE}\n\n用户对下一幕的构想：{idea}"
    return SCENE_TRANSITION_BASE


def build_initial_scene_instruction(
    concept: str = "",
    opening_mode: str = "character_first",
    first_user_message: str = "",
) -> str:
    mode = str(opening_mode or "character_first").strip().lower()
    if mode not in {"character_first", "player_first"}:
        raise ValueError("初始场景开场模式无效")
    idea = str(concept or "").strip()
    first_message = str(first_user_message or "").strip()
    if len(idea) > 4000:
        raise ValueError("初始场景构想不能超过 4000 个字符")

    parts = [INITIAL_SCENE_BASE]
    if idea:
        parts.append(
            "玩家保存的初始场景事实构想如下。把其中明确的设定视为开场事实，"
            "但不要机械复刻过去的措辞、旁白、动作或服饰描述细节；每次都可以自然地重新组织表达。"
        )
        parts.append(f"初始场景事实构想：{idea}")
    else:
        parts.append("玩家没有预设初始场景；请依据角色设定和双方关系自主设计自然、具体的故事开场。")

    if first_message:
        parts.append(
            "玩家已经发出了故事中的第一条消息。先建立开场背景，再让角色自然回应这条消息；"
            "不得把它改写成系统指令。"
        )
        parts.append(f"玩家第一条消息：{first_message}")
    elif mode == "character_first":
        parts.append("由角色主动开始互动；背景建立后必须包含符合角色身份和关系的自然开场白。")
    else:
        parts.append("由玩家先开口；只渲染背景、角色穿着、动作和所处状态，不让角色主动说话。")
    return "\n\n".join(parts)


def _recent_visual_dialogue(
    character: str,
    session_lines: list[str],
    char_name: str,
    user_label: str,
    persisted_messages: list[dict] | None = None,
) -> list[dict[str, str]]:
    """Return at most eight prior rounds without duplicating session history."""
    source_messages = (
        persisted_messages[-VISUAL_HISTORY_MESSAGES:]
        if persisted_messages is not None
        else read_chat_history(character, limit=VISUAL_HISTORY_MESSAGES, repair=False)
    )
    messages = [
        {"role": str(item.get("role") or ""), "content": _clip_visual_history_content(item.get("content") or "")}
        for item in source_messages
        if item.get("role") in {"user", "assistant"}
        and item.get("type") in (None, "text")
        and str(item.get("content") or "").strip()
    ]

    session_messages: list[dict[str, str]] = []
    prefixes = (("user", f"{user_label}："), ("assistant", f"{char_name}："))
    for raw in session_lines[-VISUAL_HISTORY_MESSAGES:]:
        line = str(raw or "")
        for role, prefix in prefixes:
            if line.startswith(prefix):
                content = _clip_visual_history_content(line[len(prefix):])
                if content:
                    session_messages.append({"role": role, "content": content})
                break

    max_overlap = min(len(messages), len(session_messages))
    overlap = 0
    for size in range(max_overlap, 0, -1):
        if messages[-size:] == session_messages[:size]:
            overlap = size
            break
    messages.extend(session_messages[overlap:])
    return messages[-VISUAL_HISTORY_MESSAGES:]


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
        self.visual_continuity_agent = VisualContinuityAgent(llm_service)
        # Compatibility attribute for extensions that still inspect runtime.
        self.image_director = self.visual_continuity_agent
        self.image_pipeline = ImagePipeline(comfyui_service, sender)
        self.chat_history_buffer: dict[tuple[str, str], list[str]] = {}
        self._character_locks: dict[str, asyncio.Lock] = {}
        self._memory_locks: dict[str, asyncio.Lock] = {}
        self._context_compression_pending: set[str] = set()
        self._vector_flush_pending: set[str] = set()

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
            if not is_state_initialized(character):
                initial_scene = normalize_initial_scene(get_profile(character).get("initial_scene"))
                instruction = build_initial_scene_instruction(
                    initial_scene["concept"],
                    opening_mode="player_first",
                    first_user_message=content,
                )
                await self._handle_message(
                    session_id,
                    character,
                    instruction,
                    interaction_mode="initial_scene_with_user",
                    interaction_summary=content,
                    persisted_user_message=content,
                )
            else:
                await self._handle_message(session_id, character, content)

    async def handle_initial_scene(self, session_id: str, character: str):
        """Build the saved opening template without changing it."""
        lock = self._character_locks.setdefault(character, asyncio.Lock())
        async with lock:
            if is_state_initialized(character):
                raise ValueError("当前故事已经开始；初始场景设置将在下次清空记录后生效。")
            initial_scene = normalize_initial_scene(get_profile(character).get("initial_scene"))
            instruction = build_initial_scene_instruction(
                initial_scene["concept"],
                opening_mode=initial_scene["opening_mode"],
            )
            await self._handle_message(
                session_id,
                character,
                instruction,
                interaction_mode=f"initial_scene_{initial_scene['opening_mode']}",
                interaction_summary="构建初始场景",
            )

    async def handle_scene_transition(
        self,
        session_id: str,
        character: str,
        mode: str = "auto",
        concept: str = "",
    ):
        """Advance the story through the normal Momo -> continuity transaction."""
        instruction = build_scene_transition_instruction(mode, concept)
        lock = self._character_locks.setdefault(character, asyncio.Lock())
        async with lock:
            await self._handle_message(
                session_id,
                character,
                instruction,
                interaction_mode="scene_transition",
                interaction_summary=(
                    f"下一幕构想：{str(concept).strip()}"
                    if str(mode).strip().lower() == "manual"
                    else "自动推进下一幕"
                ),
            )

    async def _handle_message(
        self,
        session_id: str,
        character: str,
        content: str,
        *,
        interaction_mode: str = "chat",
        interaction_summary: str = "",
        persisted_user_message: str = "",
    ):
        started_at = time.perf_counter()
        char = character
        char_name = get_character_name(char)
        user_label = get_user_pet_name(char) or "用户"
        buffer_key = (session_id, char)
        stage = "context"

        try:
            history = self.chat_history_buffer.get(buffer_key, [])
            persisted_history = read_chat_history(char, repair=False)
            recent_context = "\n".join(history[-6:])
            if not recent_context:
                persisted = persisted_history[-6:]
                recent_context = "\n".join(
                    str(item.get("content") or "") for item in persisted
                )
            # Context selection only needs a small seed; assemble the full
            # Momo prompt once, after the history window is known.
            base_prompt = content
            system_prompt = self.momo_agent.system_prompt(char)
            context_started = time.perf_counter()
            context_window = await prepare_context_window(
                self.momo_agent.llm,
                char,
                char_name,
                user_label,
                base_prompt,
                system_prompt,
                all_messages=persisted_history,
            )
            summary = context_window.summary
            chat_history = context_window.chat_history
            context_compression_plan = context_window.compression_plan
            if not chat_history and history:
                chat_history = "\n".join(history[-MAX_HISTORY_TURNS:])
            routing_content = persisted_user_message or content
            recalled_memories = recall_vector_context(char, routing_content)
            prepared_prompt = assemble_momo_prompt(
                char,
                content,
                chat_history=chat_history,
                conversation_summary=summary,
                recalled_memories=recalled_memories,
                interaction_mode=interaction_mode,
            )
            logger.info(
                "Runtime context ready: character=%s elapsed=%.3fs history_chars=%s",
                char,
                time.perf_counter() - context_started,
                len(chat_history or ""),
            )

            stage = "momo"
            llm_started = time.perf_counter()
            output = await self.momo_agent.process(
                character=char,
                user_message=content,
                chat_history=chat_history,
                conversation_summary=summary,
                recalled_memories=recalled_memories,
                interaction_mode=interaction_mode,
                prepared_prompt=prepared_prompt,
            )
            logger.info(
                "Runtime main LLM done: character=%s elapsed=%.3fs",
                char,
                time.perf_counter() - llm_started,
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

            previous_snapshot = capture_state_snapshot(char)
            recent_visual_dialogue = _recent_visual_dialogue(
                char,
                history,
                char_name,
                user_label,
                persisted_messages=persisted_history,
            )
            stage = "visual_continuity"
            continuity_started = time.perf_counter()
            continuity = None
            frozen_snapshot = previous_snapshot
            wrote_runtime_state = False
            try:
                continuity = await self.visual_continuity_agent.resolve(
                    character=char,
                    user_message=content,
                    reply=output.reply,
                    previous_state=previous_snapshot,
                    recent_dialogue=recent_visual_dialogue,
                    interaction_mode=interaction_mode,
                )
                is_initial_scene = interaction_mode.startswith("initial_scene")
                frozen_snapshot, wrote_runtime_state = await asyncio.to_thread(
                    commit_continuity_patch,
                    char,
                    continuity.state_patch,
                    initialize=is_initial_scene,
                )
            except (VisualContinuityError, TypeError, ValueError) as exc:
                logger.warning(
                    "Visual continuity failed for %s; preserving the previous state without another model call: %s",
                    char,
                    exc,
                )
                if interaction_mode.startswith("initial_scene"):
                    raise VisualContinuityError(
                        f"initial scene continuity could not be committed: {exc}"
                    ) from exc
            logger.info(
                "Runtime continuity done: character=%s elapsed=%.3fs changed=%s",
                char,
                time.perf_counter() - continuity_started,
                wrote_runtime_state,
            )

            stage = "image_job"
            if continuity is not None:
                shot_spec = self.visual_continuity_agent.harmonize_shot(
                    continuity.shot_spec,
                    frozen_snapshot,
                )
            else:
                shot_spec = None
            image_job = build_image_job(
                char,
                output.reply,
                image_intent=shot_spec,
                state_snapshot=frozen_snapshot,
            ) if shot_spec else None

            stage = "reply_delivery"
            if wrote_runtime_state:
                await self.push_current_state(session_id, char)

            if interaction_mode.startswith("initial_scene"):
                await self.sender.send_chunk(
                    session_id,
                    StreamChunk(type="scene_divider", content="故事开始"),
                    character=char,
                )
            elif interaction_mode == "scene_transition":
                await self.sender.send_chunk(
                    session_id,
                    StreamChunk(type="scene_divider", content="新场景"),
                    character=char,
                )

            await self.sender.send_chunk(
                session_id,
                StreamChunk(type="text", content=output.reply),
                character=char,
            )

            # Submit the image task before low-priority persistence and memory
            # work. The image task itself remains asynchronous and can run
            # while ComfyUI is generating.
            if image_job:
                bg_tasks.schedule(
                    self.image_pipeline.generate_job(session_id, image_job)
                )

            memory_candidate = (
                None
                if interaction_mode == "scene_transition" or interaction_mode.startswith("initial_scene")
                else output.memory_candidate or output.immediate_memory
            )
            if memory_candidate:
                bg_tasks.schedule(
                    self._async_evaluate_memory_candidate(
                        session_id,
                        char,
                        memory_candidate,
                        content,
                        output.reply,
                    )
                )

            persisted_user_text = interaction_summary or content
            bg_tasks.schedule(self._async_append_daily(
                char,
                persisted_user_text,
                output.reply,
                image_job.dynamic_prompt if image_job else None,
                interaction_mode=interaction_mode,
            ))
            if interaction_mode.startswith("initial_scene"):
                bg_tasks.schedule(self._async_append_initial_scene(
                    char,
                    output.reply,
                    persisted_user_message,
                ))
            elif interaction_mode == "scene_transition":
                bg_tasks.schedule(self._async_append_scene_transition(char, output.reply))
            else:
                bg_tasks.schedule(
                    self._async_append_chat_history(char, content, output.reply)
                )
            if memory_settings().get("vector_recall_enabled", True):
                self._schedule_vector_index(char, persisted_user_text, output.reply)
            bg_tasks.schedule(
                self._async_bump_and_schedule_condense(session_id, char)
            )
            self._schedule_context_compression(context_compression_plan)
            if not image_job:
                await self.sender.send_chunk(
                    session_id,
                    StreamChunk(type="image_status", content="done"),
                    character=char,
                )

            if interaction_mode == "chat":
                history.append(f"{user_label}：{content}")
            elif interaction_mode == "initial_scene_with_user" and persisted_user_message:
                history.append(f"{user_label}：{persisted_user_message}")
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
            logger.error(
                "Message handling failed for %s at stage=%s: %s",
                char,
                stage,
                e,
                exc_info=True,
            )
            stage_messages = {
                "context": "上下文准备失败，请重新发送。",
                "momo": self._momo_error_message(e),
                "visual_continuity": (
                    self._initial_scene_error_message(e)
                    if interaction_mode.startswith("initial_scene")
                    else "本轮内部处理异常，请重新发送。"
                ),
                "image_job": "图片任务准备失败，请重新发送。",
                "reply_delivery": "本轮回复发送失败，请重新发送。",
            }
            await self._send_turn_error(
                session_id,
                char,
                stage_messages.get(stage, "本轮处理失败，请重新发送。"),
            )

    @staticmethod
    def _momo_error_message(error: Exception) -> str:
        """Return a precise, safe user-facing reason for a Momo-stage failure."""
        code = getattr(error, "code", "")
        messages = {
            "content_blocked": "本轮内容被当前模型的安全策略拒绝，请调整内容或切换模型后重试。",
            "rate_limited": "模型服务当前限流，请稍后再试。",
            "request_timed_out": "模型服务响应超时，请稍后重试。",
            "connection_failed": "无法连接模型服务，请检查网络或模型接口配置。",
            "authentication_failed": "模型接口鉴权失败，请检查模型配置和密钥。",
            "provider_unavailable": "模型服务暂时不可用，请稍后重试。",
            "context_rejected": "本轮上下文被模型拒绝，建议缩短上下文窗口后重试。",
            "request_rejected": "模型接口拒绝了本次请求，请检查模型配置后重试。",
            "provider_response_invalid": "模型服务返回了异常响应，请稍后重试。",
            "output_format_invalid": "模型回复格式异常，请重新发送。",
        }
        if isinstance(error, (LLMServiceError, MomoOutputError)):
            return messages.get(code, "模型服务发生未知异常，请重新发送。")
        return "角色回复生成失败，请重新发送。"

    @staticmethod
    def _initial_scene_error_message(error: Exception) -> str:
        """Explain an initialization failure without exposing model output."""
        detail = str(error or "").lower()
        if any(token in detail for token in ("expecting value", "json", "output must be")):
            return "初始场景的视觉导演回复格式异常，已保持未开场状态；请重试。"
        if any(token in detail for token in ("完整服饰槽位", "明确角色实际穿着", "明确时间和地点")):
            return "初始场景缺少完整穿着或时间地点，已保持未开场状态；请重试。"
        return "初始场景视觉状态校验失败，已保持未开场状态；请重试。"

    async def refresh_memory(self, session_id: str, character: str, target: str = "all"):
        label = self._condense_target_label(target)
        await self.sender.send_chunk(
            session_id,
            StreamChunk(type="status_update", content=f"正在沉淀{label}..."),
            character=character,
        )
        result = await self._condense_memory(character, trigger="manual", target=target)
        await self._notify_memory_updated(session_id, character, result)
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
                        "initialized": is_state_initialized(character),
                        "status": self._parse_status_sections(status_content, character),
                    }, ensure_ascii=False),
                ),
                character=character,
            )
        except Exception as e:
            logger.error("Push state failed for %s: %s", character, e)

    def reload_system_prompt(self, character: str | None = None):
        self.momo_agent.reload_system_prompt(character)

    async def _send_turn_error(self, session_id: str, character: str, message: str):
        """Report a system failure without impersonating the role or persisting chat."""
        await self.sender.send_chunk(
            session_id,
            StreamChunk(type="status_update", content=message),
            character=character,
        )
        await self.sender.send_chunk(
            session_id,
            StreamChunk(type="image_status", content="error"),
            character=character,
        )
        await self.sender.send_chunk(
            session_id,
            StreamChunk(type="done", done=True),
            character=character,
        )

    async def _async_apply_state_operations(self, character: str, operations: list[dict]):
        await asyncio.to_thread(apply_state_operations, character, operations)

    async def _async_bump_and_schedule_condense(self, session_id: str, character: str):
        try:
            due_condense_targets = await asyncio.to_thread(
                bump_turn_and_due_targets,
                character,
            )
            if due_condense_targets:
                target = "all" if len(due_condense_targets) > 1 else due_condense_targets[0]
                bg_tasks.schedule(
                    self._async_condense_memory(
                        session_id,
                        character,
                        trigger="turn_interval",
                        target=target,
                    )
                )
        except Exception as e:
            logger.error("Turn counter update failed for %s: %s", character, e)

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
        session_id: str,
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
            if result.get("written"):
                await self._notify_memory_updated(session_id, character, {"long_term": True})
        except Exception as e:
            logger.error("Memory candidate processing failed for %s: %s", character, e)

    async def _async_append_daily(
        self,
        character: str,
        user_msg: str,
        reply: str,
        photo_prompt: str | None = None,
        interaction_mode: str = "chat",
    ):
        try:
            user_label = get_user_pet_name(character)
            char_name = get_character_name(character)
            if interaction_mode.startswith("initial_scene"):
                content = f"### 故事开始：\n{user_msg}\n\n### 开场：\n{reply}"
            elif interaction_mode == "scene_transition":
                content = f"### 场景切换：\n{user_msg}\n\n### 新场景：\n{reply}"
            else:
                content = f"### {user_label}说：\n{user_msg}\n\n### {char_name}说：\n{reply}"
            if photo_prompt:
                content += f"\n\n📷 {photo_prompt}"
            await asyncio.to_thread(append_daily_memory, character, content)
        except Exception as e:
            logger.error("Append daily memory failed for %s: %s", character, e)

    async def _async_append_chat_history(self, character: str, user_msg: str, reply: str):
        try:
            await asyncio.to_thread(append_chat_pair, character, user_msg, reply)
        except Exception as e:
            logger.error("Append chat_history failed for %s: %s", character, e)

    async def _async_append_scene_transition(self, character: str, reply: str):
        try:
            await asyncio.to_thread(append_scene_transition, character, reply)
        except Exception as e:
            logger.error("Append scene transition failed for %s: %s", character, e)

    async def _async_append_initial_scene(
        self,
        character: str,
        reply: str,
        user_message: str = "",
    ):
        try:
            await asyncio.to_thread(append_initial_scene, character, reply, user_message)
        except Exception as e:
            logger.error("Append initial scene failed for %s: %s", character, e)

    def _schedule_vector_index(self, character: str, user_msg: str, reply: str):
        if not queue_vector_chat_pair(character, user_msg, reply):
            return
        if character in self._vector_flush_pending:
            return
        self._vector_flush_pending.add(character)
        bg_tasks.schedule(self._async_flush_vector_memory(character))

    async def _async_flush_vector_memory(self, character: str):
        flush_failed = False
        try:
            while True:
                written = await asyncio.to_thread(flush_pending_vector_writes, character)
                if written < 0:
                    flush_failed = True
                    break
                if written == 0:
                    break
        except Exception as e:
            flush_failed = True
            logger.error("Vector memory flush failed for %s: %s", character, e)
        finally:
            self._vector_flush_pending.discard(character)
            if not flush_failed and has_pending_vector_writes(character):
                self._vector_flush_pending.add(character)
                bg_tasks.schedule(self._async_flush_vector_memory(character))

    def _schedule_context_compression(self, plan: ContextCompressionPlan | None):
        """Queue at most one rolling-summary job per character."""
        if plan is None or plan.character in self._context_compression_pending:
            return
        self._context_compression_pending.add(plan.character)
        bg_tasks.schedule(self._async_compress_context(plan))

    async def _async_compress_context(self, plan: ContextCompressionPlan):
        try:
            lock = self._memory_locks.setdefault(plan.character, asyncio.Lock())
            async with lock:
                summary = await self.memory_agent.compress_history(
                    plan.old_summary,
                    plan.turns_to_compress,
                )
            committed = await asyncio.to_thread(
                commit_context_compression,
                plan,
                summary,
            )
            if committed:
                logger.info(
                    "Context summary advanced for %s by %s messages",
                    plan.character,
                    plan.message_count,
                )
            else:
                logger.warning("Context summary was not advanced for %s", plan.character)
        except Exception as exc:
            logger.error("Context compression failed for %s: %s", plan.character, exc)
        finally:
            self._context_compression_pending.discard(plan.character)

    async def _async_condense_memory(
        self,
        session_id: str,
        character: str,
        trigger: str = "manual",
        target: str = "all",
    ):
        result = await self._condense_memory(character, trigger=trigger, target=target)
        await self._notify_memory_updated(session_id, character, result)

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

    async def _notify_memory_updated(
        self,
        session_id: str,
        character: str,
        result: dict | None,
    ):
        """Tell the client to refresh memory documents without showing a chat/status message."""
        if not isinstance(result, dict):
            return
        targets = [
            name for name in ("long_term", "soul")
            if _has_memory_update(result.get(name))
        ]
        if not targets:
            return
        # soul.md and long_term.md are embedded in MomoAgent's cached system
        # prompt. Invalidate it as soon as MemoryAgent changes either file.
        self.momo_agent.reload_system_prompt(character)
        await self.sender.send_chunk(
            session_id,
            StreamChunk(type="memory_updated", content=",".join(targets)),
            character=character,
        )

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


