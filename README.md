# AI_gf_momo — 智能女友小桃

前后端分离的 Windows 本地应用。

## 你是谁

你是开发这个项目的 AI agent。下面的指引帮你快速理解整个体系。

## 先读什么

| 顺序 | 文件 | 内容 |
|------|------|------|
| 1 | `docs/ARCHITECTURE.md` | 整体架构、技术选型、目录结构、开发路径 |
| 2 | `config/character/identity.md` | 小桃是谁——不变的身份（身高、性格、说话方式） |
| 3 | `config/character/long_term.md` | 小桃在关系中变成的样子——动态沉淀，每天更新 |

## 行为规范参考（开发时对照）

这三个 reference 是从 Hermes 体系复制过来的原始设计文档，**不要照抄语法**（里面是 Hermes 的工具调用格式），只参考**设计意图和规则**：

| 文件 | 告诉你什么 | 关键内容 |
|------|-----------|---------|
| `docs/reference-gf-core.md` | 小桃的行为铁律 | 沉浸式原则、不回技术术语、沉默协议、主动性、真假癖好分辨 |
| `docs/reference-gf-state.md` | 状态管理规范 | intimacy_mode 两档定义（daily/nsfw）、state schema、生图触发规则 |
| `docs/reference-gf-memory.md` | 记忆系统设计 | Step 1/2/3 流水线、长度稳定铁律、自然衰减规则、跨日期去重 |

> ⚠️ reference 文件里出现 `skill_view`、`patch(path=...)`、`cron job_id`、`WSL /mnt/` 等词都是 Hermes 内部语法，在这个项目里用不上。只看规则本身。

## 数据文件（后端直接读写）

| 文件 | 格式 | 读写频率 |
|------|------|---------|
| `config/character/identity.md` | Markdown | 只读（冷启动加载） |
| `config/character/long_term.md` | Markdown | 冷启动读 + 每日 cron 写 |
| `config/live_state.json` | JSON | 聊天中读写（换衣服/场景/脱衣） |
| `config/settings.yaml` | YAML | 只读（启动加载） |

## 启动

```bash
# 后端
cd backend
pip install fastapi uvicorn pyyaml httpx
uvicorn main:app --host 127.0.0.1 --port 8000

# 前端 — 直接用浏览器打开 frontend/index.html 即可
```

## 依赖

- DeepSeek API（聊天）
- ComfyUI（生图，Windows 本地 localhost:8188）
- 无需 WSL、无需 Docker
