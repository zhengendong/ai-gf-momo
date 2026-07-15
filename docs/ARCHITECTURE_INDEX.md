# AI_gf_momo 架构索引

> 更新规则：凡修改模块职责、数据流、输出契约、配置入口、运行数据格式或验证方式，必须同步更新本文档和 `AGENTS.md` 中对应约束。

## 目标与边界

项目是多角色沉浸式聊天与 ComfyUI 生图应用。正常一轮对话保持一次同步主角色模型调用：主 Agent 负责角色决策、自然回复、已完成状态操作、高层图片目标和长期记忆候选；确定性后端负责状态归约和提交。只有图片轮次才在后台按需调用 `ImageDirectorAgent` 设计镜头，记忆审核继续由独立后台 Agent 完成；协议修复模型只允许在本轮输出校验失败的异常路径调用一次。

角色人格属于 `characters/<character>/identity.md`，由用户维护。通用运行规则属于 `config/agent.md`，全局业务知识属于 `config/knowledge/`。历史召回和长期记忆写入是两条独立的数据链路。

## 顶层目录

| 路径 | 职责 |
| --- | --- |
| `backend/agents/` | 主角色 Agent、记忆 Agent、按需图片导演、后台图片管线 |
| `backend/core/` | 运行时编排、上下文、分层服饰/状态归约、记忆策略、事务检查、业务知识路由、ImageJob |
| `backend/services/` | LLM、ComfyUI、最终提示词组装、TTS 等服务适配 |
| `backend/tools/` | 面向 Agent/管线的工具封装；ImageTool 将 ImageJob 编译为工作流 |
| `backend/api/` | HTTP / WebSocket 接口 |
| `characters/<id>/` | 角色资料、运行时状态、记忆、向量库和用户图片；不要随意改动运行数据 |
| `config/` | 全局运行配置、主 Agent 协议、全局业务知识 |
| `scripts/` | 诊断与离线烟雾测试 |
| `docs/` | 架构和开发协作资料 |

## 服务地址与端口

根目录 `.env` 的 `SERVER_PORT` 是后端端口唯一配置来源，默认后端绑定 `127.0.0.1:8001`。`启动.bat` 用它清理旧后端并启动 `python -m backend.main`；清理时同时终止监听进程及继承其端口的 `spawn_main` 孤儿 Worker，端口未释放时拒绝启动，启动完成后还会校验该端口只有一个监听实例，避免浏览器继续命中旧代码。开发模式下 `frontend/vite.config.js` 读取同一份 `.env`，将 `/api`、`/ws` 和 `/static` 代理到该端口。以后只改 `.env` 的 `SERVER_PORT`，然后重启后端和 Vite。

### 前端部署模式

- `启动.bat` 是日常使用的单服务生产模式：若 `frontend/dist/index.html` 不存在，会先执行一次前端构建；随后只启动 FastAPI，并在同一个 `SERVER_PORT` 提供 `/api`、`/ws`、`/static` 和构建后的 Vue 页面。该模式固定关闭 `SERVER_RELOAD`，浏览器打开 `http://127.0.0.1:<SERVER_PORT>`。
- `开发启动.bat` 保留开发体验：FastAPI 以 `SERVER_RELOAD=true` 启动，Vite 仍监听 `5173`，并将 `/api`、`/ws`、`/static` 代理至 `.env` 中的 `SERVER_PORT`。
- 前端源码改动后，日常启动前运行 `构建前端.bat`（或手动在 `frontend/` 执行 `npm run build`）。`frontend/dist/` 是可再生构建产物，不提交 Git。
- 后端的 Vue 静态托管只对浏览器 HTML 导航执行 `index.html` 回退；不存在的 JS、CSS、图片等资源仍返回 404，避免掩盖构建问题。

## 一轮消息的数据流

```text
WebSocket / API 输入
  -> AgentRuntime.handle_message（同一角色串行锁）
  -> 读取最近对话、状态、摘要、记忆召回
  -> KnowledgeRouter：按需读取 config/knowledge 的全局领域手册
  -> MomoAgent：一次同步主 LLM 调用
  -> AgentOutput V2: reply + state_ops + image_goal + memory_candidate
  -> 本地事务检查；仅失败时允许一次异常修复调用
  -> StateReducer 确定性提交 state_ops，写 status.md 并同步 state_snapshot.json
  -> 冻结本轮提交后的状态快照，再立即发送文本
  -> image_goal 存在时，后台 ImageDirectorAgent 只读取用户消息、回复、目标、业务知识和冻结状态，输出 ShotSpec
  -> ShotSpec 编译为不可变 ImageJob；旧 image_intent/photo_prompt 仍走兼容入口
  -> 记忆写入和图片生成均为后台任务
  -> 后台记忆实际刷新时推送静默 memory_updated 通知，前端刷新记忆页
  -> ImageTool：读取 config/settings.json 的全局 comfyui 配置；从 <root_dir>/ComfyUI/user/default/workflows 读取选定工作流，按可选 workflow adapter 注入人物预设 + 冻结服饰/场景 + 画面意图。模型、CLIP、VAE、LoRA 与未覆盖的节点参数保留工作流默认值
  -> ComfyUI：先连接同 client_id 的 /ws，再 POST /prompt；收到完成事件后 GET /history，再 GET /view 下载最终图 -> 图片历史和应用 WebSocket 图片消息
```

