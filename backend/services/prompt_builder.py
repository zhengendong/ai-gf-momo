"""
Prompt 构建器
从角色配置和状态文件构建最终英文 Danbooru prompt。
"""

import re
import logging

from ..core.state import read_status, read_state_snapshot
from ..core.characters import get_active
from ..core.context import load_character_profile

logger = logging.getLogger(__name__)

EXPLICIT_NUDE_TAGS = {
    "completely_nude",
    "nude",
    "naked",
    "bare_body",
    "topless",
    "bottomless",
    "no_bra",
    "no_panties",
}

CHINESE_NUDE_WORDS = ("全裸", "裸体", "脱光", "一丝不挂", "没穿衣服", "裸着")

ACCESSORY_HINTS = (
    "necklace",
    "collar",
    "bracelet",
    "ring",
    "earrings",
    "hair_ornament",
    "ribbon",
    "choker",
    "glasses",
)

CLOTHING_HINTS = (
    "shirt",
    "blouse",
    "sweater",
    "hoodie",
    "jacket",
    "coat",
    "dress",
    "skirt",
    "shorts",
    "pants",
    "jeans",
    "bra",
    "panties",
    "lingerie",
    "bikini",
    "swimsuit",
    "uniform",
    "apron",
    "shoe",
    "shoes",
    "boot",
    "boots",
    "sneaker",
    "sneakers",
    "sandal",
    "sandals",
    "mary_jane",
    "loafers",
    "heels",
    "sock",
    "socks",
    "thighhigh",
    "thighhighs",
    "stocking",
    "stockings",
    "pantyhose",
    "tights",
    "collar",
    "choker",
    "necklace",
    "ribbon",
    "hair_ornament",
    "glasses",
    "hat",
    "cap",
)

CONFLICT_GROUPS = {
    "body_pose": {
        "standing",
        "sitting",
        "lying",
        "lying_down",
        "kneeling",
        "on_all_fours",
        "all_fours",
        "crouching",
        "squatting",
    },
    "shot": {
        "close-up",
        "closeup",
        "medium_shot",
        "medium shot",
        "wide_shot",
        "full_body",
        "upper_body",
        "cowboy_shot",
    },
    "angle": {
        "from_behind",
        "from_above",
        "from_below",
        "front_view",
        "back_view",
        "side_view",
    },
}

POSE_OVERRIDE_TAGS = {
    "standing",
    "sitting",
    "sitting_on_bed",
    "sitting_on_chair",
    "sitting_on_floor",
    "seiza",
    "lying",
    "lying_down",
    "lying_on_bed",
    "lying_down_on_bed",
    "prone",
    "on_stomach",
    "kneeling",
    "on_all_fours",
    "all_fours",
    "crouching",
    "squatting",
}

REPLY_POSE_OVERRIDES = (
    ("standing", ("站着", "站起", "站起来", "站在", "站到", "站好", "站直")),
    ("sitting", ("坐着", "坐下", "坐在", "坐到", "坐回", "坐好")),
    ("on_stomach", ("趴着", "趴下", "趴在", "趴好")),
    ("lying_down", ("躺着", "躺下", "躺在", "躺到", "躺好")),
)

CAMERA_ACTION_RULES = [
    {
        "name": "pussy_focus",
        "triggers": {"pussy_focus", "spread_pussy"},
        "add": [
            "lying_down",
            "legs_spread",
            "presenting_pussy",
            "close-up",
            "pussy_focus",
        ],
        "remove_groups": {"body_pose", "shot"},
    },
    {
        "name": "feet_focus",
        "triggers": {"feet_focus", "foot_focus"},
        "add": [
            "sitting",
            "legs_extended",
            "feet_forward",
            "close-up",
            "feet_focus",
            "from_below",
        ],
        "remove_groups": {"body_pose", "shot", "angle"},
    },
    {
        "name": "chest_focus",
        "triggers": {"chest_focus", "breast_focus"},
        "add": [
            "upper_body",
            "close-up",
            "chest_focus",
        ],
        "remove_groups": {"shot"},
    },
    {
        "name": "face_focus",
        "triggers": {"face_focus"},
        "add": [
            "close-up",
            "face_focus",
            "looking_at_viewer",
        ],
        "remove_groups": {"shot"},
    },
    {
        "name": "from_behind",
        "triggers": {"from_behind", "back_view"},
        "add": [
            "on_all_fours",
            "looking_back",
            "from_behind",
        ],
        "remove_groups": {"body_pose", "angle"},
    },
    {
        "name": "full_body",
        "triggers": {"full_body", "wide_shot"},
        "add": [
            "standing",
            "full_body",
        ],
        "remove_groups": {"body_pose", "shot"},
        "skip_if": {
            "pussy_focus",
            "feet_focus",
            "chest_focus",
            "face_focus",
            "from_behind",
        },
    },
]


