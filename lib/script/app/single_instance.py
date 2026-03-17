"""应用单实例锁与重复启动提示。"""

from __future__ import annotations

import ctypes
import os

from lib.core.logger import get_logger

logger = get_logger(__name__)

_ERROR_ALREADY_EXISTS = 183
_SINGLE_INSTANCE_MUTEX_NAME = 'Local\\FeiXingXueRongDesktopPet_SingleInstance'
_single_instance_mutex_handle = None


def notify_already_running() -> None:
    """提示用户程序已在运行，避免重复启动。"""
    message = '飞行雪绒已在运行中，本次重复启动已被阻止。'
    try:
        print(message)
    except Exception:
        pass
    try:
        ctypes.windll.user32.MessageBoxW(0, message, '飞行雪绒', 0x40)
    except Exception:
        pass


def acquire_single_instance_lock() -> bool:
    """获取单实例锁；返回是否允许继续启动。"""
    global _single_instance_mutex_handle
    if os.name != 'nt':
        return True

    try:
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int

        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, False, _SINGLE_INSTANCE_MUTEX_NAME)
        if not handle:
            logger.warning('创建单实例锁失败，继续启动（fail-open）')
            return True

        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False

        _single_instance_mutex_handle = handle
        return True
    except Exception as e:
        logger.warning('单实例检测异常，继续启动（fail-open）: %s', e)
        return True


def release_single_instance_lock() -> None:
    """释放单实例锁。"""
    global _single_instance_mutex_handle
    if os.name != 'nt' or not _single_instance_mutex_handle:
        _single_instance_mutex_handle = None
        return

    try:
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        kernel32.CloseHandle(_single_instance_mutex_handle)
    except Exception:
        pass
    finally:
        _single_instance_mutex_handle = None
