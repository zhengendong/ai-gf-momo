# AI GF Momo — 智能女友小桃

沉浸式 AI 女友，支持聊天、生图、状态管理、多角色、多模型切换。

## 架构

```
前端 Vue 3 (Vite) ←→ 后端 FastAPI (WebSocket + REST) ←→ LLM (MiniMax/DeepSeek) + ComfyUI
```

## 启动

```bash
# 后端
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000

# 前端
cd frontend
npm install
npm run dev
```

## 功能

- **实时聊天** — WebSocket 流式对话，LLM 驱动
- **AI 生图** — 接 ComfyUI，WaiNSFWIllustrious 模型
- **智能拍照** — LLM 自主判断拍照时机，自动拼 Danbooru 标签
- **多模型** — 前端切换 MiniMax / DeepSeek 等，API key 后端管理
- **多角色** — 目录名隔离，config/characters/{name}/ + memory/{name}/
- **状态管理** — 穿着/场景/心情存 status.md，LLM 自主维护
- **图片历史** — 持久化，按角色分组，左右翻阅

## 目录结构

```
config/
  agent.md              # LLM system prompt
  tag_reference.md      # SD 标签速查
  characters/{name}/    # 角色固定设定 (identity.md, profile.json)
memory/{name}/          # 角色运行时状态 (status.md, plans.md, soul.md, long_term.md)
data/{name}/images/     # 生成的图片 + _history.json
backend/                # FastAPI 后端
frontend/               # Vue 3 前端
```

## 配置

复制 `.env.example` 为 `.env`，填 LLM API key。首次启动自动从 `.env` 创建 `config/llm_profiles.json`。

## 依赖

- LLM: MiniMax / DeepSeek API
- 生图: ComfyUI（本地 Windows，默认 localhost:8188）