def parse_clothing_status(status_md: str) -> list[str]:
    """
    从 status.md 解析 ## 穿着 section，返回 SD 标签列表。
    状态文件直接写英文标签，不做翻译。

    重要：未知/空/中文残留不等于 nude。只有状态明确写了裸露标签，才注入 nude 标签。
    """
    m = re.search(r"## 穿着\n(.*?)(?=## |\Z)", status_md, re.DOTALL)
    if not m:
        logger.warning("status.md 缺少 ## 穿着 section，跳过服饰注入")
        return []

    content = m.group(1).strip()
    if not content:
        logger.warning("status.md 穿着为空，跳过服饰注入")
        return []

    if any(w in content for w in CHINESE_NUDE_WORDS):
        logger.warning("穿着状态含中文裸露描述，按明确 nude 处理；建议改为英文标签")
        return ["completely_nude", "nude", "bare_body"]

    lines = content.strip().split("\n")
    tags = []
    for line in lines:
        line = line.strip()
        if not line.startswith("-"):
            continue
        raw = line[1:].strip()
        for tag in _split_status_tags(raw):
            if tag not in tags:
                tags.append(tag)

    if not tags:
        logger.warning("穿着状态没有可用英文标签，跳过服饰注入")
        return []

    logger.info(f"已从状态生成服饰标签: {tags}")
    return tags


def get_clothing_tags(character: str = None) -> str:
    """获取角色的服饰标签字符串"""
    char = character or get_active()
    try:
        status_md = read_status(char)
        tags = parse_clothing_status(status_md)
        if not tags:
            snapshot = read_state_snapshot(char)
            tags = snapshot.get("outfit", {}).get("tags", [])
    except Exception as e:
        logger.warning(f"读取 status.md 失败，回退 state_snapshot: {e}")
        snapshot = read_state_snapshot(char)
        tags = snapshot.get("outfit", {}).get("tags", [])
    tags = _resolve_clothing_conflicts(tags)
    return ", ".join(tags)


def parse_scene_status(status_md: str) -> list[str]:
    """从 status.md 的 ## 场景细节 section 解析英文 SD 标签。"""
    m = re.search(r"## 场景细节\n(.*?)(?=## |\Z)", status_md, re.DOTALL)
    if not m:
        logger.warning("status.md 缺少 ## 场景细节 section，跳过场景注入")
        return []

    content = m.group(1).strip()
    if not content:
        logger.warning("status.md 场景细节为空，跳过场景注入")
        return []

    tags = []
    for line in content.split("\n"):
        line = line.strip()
        if not line.startswith("-"):
            continue
        raw = line[1:].strip()
        for tag in _split_status_tags(raw):
            if tag not in tags:
                tags.append(tag)

    if not tags:
        logger.warning("场景细节没有可用英文标签，跳过场景注入")
        return []

    logger.info(f"已从状态生成场景标签: {tags}")
    return tags


def get_scene_tags(character: str = None) -> str:
    """获取角色当前场景标签字符串，用于生图 prompt 注入。"""
    char = character or get_active()
    try:
        status_md = read_status(char)
        tags = parse_scene_status(status_md)
        if not tags:
            snapshot = read_state_snapshot(char)
            tags = snapshot.get("scene", {}).get("tags", [])
    except Exception as e:
        logger.warning(f"读取 status.md 场景失败，回退 state_snapshot: {e}")
        snapshot = read_state_snapshot(char)
        tags = snapshot.get("scene", {}).get("tags", [])
    return ", ".join(tags)