关键入口：[AgentRuntime](../backend/core/runtime.py)、[MomoAgent](../backend/agents/momo.py)、[图片导演](../backend/agents/image_director.py)、[状态模块](../backend/core/state.py)、[分层服饰模块](../backend/core/wardrobe.py)、[ImageJob](../backend/core/image_job.py)、[提示词编译器](../backend/services/prompt_builder.py)。

## 主 Agent 契约

定义位于 `backend/models/schemas.py` 的 `AgentOutput`。新协议由 `config/agent.md` 约束：

```json
{
  "reply": "角色自然回复",
  "state_ops": [
    {
      "domain": "wardrobe",
      "operation": "remove",
      "slot": "footwear",
      "target": "outermost"
    }
  ],
  "image_goal": {
    "required": true,
    "purpose": "展示本轮已经发生的视觉变化",
    "subject": "用户要求观看的对象",
    "visibility": "clear",
    "mood": "shy",
    "rating": "general"
  },
  "memory_candidate": null,
  "persist_context": true
}
```

`state_ops` 只记录本轮已经完成的持久变化；用户请求、犹豫、拒绝、承诺稍后执行都不能提交。主 Agent 不再重建变化后的完整服饰，也不再设计镜头标签。`image_goal` 只描述图片交付的目的、主体、可见程度、情绪和 rating，不包含人物外貌、服饰、场景、镜头、画质、负面提示词或模型配置。

主 Agent把一轮输出视为一个对话事务：先以 `status.md` 为起点形成角色决定和 `reply`，再提交回复中已经完成的 `state_ops`，随后判断是否存在 `image_goal`，最后才提出可选 `memory_candidate`。坐、站、躺、转身等即时动作只属于回复和图片，不属于持久状态操作。事务校验在回复发送前完成；若回复声称状态或视觉交付已完成但缺少对应结构，异常修复仍失败时会替换为明确的未完成降级回复，而不是保留虚假叙事。

`effects`、`image_intent`、`photo_prompt` 和 `state_updates` 仍由后端兼容层读取，供已有模型输出和手动接口过渡使用；新提示词不再要求模型输出它们。

## 状态与并发

- `characters/<id>/memory/status.md`：供主 Agent 和界面读取的 Markdown 投影。
- `characters/<id>/memory/state_snapshot.json`：机器可读快照；V2 包含版本、分层 `wardrobe`、可见服饰兼容投影和场景标签。
- `backend/core/wardrobe.py`：维护 `upper`、`lower`、`legwear`、`footwear`、`accessories` 五个可扩展槽位；每槽从内到外排列，同一连体衣物可占多个槽位。
- `apply_state_operations()`：先完整验证本轮操作，再由 Reducer 确定性提交；单件移除不会要求模型重建其他服饰层。
- 旧平面标签第一次读取时保守投影到分层结构；未知标签进入 `legacy_visible`，不会因无法分类而误推断裸露。
- `state_updates_from_effects()`：旧协议兼容转换。
- `AgentRuntime` 对每个角色使用 `asyncio.Lock`，防止同一角色的两轮状态提交交错。

状态写入后再创建图片任务。局部姿势、镜头和动作只属于图片，不写入持久状态。

## ImageJob 与生图引擎

`ImageDirectorAgent` 是按需后台专业 Agent，只在新协议存在 `image_goal` 时调用。它不扮演角色、不修改状态、不选择工作流或模型，只把高层交付目标和冻结状态设计成动作、姿势、表情、镜头、光线与 rating 的 `ShotSpec`。

`ImageJob` 是一次图片生成的不可变内部任务。创建时冻结：

- 角色 ID；
- 本轮回复；
- 高层 `image_goal` 和图片导演 `ShotSpec`（旧协议可直接使用 `image_intent`）；
- 从 `ShotSpec` 编译出的动态画面标签；
- 本轮提交后的服饰、场景和状态版本；

后台图片导演和生成任务只读取这个快照。它们不会再次读取当前 `status.md`，因此后一轮换装或换场景不会污染已排队图片。

