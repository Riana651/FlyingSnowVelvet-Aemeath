"""Shared UI anchor/alignment and opacity animation helpers."""

import time

from PyQt5.QtCore import QPoint

from config.config import UI
from lib.core.event.center import Event, EventType


def _clamp_opacity_value(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 1.0
    return max(0.0, min(1.0, number))


def _ui_widget_opacity_scale() -> float:
    return _clamp_opacity_value(UI.get('ui_widget_opacity', 1.0))


def apply_ui_opacity(value: float) -> float:
    """Scale a target opacity by the global UI控件透明度设置."""
    base = _clamp_opacity_value(value)
    return _clamp_opacity_value(base * _ui_widget_opacity_scale())


def get_anchor_point(widget, anchor_id: str) -> QPoint:
    """Return anchor point in widget-local coordinates."""
    rect = widget.rect()
    x = rect.x()
    y = rect.y()
    width = rect.width()
    height = rect.height()

    anchor_map = {
        'top': QPoint(x + width // 2, y),
        'bottom': QPoint(x + width // 2, y + height),
        'left': QPoint(x, y + height // 2),
        'right': QPoint(x + width, y + height // 2),
        'top_left': QPoint(x, y),
        'top_right': QPoint(x + width, y),
        'bottom_left': QPoint(x, y + height),
        'bottom_right': QPoint(x + width, y + height),
        'center': QPoint(x + width // 2, y + height // 2),
    }
    return anchor_map.get(anchor_id, anchor_map['center'])


def get_aligned_position(
    widget,
    target_window,
    target_anchor_id: str,
    self_anchor_id: str = 'top_left',
    offset_x: int = 0,
    offset_y: int = 0,
) -> QPoint:
    """Calculate aligned global position without moving the widget."""
    target_anchor = target_window.get_anchor_point(target_anchor_id)
    target_global_x = target_window.x() + target_anchor.x()
    target_global_y = target_window.y() + target_anchor.y()
    self_anchor = get_anchor_point(widget, self_anchor_id)
    return QPoint(
        target_global_x - self_anchor.x() + offset_x,
        target_global_y - self_anchor.y() + offset_y,
    )


def align_to_anchor(
    widget,
    target_window,
    target_anchor_id: str,
    self_anchor_id: str = 'top_left',
    offset_x: int = 0,
    offset_y: int = 0,
) -> None:
    """Align widget anchor to target window anchor and move immediately."""
    pos = get_aligned_position(
        widget=widget,
        target_window=target_window,
        target_anchor_id=target_anchor_id,
        self_anchor_id=self_anchor_id,
        offset_x=offset_x,
        offset_y=offset_y,
    )
    widget.move(pos.x(), pos.y())


def align_to_point(
    widget,
    point: QPoint,
    self_anchor_id: str = 'top_left',
    offset_x: int = 0,
    offset_y: int = 0,
) -> None:
    """Align widget anchor to a global point and move immediately."""
    self_anchor = get_anchor_point(widget, self_anchor_id)
    widget.move(
        point.x() - self_anchor.x() + offset_x,
        point.y() - self_anchor.y() + offset_y,
    )


def publish_widget_anchor_response(event_center, widget, *, window_id: str, anchor_id: str, ui_id: str) -> None:
    """Publish a standard UI anchor response event for a widget."""
    anchor_point = widget.get_anchor_point(anchor_id)
    global_point = QPoint(widget.x() + anchor_point.x(), widget.y() + anchor_point.y())
    event_center.publish(Event(EventType.UI_ANCHOR_RESPONSE, {
        'window_id': window_id,
        'anchor_id': anchor_id,
        'anchor_point': global_point,
        'ui_id': ui_id,
    }))


def animate_opacity(anim, opacity_effect, target: float) -> None:
    """Run opacity animation from current opacity to target."""
    target = apply_ui_opacity(target)
    anim.stop()
    anim.setStartValue(opacity_effect.opacity())
    anim.setEndValue(target)
    anim.start()


def refresh_last_activity(owner, visible_attr: str = '_visible', ts_attr: str = '_last_activity_time') -> bool:
    """Update activity timestamp for visible widgets."""
    if not getattr(owner, visible_attr, False):
        return False
    setattr(owner, ts_attr, time.time())
    return True
