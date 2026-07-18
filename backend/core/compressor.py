"""
上下文窗口管理模块
估算 token 数，触发压缩
"""

import logging
import re
from typing import Optional

from ..config import settings

logger = logging.getLogger(__name__)


def strip_model_thinking(text: str) -> str:
    """Remove provider reasoning blocks before persisting summaries or replies."""
    if not text:
        return ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def estimate_tokens(text: str) -> int:
    """
    估算文本 token 数。
    中文约 1.5 字符/token，英文约 4 字符/token
    和前端"上下文窗口(K)"单位一致。
    """
    if not text:
        return 0
    chinese = sum(1 for c in text if "\u4e00" <= c <= "\u9fff" or "\u3400" <= c <= "\u4dbf")
    others = len(text) - chinese
    return int(chinese * 1.5 + others * 0.3)
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
    system = """你是 MemoryAgent 的连续剧情压缩模块，不参与角色对话。
将即将离开完整上下文窗口的旧对话合并进已有摘要，供后续对话继续承接。
保留人物关系、事件因果、承诺与决定、情绪转折、明确的故事时间线、地点/场景变化，以及影响后续剧情的状态变化。
合并重复信息，按故事发生顺序写成紧凑摘要，不要逐句复述，不要写成流水账。
输入不包含可采信的现实系统时间；不得根据技术时间戳补写日期或时钟。
只输出更新后的摘要正文，不要标题、解释、JSON 或 Markdown 代码块。"""
    user = f"""已有的摘要：
{old_summary or "（无）"}

需要压缩的新对话：
{turns_to_compress}

请输出合并后的紧凑剧情摘要："""

    try:
        response = await llm_client.chat_prompt(system=system, user=user)
        return strip_model_thinking(response)
    except Exception as e:
        logger.error(f"压缩对话失败: {e}")
        return old_summary
