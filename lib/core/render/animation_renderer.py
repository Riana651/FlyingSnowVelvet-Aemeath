"""动画渲染器 - 处理动画帧的渲染"""
from PyQt5.QtGui import QPainter, QPixmap, QImage
from PyQt5.QtCore import Qt, QRect

from lib.core.render.base import Renderer
from lib.core.qt_gif_loader import scale_frame, flip_frame
from config.config import ANIMATION


class AnimationRenderer(Renderer):
    """动画渲染器，支持帧管理和缩放"""

    def __init__(self, size: tuple[int, int]):
        super().__init__()
        self._size = size
        self._frames = []
        self._current_frame_index = 0
        self._flipped = False

    def set_frames(self, frames: list[QImage]):
        """设置动画帧"""
        self._frames = frames
        self._current_frame_index = 0

    def next_frame(self):
        """切换到下一帧"""
        if not self._frames:
            return

        # 检测是否回到第一帧（循环完成）
        loop_completed = self._current_frame_index == len(self._frames) - 1

        self._current_frame_index = (self._current_frame_index + 1) % len(self._frames)
        frame = self._frames[self._current_frame_index]

        # 缩放
        frame = scale_frame(frame, self._size)

        # 翻转
        if self._flipped:
            frame = flip_frame(frame)

        self.set_pixmap(QPixmap.fromImage(frame))

        return loop_completed

    def set_flipped(self, flipped: bool):
        """设置是否翻转"""
        self._flipped = flipped

    def reset(self):
        """重置到第一帧"""
        self._current_frame_index = 0
        if self._frames:
            frame = self._frames[0]
            frame = scale_frame(frame, self._size)
            if self._flipped:
                frame = flip_frame(frame)
            self.set_pixmap(QPixmap.fromImage(frame))

    def get_frame_count(self) -> int:
        """获取帧数"""
        return len(self._frames)

    def is_empty(self) -> bool:
        """检查是否为空"""
        return len(self._frames) == 0