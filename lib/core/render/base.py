"""渲染器基类模块"""
from PyQt5.QtGui import QPainter, QPixmap, QImage
from PyQt5.QtCore import Qt
from typing import Optional


class Renderer:
    """渲染器基类"""

    def __init__(self):
        self._current_pixmap: Optional[QPixmap] = None
        self._alpha = 1.0
        self._visible = True

    def set_pixmap(self, pixmap: QPixmap):
        """设置要渲染的像素图"""
        self._current_pixmap = pixmap

    def set_alpha(self, alpha: float):
        """设置透明度 (0.0 - 1.0)"""
        self._alpha = max(0.0, min(1.0, alpha))

    def set_visible(self, visible: bool):
        """设置可见性"""
        self._visible = visible

    def render(self, painter: QPainter, target_rect):
        """
        渲染到指定区域

        Args:
            painter: QPainter 对象
            target_rect: 目标矩形区域
        """
        if not self._visible or self._current_pixmap is None:
            return

        painter.save()
        painter.setOpacity(self._alpha)
        painter.drawPixmap(target_rect, self._current_pixmap)
        painter.restore()

    def clear(self):
        """清除当前像素图"""
        self._current_pixmap = None