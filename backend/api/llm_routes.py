"""
LLM 模型配置 API

密钥与 profile 分离：
- /profiles — 不含 api_key
- /providers — 管理 provider 级别的 API key
"""

import logging

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..services.llm_profiles import (
    load_profiles,
    save_profiles,
    switch_profile,
    get_active_profile,
    get_provider_key,
    set_provider_key,
    list_providers,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ProfileSwitch(BaseModel):
    name: str


class ProviderKeyBody(BaseModel):
    key: str


# ========== Profiles ==========

@router.get("/profiles")
async def get_profiles():
    """获取所有模型配置（不含 api_key）"""
    data = load_profiles()
    safe = {"active": data.get("active"), "profiles": []}
    for p in data.get("profiles", []):
        sp = {k: v for k, v in p.items() if k != "api_key"}
        safe["profiles"].append(sp)
    return safe


@router.put("/profiles")
async def update_profiles(data: dict):
    """保存模型配置（前端不传 api_key，后端从 provider 存储注入）"""
    incoming_profiles = data.get("profiles", [])

    # 防御：strip 前端可能传入的 api_key
    for p in incoming_profiles:
        p.pop("api_key", None)

    merged = {
        "active": data.get("active", ""),
        "profiles": incoming_profiles,
    }
    save_profiles(merged)

    from ..services.llm import llm_service
    llm_service.reload_from_profile()
    return {"status": "ok"}


@router.put("/profiles/active")
async def set_active_profile(body: ProfileSwitch):
    """切换激活的模型"""
    try:
        switch_profile(body.name)
        return {"status": "ok", "active": body.name}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ========== Providers ==========

@router.get("/providers")
async def get_providers():
    """列出所有已配置的 provider（不返回密钥值，只返回是否已设置）"""
    return {"providers": list_providers()}


@router.put("/providers/{provider}/key")
async def set_key(provider: str, body: ProviderKeyBody):
    """设置/更新 provider 的 API key"""
    set_provider_key(provider, body.key)
    from ..services.llm import llm_service
    llm_service.reload_from_profile()
    return {"status": "ok"}


# ========== Models ==========

@router.get("/models")
async def fetch_models(base_url: str = Query(...), provider: str = Query("")):
    """从 provider API 获取可用模型列表（密钥后端查，不经过前端）"""
    api_key = get_provider_key(provider) if provider else ""
    try:
        url = base_url.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
            models = [m.get("id", "") for m in data.get("data", [])]
            return {"models": sorted(models)}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"获取模型列表失败: {e}")
