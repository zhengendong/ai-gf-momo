"""Offline probe for layered wardrobe reduction and visible projections."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.wardrobe import (
    apply_wardrobe_patch,
    derived_absence_tags,
    reduce_wardrobe,
    wardrobe_agent_view,
    wardrobe_director_view,
    wardrobe_all_tags,
    wardrobe_from_tags,
    wardrobe_visible_tags,
    wardrobe_visible_prompt_tags,
    WardrobeOperationError,
)
from backend.core.state import _read_section_tags


def main():
    corrupted_projection = """# 测试状态
## 穿着
- 上身：上身：light blue pajamas、下身：light blue pajamas
- 下身：上身：上身：light blue pajamas、下身：light blue pajamas
- 腿部：无
- 鞋子：barefoot
- 配饰：配饰：silver heart necklace、black bell collar

## 场景细节
- bedroom
"""
    assert _read_section_tags(corrupted_projection, "穿着") == [
        "light_blue_pajamas",
        "barefoot",
        "silver_heart_necklace",
        "black_bell_collar",
    ]

    wardrobe = wardrobe_from_tags([
        "white_bra",
        "white_blouse",
        "white_panties",
        "pleated_skirt",
        "black_stockings",
        "black_high_heels",
        "silver_necklace",
    ])
    assert wardrobe_visible_tags(wardrobe) == [
        "white_blouse",
        "pleated_skirt",
        "black_stockings",
        "black_high_heels",
        "silver_necklace",
    ]

    wardrobe = reduce_wardrobe(wardrobe, [{
        "domain": "wardrobe",
        "operation": "remove",
        "slot": "footwear",
        "target": "outermost",
    }])
    assert "black_high_heels" not in wardrobe_all_tags(wardrobe)
    assert "black_stockings" in wardrobe_visible_tags(wardrobe)
    assert "barefoot" not in wardrobe_visible_tags(wardrobe)

    wardrobe = reduce_wardrobe(wardrobe, [{
        "domain": "wardrobe",
        "operation": "remove",
        "slot": "legwear",
        "target": "outermost",
    }])
    assert "barefoot" in wardrobe_visible_tags(wardrobe)

    wardrobe = reduce_wardrobe(wardrobe, [{
        "domain": "wardrobe",
        "operation": "remove",
        "slot": "lower",
        "target": "outermost",
    }])
    assert "white_panties" in wardrobe_visible_tags(wardrobe)
    assert "pleated_skirt" not in wardrobe_visible_tags(wardrobe)

    wardrobe = reduce_wardrobe(wardrobe, [{
        "domain": "wardrobe",
        "operation": "remove",
        "slot": "lower",
        "target": "outermost",
    }])
    visible = wardrobe_visible_tags(wardrobe)
    assert "bottomless" in visible and "no_panties" not in visible
    assert "white_panties" not in visible

    one_piece = reduce_wardrobe(wardrobe_from_tags([]), [{
        "domain": "wardrobe",
        "operation": "wear",
        "garment": {
            "id": "dress_1",
            "slots": ["upper", "lower"],
            "tags": ["red_evening_dress"],
        },
    }])
    assert one_piece["layers"]["upper"] == ["dress_1"]
    assert one_piece["layers"]["lower"] == ["dress_1"]
    one_piece = reduce_wardrobe(one_piece, [{
        "domain": "wardrobe",
        "operation": "remove",
        "item_id": "dress_1",
    }])
    assert not one_piece["layers"]["upper"] and not one_piece["layers"]["lower"]
    assert wardrobe_visible_tags(one_piece) == ["completely_nude"]
    assert wardrobe_visible_prompt_tags(one_piece) == ["completely_nude"]

    # Unknown legacy style tags are preserved without inferring nudity.
    unknown = wardrobe_from_tags(["original_fantasy_attire"])
    assert wardrobe_visible_tags(unknown) == ["original_fantasy_attire"]

    # The continuity contract replaces only the slots it explicitly changes.
    layered = wardrobe_from_tags([
        "white_bra", "white_blouse", "white_panties", "pleated_skirt",
        "black_stockings", "black_high_heels",
    ])
    view = wardrobe_agent_view(layered)
    assert layered["schema_version"] == 2
    assert [item["category"] for item in view["slots"]["upper"]] == ["underwear", "outerwear"]
    assert [item["category"] for item in view["slots"]["lower"]] == ["underwear", "outerwear"]
    assert wardrobe_visible_prompt_tags(layered) == [
        "white blouse", "pleated skirt", "black stockings",
        "black high heels",
    ]
    assert wardrobe_director_view(layered) == {
        "upper": ["white_bra", "white_blouse"],
        "lower": ["white_panties", "pleated_skirt"],
        "legwear": ["black_stockings"],
        "footwear": ["black_high_heels"],
        "accessories": [],
    }

    # The normal director protocol uses string arrays; identical phrases in
    # upper/lower become one canonical multi-slot garment.
    simple = apply_wardrobe_patch(layered, {
        "upper": ["white_lace_bra", "red_evening_dress"],
        "lower": ["white_lace_panties", "red_evening_dress"],
        "legwear": [],
        "footwear": ["black_high_heels"],
    })
    dress_ids = [
        item_id for item_id, item in simple["items"].items()
        if item["tags"] == ["red_evening_dress"]
    ]
    assert len(dress_ids) == 1
    assert simple["items"][dress_ids[0]]["slots"] == ["upper", "lower"]
    assert dress_ids[0] in simple["layers"]["upper"]
    assert dress_ids[0] in simple["layers"]["lower"]

    # Removing underwear while retaining outerwear records known absence without
    # incorrectly making the outer garment disappear.
    layered = apply_wardrobe_patch(layered, {
        "lower": {"mode": "replace", "layers": [{
            "id": "pleated_skirt_1",
            "slots": ["lower"],
            "category": "outerwear",
            "tags": ["pleated_skirt"],
        }]},
        "upper": {"mode": "replace", "layers": [{
            "id": "white_blouse_1",
            "slots": ["upper"],
            "category": "outerwear",
            "tags": ["white_blouse"],
        }]},
    })
    assert "white_panties" not in wardrobe_all_tags(layered)
    assert "white_bra" not in wardrobe_all_tags(layered)
    assert "pleated_skirt" in wardrobe_visible_tags(layered)
    assert "white_blouse" in wardrobe_visible_tags(layered)
    assert not ({"no_bra", "no_panties"} & set(derived_absence_tags(layered)))

    compact = apply_wardrobe_patch(layered, {
        "lower": {"mode": "replace", "layers": [{
            "id": "white_lace_panties_1",
            "slots": ["lower"],
            "category": "underwear",
            "tags": ["white", "lace", "panties"],
        }]},
    })
    assert compact["items"]["white_lace_panties_1"]["tags"] == ["white_lace_panties"]
    assert wardrobe_visible_prompt_tags(compact) == [
        "white blouse", "white lace panties", "black stockings",
        "black high heels",
    ]

    # Shoes and legwear remain independent slots, so removing one never removes
    # the other or invents barefoot while stockings are still worn.
    layered = apply_wardrobe_patch(layered, {
        "footwear": {"mode": "replace", "layers": []},
    })
    assert "black_stockings" in wardrobe_visible_tags(layered)
    assert "barefoot" not in wardrobe_visible_tags(layered)
    layered = apply_wardrobe_patch(layered, {
        "legwear": {"mode": "replace", "layers": []},
    })
    assert "barefoot" in wardrobe_visible_tags(layered)

    # A one-piece garment cannot silently mutate an omitted companion slot.
    one_piece = wardrobe_from_tags(["red_evening_dress"])
    try:
        apply_wardrobe_patch(one_piece, {
            "upper": {"mode": "replace", "layers": []},
        })
    except WardrobeOperationError:
        pass
    else:
        raise AssertionError("multi-slot replacement must name every occupied slot")

    print("wardrobe layer probe: ok")


if __name__ == "__main__":
    main()