def get_visual_anchor_tags(character: str) -> dict:
    """获取角色生图皮肤/视觉锚点标签，兼容新旧 profile 结构。"""
    profile = load_character_profile(character)
    visual = profile.get("visual_anchor") or {}
    return {
        "role_tags": visual.get("role_tags") or profile.get("avatar_role", ""),
        "body_tags": visual.get("body_tags") or profile.get("body_type", ""),
        "appearance_tags": visual.get("appearance_tags") or profile.get("appearance", ""),
    }


def normalize_prompt(prompt: str) -> str:
    """标准化 prompt 标签：去重、修正非法 rating。"""
    tags = _split_prompt_tags(prompt)
    return ", ".join(_dedupe_tags(tags))


def sanitize_dynamic_photo_prompt(prompt: str) -> str:
    """
    Remove persistent outfit tags from the LLM-provided photo prompt.

    status.md is the single source of truth for clothing. The Agent may still
    mention clothes in photo_prompt, especially after old prompts or repairs;
    stripping them here prevents "two outfits" from reaching ComfyUI.
    """
    kept = []
    removed = []
    for tag in _split_prompt_tags(prompt or ""):
        norm = _norm_tag(tag)
        if _is_persistent_outfit_prompt_tag(norm):
            removed.append(tag)
            continue
        kept.append(tag)
    if removed:
        logger.info("已从 photo_prompt 移除服饰/持久身体状态标签: %s", removed)
    return ", ".join(_dedupe_tags(kept))


def normalize_camera_action_tags(prompt: str) -> str:
    """补齐视角/动作必需标签，并删除明显冲突标签。"""
    tags = _dedupe_tags(_split_prompt_tags(prompt))
    normalized = {_norm_tag(t) for t in tags}

    for rule in CAMERA_ACTION_RULES:
        if rule.get("skip_if") and normalized & rule["skip_if"]:
            continue
        if not (normalized & rule["triggers"]):
            continue

        remove_tags = set()
        for group in rule.get("remove_groups", set()):
            remove_tags.update(CONFLICT_GROUPS[group])

        tags = [t for t in tags if _norm_tag(t) not in remove_tags]
        for tag in rule["add"]:
            tags.append(tag)
        tags = _dedupe_tags(tags)
        normalized = {_norm_tag(t) for t in tags}
        logger.info(f"已应用视角/动作规则: {rule['name']}")

    return ", ".join(tags)


def harmonize_pose_from_reply(prompt: str, reply: str | None = None) -> str:
    """Lightly replace only the explicit body pose tags when reply is clear.

    This never cancels image generation and never calls the LLM. It preserves
    the model's prompt, replacing only simple conflicting pose tags for the
    currently supported reply poses: standing, sitting, prone/on_stomach, lying.
    """
    desired = _reply_pose_override(reply or "")
    if not desired:
        return prompt

    tags = _split_prompt_tags(prompt)
    kept = [tag for tag in tags if _norm_tag(tag) not in POSE_OVERRIDE_TAGS]
    if desired not in {_norm_tag(tag) for tag in kept}:
        kept.append(desired)
    logger.info("已按回复姿势轻量替换 prompt 姿势: %s", desired)
    return ", ".join(_dedupe_tags(kept))


def _reply_pose_override(reply: str) -> str | None:
    text = reply or ""
    for tag, patterns in REPLY_POSE_OVERRIDES:
        for pattern in patterns:
            if pattern in text and not _is_negated_reply_pose(text, pattern):
                return tag
    return None


def _is_negated_reply_pose(text: str, pattern: str) -> bool:
    idx = text.find(pattern)
    if idx < 0:
        return False
    window = text[max(0, idx - 4):idx + len(pattern) + 2]
    return any(mark in window for mark in ("不是", "不再", "没有", "别", "不要"))


def _split_prompt_tags(prompt: str) -> list[str]:
    return [t.strip() for t in prompt.split(",") if t.strip()]


def _norm_tag(tag: str) -> str:
    return tag.strip().lower().replace(" ", "_")


def _dedupe_tags(tags: list[str]) -> list[str]:
    seen = set()
    result = []
    for tag in tags:
        t = tag.strip()
        if not t:
            continue
        if _norm_tag(t).startswith("rating:explicit"):
            t = "rating:nsfw"
        norm = _norm_tag(t)
        if norm not in seen:
            seen.add(norm)
            result.append(t)
    return result


