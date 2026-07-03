"""REST API routes for settings, characters, memory, and chat history."""

import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agents.memory import MemoryAgent
from ..config import settings
from ..core.characters import (
    clear_character_records,
    create_character,
    delete_character,
    get_active,
    get_profile,
    list_characters,
    migrate_character_assets,
    reset_character_memory,
    switch_character,
    update_profile,
)
from ..services.llm import llm_service

logger = logging.getLogger(__name__)
router = APIRouter()


class SettingsUpdate(BaseModel):
    active_character: str = None
    context: dict = None
    comfyui: dict = None
    heartbeat: dict = None
    memory: dict = None


@router.get("/settings")
async def get_settings():
    path = settings.settings_file
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


@router.put("/settings")
async def update_settings(updates: SettingsUpdate):
    path = settings.settings_file
    current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for key, val in updates.model_dump(exclude_none=True).items():
        if val is not None:
            current[key] = val
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return current


class ProfileUpdate(BaseModel):
    name: str = None
    gender: str = None
    avatar: str = None
    avatar_role: str = None
    body_type: str = None
    appearance: str = None
    visual_anchor: dict = None


class CreateCharacterRequest(BaseModel):
    name: str
    display_name: str = None
    gender: str = "female"
    avatar: str = "💕"
    avatar_role: str = ""
    body_type: str = ""
    appearance: str = ""
    visual_anchor: dict = None
    identity: str = ""


@router.get("/characters")
async def get_characters():
    return {"characters": list_characters(), "active": get_active()}


@router.post("/characters/switch")
async def switch_char(name: str):
    try:
        switch_character(name)
        return {"status": "ok", "active": name}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/characters/create")
async def create_char(request: CreateCharacterRequest):
    try:
        visual_anchor = request.visual_anchor or {
            "role_tags": request.avatar_role,
            "body_tags": request.body_type,
            "appearance_tags": request.appearance,
        }
        # 皮肤信息只落 visual_anchor（profile.json 里只有这一份真相）。
        # avatar_role / body_type / appearance / gender 都不再回写到 profile.json 顶层。
        create_character(request.name, {
            "name": request.display_name or request.name,
            "gender": request.gender,
            "avatar": request.avatar,
            "visual_anchor": visual_anchor,
            "identity": request.identity,
        })
        return {"status": "ok", "name": request.name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/characters/{name}")
async def delete_char(name: str):
    try:
        delete_character(name)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/characters/{name}/records")
async def clear_char_records(name: str):
    try:
        clear_character_records(name)
        from ..api.image import _histories
        from ..api.ws import chat_history_buffer
        _histories.pop(name, None)
        chat_history_buffer.clear()
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/characters/{name}/profile")
async def get_char_profile(name: str):
    try:
        return get_profile(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/characters/{name}/profile")
async def update_char_profile(name: str, updates: ProfileUpdate):
    try:
        update_profile(name, updates.model_dump(exclude_none=True))
        from ..api.ws import momo_agent
        momo_agent.reload_system_prompt(name)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/characters/{name}/identity")
async def get_char_identity(name: str):
    migrate_character_assets(name)
    path = settings.get_character_dir(name) / "identity.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="identity.md 不存在")
    return {"content": path.read_text(encoding="utf-8")}


class TextUpdate(BaseModel):
    content: str


@router.put("/characters/{name}/identity")
async def update_char_identity(name: str, body: TextUpdate):
    migrate_character_assets(name)
    path = settings.get_character_dir(name) / "identity.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.content, encoding="utf-8")
    return {"status": "ok"}


@router.get("/characters/{name}/chat-history")
async def get_char_chat_history(name: str, limit: int = 500):
    try:
        from ..core.chat_history import read_chat_history
        return {"messages": read_chat_history(name, limit=limit)}
    except Exception as e:
        logger.error("读取聊天记录失败: %s", e)
        return {"messages": []}


class UserProfileUpdate(BaseModel):
    user_pet_name: str = None
    identity: str = None
    communication_style: str = None
    notes: str = None


@router.get("/characters/{name}/user-profile")
async def get_char_user_profile(name: str):
    from ..core.memory_v3 import load_user_profile
    return load_user_profile(name)


@router.put("/characters/{name}/user-profile")
async def update_char_user_profile(name: str, body: UserProfileUpdate):
    from ..core.memory_v3 import save_user_profile
    return save_user_profile(name, body.model_dump(exclude_none=True))


@router.get("/characters/{name}/long-term")
async def get_char_long_term(name: str):
    migrate_character_assets(name)
    path = settings.get_memory_dir(name) / "long_term.md"
    if not path.exists():
        return {"content": ""}
    return {"content": path.read_text(encoding="utf-8")}


@router.put("/characters/{name}/long-term")
async def update_char_long_term(name: str, body: TextUpdate):
    migrate_character_assets(name)
    path = settings.get_memory_dir(name) / "long_term.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.content, encoding="utf-8")
    return {"status": "ok"}


@router.post("/memory/condense")
async def trigger_condensation(character: str = None, days: int = 1):
    char = character or get_active()
    agent = MemoryAgent(llm_service)
    result = await agent.condense(char, days)
    from ..core.memory_policy import reset_condense_counter
    reset_condense_counter(char, trigger="manual_api")
    return {"status": "ok", "character": char, "result": result}


@router.get("/memory/status")
async def get_memory_status(character: str = None):
    char = character or get_active()
    from ..core.memory_policy import load_runtime_state, memory_settings
    return {
        "character": char,
        "settings": memory_settings(),
        "runtime": load_runtime_state(char),
    }


@router.get("/memory/daily/{date_str}")
async def get_daily_memory(date_str: str, character: str = None):
    char = character or get_active()
    migrate_character_assets(char)
    path = settings.get_memory_dir(char) / f"{date_str}.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="该日期无日记")
    return {"date": date_str, "content": path.read_text(encoding="utf-8")}


@router.post("/characters/{name}/memory/reset")
async def reset_char_memory(name: str):
    try:
        reset_character_memory(name)
        from ..api.image import _histories
        from ..api.ws import chat_history_buffer
        _histories.pop(name, None)
        chat_history_buffer.clear()
        return {"status": "ok", "character": name}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/state")
async def get_app_state():
    from ..core.context import load_long_term, load_soul
    from ..core.state import read_plans, read_status
    char = get_active()
    return {
        "active_character": char,
        "has_soul": bool(load_soul(char)),
        "has_long_term": bool(load_long_term(char)),
        "has_status": bool(read_status(char)),
        "has_plans": bool(read_plans(char)),
    }
