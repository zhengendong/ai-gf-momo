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
    business_knowledge: str = "",
) -> str:
    """
    组装 Momo Agent 的 user prompt

    system prompt 已包含：agent.md + identity.md + soul.md + long_term.md
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
        "## 2. status.md（本轮开始时的客观视觉事实）",
        "以下状态由上一轮 VisualContinuityAgent 还原并已提交。它不是猜测、建议或可选参考；服饰和场景事实不得被历史对话、记忆或角色惯性否认。角色回复必须从此状态继续，只能通过本轮明确发生的新动作改变它。",
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

    if business_knowledge:
        parts.append("## 本轮适用业务知识")
        parts.append("以下知识只补充当前场景的常识、一致性和审美，不替代角色身份与自主判断。")
        parts.append(business_knowledge)

    # 用户消息
    parts.append("## 当前视觉事实约束")
    parts.append(
        "生成回复前必须以 status.md 为本轮起点。若历史对话与 status.md 的任何事实冲突，"
        "以 status.md 为准；不得否认、改写、遗漏或凭空补造其中任何当前事实。"
    )
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
