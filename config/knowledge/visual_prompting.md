# VisualContinuityAgent 视觉提示词手册

本手册是从通用服饰、动作、构图和成人场景标签资料中蒸馏出的写法，不注入原始整表。

## 服饰连续性

- 状态记录必须完整；每件衣物使用一个短语，如 `white_shirt`、`white_pleated_skirt`、`black_pantyhose`、`white_lace_panties`。
- 槽位数组从内到外排列。Bra 和内裤分别属于 `upper/lower`；袜类属于 `legwear`；鞋类属于 `footwear`。
- 状态变化以角色回复中已经完成的结果为准。未变化槽位保持，不根据镜头擅自删除衣物。

## 镜头与构图

- 明确观看某部位时，`camera.view` 只使用一个 `face_focus/chest_focus/foot_focus/pussy_focus/ass_focus` 等焦点。
- 没有特指部位时，`camera.view` 只使用一个 `medium_shot/full_shot/wide_shot` 等景别。
- 焦点与景别不叠加；`camera.angle` 可另选一个 `front_view/from_side/from_below/from_above/from_back`。
- 性爱互动可在更清楚表现主体与玩家关系时使用玩家 POV；普通展示仍选择最清楚的常规角度。
- 画面主体始终是角色。不要用第二个角色数量标签描述玩家；玩家只通过 POV、局部身体或动作关系出现。

## 动作与姿势

先确定一个核心可见行为，再选一个支撑姿势和必要表情。动作贵在准确，不堆叠同义标签。

常见组合：

- `presenting_foot` + `sitting_on_bed`
- `holding_shoes` + `sitting`
- `lifting_skirt` / `lifting_shirt` + `standing` 或 `sitting`
- `adjusting_clothes` + `standing`
- `giving` / `holding_<object>` + `outstretched_hand`
- `opening_door` + `standing`
- `leaning_forward` + `standing` 或 `sitting`

已经完成的动作写结果；正在进行的动作写过程。标签不足时，用一句客观英文动宾短语补充手、身体、道具和空间关系，例如 `gripping the skirt hem with both hands and lifting it toward the waist`。省略 `she/he`，不使用主人、客人、恋人等剧情称谓；涉及另一人时写客观对象，如 `touching a man's chest with one hand`。

亲密或性爱画面必须写出实际发生的一个核心双方行为，并用简短动作句说明接触或位置关系；不能只写泛泛的站立、坐着或张腿，也不要把多个行为叠成一幕。身体细节只保留与当前裸露、动作和观看重点直接相关的少量内容。

## 环境

`environment` 保持低比重：一个主要地点，加可选的一项光线、关键道具或空间关系即可，例如 `bedroom, soft warm light`、`classroom, late afternoon light`、`massage parlor, massage bed behind the character`。不重复人物动作，不写完整剧情句。

## 编辑检查

输出前只检查四点：状态是否与已发生事实一致；镜头是否突出本轮重点；动作与镜头是否冲突；动作和环境短语是否简洁。不要使用数值权重。长度只作编辑目标，不能成为取消状态提交、图片或整轮回复的原因。
