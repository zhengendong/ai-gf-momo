"""
LLM 服务模块
封装 OpenAI 兼容 API 调用（支持 Minimax / DeepSeek / OpenAI）
"""

import json
import logging
from typing import AsyncGenerator, Optional

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


class LLMService:
    """LLM 服务"""

    def __init__(self):
        self.api_key = ""
        self.model = ""
        self.base_url = ""
        self.temperature = 0.8
        self.max_tokens = 2048
        self._client: Optional[httpx.AsyncClient] = None
        self.reload_from_profile()

    def reload_from_profile(self):
        """从 llm_profiles.json 重新加载当前激活的配置"""
        try:
            from .llm_profiles import get_active_profile
            profile = get_active_profile()
            self.api_key = profile.get("api_key", "")
            self.model = profile.get("model", "")
            self.base_url = profile.get("base_url", "")
            self.temperature = profile.get("temperature", 0.8)
            self.max_tokens = profile.get("max_tokens", 2048)
            self._client = None
            logger.info(f"LLMService 已加载: {profile.get('name')} model={self.model} url={self.base_url}")
        except Exception as e:
            logger.error(f"加载 profile 失败: {e}", exc_info=True)
            self.api_key = settings.llm.api_key
            self.model = settings.llm.model
            self.base_url = settings.llm.base_url
            self.temperature = settings.llm.temperature
            self.max_tokens = settings.llm.max_tokens
            logger.info(f"LLMService 回退 env: model={self.model} url={self.base_url}")
    
    async def _get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                timeout=120.0
            )
        return self._client
    
    async def chat_prompt(
        self,
        system: str,
        user: str,
        temperature: float = None,
        max_tokens: int = None
    ) -> str:
        """使用 system + user 字符串的便捷聊天接口"""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        return await self.chat(messages, temperature, max_tokens)

    async def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = None,
        max_tokens: int = None
    ) -> str:
        """聊天补全（非流式）"""
        client = await self._get_client()
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature or self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }
        
        try:
            response = await client.post("/chat/completions", json=payload)
            response.raise_for_status()
            
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            
            logger.info(f"LLM 聊天完成: model={self.model}")
            return content
            
        except httpx.HTTPStatusError as e:
            body = e.response.text[:500]
            logger.error(f"LLM API {e.response.status_code}: {body}")
            if e.response.status_code == 422:
                from ..core.compressor import estimate_tokens
                prompt_text = json.dumps(payload, ensure_ascii=False)
                logger.error(f"422 请求大小: {len(prompt_text)} 字符 ~{estimate_tokens(prompt_text)} tokens")
            raise
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            raise
    
    async def chat_stream(
        self,
        messages: list[dict[str, str]],
        temperature: float = None,
        max_tokens: int = None
    ) -> AsyncGenerator[str, None]:
        """聊天补全（流式）- 带自动降级到非流式"""
        client = await self._get_client()
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature or self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": True
        }
        
        try:
            async with client.stream("POST", "/chat/completions", json=payload) as response:
                response.raise_for_status()
                
                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        
                        if not line:
                            continue
                        
                        if line.startswith("data: "):
                            data_str = line[6:]
                            
                            if data_str == "[DONE]":
                                return
                            
                            try:
                                data = json.loads(data_str)
                                choices = data.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    content = delta.get("content", "")
                                    if content:
                                        yield content
                            except json.JSONDecodeError:
                                continue
            
            logger.info(f"LLM 流式聊天完成: model={self.model}")
            
        except httpx.HTTPStatusError as e:
            logger.warning(f"流式请求失败，降级到非流式: {e.response.status_code}")
            content = await self.chat(messages, temperature, max_tokens)
            yield content
        except Exception as e:
            logger.warning(f"流式请求异常，降级到非流式: {e}")
            content = await self.chat(messages, temperature, max_tokens)
            yield content
    
    async def close(self):
        """关闭客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# 全局 LLM 服务实例
llm_service = LLMService()
