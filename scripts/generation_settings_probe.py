"""Verify workflow-default inheritance and frontend overrides without generating an image."""

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
from backend.services.generation_settings import load_generation_settings


def _ksampler_inputs(workflow: dict) -> dict:
    samplers = [node["inputs"] for node in workflow.values() if node["class_type"] == "KSampler"]
    if len(samplers) != 1:
        raise AssertionError(f"Expected one KSampler, got {len(samplers)}")
    return samplers[0]


def _latent_inputs(workflow: dict) -> dict:
    latents = [node["inputs"] for node in workflow.values() if node["class_type"] == "EmptyLatentImage"]
    if len(latents) != 1:
        raise AssertionError(f"Expected one EmptyLatentImage, got {len(latents)}")
    return latents[0]


def _template_ksampler_inputs(workflow: dict) -> dict:
    nodes = [node for node in workflow.get("nodes", []) if node.get("type") == "KSampler"]
    if len(nodes) != 1:
        raise AssertionError(f"Expected one template KSampler, got {len(nodes)}")
    values = nodes[0].get("widgets_values") or []
    has_seed_control = len(values) >= 7 and values[1] in {
        "fixed", "increment", "decrement", "randomize",
    }
    indexes = (2, 3, 4, 5) if has_seed_control else (1, 2, 3, 4)
    return dict(zip(("steps", "cfg", "sampler_name", "scheduler"), (values[index] for index in indexes)))


def _template_latent_inputs(workflow: dict) -> dict:
    nodes = [node for node in workflow.get("nodes", []) if node.get("type") == "EmptyLatentImage"]
    if len(nodes) != 1:
        raise AssertionError(f"Expected one template EmptyLatentImage, got {len(nodes)}")
    node = nodes[0]
    values = node.get("widgets_values") or []
    widget_names = [
        item["widget"]["name"]
        for item in node.get("inputs", [])
        if item.get("link") is None and "widget" in item
    ]
    return dict(zip(widget_names, values))


def _build(service: ComfyUIService, profile):
    return service.build_workflow_from_template(
        prompt="probe",
        workflow_name=profile.workflow,
        negative_prompt=profile.negative_prompt,
        width=profile.width,
        height=profile.height,
        steps=profile.steps,
        cfg=profile.cfg,
        sampler=profile.sampler,
        scheduler=profile.scheduler,
        inject_character_tags=False,
    )


def main():
    original_base_dir = settings.base_dir
    service = ComfyUIService()
    try:
        with tempfile.TemporaryDirectory(prefix="ai_gf_generation_probe_") as tmp:
            settings.base_dir = Path(tmp)
            config_dir = settings.base_dir / "config"
            config_dir.mkdir(parents=True)
            config_file = config_dir / "settings.json"

            config_file.write_text(json.dumps({
                "comfyui": {
                    "root_dir": "D:/ComfyUI",
                    "workflow": "ANIMA_workflow.json",
                },
            }), encoding="utf-8")
            inherited_profile = load_generation_settings()
            assert inherited_profile.workflow_dir == Path("D:/ComfyUI/ComfyUI/user/default/workflows")
            template = json.loads(
                (inherited_profile.workflow_dir / inherited_profile.workflow).read_text(encoding="utf-8")
            )
            template_sampler = _template_ksampler_inputs(template)
            template_latent = _template_latent_inputs(template)
            inherited = _ksampler_inputs(_build(service, inherited_profile))
            inherited_latent = _latent_inputs(_build(service, inherited_profile))
            for key in ("steps", "cfg", "sampler_name", "scheduler"):
                assert inherited[key] == template_sampler[key]
            for key in ("width", "height"):
                assert inherited_latent[key] == template_latent[key]

            config_file.write_text(json.dumps({
                "comfyui": {
                    "root_dir": "D:/ComfyUI",
                    "workflow": "ANIMA_workflow.json",
                    "steps": 10,
                    "cfg": 1,
                    "sampler": "euler",
                    "scheduler": "normal",
                    "width": 832,
                    "height": 1216,
                },
            }), encoding="utf-8")
            overridden = _ksampler_inputs(_build(service, load_generation_settings()))
            overridden_latent = _latent_inputs(_build(service, load_generation_settings()))
            assert overridden["steps"] == 10
            assert overridden["cfg"] == 1
            assert overridden["sampler_name"] == "euler"
            assert overridden["scheduler"] == "normal"
            assert overridden_latent["width"] == 832
            assert overridden_latent["height"] == 1216

            print(json.dumps({
                "inherited": {key: inherited[key] for key in ("steps", "cfg", "sampler_name", "scheduler")},
                "overridden": {key: overridden[key] for key in ("steps", "cfg", "sampler_name", "scheduler")},
                "status": "ok",
            }, ensure_ascii=False, indent=2))
    finally:
        settings.base_dir = original_base_dir


if __name__ == "__main__":
    main()
