"""Deterministic layered wardrobe state and compatibility projections.

The canonical wardrobe keeps a small, extensible set of layer stacks. The
continuity agent emits complete replacements only for slots changed this turn;
omitted slots retain their previous layers.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


WARDROBE_SCHEMA_VERSION = 2
DEFAULT_SLOTS = ("upper", "lower", "legwear", "footwear", "accessories")
LAYERED_SLOTS = ("upper", "lower", "legwear", "footwear")
GARMENT_CATEGORIES = ("underwear", "outerwear", "legwear", "footwear", "accessory")

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
        # Absence of hidden underwear is only projected after it has been
        # explicitly established by a continuity patch. Legacy flat status
        # files cannot prove that an omitted bra or panties are absent.
        "known_absent": [],
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
        if not tag:
            continue
        if tag in ABSENCE_TAGS:
            if tag not in wardrobe["known_absent"]:
                wardrobe["known_absent"].append(tag)
            continue
        slots, rank = classify_tag(tag)
        if not slots:
            if tag not in wardrobe["legacy_visible"]:
                wardrobe["legacy_visible"].append(tag)
            continue

        primary = slots[0]
        counters[primary] += 1
        item_id = f"{primary}_{counters[primary]}"
        wardrobe["items"][item_id] = {
            "slots": slots,
            "tags": [tag],
            "category": infer_category([tag], slots),
        }
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
    result["schema_version"] = max(
        int(value.get("schema_version") or 0),
        WARDROBE_SCHEMA_VERSION,
    )

    raw_items = value.get("items") if isinstance(value.get("items"), dict) else {}
    for raw_id, raw_item in raw_items.items():
        if not isinstance(raw_item, dict):
            continue
        item_id = str(raw_id).strip()
        tags = _compact_garment_tags(_normalize_tags(raw_item.get("tags")))
        slots = _normalize_slots(raw_item.get("slots"))
        if item_id and tags and slots:
            result["items"][item_id] = {
                "slots": slots,
                "tags": tags,
                "category": _normalize_category(raw_item.get("category")) or infer_category(tags, slots),
            }

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

    result["known_absent"] = [
        tag for tag in _normalize_tags(value.get("known_absent")) if tag in ABSENCE_TAGS
    ]
    result["legacy_visible"] = _normalize_tags(value.get("legacy_visible"))
    return _reconcile_absence(result)


def _expand_director_wardrobe_patch(
    wardrobe: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Convert compact string-array slot replacements to the canonical patch."""
    if not any(isinstance(value, list) for value in patch.values()):
        return patch

    normalized_lists: dict[str, list[str]] = {}
    for raw_slot, raw_change in patch.items():
        slot = _norm_slot(raw_slot)
        if isinstance(raw_change, list):
            phrases: list[str] = []
            for raw_phrase in raw_change:
                if not isinstance(raw_phrase, str):
                    raise WardrobeOperationError(
                        f"wardrobe patch for {slot} must contain garment strings"
                    )
                phrase = _norm_tag(raw_phrase)
                if phrase and phrase not in phrases:
                    phrases.append(phrase)
            normalized_lists[slot] = phrases

    phrase_slots: dict[str, list[str]] = {}
    for slot, phrases in normalized_lists.items():
        for phrase in phrases:
            phrase_slots.setdefault(phrase, []).append(slot)

    definitions: dict[str, dict[str, Any]] = {}
    phrase_ids: dict[tuple[str, tuple[str, ...]], str] = {}
    expanded: dict[str, Any] = {}
    for raw_slot, raw_change in patch.items():
        slot = _norm_slot(raw_slot)
        if not isinstance(raw_change, list):
            expanded[raw_slot] = raw_change
            continue
        layers: list[dict[str, Any]] = []
        for phrase in normalized_lists.get(slot, []):
            shared_slots = phrase_slots.get(phrase, [slot])
            slots = (
                [candidate for candidate in ("upper", "lower") if candidate in shared_slots]
                if "upper" in shared_slots and "lower" in shared_slots
                else [slot]
            )
            key = (phrase, tuple(slots))
            item_id = phrase_ids.get(key)
            if item_id is None:
                item_id = _next_item_id_for_sets(wardrobe, definitions, slots[0])
                definition = {
                    "slots": slots,
                    "tags": [phrase],
                    "category": infer_category([phrase], slots),
                }
                phrase_ids[key] = item_id
                definitions[item_id] = definition
            layers.append({"id": item_id, **definitions[item_id]})
        expanded[slot] = {"mode": "replace", "layers": layers}
    return expanded


