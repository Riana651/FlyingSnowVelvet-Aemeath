"""共享的 Ollama 模型列表缓存。"""

from __future__ import annotations

import threading
from typing import Iterable

_MODEL_LOCK = threading.RLock()
_MODEL_NAMES: list[str] = []
_LAST_SOURCE: str = ""
_LAST_ERROR: str = ""


def _normalize_names(names: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for name in names:
        text = str(name or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def update_models_from_names(names: Iterable[str], *, source: str = "", allow_empty: bool = False) -> None:
    """以字符串列表的形式更新可用模型名。"""
    normalized = _normalize_names(names)
    if not normalized and not allow_empty:
        return

    with _MODEL_LOCK:
        global _MODEL_NAMES, _LAST_SOURCE, _LAST_ERROR
        _MODEL_NAMES = normalized
        if source:
            _LAST_SOURCE = source
        if normalized or allow_empty:
            _LAST_ERROR = ""


def update_models_from_tags(models: Iterable[dict]) -> None:
    """从 /api/tags 响应中提取模型名列表。"""
    names: list[str] = []
    for model in models:
        if not isinstance(model, dict):
            continue
        name = model.get("name")
        if name:
            names.append(str(name))
    update_models_from_names(names, source="api", allow_empty=True)


def record_model_error(message: str) -> None:
    """记录最近一次 CLI 检测错误，便于 UI 提示。"""
    with _MODEL_LOCK:
        global _LAST_ERROR
        _LAST_ERROR = str(message or "").strip()


def get_available_model_names() -> list[str]:
    """返回最近一次检测到的模型名列表（浅拷贝）。"""
    with _MODEL_LOCK:
        return list(_MODEL_NAMES)


def get_model_list_error() -> str:
    """返回最近一次 CLI 检测出错信息（空字符串表示最近一次成功）。"""
    with _MODEL_LOCK:
        return _LAST_ERROR


def get_model_list_source() -> str:
    """返回最近一次成功更新模型列表的来源（cli/api）。"""
    with _MODEL_LOCK:
        return _LAST_SOURCE
