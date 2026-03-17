"""UI 点击粒子特效辅助函数

在任意 UI 类的 mousePressEvent 中调用 publish_click_particle(self, event)，
即可在点击位置触发对应粒子特效：
  左键 → click（浅青色 Click 文字）
  右键 → pink_click（浅粉色 Click 文字）
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from lib.core.event.center import get_event_center, EventType, Event


def publish_click_particle(widget, event) -> None:
    """根据鼠标按钮在点击全局坐标处发射对应粒子特效。"""
    if event.button() == Qt.LeftButton:
        particle_id = 'click'
    elif event.button() == Qt.RightButton:
        particle_id = 'pink_click'
    else:
        return

    gpos = widget.mapToGlobal(event.pos())
    get_event_center().publish(Event(EventType.PARTICLE_REQUEST, {
        'particle_id': particle_id,
        'area_type':   'point',
        'area_data':   (gpos.x(), gpos.y()),
    }))
