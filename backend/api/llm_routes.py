"""
LLM 模型配置 API
"""

import logging

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..services.llm_profiles import load_profiles, save_profiles, switch_profile, get_active_profile

logger = logging.getLogger(__name__)
router = APIRouter()


class ProfileSwitch(BaseModel):
    name: str


@router.get("/profiles")
async def get_profiles():
    """获取所有模型配置（api_key 脱敏）"""
    data = load_profiles()
    # 脱敏
    safe = {"active": data.get("active"), "profiles": []}
    for p in data.get("profiles", []):
        sp = dict(p)
        if sp.get("api_key") and len(sp["api_key"]) > 8:
            sp["api_key"] = sp["api_key"][:4] + "***" + sp["api_key"][-4:]
        safe["profiles"].append(sp)
    return safe


@router.put("/profiles")
async def update_profiles(data: dict):
    """保存模型配置（含完整 api_key）"""
    save_profiles(data)
    # 重新加载当前激活的 profile
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


@router.get("/models")
async def fetch_models(base_url: str = Query(...), api_key: str = Query("")):
    """从 provider API 获取可用模型列表"""
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
