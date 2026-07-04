"""
ImageTool
角色生图工具：负责 prompt 组装、ComfyUI 调用、图片保存和历史记录。
"""

import logging
from pathlib import Path
from typing import Optional

from ..config import settings
from ..services.prompt_builder import build_image_prompt

logger = logging.getLogger(__name__)


class ImageTool:
    """角色生图工具。"""

    def __init__(self, comfyui_service):
        self.comfyui = comfyui_service

    def build_workflow(
        self,
        character: str,
        prompt: str,
        reply: str = "",
        width: int = None,
        height: int = None,
        workflow_name: str = None,
        negative_prompt: str = "",
    ) -> tuple[dict, str]:
        """构建 ComfyUI workflow，返回 workflow 和实际使用的最终 prompt。"""
        final_prompt = build_image_prompt(character, prompt, reply=reply)
        workflow = self.comfyui.build_workflow_from_template(
            prompt=final_prompt,
            negative_prompt=negative_prompt,
            workflow_name=workflow_name,
            width=width,
            height=height,
            character=character,
            filename_prefix=character,
            inject_character_tags=False,
        )
        return workflow, final_prompt

    async def generate(
        self,
        character: str,
        prompt: str,
        reply: str = "",
        width: int = None,
        height: int = None,
        workflow_name: str = None,
        negative_prompt: str = "",
    ) -> Optional[dict]:
        """
        完整生图：构建 workflow -> 提交 -> 等待 -> 保存 -> 记录历史。

        Returns:
            {
              "image_path": "...",
              "image_url": "...",
              "prompt_used": "..."
            }
        """
        workflow, prompt_used = self.build_workflow(
            character=character,
            prompt=prompt,
            reply=reply,
            width=width,
            height=height,
            workflow_name=workflow_name,
            negative_prompt=negative_prompt,
        )
        prompt_id = await self.comfyui.queue_prompt(workflow)
        history = await self.comfyui.wait_for_completion(prompt_id)
        if not history:
            logger.error(f"ComfyUI 任务未完成: {prompt_id}")
            return None

        image_path = await self.save_from_history(history, character)
        if not image_path:
            return None

        filename = Path(image_path).name
        image_url = f"/static/{character}/images/{filename}"
        self.add_history(character, prompt_used, image_url, image_path)
        return {
            "image_path": image_path,
            "image_url": image_url,
            "prompt_used": prompt_used,
        }

    async def save_from_history(self, history: dict, character: str) -> Optional[str]:
        """从 ComfyUI history 中提取第一张图片并保存到角色图片目录。"""
        outputs = history.get("outputs", {})
        for node_output in outputs.values():
            images = node_output.get("images", [])
            if not images:
                continue

            image_info = images[0]
            filename = image_info["filename"]
            subfolder = image_info.get("subfolder", "")

            image_data = await self.comfyui.get_image(filename, subfolder)
            save_dir = settings.get_images_dir(character)
            save_dir.mkdir(parents=True, exist_ok=True)
            save_path = save_dir / filename
            save_path.write_bytes(image_data)
            logger.info(f"图片已保存: {save_path}")
            return str(save_path)

        logger.error("ComfyUI history 中未找到图片输出")
        return None

    def add_history(
        self,
        character: str,
        prompt: str,
        image_url: str,
        image_path: str,
    ):
        """记录到角色图片历史。"""
        from ..api.image import _add_history

        _add_history(prompt, image_url, image_path, character=character)
