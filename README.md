# AI GF Momo — 沉浸式 AI 女友

一个本地运行的 AI 女友系统：Web 对话 + 自动生图 + 持久记忆 + 多角色 + 多模型切换。
每个角色都有独立身份、长期记忆、当前状态和向量索引，互不串戏。

## 架构

```
浏览器 (Vue 3 + Vite)
    │
    ├── HTTP/REST  ── 图片、设置、状态、历史
    └── WebSocket  ── 流式对话
                │
           FastAPI 后端 (uvicorn :8000)
                │
       ┌────────┼─────────┐
       ↓        ↓         ↓
    LLM API   ComfyUI   本地文件
  (MiniMax/  (本地       (identity/memory/
   DeepSeek)  :8188)      vector/images)
```

## 快速启动 (Windows)

双击 `启动.bat`，脚本会：
1. 自动装 Python 依赖 (`requirements.txt`)
2. 必要时装前端依赖 (`npm install`)
3. 杀掉占用 8000 端口的旧 uvicorn
4. 启动后端 (`http://127.0.0.1:8000`)
5. 启动前端 (`http://localhost:5173`)
6. 自动打开浏览器

## 手动启动

```bash
# 后端
pip install -r requirements.txt
uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000

# 前端
cd frontend
npm install
npm run dev
```

需要 Python 3.14+（启动脚本固定使用 `py -3.14`）。

## 核心特性

- **实时流式聊天** — WebSocket，token-by-token 推送，LLM 驱动
- **多角色支持** — 每个角色独立目录 (`characters/{name}/`)，独立身份/记忆/状态/向量库
  - 已内置：小桃 (momo) / 莉莉 (lili) / 小樱 (sakura) / 小文 (xiaowen)
  - 前端 `CharacterDirectory` 组件一键切换
- **多 LLM 模型** — 后端管理 API key (`config/llm_profiles.json`)，前端运行时切换
- **AI 自主生图** — 接本地 ComfyUI (默认 `localhost:8188`)，工作流 `waiNSFWIllustrious_v140.json`
- **智能拍照** — LLM 自决定何时拍照，按角色当前 `status.md` 拼装 prompt
- **服装与场景状态机** — 穿着/场景用英文 SD 标签存 `status.md`，LLM 通过 `state_updates` 维护，后端在生图时注入 prompt
- **持久记忆** — 每日对话归档 → 摘要压缩 → long-term → 向量召回 (ChromaDB)
- **心跳与静默时段** — 配置 `heartbeat.quiet_start/end` 控制主动消息时段
- **图片历史** — 按角色分组的图库 + 翻阅
- **设置面板** — 分页保存：模型 / ComfyUI / 上下文 / 心跳 / 记忆

## 目录结构

```
AI_gf_momo/
├── 启动.bat                       # Windows 一键启动
├── requirements.txt
│
├── backend/                       # FastAPI
│   ├── main.py                    # 入口
│   ├── api/                       # routes / ws / llm_routes / image
│   ├── core/                      # orchestrator / runtime / memory / state /
│   │                              # memory_v3 / memory_policy / vector_store /
│   │                              # outfit_state / plan_manager / output_monitor ...
│   ├── services/                  # llm / comfyui / tts / prompt_builder / llm_profiles
│   ├── agents/                    # momo / image / memory
│   ├── tools/                     # image_tool
│   └── models/                    # pydantic schemas
│
├── frontend/                      # Vue 3 + Vite
│   └── src/
│       ├── App.vue
│       ├── components/            # ChatWindow / ChatArea / StatePanel /
│       │                          # SettingsPanel / ImagePanel / ImageGallery /
│       │                          # StatusBar / CharacterDirectory
│       └── composables/           # useWebSocket / useCharacter / useImageHistory
│
├── characters/{name}/             # 角色数据（不入运行时 memory）
│   ├── identity.md                # 不可变身份（最高优先级）
│   ├── profile.json               # 元信息（显示名、头像、视觉锚点）
│   ├── user.json                  # 用户信息（称呼、偏好）
│   ├── memory/                    # 运行时状态（status/plans/soul/long_term/...）
│   ├── vector/                    # ChromaDB 向量索引（按角色隔离）
│   └── images/                    # 生成图片（运行时，本地）
│
├── config/
│   ├── agent.md                   # LLM system prompt + 上下文协议
│   ├── tag_reference.md           # SD 标签速查
│   ├── photo_rules.md             # 生图规则
│   ├── settings.json              # 全局配置（角色、上下文、ComfyUI、心跳、记忆）
│   └── llm_profiles.example.json  # 多模型配置示例
│
├── data/
│   └── char_skin_mapping.json     # IP 角色皮肤标签映射（新建/编辑角色时检索补全）
└── scripts/                       # 诊断 / 烟雾测试 / 探针
```

## 配置

1. 复制 `.env.example` 为 `.env`，填至少一个 LLM API key。
2. 复制 `config/llm_profiles.example.json` 为 `config/llm_profiles.json`（首次启动后端会自动生成模板）。
3. 启动 ComfyUI 服务（默认 `http://127.0.0.1:8188`）。
4. `config/settings.json` 里的 `active_character` 决定启动后进入哪个角色。

## 角色上下文协议 (config/agent.md)

每轮对话给 LLM 一个「上下文包」，按优先级：

1. `profile` — 元信息（ID、显示名、视觉锚点）
2. `identity.md` — **不可变身份**（最高优先级，禁止被记忆覆盖）
3. `user.json` — 用户信息（称呼、偏好）
4. `status.md` — 当前状态（穿着/场景/心情）
5. `plans.md` — 当前计划
6. `soul.md` — 慢变化人格
7. `long_term.md` — 长期关系记忆
8. `conversation_summary.md` — 早前对话压缩摘要
9. `chat_history` — 最近对话
10. `vector_recall` — 向量召回的历史片段

冲突规则：身份永远以 `identity.md` 为准；记忆里出现"我是别的角色"视为污染。

## 状态更新协议

LLM 通过结构化字段修改现实状态：

- `state_updates` — 改穿着 / 场景（必填英文 SD 标签，完整列出当前状态）
- `plan_updates` — 改目标 / 计划
- 拒绝、犹豫、承诺未兑现 → **不更新**对应状态
- 已在 reply 中描述的变化 → **必须**同步输出对应更新

脱衣规则：`completely_nude` / `topless` / `bottomless` / `naked_apron` 等明确标签才会被生图系统采纳为裸露状态。

## 依赖

- **LLM** — MiniMax / DeepSeek（或其他 OpenAI 兼容 API）
- **生图** — 本地 ComfyUI，工作流 `waiNSFWIllustrious_v140.json`
- **Python** 3.14+，**Node** 18+

## 开发参考

- `scripts/contract_smoke.py` — 后端契约烟雾测试
- `scripts/diagnose_runtime.py` — 运行时诊断
- `config/agent.md` — 角色对话协议和上下文组织规则
- `config/photo_rules.md` — 生图触发和照片规则
- `config/tag_reference.md` — 常用 SD 标签参考

## 隐私

- `.env` / `config/llm_profiles.json` / `config/provider_keys.json` 已在 `.gitignore`
- `data/` 与 `memory/` 为运行时数据，本地存储不入库
- `characters/*/vector/` 为每角色向量索引，**默认不入库**（与原 `characters/lili/vector/` 例外）
