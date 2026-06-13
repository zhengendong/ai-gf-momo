"""
上下文窗口管理模块
估算 token 数，触发压缩
"""

import logging
from typing import Optional

from ..config import settings

logger = logging.getLogger(__name__)


def estimate_tokens(text: str) -> int:
    """
    估算文本 token 数
    简单估算：中文约 1.5 字符/token，英文约 4 字符/token
    取粗估值：总字符数 / 2
    """
    if not text:
        return 0
    return len(text) // 2


def needs_compression(total_tokens: int, max_tokens: int = None, threshold: float = None) -> bool:
    """
    判断是否需要压缩

    Args:
        total_tokens: 当前上下文 token 数
        max_tokens: 最大窗口（从 settings 读取）
        threshold: 触发比例（从 settings 读取）

    Returns:
        是否需要压缩
    """
    settings_json = _load_settings()
    max_tokens = max_tokens or settings_json.get("context", {}).get("max_tokens", 8000)
    threshold = threshold or settings_json.get("context", {}).get("compress_at", 0.7)

    return total_tokens >= int(max_tokens * threshold)


def _load_settings() -> dict:
    """加载 settings.json"""
    import json
    path = settings.settings_file
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


async def compress_conversation(
    llm_client,
    old_summary: str,
    turns_to_compress: str,
) -> str:
    """
    压缩旧对话为摘要

    Args:
        llm_client: LLM 客户端
        old_summary: 已有的摘要
        turns_to_compress: 需要压缩的对话轮次

    Returns:
        新的摘要
    """
    system = "你是一个对话摘要助手。将以下对话压缩为一段简短摘要，保留关键信息（情绪变化、重要决定、状态变更）。不要流水账。"
    user = f"""已有的摘要：
{old_summary or "（无）"}

需要压缩的新对话：
{turns_to_compress}

请输出合并后的新摘要（一段话即可）："""

    try:
        response = await llm_client.chat_prompt(system=system, user=user)
        return response.strip()
    except Exception as e:
        logger.error(f"压缩对话失败: {e}")
        return old_summary
