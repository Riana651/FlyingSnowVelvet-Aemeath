"""应用事件处理器 - 处理应用级别的逻辑"""
from PyQt5.QtWidgets import QApplication

from lib.core.event.center import get_event_center, EventType, Event


class AppEventHandler:
    """处理应用事件的具体逻辑"""

    def __init__(self, pet_window):
        self._pet = pet_window
        self._event_center = get_event_center()

        # 订阅应用事件
        self._event_center.subscribe(EventType.APP_QUIT, self._on_app_quit)

    def _on_app_quit(self, event: Event):
        """处理应用退出"""
        QApplication.quit()