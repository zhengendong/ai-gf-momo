"""
TTS 语音服务模块
封装 Minimax TTS MCP 调用
"""

import logging
import uuid
from pathlib import Path
from typing import Optional

import httpx

from ..config import settings

logger = logging.getLogger(__name__)


class TTSService:
    """TTS 语音服务"""
    
    def __init__(self):
        self.api_key = settings.tts.api_key
        self.group_id = settings.tts.group_id
        self.model = settings.tts.model
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url="https://api.minimax.chat",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                timeout=30.0
            )
        return self._client
    
    async def text_to_speech(
        self,
        text: str,
        voice_id: str = None,
        speed: float = 1.0,
        volume: float = 1.0
    ) -> Optional[str]:
        """
        文本转语音
        
        Args:
            text: 要转换的文本
            voice_id: 语音ID（可选）
            speed: 语速（0.5-2.0）
            volume: 音量（0.5-2.0）
        
        Returns:
            生成的音频文件路径
        """
        client = await self._get_client()
        
        # 构建请求体
        payload = {
            "model": self.model,
            "text": text,
            "stream": False,
            "voice_setting": {
                "voice_id": voice_id or "momo",
                "speed": speed,
                "vol": volume,
                "pitch": 0
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3"
            }
        }
        
        try:
            # 构建请求URL（Group ID可选）
            url = "/v1/t2a_v2"
            if self.group_id:
                url = f"{url}?GroupId={self.group_id}"
            
            response = await client.post(
                url,
                json=payload
            )
            response.raise_for_status()
            
            data = response.json()
            
            if data.get("base_resp", {}).get("status_code") != 0:
                logger.error(f"TTS API 错误: {data}")
                return None
            
            # 提取音频数据（Base64编码）
            audio_data = data.get("data", {}).get("audio")
            if not audio_data:
                logger.error("未获取到音频数据")
                return None
            
            # 解码并保存
            import base64
            audio_bytes = base64.b64decode(audio_data)
            
            # 保存到文件
            filename = f"tts_{uuid.uuid4().hex[:8]}.mp3"
            audio_path = settings.data_dir / "tts" / filename
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(audio_path, "wb") as f:
                f.write(audio_bytes)
            
            logger.info(f"TTS 音频已生成: {audio_path}")
            return str(audio_path)
            
        except httpx.HTTPStatusError as e:
            logger.error(f"TTS API 错误: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"TTS 调用失败: {e}")
            return None
    
    async def speech_to_text(
        self,
        audio_path: str,
        language: str = "zh"
    ) -> Optional[str]:
        """
        语音转文本（可选功能）
        
        Args:
            audio_path: 音频文件路径
            language: 语言
        
        Returns:
            识别的文本
        """
        # 这里可以集成 Minimax 的 STT 服务
        # 暂时返回 None
        logger.warning("STT 功能暂未实现")
        return None
    
    async def close(self):
        """关闭客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# 全局 TTS 服务实例
tts_service = TTSService()
