# AI_gf_momo 架构索引

> 修改模块职责、数据流、输出契约、配置入口、运行数据格式或验证方式时，必须同步更新本文档和 `AGENTS.md`。

## 系统边界

项目是多角色沉浸式聊天与 ComfyUI 生图应用。角色人格属于 `characters/<character>/identity.md`，由用户维护；通用运行协议属于 `config/agent.md`；全局领域知识位于 `config/knowledge/`。

正常持久化对话使用两个职责分离的同步模型步骤：

1. `MomoAgent` 专心完成角色决策和自然回复，只提出高层 `image_goal` 与长期记忆候选。
2. `VisualContinuityAgent` 每轮理解用户输入、角色实际回复和上一轮快照，更新服饰与场景；存在 `image_goal` 时还负责动作、姿势和镜头设计。

状态提交成功后才向用户发送角色回复，并以同一个冻结快照创建图片任务。MemoryAgent 的候选审核和 ComfyUI 生成仍在后台执行。

右侧“下一幕”面板通过独立的 `scene_transition` WebSocket 消息触发同一条事务链。自动模式由 MomoAgent 根据当前剧情推进，手动模式额外接收用户的场景构想；预设指令是隐藏任务，不伪装成用户台词，也不写入聊天记录。MomoAgent 输出已经发生的新一幕后，VisualContinuityAgent 从回复中还原新场景和实际穿着。默认不强制生图。事务成功后写入并发送持久化 `scene_divider` 事件，前端以“新场景”分割线展示。

新角色与清空记录后的角色进入显式 `initialized=false` 状态，`status.md` 显示“未构建”；它表示尚无视觉事实，不能解释为裸体、空场景或任何默认服饰。角色的 `profile.json.initial_scene` 保存可随时编辑的开场事实模板（构想、开场方与修订号），与当前剧情状态分离：编辑模板不改变正在进行的剧情，清空记录也不会删除模板。玩家可以在右侧面板主动构建开场，也可以直接发送第一条消息触发自动构建。两种方式都走 MomoAgent → VisualContinuityAgent → 状态提交；VisualContinuityAgent 必须一次建立完整服饰槽位与包含时间、地点的场景，成功后才把 `initialized` 设为 `true`。模板只约束需要成立的事实，重新开场允许自然改写旁白、动作和服饰描述细节。开场内部指令不进聊天记录；历史顺序为“故事开始”分割线、可选真实玩家首句、角色开场。

## 顶层目录

| 路径 | 职责 |
| --- | --- |
| `backend/agents/` | Momo、视觉连续性、记忆和图片管线 |
| `backend/core/` | 运行时编排、上下文、状态与服饰模型、记忆策略、ImageJob |
| `backend/services/` | LLM、ComfyUI、提示词组装、TTS 等适配器 |
| `backend/tools/` | ImageJob 到 ComfyUI 工作流的工具封装 |
| `backend/api/` | HTTP 与 WebSocket 接口 |
| `characters/<id>/` | 用户维护的角色资料、状态、记忆、向量库和图片 |
| `config/` | 全局配置、Agent 协议、领域知识与工作流映射 |
| `scripts/` | 离线探针和烟雾测试 |

## 一轮消息的数据流

```mermaid
flowchart TD
  A["用户消息或开场构建"] --> A1{"视觉状态已初始化?"}
  A1 -- "否" --> A2["载入持久化初始场景事实模板"]
  A1 -- "是" --> B["组装身份、历史、状态、召回与领域知识"]
  A2 --> B
  B --> C["MomoAgent"]
  C --> D["reply + image_goal + memory_candidate"]
  D --> E["VisualContinuityAgent"]
  E --> F["state_patch + 可选 shot_spec"]
  F --> G["校验并提交 status.md / state_snapshot.json"]
  G --> H["冻结提交后的状态"]
  H --> I["发送角色回复"]
  H --> J{"存在 image_goal?"}
  J -- 是 --> K["创建不可变 ImageJob 并后台生图"]
  J -- 否 --> L["结束图片状态"]
  I --> M["后台聊天记录、记忆候选与向量任务"]
```

