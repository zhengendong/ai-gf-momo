"""
WebSocket 路由
接收消息 → Momo Agent → 异步推送结果
"""

import json
import logging
import asyncio
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..models.schemas import StreamChunk
from ..agents.momo import MomoAgent
from ..services.llm import llm_service
from ..services.comfyui import comfyui_service
from ..config import settings
from ..core.state import apply_state_updates
from ..core.context import (
    append_daily_memory,
    assemble_momo_prompt,
    get_character_name,
    get_user_pet_name,
)
from ..core.characters import get_active
from ..core.chat_history import append_chat_pair
from ..core.memory_policy import (
    build_context_window,
    bump_turn_and_should_condense,
    index_chat_pair,
    memory_settings,
    recall_vector_context,
    reset_condense_counter,
)
from ..core.plan_manager import (
    PLAN_FIELDS,
    add_plan as _add_plan,
    close_plan as _close_plan,
    update_plan as _update_plan,
)
from ..tools.image_tool import ImageTool
from .image import _add_history

logger = logging.getLogger(__name__)
router = APIRouter()

# Momo Agent 单例
momo_agent = MomoAgent(llm_service)
image_tool = ImageTool(comfyui_service)

# 对话历史缓冲区: {(session_id, character): [turn1, turn2, ...]}
chat_history_buffer: dict[tuple[str, str], list[str]] = {}
MAX_HISTORY_TURNS = 20  # 保留最近 N 轮原始对话


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_connections[session_id] = websocket
        logger.info(f"WebSocket 连接: session_id={session_id}")

    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]
            logger.info(f"WebSocket 断开: session_id={session_id}")

    async def send_chunk(self, session_id: str, chunk: StreamChunk, character: str = None):
        ws = self.active_connections.get(session_id)
        if ws:
            try:
                if character and not chunk.character:
                    chunk.character = character
                await ws.send_text(chunk.model_dump_json())
            except Exception as e:
                logger.error(f"发送失败: {e}")
                self.disconnect(session_id)


manager = ConnectionManager()


async def handle_message(session_id: str, character: str, content: str):
    """处理一条用户消息"""
    char_name = get_character_name(character)
    user_label = get_user_pet_name(character)
    try:
        # 1. 获取对话历史
        buffer_key = (session_id, character)
        history = chat_history_buffer.get(buffer_key, [])
        base_prompt = assemble_momo_prompt(character, content)
        summary, chat_history = await build_context_window(
            momo_agent.llm,
            character,
            char_name,
            user_label,
            base_prompt,
            momo_agent.system_prompt(character),
        )
        if not chat_history and history:
            chat_history = "\n".join(history[-MAX_HISTORY_TURNS:])
        recalled_memories = recall_vector_context(character, content)

        # 2. 调 Momo Agent
        output = await momo_agent.process(
            user_message=content,
            character=character,
            chat_history=chat_history,
            conversation_summary=summary,
            recalled_memories=recalled_memories,
        )

        # 3. 推送文字回复（立即）
        await manager.send_chunk(
            session_id,
            StreamChunk(type="text", content=output.reply),
            character=character,
        )

        # 4. 异步任务（不阻塞）
        tasks = []

        # 状态更新
        if output.state_updates:
            tasks.append(asyncio.create_task(
                _async_update_state(character, output.state_updates, session_id)
            ))

        # 生图
        if output.photo_prompt:
            tasks.append(asyncio.create_task(
                _async_generate_image(session_id, character, output.photo_prompt)
            ))
        else:
            await manager.send_chunk(
                session_id,
                StreamChunk(type="image_status", content="done"),
                character=character,
            )

        # 追加 long_term
        if output.immediate_memory:
            tasks.append(asyncio.create_task(
                _async_append_long_term(character, output.immediate_memory)
            ))

        if output.plan_updates:
            tasks.append(asyncio.create_task(
                _async_apply_plan_updates(character, output.plan_updates)
            ))

        # 追加 daily memory
        tasks.append(asyncio.create_task(
            _async_append_daily(character, content, output.reply, output.photo_prompt)
        ))
        tasks.append(asyncio.create_task(
            _async_append_chat_history(character, content, output.reply)
        ))
        tasks.append(asyncio.create_task(
            _async_index_vector_memory(character, content, output.reply)
        ))
        if bump_turn_and_should_condense(character):
            tasks.append(asyncio.create_task(
                _async_condense_memory(character, trigger="turn_interval")
            ))

        # 5. 更新对话历史
        history.append(f"{user_label}：{content}")
        history.append(f"{char_name}：{output.reply}")
        chat_history_buffer[buffer_key] = history[-MAX_HISTORY_TURNS:]

        # 6. 发送完成
        await manager.send_chunk(
            session_id,
            StreamChunk(type="done", done=True),
            character=character,
        )

        # 等待异步任务（可选的，如果需要确认）
        # await asyncio.gather(*tasks, return_exceptions=True)

    except Exception as e:
        logger.error(f"处理消息失败: {e}", exc_info=True)
        await manager.send_chunk(
            session_id,
            StreamChunk(type="text", content=f"（{char_name}走神了...等一下哦～）\n错误: {e}"),
            character=character,
        )


