# AI_gf_momo 项目协作约束

本文件是本仓库的开发记忆。修改代码前先阅读 [架构索引](docs/ARCHITECTURE_INDEX.md)，并遵守以下约束。

项目级历史决策、已废弃方案和禁止重复引入的模块记录在 [项目级记忆](docs/PROJECT_MEMORY.md)。涉及架构、Agent、状态、对话或生图链路的修改，必须同时阅读该文件和架构索引。

## 修改边界

- 先理解现有调用链和数据契约；不确定的业务语义先询问，不要凭空补设定。
- 只修改完成当前需求所必需的代码；不要顺手重构无关模块。
- 不修改角色 `identity.md` 的内容，除非用户明确要求。角色人格和人设由用户自行维护。
- `characters/*/images/`、`characters/*/vector/`、聊天记录和角色运行状态属于用户数据；除非用户明确要求，不要删除、覆盖、加入提交或用测试污染真实数据。
- 保留公开 API、WebSocket 消息和旧模型输出的兼容性。移除旧字段或旧模块前，先确认仓库内没有调用点，并提供迁移路径。
- 角色数据只存放于 `characters/<角色>/`；根目录 `data/` 是通用资料目录，角色管理流程不得扫描、移动或删除其内容。
- 提示词精简原则：删除机制、职责或字段时，直接删除对应内容，不要再添加“不要做什么”“禁止输出什么”或解释已不存在机制的反向说明。仅保留会实际改变当前模型行为且无法由正向职责自然表达的最短硬约束。

## Agent / 状态 / 生图不变量

