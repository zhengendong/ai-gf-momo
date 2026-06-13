# AI_gf_momo — 智能女友小桃

前后端分离的 Windows 本地应用。通过浏览器访问，与 AI 女友小桃聊天。

## 架构概览

```
浏览器 ──→ 前端 (localhost:3000)     ← 纯静态 HTML/JS
                │
                ↓ HTTP/WebSocket
           后端 (localhost:8000)     ← Python FastAPI
                │
     ┌──────────┼──────────┐
     ↓          ↓          ↓
  LLM API    ComfyUI   文件系统
  (DeepSeek) (本地)   (identity/long_term/live_state)
```

## 目录结构

```
D:\workspace\AI_gf_momo\
├── backend\
│   ├── main.py              # FastAPI 入口
│   ├── api\
│   │   ├── chat.py          # 聊天接口 (POST /chat, WS /ws)
│   │   └── photo.py         # 生图接口 (POST /photo)
│   ├── core\
│   │   ├── character.py     # 角色注入 (identity.md + long_term.md)
│   │   ├── state.py         # live_state 读写
│   │   └── memory.py        # 记忆流水线调度
│   └── services\
│       ├── llm.py           # DeepSeek API 封装
│       └── comfyui.py       # ComfyUI 调用 (直连，无需 WSL 桥接)
├── frontend\
│   ├── index.html           # 聊天主页面
│   ├── css\
│   │   └── chat.css
│   ├── js\
│   │   ├── chat.js          # 消息收发/渲染
│   │   └── photo.js         # 图片显示
│   └── assets\
├── config\
│   ├── character\
│   │   ├── identity.md      # 从现有 girlfriend/identity.md 复制
│   │   └── long_term.md     # 从现有 girlfriend/memory/long_term.md 复制
│   ├── live_state.json      # 从现有 live_state.json 复制
│   └── settings.yaml        # API keys / ComfyUI 地址等
├── scripts\
│   └── memory_pipeline.py   # 记忆采集流水线 (简化版，Windows 原生)
└── docs\
    └── ARCHITECTURE.md      # 本文件
```

## 核心流程

### 聊天流程

```
用户输入 → 后端 /chat
  ├── 1. 读 identity.md + long_term.md → system prompt
  ├── 2. 读 live_state.json → 追加当前状态到 prompt
  ├── 3. 调 DeepSeek API (streaming)
  ├── 4. LLM 回复中检测生图意图 → 触发 /photo
  └── 5. 流式返回文本 + 图片 URL
```

### 生图流程

```
LLM 决定生图 → 后端 /photo
  ├── 1. 读 live_state.json
  ├── 2. 调用 momo_photo.py 兼容逻辑 (直接 import 或复制核心函数)
  ├── 3. 拼装 prompt → 调 ComfyUI API (localhost:8188)
  └── 4. 返回图片路径 → 前端渲染
```

### 记忆流水线 (每日 0:00)

```
Cron / 计划任务 → scripts/memory_pipeline.py
  ├── Step 1: 从聊天记录提取原始对话 → row_session/{date}.md
  ├── Step 2: AI 分析 → short_term/{date}.md
  └── Step 3: 读连续 5 天 short_term → 更新 long_term.md
```

## 技术选型

| 层 | 选型 | 理由 |
|------|------|------|
| 前端 | 原生 HTML/CSS/JS | 无框架依赖，聊天 UI 够用 |
| 后端 | Python FastAPI | 轻量，可直接复用现有 Python 代码 |
| LLM | DeepSeek API | 当前在用，直接延续 |
| 生图 | ComfyUI (本地 Windows) | 已有工作流，直连无 WSL 开销 |
| 实时通信 | SSE (Server-Sent Events) | 比 WebSocket 简单，流式文本够用 |
| 存储 | 文件系统 (JSON/MD) | 延续现有设计，零依赖 |

## 与现有 Hermes 体系的关系

| Hermes 体系 | AI_gf_momo | 说明 |
|-------------|-----------|------|
| gf-core / identity / long_term | ✅ 直接复用 | 复制文件到 config/ |
| live_state.json | ✅ 直接复用 | 复制到 config/ |
| momo_photo.py | ✅ 逻辑复用 | 核心函数复制到 services/comfyui.py，Windows 直连 |
| memory 流水线 | ✅ 设计复用 | 简化版，不依赖 Hermes session 格式 |
| Hermes Agent 运行时 | ❌ 不需要 | 自己写 FastAPI 后端 |
| WSL/PowerShell 桥接 | ❌ 不再需要 | Windows 原生直连 ComfyUI |

## 开发路径

### Phase 1：最小可用 (1-2 天)

- [ ] 后端 FastAPI 骨架 (main.py + 基本路由)
- [ ] DeepSeek API 调用 (流式 SSE)
- [ ] 角色注入 (identity + long_term → system prompt)
- [ ] 前端聊天 UI (输入框 + 消息列表 + SSE 流式显示)

### Phase 2：生图集成 (1 天)

- [ ] ComfyUI 直连 (从 momo_photo.py 移植核心逻辑)
- [ ] 前端图片显示
- [ ] live_state 读写

### Phase 3：记忆系统 (1-2 天)

- [ ] 聊天记录存储格式设计
- [ ] 记忆流水线脚本 (Step 1/2/3)
- [ ] Cron 调度 (Windows 计划任务)

### Phase 4：完善 (按需)

- [ ] intimacy_mode 切换
- [ ] TTS 语音
- [ ] 多轮记忆管理
- [ ] 前端美化

## 配置示例 (config/settings.yaml)

```yaml
llm:
  provider: deepseek
  api_key: "sk-xxx"
  model: deepseek-chat
  base_url: https://api.deepseek.com/v1

comfyui:
  host: 127.0.0.1
  port: 8188

server:
  host: 127.0.0.1
  port: 8000
```