最终 prompt 由 `build_image_prompt()` 统一注入：角色视觉预设、冻结服饰的可见层投影、冻结场景和动态 ShotSpec 标签。外层移除后内层自动成为可见层；`footwear` 与 `legwear` 都为空才投影 `barefoot`；明确空的上下身槽位投影相应身体状态。前端全局 `comfyui.root_dir` 是本地 ComfyUI 根目录，后端从 `<root_dir>/ComfyUI/user/default/workflows` 读取 `workflow`；该工作流决定模型链路。`negative_prompt`、采样器、调度器、步数、CFG 和尺寸留空时继承该工作流，明确填写时才覆盖对应节点。主 Agent 与 ImageJob 不携带工作流或模型选择。

`config/workflow_adapters/<workflow-stem>.json` 是可选的后端维护映射，不在前端展示。它声明当前工作流的主正/负提示词、主采样器、尺寸和保存节点；存在映射时，后端仅改这些节点，避免复杂工作流的二次采样、局部提示词或修复分支被误改。映射不存在时保留旧的按节点类型自动识别行为。当前 `ANIMA_workflow.json` 已配置映射。

提交任务时，`ComfyUIService.submit_and_wait()` 会先使用同一 `client_id` 连接 ComfyUI `/ws`，再请求 `/prompt`，等待 `executing(node=null)` 完成事件；随后只请求一次 `/history/{prompt_id}` 取得最终图片元数据，图片数据仍由 `/view` 获取。下载时必须保留 history 返回的 `filename`、`subfolder` 和 `type`：存在 `SaveImage` 时优先读取 `type=output`，只有 `PreviewImage` 时读取 `type=temp`。二进制预览帧不转发，应用前端继续显示既有的“生图中”占位与最终图片。

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

## 一致性、异常修复与降级

`output_monitor.py` 在提交前确定性检查旧状态字段和 V2 `state_ops/image_goal`，包括操作能否归约、回复是否遗漏已完成状态、明确视觉交付是否漏掉图片目标。纯观看追问可以复述已经提交的状态而不重复产生 `state_ops`；同一轮同时提出脱、穿、换或场景变化时仍必须提交对应操作。正常路径不调用第二个同步模型。

只有校验失败时，`MomoAgent.repair_output()` 才允许基于当前用户消息、状态、无效输出和问题列表修复一次完整事务；修复后再次执行同一确定性检查。若仍失败，运行时清空状态、图片和记忆副作用，并将回复降级为“动作没有成功完成”，不再保留与实际状态矛盾的成功叙事。

图片导演失败时使用最小 ShotSpec 兜底；ComfyUI 失败不会回滚已经提交的现实状态。图片历史的新记录附带 `job_id`、冻结状态版本、`image_goal`、`ShotSpec` 和动态提示词，便于区分角色决策、状态、构图和生成阶段的问题。

## 维护入口

| 想调整什么 | 首选位置 |
| --- | --- |
| 全角色通用的思考顺序、自然对话、自主性、输出 JSON | `config/agent.md` |
| 服饰/场景/摄影/亲密互动业务规则 | `config/knowledge/<domain>.md` |
| 哪类输入加载哪本领域手册 | `config/knowledge/router.json` |
| 角色人格、关系、口癖 | `characters/<id>/identity.md`（仅用户明确要求时改） |
| 结构化状态格式、状态操作解释 | `backend/core/state.py`、`backend/models/schemas.py` |
| 服饰槽位、层级归约和可见投影 | `backend/core/wardrobe.py` |
| 高层图片目标到 ShotSpec | `config/image_director.md`、`backend/agents/image_director.py` |
| ShotSpec 到最终 prompt 的转换 | `backend/core/image_job.py`、`backend/services/prompt_builder.py` |
| ComfyUI 工作流节点注入 | `backend/services/comfyui.py` |
| 复杂工作流的受控节点映射 | `config/workflow_adapters/<workflow-stem>.json` |

## 验证命令

```powershell
py -m compileall -q backend scripts
py scripts/wardrobe_layer_probe.py
py scripts/turn_transaction_probe.py
py scripts/architecture_smoke.py
py scripts/memory_candidate_probe.py
py scripts/runtime_conversation_probe.py
py scripts/generation_settings_probe.py
py scripts/workflow_adapter_probe.py
py scripts/comfyui_transport_probe.py
py scripts/backend_smoke.py
git diff --check
```

`backend_smoke.py` 会检查本地 ComfyUI；其余探针使用临时角色、假 LLM 或假 ComfyUI，不读取和污染真实角色运行数据。修改对话、状态、生图或知识路由时必须运行对应的新旧探针。