- 正常对话路径包含一次主角色模型调用和一次 VisualContinuityAgent 调用：前者只负责剧情推进、沉浸式回复与记忆候选，后者每轮负责视觉状态解析，并以 `shot` 是否为空同时决定本轮是否生图和设计镜头。连续性输出协议失败时仅允许原 Agent 修复一次；不得追加 state-only 或其他额外模型调用。两次仍失败时保持上轮已提交状态，不猜测未经验证的状态变化。记忆审核继续走后台 MemoryAgent。
- `identity.md` 优先于记忆、检索结果和业务知识；业务知识只能补充常识、审美和连续性。
- 向量召回与长期记忆写入是两条独立链路：召回只提供本轮参考；主 Agent 的 `memory_candidate` 仅是候选，必须由后台 MemoryAgent 二次审核后才能刷新 `long_term.md`。不要混用两者的规则或数据。
- 长期上下文由窗口内完整对话、窗口外 `conversation_summary.md` 连续剧情摘要、`long_term.md` 稳定事实和按需向量细节召回共同组成。达到 `context.compress_at` 时由 MemoryAgent 在后台滚动合并摘要，不得阻塞当前回复；摘要和游标必须同一事务推进，且每个角色只能有一个在途压缩任务。
- 主 Agent 只输出 `reply`、`memory_candidate` 和 `persist_context`；不要让它判断生图时机、输出状态操作或拼人物外貌、服饰状态投影、场景、镜头标签、质量和负面提示词。包含旁白与台词时，`reply` 必须用空行按语义分段。VisualContinuityAgent 根据此前最多 8 轮对话、当前用户输入、角色实际回复和上一轮快照输出 `state_patch`，并独立决定 `shot`：明确观看意图且回复已呈现、明显服饰/场景变化、或性爱场景出现新的动作、接触或裸露结果时生图；日常对话、普通旁白、轻微姿势变化、重复状态，以及画面涉及接吻或拥抱的互动不生图。最近剧情只能帮助理解承接，不能覆盖快照。旧 `image_goal/state_ops/effects/image_intent/photo_prompt/state_updates` 只作为兼容结构保留，不进入正常运行时链路。
- “下一幕”自动/手动构建使用独立 `scene_transition` WebSocket 消息，但仍走 MomoAgent → VisualContinuityAgent → 状态提交的正常事务。预设指令不得作为用户台词或普通聊天记录持久化；成功后持久化 `scene_divider` 历史事件供前端显示，是否生图由 VisualContinuityAgent 按新场景的表现价值决定。
- 新角色和清空记录后的角色必须处于显式 `initialized=false` 的“未构建”状态，不得把它解释为裸体、空场景或默认服饰。持久化初始场景模板存于 `profile.json.initial_scene`，编辑模板不改变当前剧情，清空记录不删除模板。主动构建开场或第一条用户消息自动触发开场时，仍走 MomoAgent → VisualContinuityAgent → 状态提交；只有完整服饰槽位和时间/地点场景提交成功后才置为已初始化。模板只保持事实约束，不要求每次复刻服饰措辞、动作或旁白。内部开场指令不写入聊天记录，成功后持久化“故事开始”分割线。
- 新建角色时分别选择角色性别和玩家性别，存入 `profile.json.gender` 与 `user.json.gender`，并作为 MomoAgent 和 VisualContinuityAgent 的客观参与者事实。旧角色缺失字段时保持未设置，不默认角色为女性或玩家为男性。已知角色性别必须在最终角色标签前生成并校正唯一的 `1girl` 或 `1boy`。
- `status.md` 是上一轮 VisualContinuityAgent 已提交的模型可读客观事实投影，主 Agent 必须将其作为本轮视觉起点，历史、记忆和角色惯性不得否认或覆盖它；`state_snapshot.json` 是同步的结构化事实快照。服饰由 `upper/lower/legwear/footwear/accessories` 的分层状态管理；每件衣物从状态开始就使用一个精简短语（如 `white_lace_panties`），不得把颜色、材质、类型拆成互相独立的生图标签。未知旧标签必须保守保留。图片导演和图片任务必须携带创建当时冻结的状态快照，后台禁止重新读取最新状态。
- 心情不属于持久化状态：不得写入 `status.md` 或 `state_snapshot.json`，前端状态栏也不展示；情绪和表情从上下文与当前回复理解。
- 故事运行在独立虚拟时空中；真实系统时间不得注入 Agent、影响剧情或参与状态判断。聊天记录自身的技术时间戳可以保留，但不得作为故事时间输入。
- MemoryAgent 不得接收现实日期、时钟或聊天技术时间；技术日期只可在后台用于读取窗口与调度。重要里程碑只能依据对话明确的故事时间和已发生的故事先后整理，不得补写现实日期。
- VisualContinuityAgent 的提示词知识来自蒸馏后的 `config/knowledge/visual_prompting.md`，不要把 `data/pxlsan-标签选择器-完整内容.xlsx` 或 `data/sex_tag/` 整表注入上下文。导演输入参与者性别、精简服饰槽位、场景状态和剧情事实，只输出服饰/场景补丁及可选的 `camera/action/environment`；质量词、唯一角色人数性别标签、完整 `role/body/appearance` 锚点和冻结服饰/裸露事实由后端按固定顺序拼接。画面主体始终是角色，玩家不生成第二个人数标签，只通过 POV、局部身体或动作关系出现。构图中的景别与部位焦点必须二选一，角度可独立保留一个；明确看某部位时只用 `xx_focus`，无特指部位时才用 `medium_shot/full_shot` 等景别。动作和环境允许各用一段精简英文自然语言，动作句目标不超过 25 英文词、环境目标不超过 18 英文词，超长自动压缩而不报错。最终提示词以约 40 个语义单元为 SDXL 编辑目标，不由后端按数量截断；长度不得成为取消图片或对话的原因。禁止生成任何数值权重；局部特写不得忽略实际服饰或裸露事实。
- 状态变化必须先提交，再创建 ImageJob。图片、回复和状态不一致时，宁可不生图，也不要生成错误图片。
- 生图服务地址、工作流、模型和可选覆盖参数由后端读取 `config/settings.json` 的全局 `comfyui` 配置；`base_url` 为空时才回退到环境变量的 `http://127.0.0.1:8188`，保存地址后下一次图片任务必须重建 HTTP 客户端并使用新地址。`root_dir` 是本地 ComfyUI 根目录，工作流从 `<root_dir>/ComfyUI/user/default/workflows` 读取；前端只下拉选择该目录现有的 JSON 文件。主 Agent 不选择生图时机、工作流或模型。前端空值表示继承所选工作流节点的默认值，只有明确填写的值才可覆盖。复杂工作流的受控节点由 `config/workflow_adapters/<workflow-stem>.json` 声明；有映射时只能修改映射节点，不能再按类型批量覆盖。
- ComfyUI 生图使用同一 `client_id` 的 `/ws` 完成事件等待，不得恢复为固定间隔轮询 `/history`。完成事件后只读取一次 `/history/{prompt_id}` 获取输出元数据，再通过 `/view` 下载最终图片；二进制预览帧不改变当前前端展示。
- 全局业务知识位于 `config/knowledge/`；调整触发条件优先改 `router.json`，调整业务原则优先改对应领域 Markdown，不要把领域规则重新塞回 `agent.md`。
- 旧领域业务知识文件和路由当前仅保留，不注入 MomoAgent 或 VisualContinuityAgent；导演固定加载的知识手册只有 `config/knowledge/visual_prompting.md`。
- 导演协议必须保留后端不可推断的 JSON 契约示例：服饰槽位为从内到外的衣物短语数组，场景为完整短标签数组，初始场景一次提交完整服饰槽位与场景；正常镜头只包含 `camera/action/environment`。未初始化输入使用 `wardrobe=null`，初始化提交失败不得发送或持久化开场回复与分割线。
- 后端端口的唯一配置来源是根目录 `.env` 的 `SERVER_PORT`；不要在启动脚本、前端代理或代码中重新写死业务端口。

## 文档、验证和 Git

- 改动架构、模块职责、数据流、关键契约、配置入口或验证方式时，必须同步更新 `docs/ARCHITECTURE_INDEX.md`。
- 每次实现后至少运行相关的离线验证；涉及对话/状态/生图链路时运行：
  - `py scripts/architecture_smoke.py`
  - `py scripts/wardrobe_layer_probe.py`
  - `py scripts/turn_transaction_probe.py`
  - `py scripts/memory_candidate_probe.py`
  - `py scripts/context_compression_probe.py`
  - `py scripts/performance_cache_probe.py`
  - `py scripts/llm_error_classification_probe.py`
  - `py scripts/runtime_conversation_probe.py`
  - `py scripts/workflow_adapter_probe.py`
  - `py scripts/comfyui_transport_probe.py`
  - `py scripts/backend_smoke.py`（需要本地 ComfyUI）
- 保持工作区内已有的用户改动。提交前检查 `git diff --check` 和 `git status`；不要使用破坏性的 Git 命令。
