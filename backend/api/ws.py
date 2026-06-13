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
from ..core.context import append_daily_memory, load_conversation_summary, save_conversation_summary
from ..core.characters import get_active
from .image import _add_history

logger = logging.getLogger(__name__)
router = APIRouter()

# Momo Agent 单例
momo_agent = MomoAgent(llm_service)

# 对话历史缓冲区: {session_id: [turn1, turn2, ...]}
chat_history_buffer: dict[str, list[str]] = {}
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

    async def send_chunk(self, session_id: str, chunk: StreamChunk):
        ws = self.active_connections.get(session_id)
        if ws:
            try:
                await ws.send_text(chunk.model_dump_json())
            except Exception as e:
                logger.error(f"发送失败: {e}")
                self.disconnect(session_id)


manager = ConnectionManager()


async def handle_message(session_id: str, content: str):
    """处理一条用户消息"""
    try:
        # 1. 获取对话历史
        history = chat_history_buffer.get(session_id, [])
        chat_history = "\n".join(history[-MAX_HISTORY_TURNS:])
        summary = load_conversation_summary(get_active())

        # 2. 调 Momo Agent
        output = await momo_agent.process(
            user_message=content,
            chat_history=chat_history,
            conversation_summary=summary,
        )

        # 3. 推送文字回复（立即）
        await manager.send_chunk(
            session_id,
            StreamChunk(type="text", content=output.reply)
        )

        # 4. 异步任务（不阻塞）
        tasks = []

        # 状态更新
        if output.state_updates:
            tasks.append(asyncio.create_task(
                _async_update_state(output.state_updates, session_id)
            ))

        # 生图
        if output.photo_prompt:
            tasks.append(asyncio.create_task(
                _async_generate_image(session_id, output.photo_prompt)
            ))
        else:
            await manager.send_chunk(
                session_id,
                StreamChunk(type="image_status", content="done")
            )

        # 追加 long_term
        if output.immediate_memory:
            tasks.append(asyncio.create_task(
                _async_append_long_term(output.immediate_memory)
            ))

        # 追加 daily memory
        tasks.append(asyncio.create_task(
            _async_append_daily(content, output.reply, output.photo_prompt)
        ))

        # 5. 更新对话历史
        history.append(f"主人：{content}")
        history.append(f"小桃：{output.reply}")
        chat_history_buffer[session_id] = history[-MAX_HISTORY_TURNS:]

        # 6. 发送完成
        await manager.send_chunk(
            session_id,
            StreamChunk(type="done", done=True)
        )

        # 等待异步任务（可选的，如果需要确认）
        # await asyncio.gather(*tasks, return_exceptions=True)

    except Exception as e:
        logger.error(f"处理消息失败: {e}", exc_info=True)
        await manager.send_chunk(
            session_id,
            StreamChunk(type="text", content=f"（小桃走神了...等一下哦～）\n错误: {e}")
        )


# 白名单：只推送这 3 个 section 给前端
_ALLOWED_SECTIONS = {"穿着", "场景细节", "小桃的心情状态"}


def _parse_status_sections(content: str) -> dict:
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

    return {k: v for k, v in sections.items() if k in _ALLOWED_SECTIONS}


async def _push_current_state(session_id: str):
    """推送当前角色状态给指定客户端"""
    try:
        char = get_active()
        from ..core.state import read_status, read_plans
        status_content = read_status(char)
        plans_content = read_plans(char)
        await manager.send_chunk(
            session_id,
            StreamChunk(
                type="state_update",
                content=json.dumps({
                    "status": _parse_status_sections(status_content),
                    "plans": _parse_status_sections(plans_content),
                }, ensure_ascii=False)
            )
        )
    except Exception as e:
        logger.error(f"推送状态失败: {e}")


async def _async_update_state(state_updates: dict, session_id: str = None):
    """异步写入状态文件，并通过 WebSocket 推送给客户端"""
    try:
        char = get_active()
        apply_state_updates(char, state_updates)
        # 读取更新后的状态，推送给前端
        if session_id:
            await _push_current_state(session_id)
    except Exception as e:
        logger.error(f"状态更新失败: {e}")


