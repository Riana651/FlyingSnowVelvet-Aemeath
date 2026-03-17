"""系统音频输出峰值检测器

通过 WASAPI IAudioMeterInformation 获取当前系统默认输出设备的实时峰值（0.0–1.0）。

使用方式：
    from lib.core.audio_meter import get_audio_meter

    meter = get_audio_meter()       # 单例
    peak  = meter.get_peak()        # 0.0–1.0，采样无锁，可在任意线程调用

设计原则：
  - 单例延迟初始化，pycaw 不可用时静默降级（始终返回 0.0）
  - 无后台线程：调用方按需采样，不产生额外开销
  - 线程安全：每次调用前初始化COM，确保多线程安全
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


class AudioMeter:
    """
    系统默认音频输出设备的实时峰值读取器。

    - 初始化失败时静默降级，`get_peak()` 始终返回 0.0
    - 不持有后台线程，由调用方按帧驱动采样
    - 线程安全：每次调用前初始化COM
    """

    def __init__(self) -> None:
        self._meter = None
        self._init_meter()

    def _init_meter(self) -> None:
        """初始化 pycaw COM 接口；失败时静默降级。"""
        try:
            from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
            from ctypes import POINTER, cast
            from comtypes import CLSCTX_ALL

            speakers  = AudioUtilities.GetSpeakers()
            dev       = speakers._dev
            interface = dev.Activate(IAudioMeterInformation._iid_, CLSCTX_ALL, None)
            self._meter = cast(interface, POINTER(IAudioMeterInformation))
            logger.debug("[AudioMeter] IAudioMeterInformation 初始化成功")
        except ImportError:
            logger.warning("[AudioMeter] pycaw 未安装，响度检测不可用")
        except Exception as e:
            logger.warning(f"[AudioMeter] 初始化失败，响度检测不可用: {e}")

    def _ensure_com_initialized(self) -> None:
        """确保当前线程已初始化COM（多线程安全）。"""
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass  # COM可能已初始化或初始化失败，忽略

    def get_peak(self) -> float:
        """
        返回当前系统音频输出峰值（0.0–1.0）。

        COM 调用失败时返回 0.0（静默降级）。
        """
        if self._meter is None:
            return 0.0
        try:
            self._ensure_com_initialized()
            return float(self._meter.GetPeakValue())
        except Exception:
            return 0.0

    def get_frequency_intensity(self) -> float | None:
        """
        返回当前音频的频率强度（0.0–1.0）。

        基于峰值和播放状态的模拟频率响应。
        返回 None 表示无法获取频率数据。
        """
        peak = self.get_peak()
        # 基于峰值模拟频率响应，使用平方根函数使低频响应更明显
        if peak > 0.01:
            import math
            # 使用 sqrt 增强低频部分的响应
            freq_intensity = math.sqrt(peak)
            return min(1.0, freq_intensity)
        return 0.0


# ── 单例访问 ──────────────────────────────────────────────────────────────
_instance: AudioMeter | None = None


def get_audio_meter() -> AudioMeter:
    """获取 AudioMeter 全局单例（首次调用时创建）。"""
    global _instance
    if _instance is None:
        _instance = AudioMeter()
    return _instance
