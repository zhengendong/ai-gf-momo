"""Deterministic layered wardrobe state and compatibility projections.

The canonical wardrobe keeps a small, extensible set of layer stacks.  The
runtime model emits completed operations; it never has to reconstruct the
whole outfit after removing or adding one garment.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


WARDROBE_SCHEMA_VERSION = 1
DEFAULT_SLOTS = ("upper", "lower", "legwear", "footwear", "accessories")
LAYERED_SLOTS = ("upper", "lower", "legwear", "footwear")

FULL_NUDE_TAGS = {"completely_nude", "nude", "naked", "bare_body"}
ABSENCE_TAGS = FULL_NUDE_TAGS | {
    "barefoot",
    "topless",
    "bottomless",
    "no_bra",
    "no_panties",
}

ACCESSORY_HINTS = (
    "necklace", "choker", "collar", "earring", "bracelet", "ring",
    "glasses", "hair_ornament", "ribbon", "brooch", "anklet",
)
FOOTWEAR_HINTS = (
    "shoe", "heel", "boot", "sneaker", "sandal", "loafer", "slipper",
    "mary_jane",
)
LEGWEAR_HINTS = (
    "sock", "stocking", "thighhigh", "pantyhose", "tights", "legwear",
)
UPPER_INNER_HINTS = ("bra", "bandeau", "undershirt", "camisole")
UPPER_OUTER_HINTS = (
    "shirt", "blouse", "sweater", "hoodie", "jacket", "coat", "top",
    "vest", "corset", "bodice", "cardigan",
)
LOWER_INNER_HINTS = ("panties", "briefs", "underpants", "thong")
LOWER_OUTER_HINTS = (
    "skirt", "pants", "shorts", "jeans", "trousers", "bottom",
)
MULTI_SLOT_HINTS = (
    "dress", "robe", "kimono", "yukata", "bodysuit", "swimsuit",
    "pajamas", "nightgown", "onesie", "jumpsuit", "romper",
)


class WardrobeOperationError(ValueError):
    """Raised when a completed wardrobe operation cannot be applied safely."""


def empty_wardrobe() -> dict[str, Any]:
    return {
        "schema_version": WARDROBE_SCHEMA_VERSION,
        "items": {},
        "layers": {slot: [] for slot in DEFAULT_SLOTS},
        # Unknown legacy tags remain visible and suppress absence inference.
        "legacy_visible": [],
    }


def wardrobe_from_tags(tags: list[str]) -> dict[str, Any]:
    """Create a conservative layered wardrobe from a legacy flat tag list."""
    wardrobe = empty_wardrobe()
    counters = {slot: 0 for slot in DEFAULT_SLOTS}
    ranked: dict[str, list[tuple[int, str]]] = {slot: [] for slot in DEFAULT_SLOTS}

    for raw in tags or []:
        tag = _norm_tag(raw)
        if not tag or tag in ABSENCE_TAGS:
            continue
        slots, rank = classify_tag(tag)
        if not slots:
            if tag not in wardrobe["legacy_visible"]:
                wardrobe["legacy_visible"].append(tag)
            continue

        primary = slots[0]
        counters[primary] += 1
        item_id = f"{primary}_{counters[primary]}"
        wardrobe["items"][item_id] = {"slots": slots, "tags": [tag]}
        for slot in slots:
            ranked[slot].append((rank, item_id))

    for slot in DEFAULT_SLOTS:
        wardrobe["layers"][slot] = [
            item_id for _, item_id in sorted(ranked[slot], key=lambda item: item[0])
        ]
    return wardrobe


def normalize_wardrobe(value: Any) -> dict[str, Any]:
    """Return a validated, deduplicated wardrobe without mutating input."""
    if not isinstance(value, dict):
        return empty_wardrobe()
    result = empty_wardrobe()
    result["schema_version"] = int(value.get("schema_version") or WARDROBE_SCHEMA_VERSION)

    raw_items = value.get("items") if isinstance(value.get("items"), dict) else {}
    for raw_id, raw_item in raw_items.items():
        if not isinstance(raw_item, dict):
            continue
        item_id = str(raw_id).strip()
        tags = _normalize_tags(raw_item.get("tags"))
        slots = _normalize_slots(raw_item.get("slots"))
        if item_id and tags and slots:
            result["items"][item_id] = {"slots": slots, "tags": tags}

    raw_layers = value.get("layers") if isinstance(value.get("layers"), dict) else {}
    all_slots = list(DEFAULT_SLOTS)
    for slot in raw_layers:
        normalized_slot = _norm_slot(slot)
        if normalized_slot and normalized_slot not in all_slots:
            all_slots.append(normalized_slot)
    result["layers"] = {slot: [] for slot in all_slots}

    for slot, raw_ids in raw_layers.items():
        normalized_slot = _norm_slot(slot)
        if not normalized_slot or not isinstance(raw_ids, list):
            continue
        for raw_id in raw_ids:
            item_id = str(raw_id).strip()
            item = result["items"].get(item_id)
            if not item or normalized_slot not in item["slots"]:
                continue
            if item_id not in result["layers"][normalized_slot]:
                result["layers"][normalized_slot].append(item_id)

    # Repair omitted layer references from item slot declarations.
    for item_id, item in result["items"].items():
        for slot in item["slots"]:
            result["layers"].setdefault(slot, [])
            if item_id not in result["layers"][slot]:
                result["layers"][slot].append(item_id)

    result["legacy_visible"] = _normalize_tags(value.get("legacy_visible"))
    return result


def reduce_wardrobe(wardrobe: dict[str, Any], operations: list[dict]) -> dict[str, Any]:
    """Apply completed wardrobe operations to a copy of the current state."""
    result = normalize_wardrobe(deepcopy(wardrobe))
    for operation in operations or []:
        if not isinstance(operation, dict):
            raise WardrobeOperationError("wardrobe operation must be an object")
        domain = str(operation.get("domain") or "wardrobe").strip().lower()
        if domain != "wardrobe":
            continue
        op = str(operation.get("operation") or operation.get("type") or "").strip().lower()
        op = op.removeprefix("wardrobe.")
        if op == "remove":
            _apply_remove(result, operation)
        elif op == "wear":
            _apply_wear(result, operation)
        elif op in {"replace", "replace_outfit"}:
            result = _apply_replace(operation)
        else:
            raise WardrobeOperationError(f"unsupported wardrobe operation: {op or '<empty>'}")
    return normalize_wardrobe(result)


def wardrobe_all_tags(wardrobe: dict[str, Any]) -> list[str]:
    """Return all currently worn tags for the model-readable status projection."""
    value = normalize_wardrobe(wardrobe)
    result: list[str] = []
    seen_items: set[str] = set()
    for slot in value["layers"]:
        for item_id in value["layers"][slot]:
            if item_id in seen_items:
                continue
            seen_items.add(item_id)
            _extend_unique(result, value["items"][item_id]["tags"])
    _extend_unique(result, value["legacy_visible"])
    _extend_unique(result, derived_absence_tags(value))
    return result


def wardrobe_visible_tags(wardrobe: dict[str, Any]) -> list[str]:
    """Project only currently visible layers plus explicit absence markers."""
    value = normalize_wardrobe(wardrobe)
    result: list[str] = []
    seen_items: set[str] = set()
    for slot in value["layers"]:
        layer = value["layers"][slot]
        if not layer:
            continue
        item_ids = layer if slot == "accessories" else [layer[-1]]
        for item_id in item_ids:
            if item_id in seen_items:
                continue
            seen_items.add(item_id)
            _extend_unique(result, value["items"][item_id]["tags"])
    _extend_unique(result, value["legacy_visible"])
    _extend_unique(result, derived_absence_tags(value))
    return result


def derived_absence_tags(wardrobe: dict[str, Any]) -> list[str]:
    """Derive explicit visual absence only when legacy coverage is unambiguous."""
    value = normalize_wardrobe(wardrobe)
    if value["legacy_visible"]:
        return []
    layers = value["layers"]
    upper_empty = not layers.get("upper")
    lower_empty = not layers.get("lower")
    legwear_empty = not layers.get("legwear")
    footwear_empty = not layers.get("footwear")

    if upper_empty and lower_empty and legwear_empty and footwear_empty:
        return ["completely_nude", "nude", "bare_body", "barefoot"]

    result: list[str] = []
    if upper_empty:
        result.extend(["topless", "no_bra"])
    if lower_empty:
        result.extend(["bottomless", "no_panties"])
    if legwear_empty and footwear_empty:
        result.append("barefoot")
    return result


def classify_tag(tag: str) -> tuple[list[str], int]:
    """Classify a common legacy tag; unknown style tags remain losslessly visible."""
    value = _norm_tag(tag)
    if _has_hint(value, ACCESSORY_HINTS):
        return ["accessories"], 100
    if _has_hint(value, FOOTWEAR_HINTS):
        return ["footwear"], 20
    if _has_hint(value, LEGWEAR_HINTS):
        return ["legwear"], 10
    if _has_hint(value, MULTI_SLOT_HINTS):
        return ["upper", "lower"], 20
    if _has_hint(value, UPPER_INNER_HINTS):
        return ["upper"], 10
    if _has_hint(value, UPPER_OUTER_HINTS):
        rank = 40 if _has_hint(value, ("jacket", "coat", "cardigan")) else 20
        return ["upper"], rank
    if _has_hint(value, LOWER_INNER_HINTS):
        return ["lower"], 10
    if _has_hint(value, LOWER_OUTER_HINTS):
        return ["lower"], 20
    return [], 0


def _apply_remove(wardrobe: dict[str, Any], operation: dict):
    item_id = str(operation.get("item_id") or "").strip()
    if not item_id:
        slot = _norm_slot(operation.get("slot"))
        target = str(operation.get("target") or "outermost").strip().lower()
        match_tag = _norm_tag(operation.get("match_tag") or operation.get("tag") or "")
        layer = wardrobe["layers"].get(slot, [])
        if not slot or not layer:
            raise WardrobeOperationError(f"cannot remove from empty or unknown slot: {slot or '<empty>'}")
        if match_tag:
            candidates = [candidate for candidate in layer if match_tag in wardrobe["items"][candidate]["tags"]]
            if not candidates:
                raise WardrobeOperationError(f"no garment with tag {match_tag!r} in slot {slot}")
            item_id = candidates[-1]
        elif target == "innermost":
            item_id = layer[0]
        else:
            item_id = layer[-1]

    if item_id not in wardrobe["items"]:
        raise WardrobeOperationError(f"garment is not currently worn: {item_id}")
    for layer in wardrobe["layers"].values():
        while item_id in layer:
            layer.remove(item_id)
    wardrobe["items"].pop(item_id, None)


def _apply_wear(wardrobe: dict[str, Any], operation: dict):
    garment = operation.get("garment") if isinstance(operation.get("garment"), dict) else operation
    tags = _normalize_tags(garment.get("tags"))
    slots = _normalize_slots(garment.get("slots") or garment.get("slot"))
    if not tags or not slots:
        raise WardrobeOperationError("wear requires garment tags and at least one slot")

    requested_id = str(garment.get("id") or garment.get("item_id") or "").strip()
    item_id = requested_id or _next_item_id(wardrobe, slots[0])
    if item_id in wardrobe["items"]:
        raise WardrobeOperationError(f"garment id is already worn: {item_id}")
    wardrobe["items"][item_id] = {"slots": slots, "tags": tags}
    position = str(operation.get("position") or "outermost").strip().lower()
    for slot in slots:
        wardrobe["layers"].setdefault(slot, [])
        if position == "innermost":
            wardrobe["layers"][slot].insert(0, item_id)
        else:
            wardrobe["layers"][slot].append(item_id)


def _apply_replace(operation: dict) -> dict[str, Any]:
    wardrobe_value = operation.get("wardrobe")
    if isinstance(wardrobe_value, dict):
        return normalize_wardrobe(wardrobe_value)
    garments = operation.get("garments")
    if isinstance(garments, list):
        result = empty_wardrobe()
        for garment in garments:
            if not isinstance(garment, dict):
                raise WardrobeOperationError("replace garments must be objects")
            _apply_wear(result, {"garment": garment, "position": garment.get("position")})
        return result
    tags = operation.get("tags") or operation.get("outfit_tags")
    if isinstance(tags, list) or isinstance(tags, str):
        return wardrobe_from_tags(_normalize_tags(tags))
    raise WardrobeOperationError("replace requires wardrobe, garments, or tags")


def _normalize_tags(value: Any) -> list[str]:
    raw_values = value if isinstance(value, list) else str(value or "").replace("\n", ",").split(",")
    result: list[str] = []
    for raw in raw_values:
        tag = _norm_tag(raw)
        if tag and tag not in result:
            result.append(tag)
    return result


def _normalize_slots(value: Any) -> list[str]:
    raw_values = value if isinstance(value, list) else [value]
    result: list[str] = []
    for raw in raw_values:
        slot = _norm_slot(raw)
        if slot and slot not in result:
            result.append(slot)
    return result


def _norm_tag(value: Any) -> str:
    return str(value or "").strip().removeprefix("-").strip().lower().replace(" ", "_")


def _norm_slot(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _has_hint(tag: str, hints: tuple[str, ...]) -> bool:
    return any(hint in tag for hint in hints)


def _extend_unique(target: list[str], values: list[str]):
    for value in values:
        if value and value not in target:
            target.append(value)


def _next_item_id(wardrobe: dict[str, Any], slot: str) -> str:
    prefix = _norm_slot(slot) or "garment"
    index = 1
    while f"{prefix}_{index}" in wardrobe["items"]:
        index += 1
    return f"{prefix}_{index}"
