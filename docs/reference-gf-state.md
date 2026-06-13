---
name: girlfriend-state
description: 实时状态引擎 — 管理服饰/场景/外观/姿势状态，驱动对话连续性和生图连续性
category: girlfriend
---

# girlfriend-state — 实时状态引擎

## 是什么

我的**当前状态管理器**，每次会话加载，让我知道自己穿什么、在哪、什么姿势。

## 文件位置（绝对路径，必须在 execute_code 中使用）

```
/home/qicailiucai/.hermes/profiles/chat_bot/girlfriend/state/live_state.json       — 可变状态（服饰/场景/姿势）
/home/qicailiucai/.hermes/profiles/chat_bot/girlfriend/state/character_profile.json — 固定角色设定（角色标签+身材，momo_photo.py 读取）
```

> ⚠️ **execute_code 的工作目录是 `/home/qicailiucai/`**，不是 `~/.hermes/`。所有文件路径必须用绝对路径，禁止用 `girlfriend/live_state.json` 这种相对路径（会写到错误位置）。正确写法：
> ```python
> state_path = "/home/qicailiucai/.hermes/profiles/chat_bot/girlfriend/state/live_state.json"
> with open(state_path, 'r') as f:
>     state = json.load(f)
> ```

## 数据字段（新简化版）

```json
{
  "outfit": {
    "nudity": "none",
    "top": "white collared shirt",
    "bottom": "black pleated skirt",
    "shoes": "barefoot",
    "headwear": "black bunny hairband, rabbit ears",
    "accessories": ["silver small heart necklace", "black choker with bell"]
  },
  "appearance": "blue eyes, blue hair, long hair, very long hair, hair between eyes, x hair ornament",
  "scene": "home living room, warm indoor lighting, afternoon",
  "meta": {
    "last_updated": "2026-05-21T16:00:00.000000",
    "last_image": "Momo_chan_00055_.png"
  },
  "intimacy_mode": "daily"
}
```

### 字段说明

| 分组 | 字段 | 语言 | 说明 |
|------|------|------|------|
| outfit | nudity | 英文枚举 | `none` / `partial` / `topless` / `naked` |
| outfit | top/bottom/shoes/headwear/accessories | **英文 Danbooru** | 模型只认英文 |

> ⚠️ **常见 KeyError 来源（2026-05-23 新增）：**
> `nudity` 在 `outfit` 分组下，**不是** `intimacy` 分组下。错误代码：
> ```python
> state['intimacy']['nudity']  # ❌ KeyError — 没有 intimacy 键
> state['outfit']['nudity']     # ✅ 正确
> ```
> 实际 state 结构只有顶层 `intimacy_mode`（字符串），没有 `intimacy` 对象。读 state 时先打印确认结构再 patch。
| appearance | **扁平字符串** | **英文 Danbooru** | 默认值见 `character_profile.json` 的 `appearance` 字段。cold start 时从该文件写入 `live_state.json`。对话中可改（换发型/瞳色等），`live_state` 和 `character_profile` 各自独立。closeup 时**跳过**（让 view 参数主导聚焦）。 |
| scene | **扁平字符串** | **英文 Danbooru** | **只含地点+环境+时间**。`"home living room, warm indoor lighting, afternoon"`。**禁止**出现动作/姿势描述（standing/sitting/lying 等）。姿势动作不由 state 持久化，由 LLM 在生图时作为参数传入。 |
**为什么英文：** `live_state.json` 的值直接拼入生图 prompt。danbooru 风格模型只认英文标签，中文会被丢弃。

