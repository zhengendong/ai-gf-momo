"""
图像生成 API 路由
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..config import settings
from ..models.schemas import ImageGenerationRequest, ImageGenerationResponse
from ..services.comfyui import comfyui_service
from ..services.generation_settings import load_generation_settings
from ..tools.image_tool import ImageTool

logger = logging.getLogger(__name__)
router = APIRouter()

_histories: dict[str, list[dict]] = {}


class ImageRegenerateRequest(BaseModel):
    """Replace one recorded image using its own frozen final prompt."""

    image_url: str
    character: str | None = None


def _history_path(character: str) -> Path:
    return settings.get_images_dir(character) / "_history.json"


def _load_history(character: str) -> list[dict]:
    if character in _histories:
        return _histories[character]
    hp = _history_path(character)
    if hp.exists():
        try:
            items = json.loads(hp.read_text(encoding="utf-8"))
        except Exception:
            items = []
    else:
        items = []
    _histories[character] = items
    logger.info(f"已加载 {len(items)} 条历史记录 [{character}]")
    return items


def _save_history(character: str):
    hp = _history_path(character)
    hp.parent.mkdir(parents=True, exist_ok=True)
    hp.write_text(json.dumps(_histories[character], ensure_ascii=False, indent=2), encoding="utf-8")


def _add_history(
    prompt: str,
    image_url: str,
    image_path: str,
    character: str | None = None,
    metadata: dict | None = None,
):
    from ..core.characters import get_active
    char = character or get_active()
    items = _load_history(char)
    record = {"prompt": prompt, "image_url": image_url, "image_path": image_path}
    if metadata:
        record["generation"] = metadata
    items.append(record)
    _save_history(char)


@router.post("/generate", response_model=ImageGenerationResponse)
async def generate_image(request: ImageGenerationRequest):
    """
    生成图像

    根据提示词生成图片。如果不传 prompt，将使用当前 live_state 自动构建 prompt。

    Args:
        request: 图像生成请求

    Returns:
        ImageGenerationResponse: 生成的图像信息
    """
    try:
        # 1. 检查 ComfyUI 是否可用
        is_available = await comfyui_service.check_status()
        if not is_available:
            raise HTTPException(
                status_code=503,
                detail="ComfyUI 服务不可用，请确认 ComfyUI 已启动（默认 http://127.0.0.1:8188）"
            )

        # 2. 获取用户输入的 prompt（角色标签由 build_workflow_from_template 自动拼接）
        prompt = request.prompt.strip()
        if not prompt:
            prompt = "solo"  # fallback，角色标签会在 build_workflow_from_template 中自动拼接

        # 3. 确定图片尺寸
        aspect_ratio = request.aspect_ratio or "1:1"
        width, height = _get_dimensions(aspect_ratio)

        # 4. 构建工作流
        profile = load_generation_settings()
        workflow = comfyui_service.build_workflow_from_template(
            prompt=prompt,
            negative_prompt=profile.negative_prompt,
            workflow_name=profile.workflow,
            workflow_dir=profile.workflow_dir,
            width=width if width is not None else profile.width,
            height=height if height is not None else profile.height,
            steps=profile.steps,
            cfg=profile.cfg,
            sampler=profile.sampler,
            scheduler=profile.scheduler,
        )

        # 5. 生成图片
        image_path = await comfyui_service.generate_image(workflow)

        if not image_path:
            raise HTTPException(status_code=500, detail="图片生成失败，ComfyUI 未返回结果")

        # 6. 构建可访问的 URL
        from ..core.characters import get_active
        char = get_active()
        filename = Path(image_path).name
        image_url = f"/static/{char}/images/{filename}"

        # 7. 记录到历史
        _add_history(prompt, image_url, image_path)

        logger.info(f"图片生成成功: {image_url}")

        return ImageGenerationResponse(
            image_url=image_url,
            prompt_used=prompt
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"图片生成失败: {e}")
        raise HTTPException(status_code=500, detail=f"图片生成失败: {str(e)}")


@router.post("/regenerate", response_model=ImageGenerationResponse)
async def regenerate_image(request: ImageRegenerateRequest):
    """Regenerate one history entry and atomically replace its visible record."""
    from ..core.characters import get_active
    from ..core.chat_history import replace_chat_image_url

    character = request.character or get_active()
    original_url = str(request.image_url or "").strip()
    items = _load_history(character)
    index = next(
        (idx for idx, item in enumerate(items) if item.get("image_url") == original_url),
        None,
    )
    if index is None:
        raise HTTPException(status_code=404, detail="未找到对应的图片历史记录")

    original = dict(items[index])
    prompt = str(original.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=422, detail="该历史图片没有可重用的提示词")

    try:
        if not await comfyui_service.check_status():
            raise HTTPException(status_code=503, detail="ComfyUI 服务不可用")

        profile = load_generation_settings()
        # History already stores the final assembled prompt. Do not rebuild it
        # from the mutable current state, otherwise this would not be a true
        # regeneration of the selected image.
        workflow = comfyui_service.build_workflow_from_template(
            prompt=prompt,
            negative_prompt=profile.negative_prompt,
            workflow_name=profile.workflow,
            workflow_dir=profile.workflow_dir,
            width=profile.width,
            height=profile.height,
            steps=profile.steps,
            cfg=profile.cfg,
            sampler=profile.sampler,
            scheduler=profile.scheduler,
            character=character,
            filename_prefix=character,
            inject_character_tags=False,
        )
        _, comfy_history = await comfyui_service.submit_and_wait(workflow)
        if not comfy_history:
            raise HTTPException(status_code=504, detail="图片生成超时")

        image_path = await ImageTool(comfyui_service).save_from_history(comfy_history, character)
        if not image_path:
            raise HTTPException(status_code=500, detail="ComfyUI 未返回可保存的最终图片")

        image_url = f"/static/{character}/images/{Path(image_path).name}"
        replacement = dict(original)
        replacement["image_url"] = image_url
        replacement["image_path"] = image_path
        metadata = dict(replacement.get("generation") or {})
        metadata["regenerated_from"] = original_url
        metadata["regeneration_count"] = int(metadata.get("regeneration_count") or 0) + 1
        replacement["generation"] = metadata

        # Keep user files intact. The history entry and the chat reference are
        # replaced only after a new image has completed successfully.
        replace_chat_image_url(character, original_url, image_url)
        items[index] = replacement
        _save_history(character)
        return ImageGenerationResponse(image_url=image_url, prompt_used=prompt)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("图片重新生成失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"图片重新生成失败: {e}")


@router.get("/status/{task_id}")
async def get_generation_status(task_id: str):
    """
    获取生成任务状态

    Args:
        task_id: 任务ID（ComfyUI prompt_id）

    Returns:
        任务状态
    """
    try:
        history = await comfyui_service.get_history(task_id)
        if history is not None:
            return {
                "task_id": task_id,
                "status": "completed",
                "data": history
            }
        else:
            return {
                "task_id": task_id,
                "status": "pending",
                "message": "任务正在进行中或不存在"
            }
    except Exception as e:
        logger.error(f"查询任务状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_generation_history(limit: int = 10, character: str = None):
    from ..core.characters import get_active
    items = _load_history(character or get_active())
    return {
        "total": len(items),
        "items": items[-limit:][::-1]
    }


@router.get("/status")
async def check_comfyui_status():
    """检查 ComfyUI 服务状态"""
    is_available = await comfyui_service.check_status()
    return {
        "comfyui_available": is_available,
        "comfyui_url": comfyui_service.base_url
    }


def _get_dimensions(aspect_ratio: str) -> tuple[int, int]:
    """根据宽高比返回图片尺寸（SDXL 原生分辨率）"""
    ratios = {
        "1:1": (1024, 1024),
        "3:4": (896, 1216),
        "2:3": (832, 1216),
        "9:16": (704, 1216),
        "4:3": (1216, 896),
        "3:2": (1216, 832),
        "16:9": (1216, 704),
    }
    return ratios.get(aspect_ratio, (1024, 1024))
