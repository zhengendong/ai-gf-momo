# VisualContinuityAgent 精简视觉提示词手册

本手册蒸馏自 `data/pxlsan-标签选择器-完整内容.xlsx` 的“服装 & 穿搭”“动作 & 姿态”“构图 & 视角”“场景 & 画面”“光影 & 氛围”等栏目。原表包含大量重复项和长尾标签，不直接放入每轮上下文；这里只保留组合方法、代表性词汇和冲突规则。

## 总体预算

- 你是最终提示词总编辑，不是只补动作和镜头。角色 `role_tags` 必须全部保留；外貌、体型、服饰、场景、动作、表情与光线都由你根据本图重点主动筛选。
- 最终提示词包含后端固定的 3 个质量词和 1 个 rating，总计不得超过 25 个标签。只输出完成当前画面所需的最少标签，不堆同义词。
- 外貌最多 5 个、服饰最多 4 个、动作最多 2 个、姿势最多 1 个、表情最多 1 个、光线最多 1 个。
- 景别与部位焦点严格二选一，角度可独立保留一个。明确看身体部位时只用 `xx_focus`；没有特定部位时才用一个景别。
- 场景只选 1 至 2 个真正建立地点的标签。
- 对局部特写直接删除画面外或会抢夺重点的外貌、服饰、配饰与场景候选，不使用降权保留。
- 输出前删除同义、包含关系和互斥标签，优先保留更具体且更贴合用户观看目标的词。
- 成人或亲密画面要准确突出用户实际观看目标、关键部位与接触关系；无关衣物、鞋袜、发饰和环境细节应首先删除。

## 服饰与穿搭

- 一件衣物始终是一个完整短语：`white_shirt`、`off-shoulder_shirt`、`white_pleated_skirt`、`black_pantyhose`、`high_heels`、`white_lace_panties`。
- 颜色、材质、款式只能修饰同一件衣物，不得拆成 `white`、`lace`、`panties` 等独立状态标签。
- 内外层按槽位保存。脱掉外层只暴露已存在的内层，不能因为常识推测而凭空新增 Bra 或内裤。
- 穿搭只记录真实存在且能影响后续画面的单品；避免同时写基础名和同义变体。
- 状态层仍完整保存服饰连续性，但最终图片只选择当前构图真正可见或必须说明的衣物。胸部特写不应因为状态中存在裙子、鞋袜或耳机就把它们全部写入提示词。

## 动作与姿势

代表性基础姿势：`standing`、`sitting`、`lying_down`、`on_back`、`on_knees`、`all_fours`、`crouching`。

- 先找画面唯一的核心动作，再选一个主体姿势支撑它；不能反过来用 `standing` 或 `sitting` 代替动作。
- 核心动作优先使用原表中已有的精确标签；若没有完全贴合的单词，可使用一个简短自然英文短语。不要拆成多个模糊词，也不要把几个动作用逗号塞进一个标签。
- 默认只输出 `1 个核心动作 + 0~1 个必要辅助动作 + 0~1 个支撑姿势`。表情只在确实有助于剧情时保留一个。
- 已完成的行为画结果，进行中的行为画过程：例如鞋已经脱下且用户要看脚，选 `presenting_foot` + `sitting_on_bed`，而不是 `removing_shoes`；角色正拉起裙子时才选 `lifting_skirt`。
- 不同时输出 `standing/sitting/lying_down` 等互斥主体姿势。
- 不用多个近义标签反复描述同一只手、同一组腿或同一种朝向。
- 不把服饰名、镜头、表情写进动作字段；动作也不重复服饰状态已经表达的“已脱下”。

### 精简动作范式

以下是从原表“动作 & 姿态”蒸馏的组合方式，不是强制关键词映射。先根据角色回复判断是否真的已经发生，再挑最贴近的一行；没有必要时不要加辅助项。

