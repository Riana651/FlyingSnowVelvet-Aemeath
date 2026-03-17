"""键盘输入处理器"""
from PyQt5.QtCore import Qt

from lib.core.event.center import get_event_center, EventType, Event


class KeyHandler:
    """处理键盘按键事件，只负责激活事件"""

    def __init__(self, pet_window):
        self._pet = pet_window
        self._event_center = get_event_center()

    def handle_key_press(self, event):
        """处理键盘按下事件"""
        event_data = {
            'key': event.key(),
            'text': event.text(),
            'modifiers': event.modifiers(),
            'is_auto_repeat': event.isAutoRepeat(),
            'pet': self._pet
        }

        key_event = Event(EventType.KEY_PRESS, event_data)
        self._event_center.publish(key_event)

    def handle_key_release(self, event):
        """处理键盘释放事件"""
        event_data = {
            'key': event.key(),
            'text': event.text(),
            'modifiers': event.modifiers(),
            'is_auto_repeat': event.isAutoRepeat(),
            'pet': self._pet
        }

        key_event = Event(EventType.KEY_RELEASE, event_data)
        self._event_center.publish(key_event)
