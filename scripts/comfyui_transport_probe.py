"""Verify ComfyUI WebSocket completion handling without submitting an image."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.comfyui import ComfyUIService


class FakeSocket:
    def __init__(self, messages):
        self.messages = iter(messages)

    async def recv(self):
        return next(self.messages)


async def main():
    service = ComfyUIService()
    service.base_url = "http://127.0.0.1:8188"
    assert service._websocket_url("probe client") == "ws://127.0.0.1:8188/ws?clientId=probe+client"

    async def history(prompt_id):
        assert prompt_id == "prompt-1"
        return {"outputs": {"9": {"images": [{"filename": "final.png"}]}}}

    service.get_history = history
    websocket = FakeSocket([
        json.dumps({"type": "progress", "data": {"prompt_id": "prompt-1", "value": 5}}),
        b"preview-frame",
        json.dumps({"type": "executing", "data": {"prompt_id": "prompt-1", "node": None}}),
    ])
    result = await service._wait_for_socket_completion(websocket, "prompt-1", 1)
    assert result["outputs"]["9"]["images"][0]["filename"] == "final.png"
    print(json.dumps({"status": "ok", "transport": "websocket_then_history"}))


if __name__ == "__main__":
    asyncio.run(main())
