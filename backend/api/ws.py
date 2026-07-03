"""WebSocket routes.

This module owns transport concerns only. Message orchestration lives in
backend.core.runtime.AgentRuntime.
"""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..core.characters import get_active
from ..core.runtime import AgentRuntime
from ..models.schemas import StreamChunk
from ..services.comfyui import comfyui_service
from ..services.llm import llm_service

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    """WebSocket connection manager."""

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_connections[session_id] = websocket
        logger.info("WebSocket connected: session_id=%s", session_id)

    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]
            logger.info("WebSocket disconnected: session_id=%s", session_id)

    async def send_chunk(
        self,
        session_id: str,
        chunk: StreamChunk,
        character: str | None = None,
    ):
        websocket = self.active_connections.get(session_id)
        if not websocket:
            return
        try:
            if character and not chunk.character:
                chunk.character = character
            await websocket.send_text(chunk.model_dump_json())
        except Exception as e:
            logger.error("WebSocket send failed: %s", e)
            self.disconnect(session_id)


manager = ConnectionManager()
runtime = AgentRuntime(llm_service, comfyui_service, manager)

# Backward-compatible names used by REST routes.
momo_agent = runtime.momo_agent
chat_history_buffer = runtime.chat_history_buffer


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await manager.connect(websocket, session_id)
    await runtime.push_current_state(session_id, get_active())

    try:
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            msg_type = message_data.get("type", "text")

            if msg_type == "text":
                content = message_data.get("content", "")
                character = (
                    message_data.get("character_id")
                    or message_data.get("character")
                    or get_active()
                )
                if content:
                    await runtime.handle_message(session_id, character, content)

            elif msg_type == "ping":
                await manager.send_chunk(session_id, StreamChunk(type="pong", content=""))

            elif msg_type == "sync_character":
                character = (
                    message_data.get("character_id")
                    or message_data.get("character")
                    or get_active()
                )
                await runtime.push_current_state(session_id, character)

            elif msg_type == "refresh_memory":
                character = (
                    message_data.get("character_id")
                    or message_data.get("character")
                    or get_active()
                )
                await runtime.refresh_memory(session_id, character)

            else:
                logger.warning("Unknown websocket message type: %s", msg_type)

    except WebSocketDisconnect:
        manager.disconnect(session_id)
        runtime.clear_session(session_id)
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        manager.disconnect(session_id)
        runtime.clear_session(session_id)
