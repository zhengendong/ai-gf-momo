"""
REST API 路由
设置读写、角色管理、手动沉淀
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import settings
from ..core.characters import (
    list_characters, get_active, switch_character,
    create_character, get_profile, update_profile
)
from ..agents.memory import MemoryAgent
from ..services.llm import llm_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ========== 设置 ==========

class SettingsUpdate(BaseModel):
    active_character: str = None
    context: dict = None
    comfyui: dict = None
    heartbeat: dict = None
    memory: dict = None


@router.get("/settings")
async def get_settings():
    """获取全局设置"""
    path = settings.settings_file
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


@router.put("/settings")
async def update_settings(updates: SettingsUpdate):
    """更新全局设置"""
    path = settings.settings_file
    current = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            current = json.load(f)

    for key, val in updates.model_dump(exclude_none=True).items():
        if val is not None:
            current[key] = val

    with open(path, "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)

    return current


# ========== 角色管理 ==========

class ProfileUpdate(BaseModel):
    name: str = None
    avatar: str = None
    avatar_role: str = None
    body_type: str = None
    appearance: str = None


class CreateCharacterRequest(BaseModel):
    name: str
    avatar: str = "💕"
    avatar_role: str = ""
    body_type: str = ""
    appearance: str = ""
    identity: str = ""


@router.get("/characters")
async def get_characters():
    """列出所有角色"""
    chars = list_characters()
    active = get_active()
    return {
        "characters": chars,
        "active": active
    }


@router.post("/characters/switch")
async def switch_char(name: str):
    """切换角色"""
    try:
        switch_character(name)
        return {"status": "ok", "active": name}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/characters/create")
async def create_char(request: CreateCharacterRequest):
    """创建新角色"""
    try:
        create_character(request.name, {
            "name": request.name,
            "avatar": request.avatar,
            "avatar_role": request.avatar_role,
            "body_type": request.body_type,
            "appearance": request.appearance,
            "identity": request.identity,
        })
        return {"status": "ok", "name": request.name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/characters/{name}/profile")
async def get_char_profile(name: str):
    """获取角色 profile"""
    try:
        return get_profile(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/characters/{name}/profile")
async def update_char_profile(name: str, updates: ProfileUpdate):
    """更新角色 profile"""
    try:
        from ..api.ws import momo_agent
        update_profile(name, updates.model_dump(exclude_none=True))
        # 清除 Agent 缓存，让下次对话使用最新的角色信息
        momo_agent.reload_system_prompt()
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/characters/{name}/identity")
async def get_char_identity(name: str):
    """获取角色 identity.md"""
    path = settings.get_character_dir(name) / "identity.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="identity.md 不存在")
    return {"content": path.read_text(encoding="utf-8")}


class IdentityUpdate(BaseModel):
    content: str


@router.put("/characters/{name}/identity")
async def update_char_identity(name: str, body: IdentityUpdate):
    """更新角色 identity.md"""
    path = settings.get_character_dir(name) / "identity.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.content, encoding="utf-8")
    return {"status": "ok"}


# ========== 记忆沉淀 ==========

@router.post("/memory/condense")
async def trigger_condensation(character: str = None, days: int = 1):
    """手动触发记忆沉淀"""
    from ..core.characters import get_active
    char = character or get_active()
    agent = MemoryAgent(llm_service)
    result = await agent.condense(char, days)
    return {"status": "ok", "character": char, "result": result}


@router.get("/memory/daily/{date_str}")
async def get_daily_memory(date_str: str, character: str = None):
    """获取指定日期的日记"""
    from ..core.characters import get_active
    char = character or get_active()
    path = settings.get_memory_dir(char) / f"{date_str}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="该日期无日记")
    return {"date": date_str, "content": path.read_text(encoding="utf-8")}


# ========== 应用状态 ==========

@router.get("/state")
async def get_app_state():
    """获取当前应用状态"""
    from ..core.characters import get_active
    from ..core.state import read_status, read_plans
    from ..core.context import load_soul, load_long_term
    char = get_active()

    return {
        "active_character": char,
        "has_soul": bool(load_soul(char)),
        "has_long_term": bool(load_long_term(char)),
        "has_status": bool(read_status(char)),
        "has_plans": bool(read_plans(char)),
    }
