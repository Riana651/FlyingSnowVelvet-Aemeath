"""屏幕几何辅助工具。

统一处理多屏环境下的坐标归属与边界裁剪，避免各模块直接使用
QApplication.primaryScreen() 导致副屏坐标被错误裁到主屏。
"""

from __future__ import annotations

from PyQt5.QtCore import QPoint, QRect
from PyQt5.QtWidgets import QApplication, QWidget


def get_virtual_screen_geometry() -> QRect:
    """返回所有屏幕组成的虚拟桌面几何。"""
    app = QApplication.instance()
    screens = list(app.screens()) if app is not None else []
    if not screens:
        primary = QApplication.primaryScreen()
        if primary is not None:
            return primary.geometry()
        return QRect(0, 0, 1920, 1080)

    geoms = [s.geometry() for s in screens]
    left = min(g.x() for g in geoms)
    top = min(g.y() for g in geoms)
    right = max(g.x() + g.width() for g in geoms)
    bottom = max(g.y() + g.height() for g in geoms)
    return QRect(left, top, max(1, right - left), max(1, bottom - top))


def get_screen_geometry_for_point(
    point: QPoint | None = None,
    fallback_widget: QWidget | None = None,
) -> QRect:
    """按点位优先获取所属屏幕几何，失败时回退到虚拟桌面。"""
    screen = None

    if point is not None:
        screen = QApplication.screenAt(point)

    if screen is None and fallback_widget is not None:
        try:
            handle = fallback_widget.windowHandle()
        except Exception:
            handle = None
        if handle is not None:
            screen = handle.screen()
        if screen is None:
            try:
                screen = fallback_widget.screen()
            except Exception:
                screen = None

    if screen is None:
        screen = QApplication.primaryScreen()

    return screen.geometry() if screen is not None else get_virtual_screen_geometry()


def clamp_rect_position(
    x: int,
    y: int,
    width: int,
    height: int,
    point: QPoint | None = None,
    fallback_widget: QWidget | None = None,
) -> tuple[int, int, QRect]:
    """将窗口左上角裁剪到指定屏幕范围内。"""
    geom = get_screen_geometry_for_point(point=point, fallback_widget=fallback_widget)

    min_x = geom.x()
    min_y = geom.y()
    max_x = geom.x() + geom.width() - width
    max_y = geom.y() + geom.height() - height

    if max_x < min_x:
        max_x = min_x
    if max_y < min_y:
        max_y = min_y

    cx = max(min_x, min(int(x), int(max_x)))
    cy = max(min_y, min(int(y), int(max_y)))
    return cx, cy, geom
