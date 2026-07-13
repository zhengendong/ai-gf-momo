# AI_gf_momo 架构索引

> 更新规则：凡修改模块职责、数据流、输出契约、配置入口、运行数据格式或验证方式，必须同步更新本文档和 `AGENTS.md` 中对应约束。

## 目标与边界

项目是多角色沉浸式聊天与 ComfyUI 生图应用。正常一轮对话保持一次主生成模型调用：主 Agent 负责角色决策、自然回复、已完成状态事件、画面意图和长期记忆候选；确定性后端负责状态提交、提示词组装、图片生成和持久化。

角色人格属于 `characters/<character>/identity.md`，由用户维护。通用运行规则属于 `config/agent.md`，全局业务知识属于 `config/knowledge/`。历史召回和长期记忆写入是两条独立的数据链路。

## 顶层目录

| 路径 | 职责 |
| --- | --- |
| `backend/agents/` | 对话 Agent、记忆 Agent、后台图片管线 |
| `backend/core/` | 运行时编排、上下文、状态、记忆策略、一致性检查、业务知识路由、ImageJob |
| `backend/services/` | LLM、ComfyUI、最终提示词组装、TTS 等服务适配 |
| `backend/tools/` | 面向 Agent/管线的工具封装；ImageTool 将 ImageJob 编译为工作流 |
| `backend/api/` | HTTP / WebSocket 接口 |
| `characters/<id>/` | 角色资料、运行时状态、记忆、向量库和用户图片；不要随意改动运行数据 |
| `config/` | 全局运行配置、主 Agent 协议、全局业务知识 |
| `scripts/` | 诊断与离线烟雾测试 |
| `docs/` | 架构和开发协作资料 |

## 服务地址与端口

根目录 `.env` 的 `SERVER_PORT` 是后端端口唯一配置来源，默认后端绑定 `127.0.0.1:8001`。`启动.bat` 用它清理旧后端并启动 `python -m backend.main`；开发模式下 `frontend/vite.config.js` 读取同一份 `.env`，将 `/api`、`/ws` 和 `/static` 代理到该端口。以后只改 `.env` 的 `SERVER_PORT`，然后重启后端和 Vite。

## 一轮消息的数据流

```text
WebSocket / API 输入
  -> AgentRuntime.handle_message（同一角色串行锁）
  -> 读取最近对话、状态、摘要、记忆召回
  -> KnowledgeRouter：按需读取 config/knowledge 的全局领域手册
  -> MomoAgent：一次主 LLM 调用
  -> AgentOutput: reply + effects + image_intent + memory_candidate
  -> 本地一致性检查
  -> effects 转 state_updates，写 status.md 并同步 state_snapshot.json
  -> 冻结 ImageJob（本轮 reply + image_intent + 状态快照）
  -> 立即发送文本；记忆写入和图片生成走后台任务
  -> 后台记忆实际刷新时推送静默 memory_updated 通知，前端刷新记忆页
  -> ImageTool：读取 config/settings.json 的全局 comfyui 配置，选定工作流；注入人物预设 + 冻结服饰/场景 + 画面意图。模型、CLIP、VAE、LoRA 与未覆盖的节点参数保留工作流默认值
  -> ComfyUI 工作流 -> 图片历史和 WebSocket 图片消息
```

关键入口：[AgentRuntime](../backend/core/runtime.py)、[MomoAgent](../backend/agents/momo.py)、[状态模块](../backend/core/state.py)、[ImageJob](../backend/core/image_job.py)、[提示词组装器](../backend/services/prompt_builder.py)。

## 主 Agent 契约

定义位于 `backend/models/schemas.py` 的 `AgentOutput`。新协议由 `config/agent.md` 约束：

```json
{
  "reply": "角色自然回复",
  "effects": [
    {
      "type": "replace_outfit",
      "tags": ["完整的英文 SD 服饰标签"]
    }
  ],
  "image_intent": {
    "generate": true,
    "pose": ["sitting_on_bed"],
    "expression": ["slight_smile", "looking_at_viewer"],
    "camera": {"shot": "medium_shot", "angle": "front_view"},
    "lighting": ["warm_lighting"],
    "rating": "general"
  },
  "memory_candidate": null,
  "persist_context": true
}
```

`effects` 只记录本轮已经完成的现实变化；用户请求、犹豫、拒绝、承诺稍后执行都不能提交状态。`image_intent` 只描述画面，不包含人物外貌、服饰、场景、画质和负面提示词。

主 Agent把一轮输出视为一个对话事务：先以 `status.md` 为起点形成角色决定和 `reply`，再从回复中提交结束后仍需成立的 `effects`，随后基于“起始状态 + effects”判断是否生成 `image_intent`，最后才提出可选 `memory_candidate`。`reply` 是本轮叙事事实基准；图片和记忆候选都不能自行创造回复与状态中不存在的新事实。坐、站、躺、转身等即时动作只属于回复和图片，不属于持久状态事件。

`photo_prompt` 和 `state_updates` 仍由后端模型兼容层读取，供已有模型输出和手动接口过渡使用；新提示词不再要求模型输出它们。

## 状态与并发

