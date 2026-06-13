"""
AI 女友 — FastAPI 应用入口
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.config import settings

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("🚀 启动 AI 女友应用...")

    # 确保数据目录存在
    for dir_path in [settings.data_dir, settings.memory_dir]:
        dir_path.mkdir(parents=True, exist_ok=True)

    logger.info("✅ 应用初始化完成")

    yield

    logger.info("👋 应用关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="AI 女友",
    description="沉浸式 AI 伴侣 — 聊天、图像生成、语音对话",
    version="2.0.0",
    lifespan=lifespan
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.server.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 健康检查端点
@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "version": "2.0.0"
    }


# 路由注册
from .api import image, routes, llm_routes
app.include_router(routes.router, prefix="/api", tags=["设置 & 角色"])
app.include_router(image.router, prefix="/api/image", tags=["图像"])
app.include_router(llm_routes.router, prefix="/api/llm", tags=["LLM 模型"])

# WebSocket 路由
from .api import ws
app.include_router(ws.router, tags=["WebSocket"])

# 静态文件服务 — 生成的图片
settings.data_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(settings.data_dir)), name="static")

# 静态文件服务（前端 build）
frontend_dir = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.server.host,
        port=settings.server.port,
        reload=settings.server.reload
    )