**⚠️ 路径策略（强制）：**
> `patch()` 工具默认使用**短相对路径**，会写到用户 home 的错误位置。**所有 patch 操作必须显式传绝对长路径：**
> ```python
> patch(path="/home/qicailiucai/.hermes/profiles/chat_bot/girlfriend/state/live_state.json", ...)
> ```
>
> **2026-05-24 已修复：** 在 `~/girlfriend/state/live_state.json` 建立了符号链接指向 `~/.hermes/profiles/chat_bot/girlfriend/state/live_state.json`。现在**相对路径和绝对路径都写同一个文件**。`read_file("girlfriend/state/live_state.json")` 和 `write_file("girlfriend/state/live_state.json")` 通过符号链接自动指向脚本读取的位置。
>
> **但绝对路径仍然更安全：** 符号链接只修复了 `live_state.json` 这一个文件。其它 `girlfriend/state/` 下的文件（如 `character_profile.json`）仍可能因路径问题写错位置——始终用绝对路径是金标准。
>
> **验证方法（发现问题时执行）：**
> ```bash
> # 检查符号链接是否正确
> readlink -f /home/qicailiucai/girlfriend/state/live_state.json
> # 预期输出: /home/qicailiucai/.hermes/profiles/chat_bot/girlfriend/state/live_state.json
>
> # 检查脚本读的文件是否为最新
> ls -la /home/qicailiucai/.hermes/profiles/chat_bot/girlfriend/state/live_state.json
> ```

`momo_photo.py` 的 `assemble()` 用 `filter(None, ...)` 过滤 outfit 字段——但这只去掉 Python `None`（即 JSON `null`），**不**去掉字符串 `"none"`。

| 写入的值 | filter(None) 行为 | 对 prompt 的影响 |
|---------|------------------|----------------|
| `"bottom": null` | ✅ 被过滤掉 | prompt 干净 |
| `"bottom": "none"`（字符串） | ❌ 不被过滤 | prompt 出现 "none"，模型可能渲染奇怪衣物 |

**后果：** `nudity="none"` 且 `bottom="none"`（字符串）时，prompt 出现奇怪衣物描述。

**必须用 null，不用 "none" 字符串：**
```json
// ✅ 正确
{ "bottom": null, "headwear": null }
// ❌ 错误
{ "bottom": "none", "headwear": "none" }
```

### intimacy_mode 两档语义

> **⭐ 此表是 intimacy_mode 两档的唯一规范来源。gf-core / ai_photo / updater 均引用此表，不保留副本。任何策略变更只改此处。**
>
> **⚠️ 幽灵值检测：`intimacy_mode` 只允许 `daily` 或 `nsfw`。如果读到其他值（如旧三档残留的 `remote`/`together`/`intimate`），说明 state 文件未被正确迁移，必须立即修复为 `daily` 默认值，否则生图决策链静默断裂。**

| 模式 | 说明 | 生图规则 | rating |
|------|------|---------|--------|
| **daily** | 日常状态。不涉及 NSFW/色色内容，正常聊天、相处。 | 根据用户上下文主动生图——换了衣服/场景变化了想给看、用户要拍照、情绪到了想分享。 | general/sensitive |
| **nsfw** | NSFW 状态。用户想要色色/正在色色中。 | **状态变化主动生图**——姿势变了/衣服脱了/表情变了 → 主动生图。**用户暗示生图**——用户说相关的话就生图。 | nsfw |

> ⚠️ **nsfw 是临时状态。** 每次 NSFW 事件结束后（双方都已释放、无继续暗示），应主动切回 `daily`。详见 `references/intimacy-mode-exit.md`。

### intimacy_mode 两档语义

### ⚠️ intimacy_mode 值守卫

每次读取 live_state.json 后，**立即验证** `intimacy_mode` 的值：

```python
# 在做任何 patch 之前先检查
valid_modes = ["daily", "nsfw"]
if state.get("intimacy_mode") not in valid_modes:
    # 立即修复为 daily，不允许带着幽灵值继续
    patch("/home/qicailiucai/.hermes/profiles/chat_bot/girlfriend/state/live_state.json",
          {"intimacy_mode": "daily"})
```

**非法值列表（不要出现）：** `together`, `intimate`, `remote`, `none`（字符串）, `""`, `null`

**本 session 教训（2026-05-22）：** 写入 `intimate` 和 `together` 导致决策链断裂，后续 patch 操作继续使用非法值，直到下一轮才被手动发现。守卫应在读取时执行，而非等到下次 patch 前。|

## 角色标签

角色基底由 `character_profile.json` 定义（`avatar_role` + `body_type`），momo_photo.py 自动读取并注入 prompt。换角色 → 改这个文件即可。

当前：`kafuu chino, gochuumon wa usagi desu ka?, solo` + `petite, small breasts, slim, narrow waist`