- `characters/<id>/memory/status.md`：供主 Agent 和界面读取的 Markdown 状态。
- `characters/<id>/memory/state_snapshot.json`：每次状态写入同步更新的结构化视觉快照，包含版本、服饰和场景标签。
- `state_updates_from_effects()`：将新协议转换为兼容写入格式。
- `AgentRuntime` 对每个角色使用 `asyncio.Lock`，防止同一角色的两轮状态提交交错。

状态写入后再创建图片任务。局部姿势、镜头和动作只属于图片，不写入持久状态。

## ImageJob 与生图引擎

`ImageJob` 是一次图片生成的不可变内部任务，不是新的 LLM 或子 Agent。创建时冻结：

- 角色 ID；
- 本轮回复；
- 从 `image_intent` 编译出的动态画面标签；
- 本轮提交后的服饰、场景和状态版本；

后台任务只读取这个快照。它不会再次读取当前 `status.md`，因此后一轮换装或换场景不会污染已排队图片。

最终 prompt 由 `build_image_prompt()` 统一注入：角色视觉预设、冻结服饰、冻结场景和动态画面标签。工作流选择及参数覆盖由前端全局 `comfyui` 配置控制：`workflow` 决定模型链路；`negative_prompt`、采样器、调度器、步数、CFG 和尺寸留空时继承该工作流，明确填写时才覆盖对应节点。主 Agent 与 ImageJob 不携带工作流或模型选择。

## 全局业务知识与渐进加载

`config/knowledge/` 是当前全角色共用的领域业务知识库，可理解为全局 Rule Packs，但按“领域手册”维护，而不是为每件衣服创建一个 Pack：

| 文件 | 内容 |
| --- | --- |
| `router.json` | 用户输入与模糊续接时的领域触发信号；可直接调整，无需改代码 |
| `wardrobe.md` | 换装完整性、服饰常识与审美 |
| `scene.md` | 地点、时间、光线与场景连续性 |
| `photography.md` | 生图时的构图、姿势、镜头和 rating 原则 |
| `intimacy.md` | 亲密互动的连续性和状态约束 |
| `recall.md` | 已召回历史片段在本轮回复中的使用原则 |

`KnowledgeRouter` 根据当前输入和必要时最近对话，加载命中的完整领域手册并写入“本轮适用业务知识”。它不调用 LLM。当前不实现角色专属知识包；未来若需要，可在该路由器之后增加“角色挂载的覆盖手册”，但不能复制全局核心规则。

### 记忆的两条独立链路

**历史召回**发生在主 LLM 调用之前：`memory_policy.recall_vector_context()` 根据用户输入判断是否查询向量库；命中结果作为 `vector_recall` 放进本轮上下文。`recall.md` 只告诉模型如何谨慎使用这些片段，不能写入长期记忆，也不能改变当前状态。

**长期记忆写入**发生在主 LLM 返回之后：主 Agent只在可能稳定且重要的事实出现时填写 `memory_candidate`。运行时将它连同本轮用户消息和角色回复交给后台 `MemoryAgent.evaluate_candidate()`；MemoryAgent 二次审核、去重并在通过时刷新完整的 `long_term.md`。这不依赖向量召回，也不应因用户只是提及“上次”就自动写入。

当候选审核或后台沉淀实际刷新 `long_term.md` / `soul.md` 后，运行时向当前会话发送不展示给用户的 `memory_updated` WebSocket 消息。前端“记忆”设置页仅在当前角色匹配且标签打开时重新读取相关文档。

## 一致性与降级

`output_monitor.py` 只做本地确定性检查，不调用第二个修复模型。若检测到服饰冲突、明显不完整状态或回复/状态矛盾：保留文本回复，但取消状态提交和图片生成，避免错误状态或图文不符。

主 LLM 失败或输出无法解析时，保留已有的文本降级行为。不要在正常路径增加同步摘要、修复模型或生图提示词优化模型。

## 维护入口

| 想调整什么 | 首选位置 |
| --- | --- |
| 全角色通用的思考顺序、自然对话、自主性、输出 JSON | `config/agent.md` |
| 服饰/场景/摄影/亲密互动业务规则 | `config/knowledge/<domain>.md` |
| 哪类输入加载哪本领域手册 | `config/knowledge/router.json` |
| 角色人格、关系、口癖 | `characters/<id>/identity.md`（仅用户明确要求时改） |
| 结构化状态格式、状态事件解释 | `backend/core/state.py`、`backend/models/schemas.py` |
| 画面意图到最终 prompt 的转换 | `backend/core/image_job.py`、`backend/services/prompt_builder.py` |
| ComfyUI 工作流节点注入 | `backend/services/comfyui.py` |

## 验证命令

```powershell
py -m compileall -q backend scripts
py scripts/architecture_smoke.py
py scripts/memory_candidate_probe.py
py scripts/runtime_conversation_probe.py
py scripts/generation_settings_probe.py
py scripts/backend_smoke.py
git diff --check
```

`backend_smoke.py` 会检查本地 ComfyUI；其余两项不依赖真实 LLM。修改对话、状态、生图或知识路由时至少运行前三项中的相关测试。