def apply_wardrobe_patch(wardrobe: dict[str, Any], patch: Any) -> dict[str, Any]:
    """Merge VisualContinuityAgent slot replacements into canonical state.

    Each mentioned slot is a complete inner-to-outer layer list. Omitted slots
    remain unchanged. The language model decides meaning; this function only
    validates and persists its structured result.
    """
    result = normalize_wardrobe(deepcopy(wardrobe))
    if patch in (None, {}):
        return result
    if not isinstance(patch, dict):
        raise WardrobeOperationError("wardrobe patch must be an object")
    patch = _expand_director_wardrobe_patch(result, patch)

    replacements: dict[str, list[dict[str, Any]]] = {}
    for raw_slot, raw_change in patch.items():
        slot = _norm_slot(raw_slot)
        if slot not in DEFAULT_SLOTS:
            raise WardrobeOperationError(f"unknown wardrobe slot in patch: {slot or '<empty>'}")
        if raw_change is None:
            continue
        if not isinstance(raw_change, dict):
            raise WardrobeOperationError(f"wardrobe patch for {slot} must be an object or null")
        mode = str(raw_change.get("mode") or "replace").strip().lower()
        if mode != "replace":
            raise WardrobeOperationError(f"unsupported wardrobe patch mode for {slot}: {mode}")
        layers = raw_change.get("layers")
        if not isinstance(layers, list):
            raise WardrobeOperationError(f"wardrobe patch for {slot} requires a layers array")
        replacements[slot] = layers

    if not replacements:
        return result

    # Removing one side of a multi-slot garment removes the same item from all
    # occupied slots before the replacement layers are installed.
    removed_ids = {
        item_id
        for slot in replacements
        for item_id in result["layers"].get(slot, [])
    }
    for item_id in removed_ids:
        occupied = set(result["items"].get(item_id, {}).get("slots") or [])
        omitted = occupied - set(replacements)
        if omitted:
            raise WardrobeOperationError(
                f"multi-slot garment {item_id} also occupies omitted slots: {', '.join(sorted(omitted))}"
            )
    for item_id in removed_ids:
        for layer in result["layers"].values():
            while item_id in layer:
                layer.remove(item_id)
        result["items"].pop(item_id, None)

    definitions: dict[str, dict[str, Any]] = {}
    requested_order: dict[str, list[str]] = {slot: [] for slot in replacements}
    for slot, layers in replacements.items():
        for index, raw_garment in enumerate(layers, start=1):
            if not isinstance(raw_garment, dict):
                raise WardrobeOperationError(f"garment layer {slot}[{index}] must be an object")
            tags = _compact_garment_tags(_normalize_tags(raw_garment.get("tags")))
            slots = _normalize_slots(raw_garment.get("slots") or [slot])
            if not tags or not slots or slot not in slots:
                raise WardrobeOperationError(
                    f"garment layer {slot}[{index}] requires tags and must include slot {slot}"
                )
            if any(item_slot not in DEFAULT_SLOTS for item_slot in slots):
                raise WardrobeOperationError(f"garment layer {slot}[{index}] uses an unknown slot")
            omitted_slots = set(slots) - set(replacements)
            if omitted_slots:
                raise WardrobeOperationError(
                    f"multi-slot garment in {slot}[{index}] also changes omitted slots: "
                    f"{', '.join(sorted(omitted_slots))}"
                )
            item_id = str(raw_garment.get("id") or raw_garment.get("item_id") or "").strip()
            if not item_id:
                item_id = _next_item_id_for_sets(result, definitions, slots[0])
            definition = {
                "slots": slots,
                "tags": tags,
                "category": _normalize_category(raw_garment.get("category")) or infer_category(tags, slots),
            }
            existing = definitions.get(item_id)
            if existing is not None and existing != definition:
                raise WardrobeOperationError(f"garment id has conflicting definitions: {item_id}")
            definitions[item_id] = definition
            if item_id not in requested_order[slot]:
                requested_order[slot].append(item_id)

    result["items"].update(definitions)
    for slot, order in requested_order.items():
        result["layers"][slot] = list(order)
    for item_id, item in definitions.items():
        for slot in item["slots"]:
            result["layers"].setdefault(slot, [])
            if item_id not in result["layers"][slot]:
                result["layers"][slot].append(item_id)

    # A complete replacement of upper/lower establishes hidden underwear
    # presence or absence without creating separate top-level slots.
    known_absent = set(result.get("known_absent") or [])
    if "upper" in replacements:
        if _slot_has_category(result, "upper", "underwear"):
            known_absent.discard("no_bra")
        else:
            known_absent.add("no_bra")
    if "lower" in replacements:
        if _slot_has_category(result, "lower", "underwear"):
            known_absent.discard("no_panties")
        else:
            known_absent.add("no_panties")
    result["known_absent"] = sorted(known_absent)
    return _reconcile_absence(normalize_wardrobe(result))


