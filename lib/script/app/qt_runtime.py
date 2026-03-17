"""Qt 运行环境准备。"""

from __future__ import annotations

import os
import sys

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt


def _ensure_qt_plugin_paths(logger) -> None:
    if ('QT_QPA_PLATFORM_PLUGIN_PATH' in os.environ
            and 'QT_PLUGIN_PATH' in os.environ):
        return

    try:
        import PyQt5.QtCore

        qt_path = os.path.dirname(PyQt5.QtCore.__file__)
        plugins_path = os.path.join(qt_path, 'Qt5', 'plugins')
        platforms_path = os.path.join(plugins_path, 'platforms')
        if ('QT_QPA_PLATFORM_PLUGIN_PATH' not in os.environ
                and os.path.exists(platforms_path)):
            os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = platforms_path
            logger.info('Qt平台插件路径: %s', platforms_path)
        if ('QT_PLUGIN_PATH' not in os.environ
                and os.path.exists(plugins_path)):
            os.environ['QT_PLUGIN_PATH'] = plugins_path
            logger.info('Qt插件路径: %s', plugins_path)
    except Exception as e:
        logger.warning('警告: 无法自动设置Qt插件路径: %s', e)


def create_qt_application(logger, argv: list[str] | None = None) -> QApplication:
    """准备 Qt 运行环境并创建 QApplication。"""
    _ensure_qt_plugin_paths(logger)

    dont_use_native_menus_attr = getattr(Qt, 'AA_DontUseNativeMenuWindows', None)
    if dont_use_native_menus_attr is not None:
        QApplication.setAttribute(dont_use_native_menus_attr, True)

    app = QApplication(sys.argv if argv is None else argv)
    app.setQuitOnLastWindowClosed(False)
    return app