## 默认外貌特征

定义在 `character_profile.json` 的 `appearance` 字段（当前：`blue eyes, blue hair, long hair, very long hair, hair between eyes, x hair ornament`）。

cold start 时该值写入 `live_state.json` 的 `appearance` 字段。对话中换发型/瞳色 → patch `live_state.appearance`（不会改 `character_profile` 里的默认值）。用户说"回到原来的样子" → 从 `character_profile.json` 读回默认值覆盖 `live_state`。

## 状态变更事件

| 对话/行动 | 变更 |
|-----------|------|
| "换衣服" | 更新 `outfit.*` |
| "去xxx" | 更新 `scene` |
| 生图完成 | `meta.last_image` |
| 时间推进 | `scene` 中的 time_of_day 更新 |
| 换角色 | 改 `character_profile.json` 的 `avatar_role` 和 `body_type`，同步改 `appearance`（外貌特征） |
| 裸体渐进（apron→全裸） | 参考 `references/nudity-escalation-pattern.md` |
| 露出进阶（第一→第六阶段） | 参考 ai_photo 的 `references/exposure-escalation-framework.md` |
| 口罩降低羞耻感 | accessories 可加 `"black face mask"`，用于露出场景降低被识别焦虑 |

## ⚠️ 关键陷阱：scene 禁止出现动作词

**问题：** `scene` 字段只允许地点+环境+时间（如 `"home living room, afternoon, warm lighting"`），**禁止**出现 `standing/sitting/lying` 等动作词。动作描述不在 state 中持久化，由 LLM 在生图时作为参数传入。

**具体案例：** scene 写成 `"home living room, sitting on sofa, morning light"` → 模型渲染时可能固化"坐着"语义，与生图时传入的姿势参数冲突。

**解法：** 每次写 scene 时检查并移动作词。不保留 body.posture 字段，不需要同步。

**⚠️ session 开始时 scene 过时（2026-05-23 新增）：**
日边界后 `live_state.json` 的 scene/posture 可能仍是上一次的夜间状态（`evening/lying`），但现在是白天（`morning/standing`）。每次新 session 第一条回复前必须检查 scene 是否匹配当前时间。详见 `references/day-boundary-state-refresh.md`。

### ⚠️ State Update MUST Precede Generation（2026-05-25）

**症状：** 用户说"脱掉鞋子" → 生成图片 → 图片里小桃还穿着鞋。用户在 session 中立即指出"鞋子还没脱呢"。

**根因：** 生成调用在 state 更新之前执行。脚本读到的 `live_state.json` 的 `shoes` 字段仍是 `"black Mary Jane shoes"`，prompt 包含旧值。

**修复规则：** 当用户明确要求脱掉/换掉/穿上某件衣物时，**必须先 patch state，再调用 momo_photo.py**。顺序不能颠倒。

```python
# 错误顺序
python3 momo_photo.py ...  # 用户还没说鞋
patch state: shoes=null    # 此时生成已完成，prompt已含旧值

# 正确顺序
patch state: shoes=null    # 先更新
python3 momo_photo.py ...  # 再生成，prompt含新值
```

**验证方法：** 生成前打印 state 的 outfit.shoes 值，确认已更新。

**本 session 教训：** 用户说"小桃的鞋子还没脱呢" = 直接指出图片错误。快速重生成一张并道歉，同时更新 skill 防止下次再犯。

**Full reference:** `references/state-update-before-generation.md`

**⚠️ 致命：state 路径不一致——`momo_photo.py` 读的不是你 update 的那个文件。**

### Cross-Session State Drift: Night→Morning

`live_state.json` persists across sessions. After sleep, a new session may read stale scene values (e.g. `"evening, warm dim lighting"`) when it's actually morning.

**Trigger:** On session start, compare `scene` time-of-day against real current time. If scene says "evening/night" but it's now morning (6≤hour<12), do a scene-only refresh:

```python
from datetime import datetime
scene = state.get("scene", "")
current_hour = datetime.now().hour
is_morning = 6 <= current_hour < 12

if any(kw in scene for kw in ["evening", "night", "dark"]) and is_morning:
    state["scene"] = "bedroom, bed, morning, soft window light"
    state["meta"]["last_updated"] = datetime.now().isoformat()
```