def _allowed_sections(character: str) -> set[str]:
    char_name = get_character_name(character)
    return {"穿着", "场景细节", f"{char_name}的心情状态", f"{character}的心情状态", "心情状态"}


def _parse_status_sections(content: str, character: str) -> dict:
    """解析 status.md 内容，只保留白名单内的 section"""
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
            continue  # 跳过主标题
        elif current_title:
            current_lines.append(line)
    if current_title:
        sections[current_title] = "\n".join(current_lines).strip()

    return {k: v for k, v in sections.items() if k in _allowed_sections(character)}


async def _push_current_state(session_id: str, character: str):
    """推送当前角色状态给指定客户端"""
    try:
        from ..core.state import read_status, read_plans
        status_content = read_status(character)
        plans_content = read_plans(character)
        await manager.send_chunk(
            session_id,
            StreamChunk(
                type="state_update",
                content=json.dumps({
                    "character": character,
                    "status": _parse_status_sections(status_content, character),
                    "plans": _parse_status_sections(plans_content, character),
                }, ensure_ascii=False)
            ),
            character=character,
        )
    except Exception as e:
        logger.error(f"推送状态失败: {e}")


async def _async_update_state(character: str, state_updates: dict, session_id: str = None):
    """异步写入状态文件，并通过 WebSocket 推送给客户端"""
    try:
        apply_state_updates(character, state_updates)
        # 读取更新后的状态，推送给前端
        if session_id:
            await _push_current_state(session_id, character)
    except Exception as e:
        logger.error(f"状态更新失败: {e}")


async def _async_apply_plan_updates(character: str, plan_updates: dict):
    """Apply plan changes emitted by the agent."""
    try:
        for p in plan_updates.get("add", []) or []:
            _add_plan(
                character,
                name=(p.get("name") or "").strip(),
                plan_type=p.get("type", "short"),
                target=p.get("target", ""),
                complete_when=p.get("complete_when", ""),
            )
        for p in plan_updates.get("update", []) or []:
            name = (p.get("name") or "").strip()
            if not name:
                continue
            kwargs = {
                k: v
                for k, v in p.items()
                if k in PLAN_FIELDS and k != "name"
            }
            _update_plan(character, name, **kwargs)
        for p in plan_updates.get("close", []) or []:
            name = (p.get("name") or "").strip()
            if name:
                _close_plan(character, name, p.get("reason", "completed"))
        logger.info("计划更新已应用: %s", character)
    except Exception as e:
        logger.error("计划更新失败 %s: %s", character, e)


async def _async_generate_image(session_id: str, character: str, photo_prompt: str):
    """异步生成图片，分阶段推送状态更新"""
    try:
        # 通知生成中
        await manager.send_chunk(
            session_id,
            StreamChunk(type="image_status", content="generating"),
            character=character,
        )

        # 阶段 1：准备
        await manager.send_chunk(
            session_id,
            StreamChunk(type="status_update", content="正在准备生成..."),
            character=character,
        )
        workflow, prompt_used = image_tool.build_workflow(character=character, prompt=photo_prompt)

        # 阶段 2：提交
        await manager.send_chunk(
            session_id,
            StreamChunk(type="status_update", content="正在提交任务..."),
            character=character,
        )
        prompt_id = await comfyui_service.queue_prompt(workflow)

        # 阶段 3：等待生成
        await manager.send_chunk(
            session_id,
            StreamChunk(type="status_update", content="正在生成图片..."),
            character=character,
        )
        history = await comfyui_service.wait_for_completion(prompt_id)

        if not history:
            await manager.send_chunk(
                session_id,
                StreamChunk(type="image_status", content="error"),
                character=character,
            )
            await manager.send_chunk(
                session_id,
                StreamChunk(type="status_update", content="生成超时"),
                character=character,
            )
            return

        # 阶段 4：获取并保存图片
        await manager.send_chunk(
            session_id,
            StreamChunk(type="status_update", content="正在保存图片..."),
            character=character,
        )

        # 提取图片信息
        outputs = history.get("outputs", {})
        image_path = None
        for node_id, node_output in outputs.items():
            images = node_output.get("images", [])
            if images:
                image_info = images[0]
                filename = image_info["filename"]
                subfolder = image_info.get("subfolder", "")

                image_data = await comfyui_service.get_image(filename, subfolder)
                save_dir = settings.get_images_dir(character)
                save_dir.mkdir(parents=True, exist_ok=True)
                save_path = save_dir / filename
                save_path.write_bytes(image_data)
                image_path = str(save_path)
                break

        if image_path:
            fn = Path(image_path).name
            url = f"/static/{character}/images/{fn}"
            await manager.send_chunk(
                session_id,
                StreamChunk(type="image", url=url, content=url),
                character=character,
            )
            try:
                from ..core.chat_history import append_chat_message
                append_chat_message(character, {
                    "role": "assistant",
                    "type": "image",
                    "imageUrl": url,
                    "content": "",
                    "completed": True,
                })
            except Exception as e:
                logger.warning(f"写入图片聊天记录失败: {e}")
            _add_history(prompt_used, url, image_path, character=character)
            await manager.send_chunk(
                session_id,
                StreamChunk(type="status_update", content="照片已生成 ✓"),
                character=character,
            )
        else:
            await manager.send_chunk(
                session_id,
                StreamChunk(type="image_status", content="error"),
                character=character,
            )
            await manager.send_chunk(
                session_id,
                StreamChunk(type="status_update", content="未找到生成图片"),
                character=character,
            )
    except Exception as e:
        logger.error(f"图片生成失败: {e}")
        await manager.send_chunk(
            session_id,
            StreamChunk(type="image_status", content="error"),
            character=character,
        )
        await manager.send_chunk(
            session_id,
            StreamChunk(type="status_update", content=f"生成失败: {e}"),
            character=character,
        )


