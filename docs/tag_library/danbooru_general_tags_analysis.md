# Danbooru 通用标签分类分析

- 来源：`D:\Arc-AI绘画\saa-win32-x64\resources\app\data\danbooru_e621_merged_zh_cn.csv`
- 过滤条件：B 列 / category_id 为 `0`
- 通用标签总数：`37045`
- 说明：分类由保守关键词规则生成，一个标签只归入一个主类；完整结果见 `danbooru_general_tags_categorized.json`。

## 分类统计

| 分类 | 数量 | 示例 |
|---|---:|---|
| 服饰与穿搭 | 4285 | `shirt`（衬衫）、`long_sleeves`（长袖）、`skirt`（裙子）、`gloves`（手套）、`dress`（连衣裙）、`hat`（帽子）、`thighhighs`（大腿袜）、`ribbon`（缎带）、`jacket`（夹克）、`bare_shoulders`（露肩）、`white_shirt`（白衬衫）、`school_uniform`（校服） |
| 动作姿势 | 1314 | `holding`（手持）、`sitting`（坐姿）、`standing`（站姿）、`lying`（躺姿）、`holding_weapon`（持械）、`spread_legs`（分腿站立）、`feet`（脚部）、`arms_up`（举臂）、`hands_up`（举手）、`feet_out_of_frame`（足部出框）、`legs`（腿部）、`bare_arms`（裸露手臂） |
| 表情情绪 | 234 | `blush`（脸红）、`smile`（微笑）、`open_mouth`（张嘴）、`closed_mouth`（闭嘴）、`closed_eyes`（闭眼）、`teeth`（牙齿）、`parted_lips`（微张嘴唇）、`tongue`（吐舌）、`tongue_out`（吐舌）、`grin`（咧嘴笑）、`tears`（眼泪）、`upper_teeth_only`（仅露上齿） |
| 发型发色 | 792 | `long_hair`（长发）、`short_hair`（短发）、`blonde_hair`（金发）、`black_hair`（黑发）、`brown_hair`（棕发）、`hair_ornament`（发饰）、`hair_between_eyes`（遮眼发）、`very_long_hair`（超长发）、`twintails`（双马尾）、`blue_hair`（蓝发）、`multicolored_hair`（彩色头发）、`white_hair`（银发） |
| 配饰物品 | 1950 | `bow`（蝴蝶结）、`jewelry`（珠宝）、`tail`（尾巴）、`flower`（花朵）、`weapon`（武器）、`earrings`（耳环）、`horns`（角）、`food`（食物）、`wings`（翅膀）、`glasses`（眼镜）、`halo`（光环）、`sword`（刀剑） |
| 光影氛围 | 199 | `sparkle`（闪光）、`shadow`（阴影）、`bright_pupils`（明亮瞳孔）、`sunlight`（阳光）、`light_particles`（光粒）、`wind`（风）、`snow`（雪景）、`lens_flare`（镜头光晕）、`rain`（雨）、`backlighting`（逆光）、`sunset`（日落）、`light_rays`（光线） |
| 场景画面 | 657 | `simple_background`（简单背景）、`white_background`（白色背景）、`outdoors`（户外）、`sky`（天空）、`indoors`（室内）、`cloud`（云朵）、`grey_background`（灰色背景）、`blue_sky`（蓝天）、`gradient_background`（渐变背景）、`window`（窗户）、`blue_background`（蓝色背景）、`night`（夜晚） |
| 构图视角 | 163 | `looking_at_viewer`（看向观众）、`full_body`（全身）、`upper_body`（上半身）、`male_focus`（男性主角）、`cowboy_shot`（牛仔式构图）、`solo_focus`（单人焦点）、`looking_at_another`（注视他人）、`looking_back`（回眸）、`from_behind`（背视）、`blurry`（模糊）、`looking_to_the_side`（侧视）、`blurry_background`（模糊背景） |
| 角色设定 | 254 | `1girl`（1个女孩）、`solo`（单人）、`blue_eyes`（蓝眼睛）、`multiple_girls`（多个女孩）、`1boy`（1个男孩）、`red_eyes`（红眼睛）、`animal_ears`（兽耳）、`2girls`（2个女孩）、`green_eyes`（绿瞳）、`purple_eyes`（紫瞳）、`brown_eyes`（棕瞳）、`yellow_eyes`（金瞳） |
| NSFW 元素 | 987 | `breasts`（胸部）、`large_breasts`（巨乳）、`cleavage`（乳沟）、`medium_breasts`（中等胸部）、`nipples`（乳头）、`ass`（臀部）、`small_breasts`（贫乳）、`nude`（裸体）、`penis`（阴茎）、`pussy`（阴部）、`sex`（性行为）、`cum`（精液） |
| 其他通用标签 | 26210 | `navel`（肚脐）、`collarbone`（锁骨）、`monochrome`（单色）、`heart`（心形）、`thighs`（大腿）、`:d`（d:XD）、`hetero`（异性恋）、`pantyhose`（连裤袜）、`sweat`（汗珠）、`comic`（漫画）、`frills`（荷叶边）、`greyscale`（灰度） |

## 生图技能赋能思路

### 1. Prompt 分层生成

把最终 prompt 拆成稳定层和动态层：

```text
角色设定层：角色锚点、发型发色、体型
状态层：当前穿着、场景、光影
意图层：本轮动作、表情、镜头、NSFW 元素
质量层：masterpiece, best quality 等固定尾缀
```

标签库可以为每一层提供候选标签、同义标签和冲突检查。

### 2. 视角/动作规则引擎

将 `pussy_focus`、`feet_focus`、`from_behind` 等构图视角标签与必要动作姿势绑定。例如：

- `pussy_focus` 自动补 `lying_down, legs_spread, presenting_pussy`
- `feet_focus` 自动补 `sitting, legs_extended, feet_forward`
- `from_behind` 自动补 `on_all_fours, looking_back`

这样可以减少 LLM 写出互相矛盾标签的概率。

### 3. 穿着状态机

用服饰标签库定义可脱卸层级：外套、上衣、裙裤、袜鞋、内衣、裸露、饰品。角色状态只保存当前完整穿着；生图时由工具层注入。

### 4. NSFW 安全一致性

NSFW 标签不应该自由散落在 prompt 里，而应通过状态和意图同时确认：

- 状态明确 `topless` / `completely_nude` 才注入裸露标签
- 聚焦标签触发动作补全
- 裸露状态自动把 `rating:general` 修正为 `rating:nsfw`

### 5. 前端配置面板

前端可用这些分类生成标签选择器：服饰、场景、光影、镜头、动作、表情、NSFW。用户编辑状态时不再手写标签，减少中文残留和错误标签。
