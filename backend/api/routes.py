"""REST API routes for settings, characters, memory, and chat history."""

import hashlib
import json
import logging
import re

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
from ..core.outfit_state import normalize_outfit_tags
from ..core.skin_mapping import search_skin_mappings

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
    initial_outfit_tags: list[str] | str | None = None
    initial_scene: dict = None


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
    user_profile: dict = None
    initial_outfit_tags: list[str] | str | None = None
    auto_generate_initial_outfit: bool = True
    initial_scene: dict = None


class OutfitGenerateRequest(BaseModel):
    display_name: str = ""
    identity: str = ""
    visual_anchor: dict = None
    skin_match: dict = None
    outfit_request: str = ""


@router.get("/skin-mapping/search")
async def search_skin_mapping(q: str = "", limit: int = 20):
    return {"results": search_skin_mappings(q, limit=limit)}


@router.post("/skin-mapping/outfit")
async def generate_skin_outfit(request: OutfitGenerateRequest):
    return await _generate_initial_outfit(
        request.display_name,
        request.visual_anchor or {},
        request.identity or "",
        request.skin_match or {},
        request.outfit_request or "",
    )


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
            "user_profile": request.user_profile,
            # Legacy field remains accepted but no longer seeds runtime state.
            "initial_outfit_tags": request.initial_outfit_tags or [],
            "initial_scene": request.initial_scene or {},
        })
        return {"status": "ok", "name": request.name}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _generate_initial_outfit(
    display_name: str,
    visual_anchor: dict,
    identity: str = "",
    skin_match: dict | None = None,
    outfit_request: str = "",
) -> dict:
    skin_match = skin_match or {}
    fallback = _fallback_outfit(display_name, visual_anchor, identity, skin_match)
    system = """You generate Stable Diffusion / Danbooru outfit tags for anime character initialization.
Return only JSON. The outfit must be safe for a normal first appearance, coherent, and not nude.
Use English lowercase tags with underscores. Do not include body, hair, eye, pose, scene, rating, or character name tags."""
    user = {
        "display_name": display_name,
        "identity": identity,
        "visual_anchor": visual_anchor,
        "matched_skin": skin_match,
        "user_outfit_request": outfit_request,
        "output_schema": {
            "outfit_tags": ["tag1", "tag2", "tag3"],
            "reason": "short Chinese reason",
        },
        "rules": [
            "Return 4 to 8 outfit/accessory tags.",
            "Tags should work as comma-separated Danbooru tags.",
            "Avoid explicit nudity and underwear-only outfits.",
            "If user_outfit_request is present, satisfy it while keeping tags coherent with the character.",
            "If user_outfit_request is empty, prefer a signature outfit that fits the character identity and visual style.",
        ],
    }
    try:
        raw = await llm_service.chat_prompt(system, json.dumps(user, ensure_ascii=False), temperature=0.7, max_tokens=512)
        data = _extract_json_object(raw)
        tags = _clean_outfit_tags(data.get("outfit_tags"))
        if tags:
            return {
                "outfit_tags": tags,
                "source": "ai",
                "reason": str(data.get("reason") or "").strip(),
            }
    except Exception as e:
        logger.warning("AI initial outfit generation failed, using fallback: %s", e)
    return {
        "outfit_tags": fallback,
        "source": "fallback",
        "reason": "AI 未返回可用服饰，已使用本地预设兜底。",
    }


