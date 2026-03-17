"""启动早期硬件信息探测。"""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
import subprocess


class _MEMORYSTATUSEX(ctypes.Structure):
    """Windows 内存状态结构。"""

    _fields_ = [
        ('dwLength', ctypes.c_ulong),
        ('dwMemoryLoad', ctypes.c_ulong),
        ('ullTotalPhys', ctypes.c_ulonglong),
        ('ullAvailPhys', ctypes.c_ulonglong),
        ('ullTotalPageFile', ctypes.c_ulonglong),
        ('ullAvailPageFile', ctypes.c_ulonglong),
        ('ullTotalVirtual', ctypes.c_ulonglong),
        ('ullAvailVirtual', ctypes.c_ulonglong),
        ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
    ]

    def __init__(self):
        super().__init__()
        self.dwLength = ctypes.sizeof(self)


def _format_bytes(num_bytes: int) -> str:
    value = float(max(0, int(num_bytes)))
    units = ('B', 'KB', 'MB', 'GB', 'TB')
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == 'B':
                return f'{int(value)}{unit}'
            return f'{value:.2f}{unit}'
        value /= 1024.0
    return '0B'


def _decode_process_output(raw: bytes | None) -> str:
    if not raw:
        return ''

    sample = raw[:256]
    has_utf16_bom = raw.startswith((b'\xff\xfe', b'\xfe\xff'))
    looks_utf16 = has_utf16_bom or (sample.count(b'\x00') > max(4, len(sample) // 10))

    if looks_utf16:
        for enc in ('utf-16', 'utf-16-le', 'utf-16-be'):
            try:
                return raw.decode(enc).replace('\x00', '')
            except Exception:
                pass

    for enc in ('utf-8-sig', 'gb18030', 'cp936', 'cp1252'):
        try:
            return raw.decode(enc)
        except Exception:
            pass

    return raw.decode('utf-8', errors='ignore')


def _run_capture_text(cmd: list[str], timeout: int) -> tuple[int, str, str]:
    result = subprocess.run(cmd, capture_output=True, text=False, timeout=timeout)
    stdout = _decode_process_output(result.stdout or b'')
    stderr = _decode_process_output(result.stderr or b'')
    return result.returncode, stdout, stderr


def _get_total_memory_bytes() -> int | None:
    try:
        memory_status = _MEMORYSTATUSEX()
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory_status)):
            total = int(memory_status.ullTotalPhys)
            if total > 0:
                return total
    except Exception:
        pass
    return None


def _get_powershell_executable() -> str:
    for candidate in ('pwsh.exe', 'powershell.exe'):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return 'powershell.exe'


def _query_gpu_names() -> list[str]:
    try:
        cmd = [
            _get_powershell_executable(),
            '-NoProfile',
            '-ExecutionPolicy',
            'Bypass',
            '-Command',
            "$ErrorActionPreference='SilentlyContinue'; "
            "(Get-CimInstance Win32_VideoController | Where-Object { $_.Name } | "
            "Select-Object -ExpandProperty Name) -join ' | '",
        ]
        rc, stdout, _stderr = _run_capture_text(cmd, timeout=3)
        if rc != 0:
            return []
        output = (stdout or '').strip()
        if not output:
            return []
        return [item.strip() for item in output.split('|') if item.strip()]
    except Exception:
        return []


def log_startup_hardware_info(logger, draw_config: dict) -> None:
    """记录启动时的硬件与缩放信息。"""
    try:
        cpu_name = (platform.processor() or os.environ.get('PROCESSOR_IDENTIFIER') or 'unknown').strip()
        logical_cores = os.cpu_count()
        total_memory = _get_total_memory_bytes()
        gpu_names = _query_gpu_names()

        logger.info('[Hardware] OS: %s', platform.platform())
        logger.info('[Hardware] Arch: %s', platform.machine() or 'unknown')
        logger.info('[Hardware] CPU: %s', cpu_name)
        logger.info('[Hardware] CPU Cores(logical): %s', logical_cores if logical_cores is not None else 'unknown')
        logger.info('[Hardware] RAM: %s', _format_bytes(total_memory) if total_memory else 'unknown')
        logger.info('[Hardware] GPU: %s', ' | '.join(gpu_names) if gpu_names else 'unknown')
        logger.info(
            '[Hardware] Primary Screen: %sx%s, draw_scale=%s',
            draw_config.get('screen_width', 'unknown'),
            draw_config.get('screen_height', 'unknown'),
            draw_config.get('scale', 1.0),
        )
    except Exception as e:
        logger.warning('硬件信息采集失败: %s (%s)', type(e).__name__, e)
