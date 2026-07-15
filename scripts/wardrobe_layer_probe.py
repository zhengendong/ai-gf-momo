"""Offline probe for layered wardrobe reduction and visible projections."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.wardrobe import (
    reduce_wardrobe,
    wardrobe_all_tags,
    wardrobe_from_tags,
    wardrobe_visible_tags,
)


def main():
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
    assert "bottomless" in visible and "no_panties" in visible
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

    # Unknown legacy style tags are preserved without inferring nudity.
    unknown = wardrobe_from_tags(["original_fantasy_attire"])
    assert wardrobe_visible_tags(unknown) == ["original_fantasy_attire"]

    print("wardrobe layer probe: ok")


if __name__ == "__main__":
    main()
