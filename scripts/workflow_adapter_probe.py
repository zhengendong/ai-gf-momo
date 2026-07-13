"""Verify that an optional workflow adapter changes only declared nodes."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import settings
from backend.services.comfyui import ComfyUIService


def node(node_id: int, node_type: str, widgets: list, inputs: list[dict], title: str = "") -> dict:
    return {"id": node_id, "type": node_type, "widgets_values": widgets, "inputs": inputs, "title": title}


def text_inputs() -> list[dict]:
    return [{"name": "text", "link": None, "widget": {"name": "text"}}]


def sampler_inputs() -> list[dict]:
    return [
        {"name": name, "link": None, "widget": {"name": name}}
        for name in ("seed", "steps", "cfg", "sampler_name", "scheduler", "denoise")
    ]


def main():
    original_base_dir = settings.base_dir
    try:
        with tempfile.TemporaryDirectory(prefix="ai_gf_adapter_probe_") as tmp:
            root = Path(tmp)
            settings.base_dir = root
            workflow_dir = root / "workflows"
            workflow_dir.mkdir(parents=True)
            (root / "config" / "workflow_adapters").mkdir(parents=True)
            (root / "config" / "workflow_adapters" / "complex.json").write_text(json.dumps({
                "workflow": "complex.json",
                "positive_prompt_nodes": ["1"],
                "negative_prompt_nodes": ["2"],
                "sampler_nodes": ["3"],
                "latent_size_nodes": ["5"],
            }), encoding="utf-8")
            workflow = {
                "nodes": [
                    node(1, "CLIPTextEncode", ["old main prompt"], text_inputs()),
                    node(2, "CLIPTextEncode", ["old negative"], text_inputs(), "negative"),
                    node(3, "KSampler", [101, "randomize", 30, 7, "dpmpp_sde", "karras", 1], sampler_inputs()),
                    node(4, "KSampler", [202, "randomize", 12, 2, "euler", "normal", 0.5], sampler_inputs()),
                    node(5, "EmptyLatentImage", [1024, 1024, 1], [
                        {"name": "width", "link": None, "widget": {"name": "width"}},
                        {"name": "height", "link": None, "widget": {"name": "height"}},
                        {"name": "batch_size", "link": None, "widget": {"name": "batch_size"}},
                    ]),
                    node(6, "EmptyLatentImage", [512, 512, 1], [
                        {"name": "width", "link": None, "widget": {"name": "width"}},
                        {"name": "height", "link": None, "widget": {"name": "height"}},
                        {"name": "batch_size", "link": None, "widget": {"name": "batch_size"}},
                    ]),
                ],
                "links": [],
            }
            (workflow_dir / "complex.json").write_text(json.dumps(workflow), encoding="utf-8")
            built = ComfyUIService().build_workflow_from_template(
                prompt="new main prompt",
                negative_prompt="new negative",
                workflow_name="complex.json",
                workflow_dir=workflow_dir,
                seed=123,
                steps=20,
                cfg=4,
                sampler="euler",
                scheduler="simple",
                width=832,
                height=1216,
                inject_character_tags=False,
            )
            assert built["1"]["inputs"]["text"] == "new main prompt"
            assert built["2"]["inputs"]["text"] == "new negative"
            assert built["3"]["inputs"]["steps"] == 20
            assert built["3"]["inputs"]["seed"] == 123
            assert built["4"]["inputs"]["steps"] == 12
            assert built["4"]["inputs"]["seed"] == 202
            assert built["5"]["inputs"]["width"] == 832
            assert built["6"]["inputs"]["width"] == 512
            print(json.dumps({"status": "ok", "managed_sampler": "3", "preserved_sampler": "4"}))
    finally:
        settings.base_dir = original_base_dir


if __name__ == "__main__":
    main()
