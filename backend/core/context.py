"""
上下文组装模块
从多角色目录读取文件，拼成 Momo Agent 的 user prompt
"""

import json
from pathlib import Path
from typing import Optional

from ..config import settings
from ..utils.helpers import read_markdown


def load_character_profile(character: str) -> dict:
    """加载角色 profile.json"""
    path = settings.get_character_dir(character) / "profile.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


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


def load_plans(character: str) -> str:
    """加载角色 plans.md"""
    from .state import read_plans
    return read_plans(character)


def load_tag_reference() -> str:
    """加载 SD 标签参考"""
    path = settings.config_dir / "tag_reference.md"
    if path.exists():
        content = read_markdown(path)
        # 只用前面部分，控制 token
        return content[:3000] if len(content) > 3000 else content
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
) -> str:
    """
    组装 Momo Agent 的 user prompt

    Args:
        character: 角色名
        user_message: 用户消息
        chat_history: 最近 N 轮对话
        conversation_summary: 超出窗口的旧对话摘要
    """
    profile = load_character_profile(character)
    identity = load_identity(character)
    soul = load_soul(character)
    long_term = load_long_term(character)
    status = load_status(character)
    plans = load_plans(character)
    char_name = profile.get("name", character)

    parts = []

    # 当前角色信息
    parts.append(f"## 你是{char_name}")
    parts.append(identity)

    # 视觉锚点（生图时用，对话时不直接显示）
    parts.append("## 角色标签（生图用）")
    parts.append(f"avatar_role: {profile.get('avatar_role', '')}")
    parts.append(f"body_type: {profile.get('body_type', '')}")
    parts.append(f"appearance: {profile.get('appearance', '')}")
    parts.append(f"name: {char_name}")

    # 灵魂
    parts.append("## 你的灵魂")
    parts.append(soul)

    # 标签参考
    tag_ref = load_tag_reference()
    if tag_ref:
        parts.append("## SD 标签参考（生图时查阅）")
        parts.append(tag_ref)

    # 长期记忆
    parts.append("## 你记得")
    parts.append(long_term)

    # 当前状态
    parts.append("## 你的当前状态")
    parts.append(status)

    # 当前计划
    parts.append("## 你的计划")
    parts.append(plans)

    # 对话摘要（压缩后的旧对话）
    if conversation_summary:
        parts.append("## 之前的对话摘要")
        parts.append(conversation_summary)

    # 最近对话历史
    if chat_history:
        parts.append("## 最近的对话")
        parts.append(chat_history)

    # 用户消息
    parts.append("---")
    parts.append(f"主人说：{user_message}")
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