`AgentRuntime` 对同一角色加 `asyncio.Lock`，因此两轮状态解析和提交不会交错。VisualContinuity 输出先做无写入合并校验，再提交；连续性 JSON 或补丁无效时允许同一个 Agent 修复一次。两次均失败时，本轮不提交状态、不发送角色台词、不创建 ImageJob，只通过系统状态消息提示重试，避免角色说出“做到了”而实际状态未变。

故事运行在独立的虚拟时空中。真实系统时间不再注入主 Agent 或 VisualContinuityAgent，也不参与剧情推进、场景判断、状态变化或“距上次聊天”的推断；聊天消息自身的技术时间戳仍由历史记录保留，用于前端显示和日志追踪。

MemoryAgent 同样不得接收现实日期、时钟或聊天技术时间。技术日期仅可在后台用于限定读取窗口和调度；传入候选审核与记忆沉淀模型的材料只保留对话顺序。长期记忆中的重要里程碑只能使用对话明确叙述的故事时间，或按已发生的故事先后排列，不得推断或补写现实日期。

关键入口：`backend/core/runtime.py`、`backend/agents/momo.py`、`backend/agents/image_director.py`、`backend/core/state.py`、`backend/core/wardrobe.py`、`backend/core/image_job.py`。

## MomoAgent 契约

新协议由 `config/agent.md` 约束：

```json
{
  "reply": "角色自然回复",
  "image_goal": {
    "purpose": "展示本轮结果",
    "subject": "需要呈现的对象",
    "visibility": "clear",
    "rating": "general"
  },
  "memory_candidate": null,
  "persist_context": true
}
```

MomoAgent 不输出 `state_ops`、服饰、场景或镜头标签。坐、站、躺、穿脱、换场景等事实只需自然地体现在 `reply`；`image_goal` 只表达是否要交付图片以及交付目的，不选择工作流、模型或提示词。每轮上下文中的 `status.md` 是上一轮视觉还原已经提交的客观事实；最近对话、记忆或角色惯性与其冲突时，主 Agent 必须以 `status.md` 为本轮起点，不得否认或凭空恢复视觉状态。解析器仍保留旧字段以兼容外部结构，但正常运行时会忽略旧 `state_ops/effects/image_intent/photo_prompt/state_updates`。

`persist_context=false` 用于不进入角色持久化链路的特殊回复，因此不会改状态、写历史或生图。

## VisualContinuityAgent 契约

协议位于 `config/image_director.md`，实现类为 `VisualContinuityAgent`；`ImageDirectorAgent` 名称只作为导入兼容别名保留。每个持久化回合都调用它，而不以是否生图为条件。

输入包括：

- 此前最多 8 轮结构化对话，用于理解剧情承接；
- 当前用户消息；
- Momo 实际 `reply`；
- 可选 `image_goal`；
- 上一轮完整服饰槽位、明确缺失标记、可见标签和场景标签；
- 本轮命中的领域知识。

最近剧情只补充动作承接、人物关系和观看目标，不能覆盖上一轮快照；本轮视觉变化仍以当前角色实际 `reply` 为主要依据。

输出包括：

```json
{
  "reason": "内部连续性判断摘要",
  "state_patch": {
    "wardrobe": {
      "footwear": {"mode": "replace", "layers": []}
    },
    "scene": null
  },
  "shot_spec": null
}
```

`state_patch` 每轮必填。没有变化时 `wardrobe={}`、`scene=null`；未出现的服饰槽位保持上一轮原样。被修改槽位使用 `mode=replace`，`layers` 是变化后完整的、从内到外排列的层级。场景确定发生变化时，以 `mode=replace` 提交变化后的完整场景标签。

只有 `image_goal` 存在时 `shot_spec` 才是对象。此时 VisualContinuityAgent 是最终提示词总编辑：它接收完整 `role/body/appearance` 候选和服饰、场景状态，输出必须完整保留的 `role_tags`、主动筛选的 `appearance_tags/wardrobe_tags/scene_tags`，以及动作、姿势、表情、景别、角度、焦点、光线与 rating。质量词、负面词、工作流和模型仍由系统统一管理。