def wardrobe_agent_view(wardrobe: dict[str, Any]) -> dict[str, Any]:
    """Return a complete, model-readable inner-to-outer wardrobe view."""
    value = normalize_wardrobe(wardrobe)
    slots: dict[str, list[dict[str, Any]]] = {}
    for slot in DEFAULT_SLOTS:
        slots[slot] = []
        for item_id in value["layers"].get(slot, []):
            item = value["items"][item_id]
            slots[slot].append({
                "id": item_id,
                "slots": list(item["slots"]),
                "category": item["category"],
                "tags": list(item["tags"]),
            })
    return {
        "layer_order": "inner_to_outer",
        "slots": slots,
        "known_absent": list(value.get("known_absent") or []),
        "visible_tags": wardrobe_visible_tags(value),
    }


def wardrobe_director_view(wardrobe: dict[str, Any]) -> dict[str, list[str]]:
    """Return the compact inner-to-outer slot view used by the director."""
    value = normalize_wardrobe(wardrobe)
    result: dict[str, list[str]] = {}
    for slot in DEFAULT_SLOTS:
        phrases: list[str] = []
        for item_id in value["layers"].get(slot, []):
            item = value["items"].get(item_id) or {}
            phrase = _compact_garment_tags(_normalize_tags(item.get("tags")))
            if phrase and phrase[0] not in phrases:
                phrases.append(phrase[0])
        result[slot] = phrases
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


def wardrobe_visible_prompt_tags(wardrobe: dict[str, Any]) -> list[str]:
    """Project visible garments as compact phrases for an image model.

    State tags may stay granular for reasoning (``white``, ``lace``,
    ``panties``), but the image prompt must keep one garment's attributes
    together (``white lace panties``) so the generator cannot attach them to
    different garments.
    """
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
            tags = value["items"][item_id]["tags"]
            phrase = " ".join(str(tag).replace("_", " ").strip() for tag in tags if str(tag).strip())
            if phrase and phrase not in result:
                result.append(phrase)
    for tag in value.get("legacy_visible") or []:
        phrase = str(tag).replace("_", " ").strip()
        if phrase and phrase not in result:
            result.append(phrase)
    for tag in derived_absence_tags(value):
        if tag not in result:
            result.append(tag)
    return result


