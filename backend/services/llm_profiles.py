"""
LLM 模型配置管理
支持多个模型配置文件的增删改查和切换

密钥与 profile 分离：
- llm_profiles.json：只保存模型配置，不保存 api_key
- provider_keys.json：按 provider 名存 api_key（后端专属，不传前端）
- get_active_profile() 从 provider_keys.json 按 provider 注入 key
"""

import json
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

PROFILES_FILE = settings.config_dir / "llm_profiles.json"
PROVIDER_KEYS_FILE = settings.config_dir / "provider_keys.json"


# ========== Provider 密钥存储 ==========

def load_provider_keys() -> dict:
    """加载所有 provider 的 API key"""
    if PROVIDER_KEYS_FILE.exists():
        try:
            return json.loads(PROVIDER_KEYS_FILE.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("provider_keys.json 损坏，重建")
    return {}


def save_provider_keys(data: dict):
    """保存 provider 密钥"""
    PROVIDER_KEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROVIDER_KEYS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_provider_key(provider: str) -> str:
    """获取指定 provider 的 API key，不存在返回空字符串"""
    if not provider:
        return ""
    return load_provider_keys().get(provider, "")


def set_provider_key(provider: str, key: str):
    """设置/更新 provider 的 API key，空字符串则删除"""
    if not provider:
        return
    data = load_provider_keys()
    key = key.strip()
    if key:
        data[provider] = key
    elif provider in data:
        del data[provider]
    save_provider_keys(data)
    logger.info(f"已{'更新' if key else '删除'} provider '{provider}' 的 API key")


def _strip_profile_api_keys(data: dict) -> bool:
    """Remove api_key fields from profile data before it is persisted."""
    changed = False
    for profile in data.get("profiles", []):
        if "api_key" in profile:
            profile.pop("api_key", None)
            changed = True
    return changed


# ========== Profile CRUD ==========

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


def _infer_provider_from_url(base_url: str) -> str:
    """从 base_url 域名推断 provider 名"""
    if not base_url:
        return ""
    try:
        host = urlparse(base_url).hostname or ""
        for segment in host.split("."):
            if segment in ("api", "www", "com", "cn", "v1"):
                continue
            return segment
    except Exception:
        pass
    return ""


def _migrate_api_keys_to_provider_store():
    """
    一次性迁移：把 profile 中的 api_key 提取到 provider_keys.json。
    provider_keys.json 中已有的 key 不会被覆盖。
    profile 中的 api_key 会被删除，避免再次传给前端或落回配置。
    """
    if not PROFILES_FILE.exists():
        return

    try:
        data = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return

    profiles = data.get("profiles", [])
    if not profiles:
        return

    provider_keys = load_provider_keys()  # 保留已有的
    changed = False
    migrated = 0

    for p in profiles:
        provider = p.get("provider", "").strip()
        key = p.get("api_key", "").strip()

        if not key or "***" in key:
            if "api_key" in p:
                p.pop("api_key", None)
                changed = True
            continue

        if not provider:
            provider = _infer_provider_from_url(p.get("base_url", ""))
            if not provider:
                continue
            p["provider"] = provider
            changed = True
            logger.info(f"已推断 provider: '{provider}' (from {p.get('base_url')})")

        if provider not in provider_keys:
            provider_keys[provider] = key
            migrated += 1

        p.pop("api_key", None)
        changed = True

    if migrated > 0:
        save_provider_keys(provider_keys)
        logger.info(f"已迁移 {migrated} 个 provider 密钥到 provider_keys.json")

    if changed:
        # 写回 profile（删除 api_key，并可能修正空 provider 名）
        save_profiles(data)


def _migrate_from_env() -> dict:
    """首次运行：从 .env 迁移（不再包含 api_key）"""
    return {
        "name": "default",
        "provider": "minimax" if "minimax" in settings.llm.base_url else "custom",
        "model": settings.llm.model,
        "base_url": settings.llm.base_url,
        "temperature": settings.llm.temperature,
        "max_tokens": settings.llm.max_tokens,
    }


def load_profiles() -> dict:
    """加载所有配置"""
    if PROFILES_FILE.exists():
        try:
            data = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
            return data
        except Exception:
            logger.warning("llm_profiles.json 损坏，重建")

    env_profile = _migrate_from_env()
    data = {"active": env_profile["name"], "profiles": [env_profile]}
    save_profiles(data)
    logger.info("已创建 llm_profiles.json")
    return data


def save_profiles(data: dict):
    """保存 profile 配置"""
    # 防御：profile 配置不落盘 api_key，密钥只进入 provider_keys.json。
    _strip_profile_api_keys(data)
    PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILES_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_active_profile() -> dict:
    """获取当前激活的 profile。

    从 provider_keys.json 注入 api_key；profile 文件自身不保存 key。
    """
    data = load_profiles()
    active_name = data.get("active", "")
    profiles = data.get("profiles", [])

    profile = {}
    for p in profiles:
        if p["name"] == active_name:
            profile = dict(p)
            break
    if not profile and profiles:
        profile = dict(profiles[0])

    if not profile:
        return {}

    # 从 provider 存储注入 api_key（优先于 profile 自身的 key）
    provider = profile.get("provider", "")
    provider_key = get_provider_key(provider)
    if provider_key:
        profile["api_key"] = provider_key

    return profile


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


def list_providers() -> list[dict]:
    """列出所有已知 provider 及是否已配置密钥"""
    keys = load_provider_keys()
    profiles = load_profiles().get("profiles", [])
    seen = set()
    result = []
    for p in profiles:
        provider = p.get("provider", "").strip()
        if not provider or provider in seen:
            continue
        seen.add(provider)
        result.append({
            "name": provider,
            "has_key": bool(keys.get(provider, "").strip()),
        })
    for provider in keys:
        if provider not in seen:
            result.append({"name": provider, "has_key": True})
    return result