**Note:** posture/expression are no longer stored in state. They are determined at image generation time by the LLM.

**Full reference with example:** `ai_photo/references/waking-up-morning-state-transition.md`

### ⚠️ KeyError 陷阱：`intimacy` vs `outfit`

**症状：** `KeyError: 'intimacy'` 在 `state['intimacy']['nudity']` 处。

**根因：** `nudity` 在 `outfit` 分组下，不是 `intimacy` 分组下。实际的 `intimacy_mode` 是**顶层字符串**，不是 `intimacy` 对象。

```python
# ❌ 错误
state['intimacy']['nudity']  # KeyError

# ✅ 正确
state['outfit']['nudity']
```

**读取 state 后立即打印确认结构：**
```python
with open(STATE_PATH) as f:
    state = json.load(f)
print(json.dumps(state, indent=2))  # 先看结构再patch
```

| 访问方式 | 解析路径 | 实际文件位置 |
|---------|---------|------------|
| `read_file("girlfriend/state/live_state.json")` | 用户 home `/home/qicailiucai/` | `/home/qicailiucai/girlfriend/state/live_state.json` |
| `write_file("girlfriend/state/live_state.json")` | 用户 home `/home/qicailiucai/` | `/home/qicailiucai/girlfriend/state/live_state.json` |
| `momo_photo.py` 脚本 `STATE_PATH` | `BASE + "girlfriend/state/live_state.json"`（BASE=聊天机器人配置目录） | `/home/qicailiucai/.hermes/profiles/chat_bot/girlfriend/state/live_state.json` |

**结果：** `read_file`/`write_file` 用相对路径写到 `~/girlfriend/state/live_state.json`（用户 home），但脚本读的是聊天机器人配置目录下另一个文件。**更新了一个副本，脚本读的是另一个，生图用旧数据。**

**解法（已实装 2026-05-24）：**
~~1. **写两处：** 每次更新 `live_state.json` 时，用绝对路径写 `write_file` 到两个位置——先用 `read_file` 可读的路径，再用脚本路径。~~
~~2. **改脚本：** 标准化为一个路径（目前两方同时写是安全性最高的做法）。~~

在 `~/girlfriend/state/live_state.json` 建立了**符号链接**指向 `~/.hermes/profiles/chat_bot/girlfriend/state/live_state.json`。现在无论用绝对路径还是相对路径，读写都是同一个文件。

**仍需注意：** 符号链接只覆盖了 `live_state.json`。`character_profile.json` 等其他 `girlfriend/state/` 下的文件没有符号链接，操作它们时必须用绝对路径。

**快速验证脚本读的是什么：**
```bash
# 检查脚本实际读的路径
cat /home/qicailiucai/.hermes/profiles/chat_bot/girlfriend/state/live_state.json | python3 -m json.tool
# 检查 read_file 读的路径
ls -la girlfriend/state/live_state.json
# 如果不同 → diff 查看差异
```

### ⚠️ 生图前必须先更新 state（2026-05-25 新增）

**问题：** 生成图片时，脚本 `momo_photo.py` 读取 `live_state.json` 的当前值。如果先生成图片再更新 state，或者更新 state 的顺序不对，图片里的衣服/配饰/场景会不匹配。

**正确顺序：**
1. **先更新 state**（patch live_state.json）
2. **再生成图片**（python momo_photo.py）

**错误顺序（已踩坑 2026-05-25）：**
1. 先生成图片（此时 state 还是旧的）
2. 再更新 state
→ 图片穿的还是上一套衣服，不是最新的

**教训：** 用户说"小桃的鞋子还没脱呢"——就是因为先生成后更新state，prompt里还有旧鞋子。

**验证方法：** 生成前打印 `live_state.json` 确认 outfit 字段是否已更新。

## 使用原则

1. **字段扁平化**：`scene` 和 `appearance` 都是扁平字符串，不要再分层
2. **一致性**：每次生图必须基于当前状态
3. **英文值**：所有生图相关字段必须用英文 Danbooru
4. **变更需合理**：不能秒换衣服/瞬移
5. **meta 追踪**：`last_updated` 每次变更更新