def derived_absence_tags(wardrobe: dict[str, Any]) -> list[str]:
    """Derive the minimal non-redundant visual absence projection.

    ``no_bra`` and ``no_panties`` may remain in ``known_absent`` to preserve
    hidden-layer continuity, but are not useful image-facing tags: an empty
    upper/lower slot already expresses that visual fact.  A fully empty body
    is represented by one canonical tag, ``completely_nude``.
    """
    value = normalize_wardrobe(wardrobe)
    known_absent = list(value.get("known_absent") or [])
    if value["legacy_visible"]:
        return known_absent
    layers = value["layers"]
    upper_empty = not layers.get("upper")
    lower_empty = not layers.get("lower")
    legwear_empty = not layers.get("legwear")
    footwear_empty = not layers.get("footwear")

    if upper_empty and lower_empty and legwear_empty and footwear_empty:
        return ["completely_nude"]

    result: list[str] = []
    if upper_empty:
        result.append("topless")
    if lower_empty:
        result.append("bottomless")
    if legwear_empty and footwear_empty:
        result.append("barefoot")
    return _unique(result)


def infer_category(tags: list[str], slots: list[str]) -> str:
    normalized = [_norm_tag(tag) for tag in tags]
    if any(_has_hint(tag, UPPER_INNER_HINTS + LOWER_INNER_HINTS) for tag in normalized):
        return "underwear"
    if slots and all(slot == "accessories" for slot in slots):
        return "accessory"
    if slots and all(slot == "footwear" for slot in slots):
        return "footwear"
    if slots and all(slot == "legwear" for slot in slots):
        return "legwear"
    return "outerwear"


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
    wardrobe["items"][item_id] = {
        "slots": slots,
        "tags": tags,
        "category": _normalize_category(garment.get("category")) or infer_category(tags, slots),
    }
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


def _normalize_category(value: Any) -> str:
    category = str(value or "").strip().lower().replace(" ", "_")
    return category if category in GARMENT_CATEGORIES else ""


def _compact_garment_tags(tags: list[str]) -> list[str]:
    """Keep one garment's descriptors in one concise canonical phrase."""
    values = [str(tag).strip().lower().replace(" ", "_") for tag in tags if str(tag).strip()]
    if len(values) <= 1:
        return values
    return ["_".join(dict.fromkeys(values))]


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


def _next_item_id_for_sets(
    wardrobe: dict[str, Any],
    definitions: dict[str, dict[str, Any]],
    slot: str,
) -> str:
    prefix = _norm_slot(slot) or "garment"
    index = 1
    while f"{prefix}_{index}" in wardrobe["items"] or f"{prefix}_{index}" in definitions:
        index += 1
    return f"{prefix}_{index}"


def _slot_has_category(wardrobe: dict[str, Any], slot: str, category: str) -> bool:
    return any(
        wardrobe["items"].get(item_id, {}).get("category") == category
        for item_id in wardrobe["layers"].get(slot, [])
    )


def _reconcile_absence(wardrobe: dict[str, Any]) -> dict[str, Any]:
    """Drop explicit absence markers contradicted by canonical garments."""
    known = set(wardrobe.get("known_absent") or [])
    layers = wardrobe.get("layers") or {}
    if _slot_has_category(wardrobe, "upper", "underwear"):
        known.discard("no_bra")
    if _slot_has_category(wardrobe, "lower", "underwear"):
        known.discard("no_panties")
    if layers.get("upper"):
        known.discard("topless")
    if layers.get("lower"):
        known.discard("bottomless")
    if layers.get("legwear") or layers.get("footwear"):
        known.discard("barefoot")
    if any(layers.get(slot) for slot in LAYERED_SLOTS):
        known.difference_update(FULL_NUDE_TAGS)
    wardrobe["known_absent"] = sorted(tag for tag in known if tag in ABSENCE_TAGS)
    return wardrobe


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
