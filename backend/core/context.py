"""
上下文组装模块
从多角色目录读取文件，拼成 Momo Agent 的 user prompt
"""

import json
from pathlib import Path
from typing import Optional

from ..config import settings
from ..utils.helpers import read_markdown
from ..core.time_system import format_time_prompt_section


def load_character_profile(character: str) -> dict:
    """加载角色 profile.json"""
    path = settings.get_character_dir(character) / "profile.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_character_name(character: str) -> str:
    """Return the display name for a character id."""
    profile = load_character_profile(character)
    return profile.get("name") or character


def load_user_profile(character: str) -> dict:
    """Load the per-character user profile."""
    from .memory_v3 import load_user_profile as _load_user_profile
    return _load_user_profile(character)


def get_user_pet_name(character: str) -> str:
    """Return the name this character should use for the user."""
    profile = load_user_profile(character)
    return profile.get("user_pet_name") or "用户"


def render_user_profile(character: str) -> str:
    """Render user.json into prompt text for this character."""
    from .memory_v3 import render_user_profile as _render_user_profile
    return _render_user_profile(load_user_profile(character))


def load_identity(character: str) -> str:
    """加载角色 identity.md"""
    path = settings.get_character_dir(character) / "identity.md"
    if path.exists():
        return read_markdown(path)
    return ""


def load_soul(character: str) -> str:
    """加载角色 soul.md"""
    path = settings.get_memory_dir(character) / "soul.md"
    if path.exists():
        return read_markdown(path)
    return ""


def load_long_term(character: str) -> str:
    """加载角色 long_term.md"""
    path = settings.get_memory_dir(character) / "long_term.md"
    if path.exists():
        return read_markdown(path)
    return ""


def load_status(character: str) -> str:
    """加载角色 status.md"""
    from .state import read_status
    return read_status(character)


def load_tag_reference() -> str:
    """加载 SD 标签参考"""
    path = settings.config_dir / "tag_reference.md"
    if path.exists():
        content = read_markdown(path)
        # 只用前面部分，控制 token
        return content[:3000] if len(content) > 3000 else content
    return ""


def load_photo_rules() -> str:
    """加载拍照和服饰状态规则。"""
    path = settings.config_dir / "photo_rules.md"
    if path.exists():
        return read_markdown(path)
    return ""


def load_conversation_summary(character: str) -> str:
    """加载对话摘要（如有）"""
    path = settings.get_memory_dir(character) / "conversation_summary.md"
    if path.exists():
        return read_markdown(path)
    return ""


def save_conversation_summary(character: str, summary: str):
    """保存对话摘要"""
    path = settings.get_memory_dir(character) / "conversation_summary.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(summary, encoding="utf-8")


def assemble_momo_prompt(
    character: str,
    user_message: str,
    chat_history: str = "",
    conversation_summary: str = "",
    recalled_memories: str = "",
) -> str:
    """
    组装 Momo Agent 的 user prompt

    system prompt 已包含：agent.md + identity.md + soul.md + long_term.md + photo_rules.md
    这里只放每轮动态变化的信息。

    Args:
        character: 角色名
        user_message: 用户消息
        chat_history: 最近 N 轮对话
        conversation_summary: 超出窗口的旧对话摘要
        recalled_memories: 用户需要查找细节时从向量库召回的历史片段
    """
    status = load_status(character)
    user_profile = render_user_profile(character)
    user_pet_name = get_user_pet_name(character)

    parts = [
        "# 当前上下文包",
        "",
        "# ---- 当前时间 ----",
        format_time_prompt_section(character),
        "",
        "## 1. user.json（用户信息）",
        user_profile or "（未填写）",
        "",
        "## 2. status.md（当前现实状态）",
        status or "（未填写）",
    ]

    # 对话摘要（压缩后的旧对话）
    if conversation_summary:
        parts.append("## 3. 历史对话摘要（conversation_summary.md）")
        parts.append(conversation_summary)

    # 最近对话历史
    if chat_history:
        parts.append("## 4. 最近对话（chat_history）")
        parts.append(chat_history)

    if recalled_memories:
        parts.append("## 5. 向量召回（vector_recall，相关历史记录）")
        parts.append("以下是检索到的与当前话题相关的过往对话记录。")
        parts.append(recalled_memories)

    # 用户消息
    parts.append("## 6. 当前用户消息")
    parts.append(f"{user_pet_name}说：{user_message}")
    parts.append("")
    parts.append("请以 JSON 格式输出。")

    return "\n\n".join(parts)


def append_daily_memory(character: str, content: str):
    """追加每日对话记录"""
    from datetime import date
    today = date.today().isoformat()
    path = settings.get_memory_dir(character) / f"{today}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(content + "\n\n")
