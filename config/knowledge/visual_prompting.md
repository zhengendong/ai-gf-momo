# VisualContinuityAgent 精简视觉提示词手册

本手册蒸馏自 `data/pxlsan-标签选择器-完整内容.xlsx` 的“服装 & 穿搭”“动作 & 姿态”“构图 & 视角”“场景 & 画面”“光影 & 氛围”等栏目。原表包含大量重复项和长尾标签，不直接放入每轮上下文；这里只保留组合方法、代表性词汇和冲突规则。

## 总体预算

- 只输出完成当前画面所需的最少标签，不堆同义词。
- 动作最多 3 个，姿势最多 2 个，表情最多 2 个，光线最多 2 个。
- 构图严格使用一个景别、一个角度、一个焦点；无必要时焦点为 `null`。
- 场景通常 2 至 4 个标签：地点、室内外、必要的时间或光线即可。
- 角色身份、外貌、身材、服饰状态、场景状态和质量词由后端注入；ShotSpec 不重复它们。
- 输出前删除同义、包含关系和互斥标签，优先保留更具体且更贴合用户观看目标的词。

## 服饰与穿搭

- 一件衣物始终是一个完整短语：`white_shirt`、`off-shoulder_shirt`、`white_pleated_skirt`、`black_pantyhose`、`high_heels`、`white_lace_panties`。
- 颜色、材质、款式只能修饰同一件衣物，不得拆成 `white`、`lace`、`panties` 等独立状态标签。
- 内外层按槽位保存。脱掉外层只暴露已存在的内层，不能因为常识推测而凭空新增 Bra 或内裤。
- 穿搭只记录真实存在且能影响后续画面的单品；避免同时写基础名和同义变体。

## 动作与姿势

代表性基础姿势：`standing`、`sitting`、`lying_down`、`on_back`、`on_knees`、`all_fours`、`crouching`。

- 先选一个主体姿势，再加一至两个真正影响画面的动作。
- 不同时输出 `standing/sitting/lying_down` 等互斥主体姿势。
- 不用多个近义标签反复描述同一只手、同一组腿或同一种朝向。
- 性爱场景必须包含明确的核心行为，而不是只写通用羞涩姿势。例如按实际行为选 `footjob`、`anal`、`vaginal`、`fellatio`、`handjob`、`paizuri`，再选择至多一个必要体位或肢体关系。不得把用户没有要求、角色回复没有完成的行为加进画面。

## 构图与视角

从原表蒸馏出的常用构图词：

- 景别：`close-up`、`macro_shot`、`medium_shot`、`cowboy_shot`、`full_shot`、`wide_shot`。
- 角度：`front_view`、`from_below`、`from_above`、`from_side`、`from_back`、`three-quarter view`。
- 焦点：`face_focus`、`foot_focus`、`chest_focus`、`pussy_focus`、`ass_focus`、`lower_body`、`upper_body`。

选择规则：

- 普通对话展示优先 `medium_shot + front_view`，不要附加无意义焦点。
- 展示整套穿搭优先 `full_shot`；环境关系重要时才使用 `wide_shot`。
- 局部观看必须使用 `close-up` 或 `macro_shot`，再加唯一的局部焦点，例如 `foot_focus`。
- `close-up/macro_shot` 不与 `full_shot/wide_shot/cowboy_shot` 共存。
- `from_below/from_above/from_side/from_back/front_view` 只保留一个主角度。
- `looking_down` 表示角色视线向下，不等于摄影机 `from_above`；不要混淆人物视线与镜头角度。

## 受控权重

- 普通画面不使用权重。
- 只有一个核心视觉目标被其他内容明显干扰时，才可设置一个强化组，权重范围 `1.05` 至 `1.20`，例如 `(foot_focus:1.1)` 或 `(close-up, foot_focus:1.1)`。
- 显式权重统一写作圆括号 `(tags:weight)`；需要整体弱化多个标签时写 `(cat girl, cat ears, cat tail:0.9)`。禁止 `[tags:0.9]`，它不是跨 ComfyUI/A1111 都可靠的显式降权语法。
- 不强化质量词、角色身份、持久服饰或场景；这些由后端统一管理。
- 局部近距离特写由后端自动将角色外貌细节和服饰降为 `0.9`，VisualContinuityAgent 不自行复制或弱化这些标签。
- 不同时对同一概念强化和弱化，不使用多层嵌套权重。

## 场景与光线

- 场景只保留能说明环境的核心词，例如 `bedroom, indoors, evening` 或 `hotel_room, indoors, night`。
- 光线最多选择一个主要来源和一个效果，例如 `warm_lighting, soft_lighting`。
- 常用光影参考：`soft lighting`、`rim lighting`、`volumetric lighting`、`studio lighting`、`bloom`。
- 场景状态不记录临时动作、镜头或人物表情。

## 输出前自检

1. 服饰是否一件一个短语？
2. 动作和姿势是否精简且没有冲突？
3. 是否只有一个景别、一个角度、一个焦点？
4. 局部特写是否真正指向用户要求的部位？
5. 性爱画面是否包含准确核心行为，而非泛化动作？
6. 场景是否控制在 2 至 4 个必要标签？
7. 是否无需权重也能表达；若用了权重，是否只有一组且不超过 1.20？
