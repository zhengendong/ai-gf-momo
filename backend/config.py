"""
配置管理模块
使用 Pydantic Settings 管理应用配置
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录
BASE_DIR = Path(__file__).parent.parent


class LLMConfig(BaseSettings):
    """LLM 服务配置"""
    api_key: str = Field(default="", description="API 密钥")
    model: str = Field(default="deepseek-chat", description="模型名称")
    base_url: str = Field(default="https://api.deepseek.com/v1", description="API 基础 URL")
    temperature: float = Field(default=0.8, description="生成温度")
    max_tokens: int = Field(default=2048, description="最大生成长度")

    model_config = SettingsConfigDict(env_prefix="LLM_", env_file=".env", extra="ignore")


class ComfyUIConfig(BaseSettings):
    """ComfyUI 配置"""
    host: str = Field(default="127.0.0.1", description="ComfyUI 主机")
    port: int = Field(default=8188, description="ComfyUI 端口")
    checkpoint: str = Field(default="waiNSFWIllustrious_v140.safetensors", description="默认模型 checkpoint")
    sampler: str = Field(default="euler", description="采样器")
    scheduler: str = Field(default="simple", description="调度器")
    steps: int = Field(default=20, description="采样步数")
    cfg: float = Field(default=5.0, description="CFG scale")
    width: int = Field(default=1024, description="默认图片宽度")
    height: int = Field(default=1024, description="默认图片高度")

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    model_config = SettingsConfigDict(env_prefix="COMFYUI_", env_file=".env", extra="ignore")


class ServerConfig(BaseSettings):
    """服务器配置"""
    host: str = Field(default="0.0.0.0", description="服务器主机")
    port: int = Field(default=8000, description="服务器端口")
    reload: bool = Field(default=True, description="开发模式自动重载")
    cors_origins: list[str] = Field(default=["http://localhost:5173", "http://localhost:3000"], description="CORS 允许的来源")

    model_config = SettingsConfigDict(env_prefix="SERVER_", env_file=".env", extra="ignore")


class AppConfig(BaseSettings):
    """应用总配置"""
    llm: LLMConfig = Field(default_factory=LLMConfig)
    comfyui: ComfyUIConfig = Field(default_factory=ComfyUIConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)

    # 应用路径
    base_dir: Path = Field(default_factory=lambda: BASE_DIR, description="项目根目录")

    @property
    def config_dir(self) -> Path:
        return self.base_dir / "config"

    @property
    def characters_dir(self) -> Path:
        return self.base_dir / "characters"

    @property
    def legacy_characters_dir(self) -> Path:
        return self.config_dir / "characters"

    @property
    def memory_dir(self) -> Path:
        return self.base_dir / "characters"

    @property
    def legacy_memory_dir(self) -> Path:
        return self.base_dir / "memory"

    @property
    def data_dir(self) -> Path:
        return self.base_dir / "data"

    @property
    def legacy_data_dir(self) -> Path:
        return self.base_dir / "data"

    @property
    def static_dir(self) -> Path:
        return self.characters_dir

    def get_images_dir(self, name: str) -> Path:
        return self.get_character_dir(name) / "images"

    @property
    def settings_file(self) -> Path:
        return self.config_dir / "settings.json"

    @property
    def agent_file(self) -> Path:
        return self.config_dir / "agent.md"

    def get_character_dir(self, name: str) -> Path:
        return self.characters_dir / name

    def get_memory_dir(self, name: str) -> Path:
        return self.get_character_dir(name) / "memory"

    def get_vector_dir(self, name: str) -> Path:
        return self.get_character_dir(name) / "vector" / "chroma_db"

    @property
    def provider_keys_file(self) -> Path:
        return self.config_dir / "provider_keys.json"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# 全局配置实例
settings = AppConfig()
