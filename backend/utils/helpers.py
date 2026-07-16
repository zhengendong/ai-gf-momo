"""
工具函数
"""

import uuid
from pathlib import Path
from typing import Any

import yaml

from ..config import settings


def generate_uuid() -> str:
    """生成 UUID"""
    return str(uuid.uuid4())


def load_yaml(file_path: Path) -> dict[str, Any]:
    """加载 YAML 文件"""
    if not file_path.exists():
        return {}
    
    with open(file_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_yaml(file_path: Path, data: dict[str, Any]) -> None:
    """保存 YAML 文件"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)


def load_json(file_path: Path) -> dict[str, Any]:
    """加载 JSON 文件"""
    import json
    if not file_path.exists():
        return {}
    
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(file_path: Path, data: dict[str, Any]) -> None:
    """保存 JSON 文件"""
    import json
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_markdown(file_path: Path) -> str:
    """读取 Markdown 文件"""
    if not file_path.exists():
        return ""
    
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def write_markdown(file_path: Path, content: str) -> None:
    """写入 Markdown 文件"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """截断文本"""
    if len(text) <= max_length:
        return text
    
    return text[:max_length - len(suffix)] + suffix


def extract_keywords(text: str, max_keywords: int = 5) -> list[str]:
    """从文本中提取关键词（简单实现）"""
    # 这里可以后续集成更复杂的关键词提取算法
    import jieba
    words = jieba.cut(text)
    # 过滤停用词和短词
    keywords = [word for word in words if len(word) > 1]
    # 返回前 N 个关键词
    return keywords[:max_keywords]


def calculate_similarity(text1: str, text2: str) -> float:
    """计算两个文本的相似度（简单实现）"""
    # 这里可以后续集成更复杂的相似度计算算法
    from difflib import SequenceMatcher
    return SequenceMatcher(None, text1, text2).ratio()
