"""
后端最小闭环检查。

不调用 LLM，不真正生成图片；只验证应用导入、Runtime、ComfyUI 连通和生图 workflow 构建。
"""

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


async def main():
    from backend.api.ws import runtime
    from backend.core.characters import get_active
    from backend.main import app
    from backend.services.comfyui import comfyui_service
    from backend.tools.image_tool import ImageTool

    character = get_active()
    image_tool = ImageTool(comfyui_service)
    workflow, prompt = image_tool.build_workflow(
        character=character,
        prompt="1girl, solo, smile",
        width=1024,
        height=1024,
    )
    comfyui_available = await comfyui_service.check_status()

    result = {
        "app": {"title": app.title, "version": app.version},
        "runtime": type(runtime).__name__,
        "active_character": character,
        "comfyui_available": comfyui_available,
        "workflow_nodes": len(workflow),
        "prompt_preview": prompt[:200],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