def _split_status_tags(raw: str) -> list[str]:
    """拆分 status.md 的单行标签，过滤中文残留和无效描述。"""
    if not raw:
        return []
    if any("一" <= c <= "鿿" for c in raw):
        logger.warning(f"服饰标签含中文，已跳过: {raw!r}")
        return []
    tags = []
    for item in raw.split(","):
        tag = item.strip().replace(" ", "_")
        if not tag:
            continue
        tags.append(tag)
    return tags


def _has_explicit_nudity(tags: list[str]) -> bool:
    normalized = {_norm_tag(t) for t in tags}
    return bool(normalized & EXPLICIT_NUDE_TAGS)


def _is_accessory_tag(tag: str) -> bool:
    return any(hint in tag.lower() for hint in ACCESSORY_HINTS)


def _is_persistent_outfit_prompt_tag(norm_tag: str) -> bool:
    if norm_tag in EXPLICIT_NUDE_TAGS:
        return True
    if norm_tag in {
        "barefoot",
        "topless",
        "bottomless",
        "no_bra",
        "no_panties",
        "naked_apron",
    }:
        return True
    return any(hint in norm_tag for hint in CLOTHING_HINTS)


def _resolve_clothing_conflicts(tags: list[str]) -> list[str]:
    """
    status 同时出现 completely_nude 和普通衣物时，优先相信 nude，只保留饰品。
    这避免“全裸 + 白衬衫”这类互斥标签进入最终 prompt。
    """
    if not _has_explicit_nudity(tags):
        return tags

    result = []
    for tag in tags:
        norm = tag.lower().replace(" ", "_")
        if norm in EXPLICIT_NUDE_TAGS or _is_accessory_tag(norm):
            result.append(tag)
    if "completely_nude" in {t.lower().replace(" ", "_") for t in result}:
        for extra in ("nude", "bare_body"):
            if extra not in result:
                result.append(extra)
    return result


def _harmonize_rating(prompt: str) -> str:
    """裸露标签存在时，避免仍标 rating:general。"""
    tags = [t.strip() for t in prompt.split(",") if t.strip()]
    if not _has_explicit_nudity(tags):
        return prompt
    fixed = []
    changed = False
    for tag in tags:
        if tag.lower().replace(" ", "_") == "rating:general":
            fixed.append("rating:nsfw")
            changed = True
        else:
            fixed.append(tag)
    if changed:
        logger.info("检测到裸露状态，已将 rating:general 修正为 rating:nsfw")
    return ", ".join(fixed)


def build_image_prompt(character: str, prompt: str, reply: str | None = None) -> str:
    """
    构建最终生图 prompt。

    LLM 只负责本轮拍照意图/局部标签；这里统一补齐角色视觉锚点和当前服饰状态。
    """
    prompt = sanitize_dynamic_photo_prompt(prompt)
    visual_anchor = get_visual_anchor_tags(character)
    avatar_role = visual_anchor["role_tags"]
    body_type = visual_anchor["body_tags"]
    appearance = visual_anchor["appearance_tags"]

    prompt_lower = prompt.lower()
    if "close-up" in prompt_lower or "closeup" in prompt_lower:
        body_type = ""
        appearance = ""
    elif any(t in prompt_lower for t in ("pussy_focus", "feet_focus", "chest_focus")):
        body_type = ", ".join(body_type.split(",")[:2])
        appearance = ", ".join(appearance.split(",")[:2])
    elif "face_focus" in prompt_lower:
        body_type = ""

    char_tags = ", ".join(p for p in [avatar_role, body_type, appearance] if p)
    scene_tags = get_scene_tags(character)
    clothing_tags = get_clothing_tags(character)
    parts = [p for p in [char_tags, prompt, scene_tags, clothing_tags] if p]
    final_prompt = normalize_prompt(
        harmonize_pose_from_reply(
            normalize_camera_action_tags(
                _harmonize_rating(", ".join(parts))
            ),
            reply,
        )
    )
    logger.info(f"最终生图 prompt 已构建: character={character}, {len(final_prompt)} 字符")
    return final_prompt
