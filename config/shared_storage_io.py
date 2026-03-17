"""Shared config storage atomic IO helpers."""

from __future__ import annotations

import os
import stat
import threading
from pathlib import Path

from lib.core.logger import get_logger
from config.shared_storage_paths import (
    PENDING_SYNC_SUFFIX,
    get_shared_config_dir,
    is_ignored,
    local_pending_root,
    local_pending_sync_path,
    pending_sync_path,
)

_logger = get_logger(__name__)


def safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def clear_readonly(path: Path) -> None:
    if not path.exists():
        return
    try:
        mode = path.stat().st_mode
        if not (mode & stat.S_IWRITE):
            path.chmod(mode | stat.S_IWRITE)
    except OSError:
        pass


def remove_pending_syncs(path: Path) -> None:
    safe_unlink(pending_sync_path(path))
    safe_unlink(local_pending_sync_path(path))


def write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f'.{path.name}.{os.getpid()}.{threading.get_ident()}.tmp')
    try:
        clear_readonly(path)
        safe_unlink(temp_path)
        temp_path.write_bytes(data)
        clear_readonly(temp_path)
        os.replace(temp_path, path)
    finally:
        safe_unlink(temp_path)


def queue_pending_bytes(path: Path, data: bytes, reason: Exception | None = None) -> None:
    pending_path = pending_sync_path(path)
    try:
        write_bytes_atomic(pending_path, data)
        if reason is None:
            _logger.info('[SharedConfig] 已缓存待同步文件: %s', pending_path)
        else:
            _logger.warning('[SharedConfig] 目标文件暂不可写，已缓存待同步文件 %s: %s', pending_path, reason)
        return
    except OSError as pending_error:
        local_pending = local_pending_sync_path(path)
        write_bytes_atomic(local_pending, data)
        _logger.warning(
            '[SharedConfig] 外部待同步文件写入失败，已回退到项目本地缓存 %s: target=%s reason=%s pending=%s',
            local_pending,
            path,
            reason or pending_error,
            pending_error,
        )


def write_shared_text(path: Path, text: str, encoding: str = 'utf-8') -> bool:
    payload = text.encode(encoding)
    try:
        write_bytes_atomic(path, payload)
        remove_pending_syncs(path)
        return True
    except OSError as e:
        queue_pending_bytes(path, payload, e)
        return False


def write_shared_bytes(path: Path, data: bytes) -> bool:
    try:
        write_bytes_atomic(path, data)
        remove_pending_syncs(path)
        return True
    except OSError as e:
        queue_pending_bytes(path, data, e)
        return False


def read_text_best_effort(path: Path, encoding: str = 'utf-8') -> str:
    data = path.read_bytes()
    for candidate in (encoding, 'utf-8-sig', os.device_encoding(0), 'mbcs', 'gbk'):
        if not candidate:
            continue
        try:
            return data.decode(candidate)
        except Exception:
            continue
    return data.decode(errors='ignore')


def flush_single_pending_file(pending_path: Path, target_path: Path) -> None:
    try:
        payload = pending_path.read_bytes()
        write_bytes_atomic(target_path, payload)
        pending_path.unlink()
        _logger.info('[SharedConfig] 已补写待同步文件: %s', target_path)
        remove_pending_syncs(target_path)
    except OSError as e:
        _logger.debug('[SharedConfig] 待同步文件仍不可写 %s: %s', target_path, e)


def flush_pending_syncs(base_dir: Path) -> None:
    if base_dir.exists():
        for pending_path in base_dir.rglob(f'*{PENDING_SYNC_SUFFIX}'):
            if pending_path.is_dir():
                continue
            target_name = pending_path.name[:-len(PENDING_SYNC_SUFFIX)]
            target_path = pending_path.with_name(target_name)
            flush_single_pending_file(pending_path, target_path)

    local_root = local_pending_root()
    if not local_root.exists():
        return
    shared_base = get_shared_config_dir()
    for pending_path in local_root.rglob(f'*{PENDING_SYNC_SUFFIX}'):
        if pending_path.is_dir():
            continue
        rel = pending_path.relative_to(local_root)
        target_name = rel.name[:-len(PENDING_SYNC_SUFFIX)]
        target_path = shared_base.joinpath(*rel.parts[:-1], target_name)
        flush_single_pending_file(pending_path, target_path)


def copy_tree_missing(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for node in src.rglob('*'):
        if is_ignored(node):
            continue
        rel = node.relative_to(src)
        target = dst / rel
        if node.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                write_shared_bytes(target, node.read_bytes())
            except Exception as e:
                _logger.warning('[SharedConfig] 复制缺失文件失败 %s: %s', target, e)