VisualContinuityAgent 会在固定协议后附加 `config/knowledge/visual_prompting.md`。该手册从 `data/pxlsan-标签选择器-完整内容.xlsx` 的服装、动作、构图、场景和光影栏目蒸馏而来，只保留组合规律、代表性词汇、few-shot、预算和冲突规则，不把原表数千行标签塞入每轮上下文。存在图片目标时，导演必须先选一个可见的核心动作（如 `lifting_skirt`、`holding_shoes`、`presenting_foot`），再以至多一个支撑姿势和必要镜头使它成立；`standing/sitting` 不能代替核心动作。构图中的景别与部位焦点严格二选一，角度可独立保留：明确看某部位时只输出 `xx_focus`，没有特指部位时才输出 `medium_shot/full_shot` 等景别。角色 `role_tags` 全部保留，外貌最多 5 个、服饰最多 4 个、动作最多 2 个、姿势/表情/光线各最多 1 个，场景只选 1 至 2 个；包含质量词与 rating 的最终提示词总计不超过 25 个标签。所有数值权重均已退出协议，局部特写通过直接删除无关候选建立重点。

## 服饰与状态模型

`state_snapshot.json` 是状态机、VisualContinuityAgent 和 ImageJob 使用的结构化事实源；`status.md` 不再维护旧的平铺服饰标签，而是由同一提交函数生成的可读投影。服饰区固定按“上身、下身、腿部、鞋子、配饰”展示，例如 `上身：topless`、`下身：white lace panties`。任何状态提交都必须同时更新两者，禁止再次写入 `white`、`lace`、`panties` 这类拆分服饰标签。

快照顶层的 `initialized` 区分“尚未构建”与真实的空服饰槽位。`initialized=false` 时 `wardrobe=null`，图片任务不会创建；只有初始场景事务提交了完整的 `upper/lower/legwear/footwear` 槽位和非空场景后，状态才切换为 `true`。旧角色若没有该字段，则根据既有 `status.md` 是否包含“未构建”进行保守兼容，不会被自动清空或迁移成新开场。

心情不是持久化视觉状态：`status.md`、`state_snapshot.json` 和前端状态栏均不保存或展示心情。旧 `status.md` 中以“心情状态”结尾的章节会在首次读取时自动移除；角色当下情绪和表情由最近剧情与当前回复自然表达，VisualContinuityAgent 需要生图时再据此设计表情。

服饰保持五个简化槽位：

| 槽位 | 内容 |
| --- | --- |
| `upper` | 上身层；Bra 为 `underwear`，上衣为 `outerwear` |
| `lower` | 下身层；内裤为 `underwear`，裙/裤为 `outerwear` |
| `legwear` | 袜、丝袜、连裤袜 |
| `footwear` | 鞋、靴、拖鞋等 |
| `accessories` | 首饰和配件 |

Bra 和内裤不是顶层槽位，而是 `upper/lower` 的内层类别。每件衣物从状态建模开始就使用一个精简短语，例如 `white_lace_panties`，而不是把颜色、材质和类型拆成互相独立的标签。这样既保留了用户要求的简单槽位，又能表达“脱掉内裤但裙子仍在”或“脱掉裙子后内裤成为可见层”。同一连体衣物可用相同 `id` 占据 `upper` 和 `lower`。

重要规则：

- 每个槽位从内到外排列；只替换本轮变化的槽位。
- `no_bra/no_panties` 仅保留为结构化快照中的隐藏内衣连续性事实，不进入前端或生图提示词。
- `footwear` 与 `legwear` 独立；两者都空时才投影 `barefoot`，但完全裸露时由 `completely_nude` 单独表达，不再重复 `barefoot`。
- 仅空上身/下身分别投影 `topless/bottomless`；四个衣物槽位均空时只投影 `completely_nude`，不再叠加 `topless`、`bottomless`、`no_bra` 或 `no_panties`。
- 未知旧标签进入 `legacy_visible`，原样保留并抑制不可靠的裸露推断。
- 旧 `apply_state_operations()`、`reduce_wardrobe()` 和 `state_updates_from_effects()` 保留作兼容入口，不参与新运行时主链路。

状态必须先提交，再创建 ImageJob。图片任务携带创建当时的快照，后台不得重新读取最新状态。

## ImageJob 与 ComfyUI

