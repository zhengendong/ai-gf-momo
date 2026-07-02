"""
时间体系模块
- 提供当前时间信息（用于注入 LLM prompt）
- 记录与读取上次对话时间
- 时段判断 + 自然语言描述
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from ..config import settings

logger = logging.getLogger(__name__)


# 时段定义（按 24h）
_TIME_SLOTS = [
    (5, 7, "清晨"),
    (7, 11, "上午"),
    (11, 13, "中午"),
    (13, 17, "下午"),
    (17, 19, "傍晚"),
    (19, 22, "晚上"),
    (22, 24, "深夜"),
    (0, 5, "凌晨"),
]

# 星期（中文）
_WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 时段到自然语言招呼的映射
_GREETING_HINTS = {
    "清晨": "清晨问候，关心睡眠",
    "上午": "上午活泼，关心早餐/工作",
    "中午": "中午可问吃了没",
    "下午": "下午问问在忙啥",
    "傍晚": "傍晚关心是否下班/回家",
    "晚上": "晚上亲密聊天，关心心情",
    "深夜": "深夜安静温柔，关心休息",
    "凌晨": "凌晨担心睡眠，语气轻",
}


def get_time_of_day(hour: int) -> str:
    """根据小时返回时段名"""
    for start, end, name in _TIME_SLOTS:
        if start <= hour < end:
            return name
    return "深夜"


def get_greeting_hint(time_of_day: str) -> str:
    """返回时段的自然语言招呼建议"""
    return _GREETING_HINTS.get(time_of_day, "自然聊天")


def _last_chat_path(character: str) -> Path:
    """上次对话时间记录文件"""
    return settings.get_memory_dir(character) / "last_chat.json"


def read_last_chat(character: str) -> Optional[datetime]:
    """读取上次对话时间（UTC）"""
    path = _last_chat_path(character)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ts = data.get("last_chat_at", "")
        if not ts:
            return None
        last = datetime.fromisoformat(ts)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        return last
    except Exception as e:
        logger.warning(f"读取 last_chat.json 失败: {e}")
        return None


def write_last_chat(character: str, dt: Optional[datetime] = None):
    """记录本次对话时间"""
    path = _last_chat_path(character)
    path.parent.mkdir(parents=True, exist_ok=True)
    if dt is None:
        dt = datetime.now(timezone.utc)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"last_chat_at": dt.isoformat(), "updated_at": datetime.now(timezone.utc).isoformat()},
            f,
            ensure_ascii=False,
            indent=2,
        )


def _format_delta(delta: timedelta) -> str:
    """把时间差转成自然语言"""
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return "刚刚"
    if total_seconds < 60:
        return f"{total_seconds}秒前"
    if total_seconds < 3600:
        return f"{total_seconds // 60}分钟前"
    if total_seconds < 86400:
        h = total_seconds // 3600
        m = (total_seconds % 3600) // 60
        return f"{h}小时{m}分钟前" if m > 0 else f"{h}小时前"
    days = total_seconds // 86400
    return f"{days}天前"


def get_current_time_info(character: str) -> dict:
    """
    返回当前时间完整信息（用于 prompt 注入）。

    Returns:
        {
            "date": "2026-06-17",
            "weekday": "周三",
            "time": "15:30",
            "time_of_day": "下午",
            "greeting_hint": "下午问问在忙啥",
            "last_chat_at": "2026-06-17 13:00",
            "last_chat_delta": "2小时30分钟前",
            "is_first_chat": False,
        }
    """
    now_local = datetime.now()
    weekday = _WEEKDAY_CN[now_local.weekday()]
    time_of_day = get_time_of_day(now_local.hour)
    last = read_last_chat(character)

    info = {
        "date": now_local.strftime("%Y-%m-%d"),
        "weekday": weekday,
        "time": now_local.strftime("%H:%M"),
        "time_of_day": time_of_day,
        "greeting_hint": get_greeting_hint(time_of_day),
        "last_chat_at": "",
        "last_chat_delta": "",
        "is_first_chat": last is None,
    }

    if last is not None:
        # 转为本地时间显示
        last_local = last.astimezone()
        info["last_chat_at"] = last_local.strftime("%Y-%m-%d %H:%M")
        delta = datetime.now(timezone.utc) - last
        info["last_chat_delta"] = _format_delta(delta)

    return info


def format_time_prompt_section(character: str) -> str:
    """
    生成 prompt 注入用的「当前时间」section 文本。
    注入到 user prompt 顶部（在「你是{char_name}」之后）。
    """
    info = get_current_time_info(character)
    lines = [
        f"日期: {info['date']} {info['weekday']}",
        f"时间: {info['time']}（{info['time_of_day']}）",
        f"招呼建议: {info['greeting_hint']}",
    ]
    if info["is_first_chat"]:
        lines.append("这是你们的第一次对话（不知道该知道些什么，自然自我介绍即可）")
    else:
        lines.append(f"上次对话: {info['last_chat_at']}（{info['last_chat_delta']}）")
    return "\n".join(lines)