async def _async_generate_image(session_id: str, photo_prompt: str):
    """异步生成图片，分阶段推送状态更新"""
    char = get_active()
    try:
        # 通知生成中
        await manager.send_chunk(
            session_id,
            StreamChunk(type="image_status", content="generating")
        )

        # 阶段 1：准备
        await manager.send_chunk(
            session_id,
            StreamChunk(type="status_update", content="正在准备生成...")
        )
        workflow = comfyui_service.build_workflow_from_template(prompt=photo_prompt)

        # 阶段 2：提交
        await manager.send_chunk(
            session_id,
            StreamChunk(type="status_update", content="正在提交任务...")
        )
        prompt_id = await comfyui_service.queue_prompt(workflow)

        # 阶段 3：等待生成
        await manager.send_chunk(
            session_id,
            StreamChunk(type="status_update", content="正在生成图片...")
        )
        history = await comfyui_service.wait_for_completion(prompt_id)

        if not history:
            await manager.send_chunk(
                session_id,
                StreamChunk(type="image_status", content="error")
            )
            await manager.send_chunk(
                session_id,
                StreamChunk(type="status_update", content="生成超时")
            )
            return

        # 阶段 4：获取并保存图片
        await manager.send_chunk(
            session_id,
            StreamChunk(type="status_update", content="正在保存图片...")
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
                save_dir = settings.get_images_dir(char)
                save_dir.mkdir(parents=True, exist_ok=True)
                save_path = save_dir / filename
                save_path.write_bytes(image_data)
                image_path = str(save_path)
                break

        if image_path:
            fn = Path(image_path).name
            url = f"/static/{char}/images/{fn}"
            await manager.send_chunk(
                session_id,
                StreamChunk(type="image", url=url, content=url)
            )
            _add_history(photo_prompt, url, image_path)
            await manager.send_chunk(
                session_id,
                StreamChunk(type="status_update", content="照片已生成 ✓")
            )
        else:
            await manager.send_chunk(
                session_id,
                StreamChunk(type="image_status", content="error")
            )
            await manager.send_chunk(
                session_id,
                StreamChunk(type="status_update", content="未找到生成图片")
            )
    except Exception as e:
        logger.error(f"图片生成失败: {e}")
        await manager.send_chunk(
            session_id,
            StreamChunk(type="image_status", content="error")
        )
        await manager.send_chunk(
            session_id,
            StreamChunk(type="status_update", content=f"生成失败: {e}")
        )


async def _async_append_long_term(memory: str):
    """异步追加长期记忆"""
    try:
        char = get_active()
        from ..config import settings
        path = settings.get_memory_dir(char) / "long_term.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n- {memory}\n")
    except Exception as e:
        logger.error(f"追加 long_term 失败: {e}")


async def _async_append_daily(user_msg: str, reply: str, photo_prompt: str = None):
    """异步追加每日日记"""
    try:
        char = get_active()
        now = datetime.now().strftime("%H:%M")
        content = f"### {now} 主人说：\n{user_msg}\n\n### 小桃说：\n{reply}"
        if photo_prompt:
            content += f"\n\n📷 {photo_prompt}"
        append_daily_memory(char, content)
    except Exception as e:
        logger.error(f"追加 daily memory 失败: {e}")


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await manager.connect(websocket, session_id)

    # 连接后立即推送当前角色状态
    await _push_current_state(session_id)

    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)

            msg_type = message_data.get("type", "text")

            if msg_type == "text":
                content = message_data.get("content", "")
                if content:
                    await handle_message(session_id, content)

            elif msg_type == "ping":
                await manager.send_chunk(
                    session_id,
                    StreamChunk(type="pong", content="")
                )

            elif msg_type == "refresh_memory":
                # 手动触发记忆沉淀
                char = get_active()
                from ..agents.memory import MemoryAgent
                mem_agent = MemoryAgent(llm_service)
                asyncio.create_task(mem_agent.condense(char))
                await manager.send_chunk(
                    session_id,
                    StreamChunk(type="text", content="记忆刷新已触发～")
                )

            else:
                logger.warning(f"未知消息类型: {msg_type}")

    except WebSocketDisconnect:
        manager.disconnect(session_id)
    except Exception as e:
        logger.error(f"WebSocket 错误: {e}")
        manager.disconnect(session_id)
