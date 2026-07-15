"""Verify ComfyUI WebSocket completion handling without submitting an image."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import settings
from backend.services.comfyui import ComfyUIService, select_history_image
from backend.tools.image_tool import ImageTool


class FakeSocket:
    def __init__(self, messages):
        self.messages = iter(messages)

    async def recv(self):
        return next(self.messages)


class FakeImageClient:
    def __init__(self):
        self.request = None

    async def get_image(self, filename, subfolder="", folder_type="output"):
        self.request = (filename, subfolder, folder_type)
        return b"preview-image"


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

    preview = select_history_image({
        "outputs": {
            "1": {"images": [{"filename": "preview.png", "subfolder": "", "type": "temp"}]},
        }
    })
    assert preview == {"filename": "preview.png", "subfolder": "", "type": "temp"}

    final = select_history_image({
        "outputs": {
            "1": {"images": [{"filename": "preview.png", "type": "temp"}]},
            "2": {"images": [{"filename": "final.png", "type": "output"}]},
        }
    })
    assert final["filename"] == "final.png"
    assert final["type"] == "output"

    fake_image_client = FakeImageClient()
    old_base_dir = settings.base_dir
    try:
        with tempfile.TemporaryDirectory() as tmp:
            settings.base_dir = Path(tmp)
            image_path = await ImageTool(fake_image_client).save_from_history(
                {"outputs": {"1": {"images": [preview]}}},
                "probe",
            )
            assert fake_image_client.request == ("preview.png", "", "temp")
            assert Path(image_path).read_bytes() == b"preview-image"
    finally:
        settings.base_dir = old_base_dir

    print(json.dumps({"status": "ok", "transport": "websocket_then_history"}))


if __name__ == "__main__":
    asyncio.run(main())