`ImageJob` 冻结角色、本轮回复、`image_goal`、`shot_spec`、服饰、场景和状态版本。正常运行时的 `build_image_prompt()` 只按固定优先级序列化导演已审核的标签计划：质量与 rating → 完整角色标签 → 精选外貌 → 精选服饰 → 构图视角 → 姿势动作 → 精选环境与光线。后端校验角色标签完整、外貌/服饰/场景均来自候选事实，并拒绝超过 25 个标签的计划；不再重新注入全部视觉状态，也不再编译任何权重。

工作流和模型由 `config/settings.json` 的全局 `comfyui` 配置决定。`root_dir` 指向本地 ComfyUI 根目录，工作流从 `<root_dir>/ComfyUI/user/default/workflows` 读取。前端空值继承工作流节点默认值，明确填写才覆盖。存在 `config/workflow_adapters/<workflow-stem>.json` 时只能改映射声明的受控节点。

`ComfyUIService.submit_and_wait()` 先连接同一 `client_id` 的 `/ws`，再提交 `/prompt`；收到完成事件后只读一次 `/history/{prompt_id}`，随后根据 history 返回的 `filename`、`subfolder` 和 `type` 调用 `/view`。有 SaveImage 时优先 `type=output`，只有 PreviewImage 时使用 `type=temp`。二进制预览帧不替代最终图片。

聊天区可以本地隐藏或重新显示全部图片，不影响图片历史。每张历史图片均可通过 `POST /api/image/regenerate` 重新生成：后端只读取该图片记录中保存的最终 prompt，不重新读取当前服饰或场景；成功后替换同一条图片历史记录和聊天中的图片 URL，不新增聊天回合。旧图片文件保留在本地，避免未经确认删除用户数据。

## 记忆和领域知识

`config/knowledge/router.json` 根据当前输入和最近对话选择领域手册，不调用 LLM。领域原则分别维护在 `wardrobe.md`、`scene.md`、`photography.md`、`intimacy.md` 和 `recall.md`，不要重新塞回 `agent.md`。

向量召回与长期记忆写入是两条独立链路：召回只为本轮提供参考；Momo 的 `memory_candidate` 只是候选，后台 `MemoryAgent` 审核、去重后才能刷新 `long_term.md`。实际刷新后，通过静默 `memory_updated` 消息通知前端。

## 服务地址和前端模式

根目录 `.env` 的 `SERVER_PORT` 是后端端口唯一来源。`启动.bat` 每次启动都会重新构建 Vue 页面、关闭 reload，并用随机查询参数打开地址，避免复用旧前端页面；`开发启动.bat` 启动 FastAPI reload 与 Vite，`frontend/vite.config.js` 从同一 `.env` 读取代理端口。前端源码变化后也可运行 `构建前端.bat` 或在 `frontend/` 执行 `npm run build`。

## 维护入口

| 调整目标 | 首选位置 |
| --- | --- |
| 角色回复与高层目标协议 | `config/agent.md`、`backend/agents/momo.py` |
| 视觉状态理解和 ShotSpec | `config/image_director.md`、`backend/agents/image_director.py` |
| 服饰槽位、层级和可见投影 | `backend/core/wardrobe.py` |
| 状态提交和 Markdown 投影 | `backend/core/state.py` |
| 领域规则与触发条件 | `config/knowledge/` |
| 精简视觉标签知识与 few-shot | `config/knowledge/visual_prompting.md` |
| ImageJob 和最终提示词 | `backend/core/image_job.py`、`backend/services/prompt_builder.py` |
| ComfyUI 工作流注入与传输 | `backend/services/comfyui.py`、`config/workflow_adapters/` |
| 角色人格 | `characters/<id>/identity.md`（仅用户明确要求时修改） |

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

`backend_smoke.py` 需要本地 ComfyUI；其余探针使用临时角色、假 LLM 或假 ComfyUI，不应读取或污染真实角色数据。
提示词拼接顺序约束：后端最终构建必须按“质量词（含 rating）→ 主体（角色标签、外貌、体型）→ 服饰 → 构图视角 → 姿势动作 → 环境与光线”排列；质量词和评级始终置于最前。