async def _async_append_long_term(character: str, memory: str):
    """异步追加长期记忆"""
    try:
        from ..config import settings
        from ..core.memory_v3 import (
            append_unique_section_lines,
            ensure_long_term_sections,
            is_identity_conflict_memory,
        )
        if is_identity_conflict_memory(character, memory):
            logger.warning("即时记忆疑似身份污染，已丢弃: %s", memory)
            return
        path = settings.get_memory_dir(character) / "long_term.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        existing = ensure_long_term_sections(existing, character)
        updated = append_unique_section_lines(existing, "重要事件", [memory])
        path.write_text(updated, encoding="utf-8")
    except Exception as e:
        logger.error(f"追加 long_term 失败: {e}")


async def _async_append_daily(character: str, user_msg: str, reply: str, photo_prompt: str = None):
    """异步追加每日日记"""
    try:
        now = datetime.now().strftime("%H:%M")
        user_label = get_user_pet_name(character)
        char_name = get_character_name(character)
        content = f"### {now} {user_label}说：\n{user_msg}\n\n### {char_name}说：\n{reply}"
        if photo_prompt:
            content += f"\n\n📷 {photo_prompt}"
        append_daily_memory(character, content)
    except Exception as e:
        logger.error(f"追加 daily memory 失败: {e}")


async def _async_append_chat_history(character: str, user_msg: str, reply: str):
    """异步追加结构化聊天记录。"""
    try:
        append_chat_pair(character, user_msg, reply)
    except Exception as e:
        logger.error(f"追加 chat_history 失败: {e}")


async def _async_index_vector_memory(character: str, user_msg: str, reply: str):
    """Index completed dialogue into the per-character vector store."""
    try:
        index_chat_pair(character, user_msg, reply)
    except Exception as e:
        logger.error("写入向量记忆失败 %s: %s", character, e)


async def _async_condense_memory(character: str, trigger: str = "manual"):
    """Condense soul/long_term and keep the turn counter coherent."""
    try:
        from ..agents.memory import MemoryAgent
        mem_agent = MemoryAgent(llm_service)
        days = int(memory_settings().get("condensation_days") or 1)
        await mem_agent.condense(character, days=days)
        reset_condense_counter(character, trigger=trigger)
    except Exception as e:
        logger.error("记忆沉淀失败 %s: %s", character, e)


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await manager.connect(websocket, session_id)

    # 连接后立即推送当前角色状态
    await _push_current_state(session_id, get_active())

    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)

            msg_type = message_data.get("type", "text")

            if msg_type == "text":
                content = message_data.get("content", "")
                character = message_data.get("character_id") or message_data.get("character") or get_active()
                if content:
                    await handle_message(session_id, character, content)

            elif msg_type == "ping":
                await manager.send_chunk(
                    session_id,
                    StreamChunk(type="pong", content="")
                )

            elif msg_type == "sync_character":
                character = message_data.get("character_id") or message_data.get("character") or get_active()
                await _push_current_state(session_id, character)

            elif msg_type == "refresh_memory":
                # 手动触发记忆沉淀
                char = message_data.get("character_id") or message_data.get("character") or get_active()
                asyncio.create_task(_async_condense_memory(char, trigger="manual"))
                await manager.send_chunk(
                    session_id,
                    StreamChunk(type="text", content="记忆刷新已触发～"),
                    character=char,
                )

            else:
                logger.warning(f"未知消息类型: {msg_type}")

    except WebSocketDisconnect:
        manager.disconnect(session_id)
    except Exception as e:
        logger.error(f"WebSocket 错误: {e}")
        manager.disconnect(session_id)