def _extract_json_object(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except Exception:
            return {}


def _clean_outfit_tags(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        raw = re.split(r"[,\n]", value)
    elif isinstance(value, list):
        raw = value
    else:
        return []

    tags = []
    blocked = {
        "nude",
        "naked",
        "bare_body",
        "completely_nude",
        "topless",
        "bottomless",
        "no_bra",
        "no_panties",
    }
    for item in raw:
        tag = str(item).strip().lower().replace(" ", "_")
        tag = tag[1:].strip() if tag.startswith("-") else tag
        if not tag or tag in blocked:
            continue
        if any("\u4e00" <= ch <= "\u9fff" for ch in tag):
            continue
        if not re.fullmatch(r"[a-z0-9_:\-]+", tag):
            continue
        if len(tag) > 48:
            continue
        if tag not in tags:
            tags.append(tag)
    return normalize_outfit_tags(tags)[:10]


def _outfit_request_text(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _should_generate_outfit_from_request(text: str) -> bool:
    if any("\u4e00" <= ch <= "\u9fff" for ch in text):
        return True
    raw_items = [item.strip() for item in re.split(r"[,\n]", text) if item.strip()]
    if not raw_items:
        return False
    prose_words = {"a", "an", "the", "with", "and", "or", "in", "on", "for", "style", "wearing"}
    for item in raw_items:
        words = [word for word in item.lower().replace("_", " ").split() if word]
        if len(words) > 3 or any(word in prose_words for word in words):
            return True
    valid_tags = _clean_outfit_tags(text)
    return len(valid_tags) != len(raw_items)


def _fallback_outfit(display_name: str, visual_anchor: dict, identity: str, skin_match: dict) -> list[str]:
    presets = [
        ["casual_dress", "cardigan", "ankle_boots", "hair_ribbon"],
        ["sailor_uniform", "pleated_skirt", "loafers", "knee_socks"],
        ["oversized_hoodie", "shorts", "sneakers", "choker"],
        ["white_blouse", "high_waist_skirt", "mary_jane_shoes", "ribbon"],
        ["summer_dress", "sandals", "bracelet", "straw_hat"],
        ["black_dress", "high_heels", "pearl_necklace", "earrings"],
    ]
    seed = "|".join([
        display_name or "",
        json.dumps(visual_anchor or {}, ensure_ascii=False, sort_keys=True),
        identity or "",
        json.dumps(skin_match or {}, ensure_ascii=False, sort_keys=True),
    ])
    idx = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % len(presets)
    return presets[idx]


@router.delete("/characters/{name}")
async def delete_char(name: str):
    try:
        delete_character(name)
        return {"status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("删除角色失败: %s: %s", name, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"删除角色失败: {e}")


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


@router.get("/characters/{name}/soul")
async def get_char_soul(name: str):
    migrate_character_assets(name)
    path = settings.get_memory_dir(name) / "soul.md"
    if not path.exists():
        return {"content": ""}
    return {"content": path.read_text(encoding="utf-8")}


@router.put("/characters/{name}/soul")
async def update_char_soul(name: str, body: TextUpdate):
    migrate_character_assets(name)
    path = settings.get_memory_dir(name) / "soul.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.content, encoding="utf-8")
    return {"status": "ok"}


@router.post("/memory/condense")
async def trigger_condensation(character: str = None, days: int = 1, target: str = "all"):
    char = character or get_active()
    agent = MemoryAgent(llm_service)
    result = await agent.condense(char, days, target=target)
    from ..core.memory_policy import mark_condense_failed, reset_condense_counter

    normalized = "long_term" if target in ("memory", "long-term", "longterm") else target
    if normalized == "long_term":
        has_update = bool(isinstance(result, dict) and (result.get("long_term") or "").strip())
    elif normalized == "soul":
        has_update = bool(isinstance(result, dict) and (result.get("soul") or "").strip())
    else:
        has_update = bool(
            isinstance(result, dict)
            and ((result.get("soul") or "").strip() or (result.get("long_term") or "").strip())
        )
    if has_update:
        reset_condense_counter(char, trigger="manual_api", target=target)
        status = "ok"
    else:
        mark_condense_failed(char, trigger="manual_api", error="empty_result", target=target)
        status = "empty"
    return {"status": status, "character": char, "result": result}


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
    from ..core.state import read_status
    char = get_active()
    return {
        "active_character": char,
        "has_soul": bool(load_soul(char)),
        "has_long_term": bool(load_long_term(char)),
        "has_status": bool(read_status(char)),
    }
