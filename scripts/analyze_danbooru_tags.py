"""
Analyze SAA danbooru_e621_merged_zh_cn.csv for general Danbooru tags.

Input CSV format has no header:
  tag, category_id, zh_cn

We keep category_id == "0" and classify tags with conservative heuristics.
"""

import csv
import json
import re
from collections import OrderedDict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(r"D:\Arc-AI绘画\saa-win32-x64\resources\app\data\danbooru_e621_merged_zh_cn.csv")
OUT_DIR = ROOT / "docs" / "tag_library"
OUT_JSON = OUT_DIR / "danbooru_general_tags_categorized.json"
OUT_MD = OUT_DIR / "danbooru_general_tags_analysis.md"


CATEGORY_NAMES = OrderedDict([
    ("clothing", "服饰与穿搭"),
    ("pose_action", "动作姿势"),
    ("expression_emotion", "表情情绪"),
    ("hair", "发型发色"),
    ("accessory_item", "配饰物品"),
    ("lighting_mood", "光影氛围"),
    ("scene_background", "场景画面"),
    ("composition_camera", "构图视角"),
    ("character_setting", "角色设定"),
    ("nsfw", "NSFW 元素"),
    ("other", "其他通用标签"),
])


PATTERNS = {
    "clothing": [
        r"(^|[_-])(shirt|skirt|dress|sweater|jacket|coat|hoodie|uniform|suit|pants|shorts|jeans|leggings|apron|kimono|yukata|maid|swimsuit|bikini|bra|panties|lingerie|thighhighs|stockings|socks|shoes|boots|heels|gloves|hat|cap|ribbon|bowtie|necktie|scarf|collar|choker|belt|cape|cloak|robe|underwear|clothes|outfit|costume|sleeves|sleeveless|bare_shoulders|off_shoulder|open_clothes|open_shirt|open_jacket|unbuttoned)([_-]|$)",
    ],
    "pose_action": [
        r"(^|[_-])(standing|sitting|kneeling|lying|crouching|squatting|walking|running|jumping|dancing|leaning|bending|reaching|holding|grabbing|hugging|kissing|waving|pointing|stretching|sleeping|eating|drinking|fighting|riding|carrying|all_fours|on_all_fours|arms|hands|legs|feet|spread_legs|crossed_legs|wariza|seiza|salute|peace_sign)([_-]|$)",
    ],
    "expression_emotion": [
        r"(^|[_-])(smile|blush|crying|tears|angry|sad|happy|embarrassed|shy|surprised|scared|afraid|nervous|worried|annoyed|pout|pouting|laughing|grin|frown|expression|closed_eyes|closed_mouth|open_mouth|parted_lips|tongue|teeth|stare|glaring|wink|sleepy|drunk|ahegao)([_-]|$)",
    ],
    "hair": [
        r"(^|[_-])(hair|bangs|twintails|ponytail|braid|drill_hair|ahoge|hair_ornament|hairclip|hairband|hair_ribbon|hair_bow|forehead|sidelocks|bob_cut|hime_cut|short_hair|long_hair|medium_hair|messy_hair|straight_hair|curly_hair|wavy_hair|blonde|brunette|black_hair|blue_hair|green_hair|pink_hair|purple_hair|red_hair|white_hair|grey_hair|silver_hair)([_-]|$)",
    ],
    "accessory_item": [
        r"(^|[_-])(necklace|bracelet|ring|earrings|piercing|glasses|goggles|mask|bag|backpack|umbrella|weapon|sword|gun|knife|staff|wand|phone|book|cup|bottle|flower|food|toy|plush|camera|microphone|instrument|tail|wings|horns|halo|bow|jewelry)([_-]|$)",
    ],
    "lighting_mood": [
        r"(^|[_-])(light|lighting|shadow|shade|sunlight|moonlight|backlighting|rim_light|volumetric|glow|sparkle|bloom|lens_flare|dim|bright|sunset|dawn|dusk|fog|mist|rain|snow|wind|atmosphere|dramatic|warm|cool|colorful)([_-]|$)",
    ],
    "scene_background": [
        r"(^|[_-])(background|scenery|room|bedroom|bathroom|kitchen|classroom|school|office|street|city|building|house|home|park|forest|beach|ocean|river|pool|garden|sky|cloud|mountain|field|road|train|car|bus|bed|sofa|chair|table|window|door|wall|floor|tatami|indoors|outdoors|night)([_-]|$)",
    ],
    "composition_camera": [
        r"(^|[_-])(close-up|closeup|upper_body|cowboy_shot|full_body|portrait|profile|from_above|from_below|from_behind|side_view|front_view|back_view|wide_shot|medium_shot|dutch_angle|fisheye|depth_of_field|blurry|foreground|perspective|pov|looking_at_viewer|looking_back|focus|solo_focus|looking)([_-]|$)",
    ],
    "character_setting": [
        r"(^1girl$|^1boy$|^2girls$|^2boys$|^solo$|^multiple_girls$|^multiple_boys$|^girl$|^boy$|^woman$|^man$|^child$|^adult$|^chibi$|^loli$|^shota$|^monster_girl$|^animal_ears$|^cat_girl$|^fox_girl$|^maid$|^student$|^teacher$|^idol$|^nurse$|^princess$|^witch$|^angel$|^demon$|^elf$|^robot$|^android$|^body_type$|(^|[_-])(petite|wide_hips|muscular|slim|eyes|skin|pupils)([_-]|$))",
    ],
    "nsfw": [
        r"(^|[_-])(nsfw|nude|naked|topless|bottomless|breasts|nipples|areola|pussy|vagina|penis|testicles|ass|butt|anus|anal|sex|cum|semen|paizuri|fellatio|cunnilingus|masturbation|orgasm|spread_pussy|presenting|cameltoe|pantyshot|upskirt|cleavage|underboob|sideboob|pubic|sex_toy|bdsm|bondage|gag|leash|tentacles|rape|molestation|explicit)([_-]|$)",
    ],
}


