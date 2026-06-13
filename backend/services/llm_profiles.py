"""
LLM 模型配置管理
支持多个模型配置文件的增删改查和切换
"""

import json
import logging
from pathlib import Path
from typing import Optional

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

PROFILES_FILE = settings.config_dir / "llm_profiles.json"


def _fetch_models_from_api(base_url: str, api_key: str) -> list[str]:
    """从 provider API 获取真实模型列表"""
    try:
        url = base_url.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        r = httpx.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        models = [m.get("id", "") for m in data.get("data", [])]
        return sorted(models)
    except Exception as e:
        logger.warning(f"获取模型列表失败: {e}")
        return []


def _migrate_from_env() -> dict:
    """首次运行：从 .env 迁移"""
    return {
        "name": "default",
        "provider": "minimax" if "minimax" in settings.llm.base_url else "custom",
        "model": settings.llm.model,
        "base_url": settings.llm.base_url,
        "api_key": settings.llm.api_key,
        "temperature": settings.llm.temperature,
        "max_tokens": settings.llm.max_tokens,
    }


def load_profiles() -> dict:
    """加载所有配置"""
    if PROFILES_FILE.exists():
        try:
            data = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
            # 检查是否还是占位名，尝试刷新
            return data
        except Exception:
            logger.warning("llm_profiles.json 损坏，重建")

    env_profile = _migrate_from_env()
    data = {"active": env_profile["name"], "profiles": [env_profile]}
    save_profiles(data)
    logger.info(f"已创建 llm_profiles.json")
    return data


def save_profiles(data: dict):
    PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_active_profile() -> dict:
    data = load_profiles()
    active_name = data.get("active", "")
    for p in data.get("profiles", []):
        if p["name"] == active_name:
            return p
    if data["profiles"]:
        return data["profiles"][0]
    return {}


def switch_profile(name: str):
    data = load_profiles()
    names = {p["name"] for p in data.get("profiles", [])}
    if name not in names:
        raise ValueError(f"模型 '{name}' 不存在")
    data["active"] = name
    save_profiles(data)
    logger.info(f"已切换到模型: {name}")
    from .llm import llm_service
    llm_service.reload_from_profile()
