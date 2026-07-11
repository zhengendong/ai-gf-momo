"""ComfyUI image generation pipeline."""

import logging
from pathlib import Path

from ..models.schemas import StreamChunk
from ..tools.image_tool import ImageTool
from ..core.image_job import ImageJob

logger = logging.getLogger(__name__)


class ImagePipeline:
    """Submit image prompts to ComfyUI and stream status back to one session."""

    def __init__(self, comfyui_service, ws_manager):
        self.comfyui = comfyui_service
        self.manager = ws_manager
        self.tool = ImageTool(comfyui_service)

    async def generate(self, session_id: str, photo_prompt: str, character: str, reply: str = ""):
        """Backward-compatible entry point for manual and legacy callers."""
        from ..core.image_job import build_image_job

        job = build_image_job(character, reply, legacy_prompt=photo_prompt)
        if job:
            await self.generate_job(session_id, job)

    async def generate_job(self, session_id: str, job: ImageJob):
        character = job.character
        try:
            await self._push(
                session_id,
                StreamChunk(type="image_status", content="generating"),
                character,
            )

            await self._push(
                session_id,
                StreamChunk(type="status_update", content="正在准备生成..."),
                character,
            )
            workflow, prompt_used = self.tool.build_job_workflow(job)

            await self._push(
                session_id,
                StreamChunk(type="status_update", content="正在提交任务..."),
                character,
            )
            prompt_id = await self.comfyui.queue_prompt(workflow)

            await self._push(
                session_id,
                StreamChunk(type="status_update", content="正在生成图片..."),
                character,
            )
            history = await self.comfyui.wait_for_completion(prompt_id)

            if not history:
                await self._push(
                    session_id,
                    StreamChunk(type="image_status", content="error"),
                    character,
                )
                await self._push(
                    session_id,
                    StreamChunk(type="status_update", content="生成超时"),
                    character,
                )
                return

            await self._push(
                session_id,
                StreamChunk(type="status_update", content="正在保存图片..."),
                character,
            )

            image_path = await self.tool.save_from_history(history, character)

            if image_path:
                fn = Path(image_path).name
                url = f"/static/{character}/images/{fn}"
                await self._push(
                    session_id,
                    StreamChunk(type="image", url=url, content=""),
                    character,
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
                    logger.warning("Failed to write image chat history for %s: %s", character, e)
                self.tool.add_history(character, prompt_used, url, image_path)
                await self._push(
                    session_id,
                    StreamChunk(type="status_update", content="照片已生成 ✓"),
                    character,
                )
            else:
                await self._push(
                    session_id,
                    StreamChunk(type="image_status", content="error"),
                    character,
                )
                await self._push(
                    session_id,
                    StreamChunk(type="status_update", content="未找到生成图片"),
                    character,
                )
        except Exception as e:
            logger.error("Image generation failed for %s: %s", character, e)
            await self._push(
                session_id,
                StreamChunk(type="image_status", content="error"),
                character,
            )
            await self._push(
                session_id,
                StreamChunk(type="status_update", content=f"生成失败: {e}"),
                character,
            )

    async def _push(self, session_id: str, chunk: StreamChunk, character: str = None):
        await self.manager.send_chunk(session_id, chunk, character=character)
