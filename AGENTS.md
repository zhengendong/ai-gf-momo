# AI_gf_momo 项目协作约束

本文件是本仓库的开发记忆。修改代码前先阅读 [架构索引](docs/ARCHITECTURE_INDEX.md)，并遵守以下约束。

## 修改边界

- 先理解现有调用链和数据契约；不确定的业务语义先询问，不要凭空补设定。
- 只修改完成当前需求所必需的代码；不要顺手重构无关模块。
- 不修改角色 `identity.md` 的内容，除非用户明确要求。角色人格和人设由用户自行维护。
- `characters/*/images/`、`characters/*/vector/`、聊天记录和角色运行状态属于用户数据；除非用户明确要求，不要删除、覆盖、加入提交或用测试污染真实数据。
- 保留公开 API、WebSocket 消息和旧模型输出的兼容性。移除旧字段或旧模块前，先确认仓库内没有调用点，并提供迁移路径。

## Agent / 状态 / 生图不变量

- 正常对话路径最多一次主生成模型调用；不要为规则选择或一致性修复默认增加第二次 LLM 调用。
- `identity.md` 优先于记忆、检索结果和业务知识；业务知识只能补充常识、审美和连续性。
- 向量召回与长期记忆写入是两条独立链路：召回只提供本轮参考；主 Agent 的 `memory_candidate` 仅是候选，必须由后台 MemoryAgent 二次审核后才能刷新 `long_term.md`。不要混用两者的规则或数据。
- 主 Agent 输出 `reply`、已完成的 `effects` 和可选 `image_intent`；不要让它拼人物外貌、服饰、场景、质量或负面提示词。
- `status.md` 是模型可读状态，`state_snapshot.json` 是同步的结构化快照。图片任务必须携带创建当时冻结的状态快照，后台生图禁止重新读取最新状态。
- 状态变化必须先提交，再创建 ImageJob。图片、回复和状态不一致时，宁可不生图，也不要生成错误图片。
- 全局业务知识位于 `config/knowledge/`；调整触发条件优先改 `router.json`，调整业务原则优先改对应领域 Markdown，不要把领域规则重新塞回 `agent.md`。
- 后端端口的唯一配置来源是根目录 `.env` 的 `SERVER_PORT`；不要在启动脚本、前端代理或代码中重新写死业务端口。

## 文档、验证和 Git

- 改动架构、模块职责、数据流、关键契约、配置入口或验证方式时，必须同步更新 `docs/ARCHITECTURE_INDEX.md`。
- 每次实现后至少运行相关的离线验证；涉及对话/状态/生图链路时运行：
  - `py scripts/architecture_smoke.py`
  - `py scripts/memory_candidate_probe.py`
  - `py scripts/runtime_conversation_probe.py`
  - `py scripts/backend_smoke.py`（需要本地 ComfyUI）
- 保持工作区内已有的用户改动。提交前检查 `git diff --check` 和 `git status`；不要使用破坏性的 Git 命令。