ORDER = [
    "nsfw",
    "composition_camera",
    "expression_emotion",
    "pose_action",
    "hair",
    "clothing",
    "accessory_item",
    "lighting_mood",
    "scene_background",
    "character_setting",
]


def matches(tag: str, category: str) -> bool:
    return any(re.search(pattern, tag) for pattern in PATTERNS[category])


def classify(tag: str) -> str:
    for category in ORDER:
        if matches(tag, category):
            return category
    return "other"


def read_general_tags() -> list[dict]:
    rows = []
    with SOURCE.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 3:
                continue
            tag, category_id, zh = row[0].strip(), row[1].strip(), row[2].strip()
            if category_id != "0" or not tag:
                continue
            rows.append({"tag": tag, "zh": zh})
    return rows


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = read_general_tags()

    categories = OrderedDict((key, []) for key in CATEGORY_NAMES)
    for item in rows:
        category = classify(item["tag"].lower())
        categories[category].append(item)

    payload = {
        "source": str(SOURCE),
        "filter": "CSV column B/category_id == 0",
        "total_general_tags": len(rows),
        "categories": categories,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Danbooru 通用标签分类分析",
        "",
        f"- 来源：`{SOURCE}`",
        "- 过滤条件：B 列 / category_id 为 `0`",
        f"- 通用标签总数：`{len(rows)}`",
        "- 说明：分类由保守关键词规则生成，一个标签只归入一个主类；完整结果见 `danbooru_general_tags_categorized.json`。",
        "",
        "## 分类统计",
        "",
        "| 分类 | 数量 | 示例 |",
        "|---|---:|---|",
    ]
    for key, title in CATEGORY_NAMES.items():
        items = categories[key]
        sample = "、".join(f"`{x['tag']}`（{x['zh']}）" for x in items[:12])
        lines.append(f"| {title} | {len(items)} | {sample} |")

    lines.extend([
        "",
        "## 生图技能赋能思路",
        "",
        "### 1. Prompt 分层生成",
        "",
        "把最终 prompt 拆成稳定层和动态层：",
        "",
        "```text",
        "角色设定层：角色锚点、发型发色、体型",
        "状态层：当前穿着、场景、光影",
        "意图层：本轮动作、表情、镜头、NSFW 元素",
        "质量层：masterpiece, best quality 等固定尾缀",
        "```",
        "",
        "标签库可以为每一层提供候选标签、同义标签和冲突检查。",
        "",
        "### 2. 视角/动作规则引擎",
        "",
        "将 `pussy_focus`、`feet_focus`、`from_behind` 等构图视角标签与必要动作姿势绑定。例如：",
        "",
        "- `pussy_focus` 自动补 `lying_down, legs_spread, presenting_pussy`",
        "- `feet_focus` 自动补 `sitting, legs_extended, feet_forward`",
        "- `from_behind` 自动补 `on_all_fours, looking_back`",
        "",
        "这样可以减少 LLM 写出互相矛盾标签的概率。",
        "",
        "### 3. 穿着状态机",
        "",
        "用服饰标签库定义可脱卸层级：外套、上衣、裙裤、袜鞋、内衣、裸露、饰品。角色状态只保存当前完整穿着；生图时由工具层注入。",
        "",
        "### 4. NSFW 安全一致性",
        "",
        "NSFW 标签不应该自由散落在 prompt 里，而应通过状态和意图同时确认：",
        "",
        "- 状态明确 `topless` / `completely_nude` 才注入裸露标签",
        "- 聚焦标签触发动作补全",
        "- 裸露状态自动把 `rating:general` 修正为 `rating:nsfw`",
        "",
        "### 5. 前端配置面板",
        "",
        "前端可用这些分类生成标签选择器：服饰、场景、光影、镜头、动作、表情、NSFW。用户编辑状态时不再手写标签，减少中文残留和错误标签。",
    ])

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "source": str(SOURCE),
        "total_general_tags": len(rows),
        "markdown": str(OUT_MD),
        "json": str(OUT_JSON),
        "counts": {CATEGORY_NAMES[k]: len(v) for k, v in categories.items()},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
