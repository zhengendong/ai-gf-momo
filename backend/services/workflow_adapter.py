"""Optional, per-workflow node maps for safe ComfyUI prompt injection.

Workflows without a map retain the legacy type-based discovery behaviour.
When a map exists, only its declared nodes are changed.  This prevents a
secondary sampler, regional conditioning, or a detailer branch from being
mistaken for the conversation image's primary controls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import settings


@dataclass(frozen=True)
class WorkflowAdapter:
    """Node ids owned by the application for one workflow file."""

    workflow: str
    positive_prompt_nodes: tuple[str, ...] = ()
    negative_prompt_nodes: tuple[str, ...] = ()
    sampler_nodes: tuple[str, ...] = ()
    latent_size_nodes: tuple[str, ...] = ()
    save_image_nodes: tuple[str, ...] = ()


def load_workflow_adapter(workflow_name: str) -> WorkflowAdapter | None:
    """Load ``config/workflow_adapters/<workflow-stem>.json`` if it exists.

    The file name is derived from the selected workflow, while the embedded
    ``workflow`` value prevents accidentally applying a map to another file.
    Invalid maps fail the image build explicitly instead of silently mutating
    the wrong ComfyUI nodes.
    """
    filename = Path(workflow_name).name
    adapter_path = settings.config_dir / "workflow_adapters" / f"{Path(filename).stem}.json"
    if not adapter_path.exists():
        return None

    try:
        raw = json.loads(adapter_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"工作流节点映射无法读取: {adapter_path}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"工作流节点映射必须是 JSON 对象: {adapter_path}")

    configured_workflow = _required_filename(raw.get("workflow"), "workflow", adapter_path)
    if configured_workflow != filename:
        raise ValueError(
            f"工作流节点映射与所选工作流不匹配: {configured_workflow} != {filename}"
        )
    return WorkflowAdapter(
        workflow=filename,
        positive_prompt_nodes=_node_ids(raw.get("positive_prompt_nodes"), adapter_path),
        negative_prompt_nodes=_node_ids(raw.get("negative_prompt_nodes"), adapter_path),
        sampler_nodes=_node_ids(raw.get("sampler_nodes"), adapter_path),
        latent_size_nodes=_node_ids(raw.get("latent_size_nodes"), adapter_path),
        save_image_nodes=_node_ids(raw.get("save_image_nodes"), adapter_path),
    )


def _required_filename(value: Any, field: str, path: Path) -> str:
    text = str(value or "").strip()
    if not text or Path(text).name != text:
        raise ValueError(f"工作流节点映射的 {field} 必须是工作流文件名: {path}")
    return text


def _node_ids(value: Any, path: Path) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, (str, int)) for item in value):
        raise ValueError(f"工作流节点映射的节点列表格式不正确: {path}")
    ids = tuple(str(item) for item in value)
    if len(set(ids)) != len(ids):
        raise ValueError(f"工作流节点映射中存在重复节点: {path}")
    return ids
