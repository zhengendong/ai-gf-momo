"""
Prompt 构建器
从角色配置和状态文件构建最终英文 Danbooru prompt。
"""

import re
import logging

from ..core.state import read_status, read_state_snapshot
from ..core.characters import get_active
from ..core.context import load_character_profile
from ..core.wardrobe import wardrobe_visible_tags

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
    "leg_position": {
        "legs_together",
        "knees_together",
        "legs_spread",
        "spread_legs",
        "spreading_legs",
    },
    "target_visibility": {
        "covering_self",
        "hands_covering_crotch",
        "covering_crotch",
    },
}

CLOSEUP_CONFLICT_TAGS = {
    "medium_shot",
    "wide_shot",
    "full_body",
    "upper_body",
    "cowboy_shot",
}

FEET_CLOSEUP_CONFLICT_TAGS = {
    "legs_extended",
    "feet_forward",
    "from_below",
}

QUALITY_TAGS = (
    "masterpiece",
    "best quality",
    "amazing quality",
)



CAMERA_ACTION_RULES = [
    {
        "name": "pussy_focus",
        "triggers": {"pussy_focus", "spread_pussy"},
        "add": [
            "legs_spread",
            "presenting_pussy",
            "pussy_focus",
        ],
        # Focus must not rewrite a valid sitting/standing/lying decision.  It
        # only removes limb/visibility states that make the target impossible.
        "remove_groups": {"leg_position", "target_visibility"},
    },
    {
        "name": "feet_focus",
        "triggers": {"feet_focus", "foot_focus"},
        "add": [
            "feet_focus",
        ],
    },
    {
        "name": "chest_focus",
        "triggers": {"chest_focus", "breast_focus"},
        "add": [
            "chest_focus",
        ],
    },
    {
        "name": "face_focus",
        "triggers": {"face_focus"},
        "add": [
            "face_focus",
        ],
    },
    {
        "name": "from_behind",
        "triggers": {"from_behind", "back_view"},
        "add": [
            "from_behind",
        ],
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
    """Apply minimal action guardrails without overriding the LLM's camera.

    The LLM owns composition tags such as close-up, from_below, upper_body,
    full_body, and wide_shot. Backend rules only canonicalize focus aliases and
    fix hard pose contradictions where a body-part focus would otherwise be
    anatomically incoherent. When the LLM emits mutually redundant composition
    tags, this keeps the tighter stated framing and removes the broader extras.
    """
    tags = _dedupe_tags(_split_prompt_tags(prompt))
    tags = _drop_redundant_composition_tags(tags)
    tags = _drop_generic_pose_conflicts(tags)
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


def _drop_generic_pose_conflicts(tags: list[str]) -> list[str]:
    """Resolve hard limb contradictions even when no special focus is set."""
    normalized = {_norm_tag(tag) for tag in tags}
    spread = {"legs_spread", "spread_legs", "spreading_legs"}
    together = {"legs_together", "knees_together"}
    if normalized & spread and normalized & together:
        tags = [tag for tag in tags if _norm_tag(tag) not in together]
        logger.info("已移除与张腿动作冲突的并腿标签")
    return tags


def _drop_redundant_composition_tags(tags: list[str]) -> list[str]:
    normalized = {_norm_tag(t) for t in tags}
    has_closeup = bool(normalized & {"close-up", "closeup"})
    if not has_closeup:
        return tags

    remove = set(CLOSEUP_CONFLICT_TAGS)
    if "feet_focus" in normalized or "foot_focus" in normalized:
        remove.update(FEET_CLOSEUP_CONFLICT_TAGS)

    result = [tag for tag in tags if _norm_tag(tag) not in remove]
    if len(result) != len(tags):
        logger.info("已移除与 close-up 冲突的冗余构图标签")
    return result


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


def _is_rating_tag(tag: str) -> bool:
    return _norm_tag(tag).startswith("rating:")


def _ensure_required_prompt_tags(prompt: str) -> str:
    tags = _dedupe_tags(_split_prompt_tags(prompt))
    if not any(_is_rating_tag(tag) for tag in tags):
        default_rating = "rating:nsfw" if _has_explicit_nudity(tags) else "rating:general"
        tags.insert(0, default_rating)
        logger.info("最终 prompt 缺少 rating，已补齐为 %s", default_rating)

    quality_norms = {_norm_tag(tag) for tag in QUALITY_TAGS}
    tags = [tag for tag in tags if _norm_tag(tag) not in quality_norms]
    tags.extend(QUALITY_TAGS)
    return ", ".join(_dedupe_tags(tags))


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


def build_image_prompt(
    character: str,
    prompt: str,
    reply: str | None = None,
    state_snapshot: dict | None = None,
) -> str:
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
    # Background image generation must use the state committed by its own
    # conversation turn. Reading status.md here would allow a later turn to
    # silently change an earlier queued image.
    if state_snapshot is None:
        scene_tags = get_scene_tags(character)
        clothing_tags = get_clothing_tags(character)
    else:
        scene_tags = ", ".join(state_snapshot.get("scene_tags") or [])
        wardrobe = state_snapshot.get("wardrobe")
        if isinstance(wardrobe, dict):
            clothing_tags = ", ".join(wardrobe_visible_tags(wardrobe))
        else:
            clothing_tags = ", ".join(state_snapshot.get("outfit_tags") or [])
    parts = [p for p in [char_tags, prompt, scene_tags, clothing_tags] if p]
    final_prompt = normalize_prompt(
        normalize_camera_action_tags(
                _harmonize_rating(", ".join(parts))
            )
    )
    final_prompt = _ensure_required_prompt_tags(final_prompt)
    logger.info(f"最终生图 prompt 已构建: character={character}, {len(final_prompt)} 字符")
    return final_prompt
