"""Shared config storage helpers.

目标：
1) 启动时优先读取 `C:\AemeathDeskPet\config` 中的配置。
2) 若外部目录不存在，则自动创建并复制项目内 `config` 目录。
3) 外部配置缺少新键时，按当前版本模板自动补齐（不覆盖已有值）。
4) 配置变更时支持镜像写入外部目录，便于跨版本复用。
"""

from __future__ import annotations

import threading

from lib.core.logger import get_logger
from config.shared_storage_paths import (
    get_project_root,
    get_project_config_dir,
    get_project_config_path,
    get_shared_root_dir,
    get_shared_config_dir,
    get_shared_config_path,
    local_pending_sync_path as _local_pending_sync_path,
    pending_sync_path as _pending_sync_path,
    resolve_shared_config_path as _resolve_shared_config_path,
)
from config.shared_storage_io import (
    copy_tree_missing as _copy_tree_missing,
    flush_pending_syncs as _flush_pending_syncs,
    write_shared_bytes as _write_shared_bytes,
)
from config.shared_storage_merge import sync_managed_python_file as _sync_managed_python_file

_logger = get_logger(__name__)

_BOOTSTRAP_LOCK = threading.Lock()
_BOOTSTRAPPED = False

_MANAGED_PY_FILES: dict[str, tuple[str, ...]] = {
    'config.py': (),
    'ollama_config.py': (
        'API_KEY',
        'FORCE_REPLY_MODE',
        'API_BASE_URL',
        'API_MODEL',
        'OLLAMA_MODEL',
        'PERSONA_FILE',
    ),
}

def ensure_shared_config_ready() -> None:
    """确保外部共享配置目录就绪，并完成“外部优先 + 缺键修复”同步。"""
    global _BOOTSTRAPPED
    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAPPED:
            return

        project_cfg = get_project_config_dir()
        shared_cfg = _resolve_shared_config_path()
        shared_cfg.mkdir(parents=True, exist_ok=True)

        _flush_pending_syncs(shared_cfg)
        _copy_tree_missing(project_cfg, shared_cfg)

        for rel_name, single_assignments in _MANAGED_PY_FILES.items():
            try:
                _sync_managed_python_file(rel_name, single_assignments)
            except Exception as e:
                _logger.warning('[SharedConfig] 同步 %s 失败: %s', rel_name, e)

        _BOOTSTRAPPED = True
        _logger.info('[SharedConfig] 外部配置目录已就绪: %s', shared_cfg)


def mirror_project_config_file_to_shared(rel_name: str) -> None:
    """将项目内 config/<rel_name> 镜像写入外部目录。"""
    ensure_shared_config_ready()
    local_path = get_project_config_path(rel_name)
    if not local_path.exists():
        return
    shared_path = get_shared_config_path(rel_name)
    shared_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _write_shared_bytes(shared_path, local_path.read_bytes())
    except Exception as e:
        _logger.warning('[SharedConfig] 镜像写入失败 %s: %s', shared_path, e)
