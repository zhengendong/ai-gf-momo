"""
Pydantic 数据模型
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class StreamChunk(BaseModel):
    """流式响应块（WebSocket）"""
    type: str = Field(
        ...,
        description="类型: text, scene_divider, image, image_status, status_update, state_update, memory_updated, done",
    )
    content: Optional[str] = Field(None, description="文本内容")
    url: Optional[str] = Field(None, description="图片 URL")
    character: Optional[str] = Field(None, description="角色 ID")
    done: bool = Field(False, description="是否结束")


class AgentOutput(BaseModel):
    """Character agent output."""
    reply: str = Field(..., description="角色的对话回复")
    state_ops: list[dict[str, Any]] = Field(
        default_factory=list,
        description="旧版状态操作兼容字段；新 MomoAgent 始终留空",
    )
    image_goal: Optional[dict[str, Any]] = Field(
        None,
        description="旧版主 Agent 图片目标兼容字段；新 MomoAgent 始终为 null",
    )
    effects: list[dict[str, Any]] = Field(
        default_factory=list,
        description="旧版结构化事件兼容字段；新 MomoAgent 始终留空",
    )
    image_intent: Optional[dict[str, Any]] = Field(
        None,
        description="画面设计任务；不包含人物外貌、服饰、场景或质量标签",
    )
    memory_candidate: Optional[str] = Field(
        None,
        description="主 Agent识别出的长期记忆候选；由后台 MemoryAgent 二次审核",
    )
    # Legacy fields remain readable for external callers. The live Momo parser
    # ignores them; VisualContinuityAgent owns visual state in the new runtime.
    photo_prompt: Optional[str] = Field(None, description="英文 Danbooru prompt，不拍照时为 null")
    state_updates: Optional[dict] = Field(None, description="状态变更，格式: {'status': {...}}")
    immediate_memory: Optional[str] = Field(None, description="旧版长期记忆候选字段，兼容读取")
    persist_context: bool = Field(True, description="是否写入上下文和记忆")


class ContinuityOutput(BaseModel):
    """Visual continuity result produced after the character reply."""
    state_patch: dict[str, Any] = Field(
        default_factory=dict,
        description="服饰与场景的局部完整槽位补丁",
    )
    shot_spec: Optional[dict[str, Any]] = Field(
        None,
        description="导演认为本轮值得生图时给出的最终画面计划；null 表示不生图",
    )
    reason: str = Field("", description="仅供内部诊断的连续性判断摘要")


class ImageGenerationRequest(BaseModel):
    """图像生成请求"""
    prompt: str = Field(..., description="生图提示词")
    style: Optional[str] = Field(None, description="风格")
    aspect_ratio: str = Field("1:1", description="宽高比")


class ImageGenerationResponse(BaseModel):
    """图像生成响应"""
    image_url: str = Field(..., description="生成的图片 URL")
    prompt_used: str = Field(..., description="实际使用的提示词")
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class CharacterProfile(BaseModel):
    """角色 profile"""
    name: str = Field(..., description="角色名称")
    avatar: str = Field(default="💕", description="头像 emoji")
    avatar_role: str = Field(..., description="视觉锚点角色")
    body_type: str = Field(..., description="体型标签")
    appearance: str = Field(..., description="外貌标签")


class AppSettings(BaseModel):
    """应用设置"""
    active_character: str = Field(default="momo")
    context: dict = Field(default_factory=lambda: {"max_tokens": 16000, "compress_at": 0.85})
    comfyui: dict = Field(default_factory=dict)
    memory: dict = Field(default_factory=lambda: {
        "condensation_days": 1,
        "retention_days": 30,
        "long_term_turns_per_condense": 15,
        "soul_turns_per_condense": 15,
        "vector_recall_enabled": True,
        "vector_top_k": 5,
        "vector_max_distance": 0.55,
    })