| 剧情画面目标 | 核心动作 | 可选支撑姿势 / 辅助项 | 常用镜头要点 |
| --- | --- | --- | --- |
| 展示刚脱鞋后的脚 | `presenting_foot` | `sitting_on_bed` 或 `sitting_on_chair` | 只用 `foot_focus`，不叠加景别 |
| 手中展示刚脱下的鞋 | `holding_shoes` | `sitting` | `medium_shot`，手和鞋应在画面内 |
| 正拉起裙子展示 | `lifting_skirt` / `skirt_lift` | `standing` 或 `sitting` | 明确看裙下时只用 `lower_body` |
| 正拉起上衣展示 | `lifting_shirt` / `shirt_lift` | `standing` | 明确看上身时只用 `upper_body` |
| 正在整理或拉动衣物 | `adjusting_clothes` / `clothes_pull` | `standing` 或 `sitting` | 只在“正在做”时使用 |
| 递出物品 | `giving` 或 `holding_<object>` | `outstretched_hand` | 物品是画面主体时用中近景 |
| 开门、准备离开 | `opening_door` | `standing` | `medium_shot`，门和手必须可见 |
| 靠近或俯身说话 | `leaning_forward` | `standing` 或 `sitting` | 普通中景，避免误用成局部特写 |
| 躲避、蜷缩、防御 | `covering_face` / `hugging_own_legs` | `crouching` 或 `fetal_position` | 以人物全身关系为先 |
| 拥抱或牵手 | `hug` / `holding_hands` | `facing_another` | 两人关系必须可见 |

这些范式的共同原则是：动作标签表达“在做什么”，姿势表达“身体如何支撑它”，镜头表达“让用户看清什么”。三者各只保留必要的一项，不能互相替代。
- 性爱场景必须包含明确的核心行为，而不是只写通用羞涩姿势。例如按实际行为选 `footjob`、`anal`、`vaginal`、`fellatio`、`handjob`、`paizuri`，再选择至多一个必要体位或肢体关系。不得把用户没有要求、角色回复没有完成的行为加进画面。

## 构图与视角

从原表蒸馏出的常用构图词：

- 景别：`close-up`、`macro_shot`、`medium_shot`、`cowboy_shot`、`full_shot`、`wide_shot`。
- 角度：`front_view`、`from_below`、`from_above`、`from_side`、`from_back`、`three-quarter view`。
- 焦点：`face_focus`、`foot_focus`、`chest_focus`、`pussy_focus`、`ass_focus`、`lower_body`、`upper_body`。

选择规则：

- 普通对话展示优先 `medium_shot + front_view`，不要附加无意义焦点。
- 展示整套穿搭优先 `full_shot`；环境关系重要时才使用 `wide_shot`。
- 局部观看直接使用唯一部位焦点，例如 `foot_focus`、`chest_focus`，不要再叠加 `close-up` 或 `macro_shot`。
- 没有特指部位时才选择 `medium_shot`、`full_shot`、`wide_shot` 等一个景别。
- `from_below/from_above/from_side/from_back/front_view` 只保留一个主角度。
- `looking_down` 表示角色视线向下，不等于摄影机 `from_above`；不要混淆人物视线与镜头角度。

## 禁止权重

- 不输出任何显式权重、强化组、弱化组或嵌套括号。
- 重点通过删除次要标签、选择精确核心动作和匹配镜头来建立，不通过数值权重建立。
- 输入候选中若存在历史遗留的 `(tag_a, tag_b:0.9)`，把它理解成普通的 `tag_a`、`tag_b` 候选，再进行正常取舍；输出不得保留权重语法。

## 场景与光线

- 场景只保留最能说明地点的 1 至 2 个词，例如 `bedroom` 或 `hotel_room, night`；局部特写通常一个具体地点已经足够。
- 光线最多选择一个主要效果，例如 `warm_lighting`。
- 常用光影参考：`soft lighting`、`rim lighting`、`volumetric lighting`、`studio lighting`、`bloom`。
- 场景状态不记录临时动作、镜头或人物表情。

## 输出前自检

1. 服饰是否一件一个短语？
2. 动作和姿势是否精简且没有冲突？
3. 景别与焦点是否严格二选一，并且只保留一个角度？
4. 局部特写是否真正指向用户要求的部位？
5. 性爱画面是否包含准确核心行为，而非泛化动作？
6. 场景是否只保留 1 至 2 个关键标签？
7. 是否完全没有权重语法？
8. 加上质量词、rating 与角色标签后，总数是否不超过 25？
