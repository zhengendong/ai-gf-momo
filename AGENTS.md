# AI_gf_momo 项目协作约束

本文件是本仓库的开发记忆。修改代码前先阅读 [架构索引](docs/ARCHITECTURE_INDEX.md)，并遵守以下约束。

## 修改边界

- 先理解现有调用链和数据契约；不确定的业务语义先询问，不要凭空补设定。
- 只修改完成当前需求所必需的代码；不要顺手重构无关模块。
- 不修改角色 `identity.md` 的内容，除非用户明确要求。角色人格和人设由用户自行维护。
- `characters/*/images/`、`characters/*/vector/`、聊天记录和角色运行状态属于用户数据；除非用户明确要求，不要删除、覆盖、加入提交或用测试污染真实数据。
- 保留公开 API、WebSocket 消息和旧模型输出的兼容性。移除旧字段或旧模块前，先确认仓库内没有调用点，并提供迁移路径。

## Agent / 状态 / 生图不变量

- 正常对话路径包含一次主角色模型调用和一次 VisualContinuityAgent 调用：前者只负责角色回复与图片目标，后者每轮负责视觉状态解析，并在需要生图时同时设计镜头。连续性输出协议失败时允许原 Agent 修复一次；记忆审核继续走后台 MemoryAgent。
- `identity.md` 优先于记忆、检索结果和业务知识；业务知识只能补充常识、审美和连续性。
- 向量召回与长期记忆写入是两条独立链路：召回只提供本轮参考；主 Agent 的 `memory_candidate` 仅是候选，必须由后台 MemoryAgent 二次审核后才能刷新 `long_term.md`。不要混用两者的规则或数据。
- 主 Agent 只输出 `reply`、可选高层 `image_goal`、`memory_candidate` 和 `persist_context`；不要让它输出状态操作，也不要让它拼人物外貌、服饰状态投影、场景、镜头标签、质量或负面提示词。VisualContinuityAgent 根据此前最多 8 轮对话、当前用户输入、角色实际回复和上一轮快照输出 `state_patch`，有图片目标时再输出 `shot_spec`；最近剧情只能帮助理解承接，不能覆盖快照。旧 `state_ops/effects/image_intent/photo_prompt/state_updates` 只作为兼容结构保留，不进入正常运行时链路。
- “下一幕”自动/手动构建使用独立 `scene_transition` WebSocket 消息，但仍走 MomoAgent → VisualContinuityAgent → 状态提交的正常事务。预设指令不得作为用户台词或普通聊天记录持久化；成功后持久化 `scene_divider` 历史事件供前端显示，默认不强制生图。
- `status.md` 是上一轮 VisualContinuityAgent 已提交的模型可读客观事实投影，主 Agent 必须将其作为本轮视觉起点，历史、记忆和角色惯性不得否认或覆盖它；`state_snapshot.json` 是同步的结构化事实快照。服饰由 `upper/lower/legwear/footwear/accessories` 的分层状态管理；每件衣物从状态开始就使用一个精简短语（如 `white_lace_panties`），不得把颜色、材质、类型拆成互相独立的生图标签。未知旧标签必须保守保留。图片导演和图片任务必须携带创建当时冻结的状态快照，后台禁止重新读取最新状态。
- 心情不属于持久化状态：不得写入 `status.md` 或 `state_snapshot.json`，前端状态栏也不展示；情绪和表情从上下文与当前回复理解。
- 故事运行在独立虚拟时空中；真实系统时间不得注入 Agent、影响剧情或参与状态判断。聊天记录自身的技术时间戳可以保留，但不得作为故事时间输入。
- VisualContinuityAgent 的提示词知识来自蒸馏后的 `config/knowledge/visual_prompting.md`，不要把 `data/pxlsan-标签选择器-完整内容.xlsx` 整表注入上下文。ShotSpec 必须遵守动作/姿势/表情/光线标签预算；每张图只选一个景别、角度和焦点。普通画面不使用权重；局部近距离特写由后端将外貌和服饰统一弱化到 `0.9`，可选强化组最多一个且范围为 `1.05-1.20`。
- 状态变化必须先提交，再创建 ImageJob。图片、回复和状态不一致时，宁可不生图，也不要生成错误图片。
- 生图工作流、模型和可选覆盖参数由后端读取 `config/settings.json` 的全局 `comfyui` 配置；`root_dir` 是本地 ComfyUI 根目录，工作流从 `<root_dir>/ComfyUI/user/default/workflows` 读取。主 Agent 只输出画面意图，不选择工作流或模型。前端空值表示继承所选工作流节点的默认值，只有明确填写的值才可覆盖。复杂工作流的受控节点由 `config/workflow_adapters/<workflow-stem>.json` 声明；有映射时只能修改映射节点，不能再按类型批量覆盖。
- ComfyUI 生图使用同一 `client_id` 的 `/ws` 完成事件等待，不得恢复为固定间隔轮询 `/history`。完成事件后只读取一次 `/history/{prompt_id}` 获取输出元数据，再通过 `/view` 下载最终图片；二进制预览帧不改变当前前端展示。
- 全局业务知识位于 `config/knowledge/`；调整触发条件优先改 `router.json`，调整业务原则优先改对应领域 Markdown，不要把领域规则重新塞回 `agent.md`。
- 后端端口的唯一配置来源是根目录 `.env` 的 `SERVER_PORT`；不要在启动脚本、前端代理或代码中重新写死业务端口。

## 文档、验证和 Git

- 改动架构、模块职责、数据流、关键契约、配置入口或验证方式时，必须同步更新 `docs/ARCHITECTURE_INDEX.md`。
- 每次实现后至少运行相关的离线验证；涉及对话/状态/生图链路时运行：
  - `py scripts/architecture_smoke.py`
  - `py scripts/wardrobe_layer_probe.py`
  - `py scripts/turn_transaction_probe.py`
  - `py scripts/memory_candidate_probe.py`
  - `py scripts/runtime_conversation_probe.py`
  - `py scripts/workflow_adapter_probe.py`
  - `py scripts/comfyui_transport_probe.py`
  - `py scripts/backend_smoke.py`（需要本地 ComfyUI）
- 保持工作区内已有的用户改动。提交前检查 `git diff --check` 和 `git status`；不要使用破坏性的 Git 命令。
