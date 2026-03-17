"""渲染管理器 - 统一管理所有渲染任务"""
from PyQt5.QtGui import QPainter, QPixmap
from PyQt5.QtCore import Qt, QRect
from typing import Dict, Optional


class RenderManager:
    """渲染管理器，统一处理所有渲染逻辑"""

    def __init__(self):
        self._renderers: Dict[str, 'Renderer'] = {}

    def register(self, name: str, renderer: 'Renderer'):
        """注册渲染器"""
        self._renderers[name] = renderer

    def unregister(self, name: str):
        """注销渲染器"""
        if name in self._renderers:
            del self._renderers[name]

    def get(self, name: str) -> Optional['Renderer']:
        """获取渲染器"""
        return self._renderers.get(name)

    def render_all(self, painter: QPainter, target_rect: QRect = None):
        """
        渲染所有已注册的渲染器

        Args:
            painter: QPainter 对象
            target_rect: 目标矩形区域，如果为 None 则使用每个渲染器自己的区域
        """
        for renderer in self._renderers.values():
            if target_rect:
                renderer.render(painter, target_rect)
            else:
                renderer.render(painter, renderer._current_pixmap.rect())

    def clear_all(self):
        """清除所有渲染器"""
        for renderer in self._renderers.values():
            renderer.clear()

    def set_alpha(self, name: str, alpha: float):
        """设置指定渲染器的透明度"""
        renderer = self.get(name)
        if renderer:
            renderer.set_alpha(alpha)

    def set_visible(self, name: str, visible: bool):
        """设置指定渲染器的可见性"""
        renderer = self.get(name)
        if renderer:
            renderer.set_visible(visible)