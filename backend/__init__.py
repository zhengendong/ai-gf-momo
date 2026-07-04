"""Backend package helpers."""

from .config import settings

__all__ = ["app", "settings"]


def __getattr__(name: str):
    if name == "app":
        from .main import app
        return app
    raise AttributeError(name)
