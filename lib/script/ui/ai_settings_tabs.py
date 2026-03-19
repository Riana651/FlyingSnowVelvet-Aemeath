"""AI 设置面板 tabs 组装辅助。"""

from __future__ import annotations

from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtWidgets import QTabBar, QWidget

from config.scale import scale_px


def attach_ai_settings_tabs(panel, general_categories: list[dict]) -> None:
    panel._tab_pages = [panel._ai_panel]
    for category in general_categories:
        page = panel._build_config_category_panel(category)
        page.hide()
        panel._tab_pages.append(page)

    panel._tab_floating = QWidget(
        panel,
        Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint,
    )
    panel._tab_floating.setAttribute(Qt.WA_TranslucentBackground)
    panel._tab_floating.setAttribute(Qt.WA_ShowWithoutActivating)

    panel._top_tab_bar = QTabBar(panel._tab_floating)
    panel._top_tab_bar.setDocumentMode(True)
    panel._top_tab_bar.setDrawBase(False)
    panel._top_tab_bar.setElideMode(Qt.ElideRight)
    panel._top_tab_bar.addTab("AI设置")
    for category in general_categories:
        panel._top_tab_bar.addTab(str(category["tab"]))
    panel._top_tab_bar.currentChanged.connect(panel._on_top_tab_changed)
    panel._top_tab_bar.setCurrentIndex(0)

    layout_ai_settings_tab_bar(panel)
    layout_ai_settings_tab_panels(panel)


def layout_ai_settings_tab_bar(panel) -> None:
    if not hasattr(panel, "_top_tab_bar") or panel._top_tab_bar is None:
        return
    if not hasattr(panel, "_tab_floating") or panel._tab_floating is None:
        return

    height = max(scale_px(28, min_abs=24), panel._top_tab_bar.sizeHint().height())
    target_width = panel._top_tab_bar.sizeHint().width() + scale_px(6, min_abs=4)
    max_width = max(scale_px(180, min_abs=160), panel.width())
    width = min(target_width, max_width)
    panel._top_tab_bar.setGeometry(0, 0, width, height)

    top_left = panel.mapToGlobal(QPoint(0, 0))
    x = int(top_left.x() + (panel.width() - width) / 2.0)
    y = int(top_left.y() - height)
    panel._tab_floating.setGeometry(x, y, width, height)
    panel._tab_floating.raise_()


def show_ai_settings_tab_bar(panel) -> None:
    if panel._tab_floating is None:
        return
    layout_ai_settings_tab_bar(panel)
    panel._tab_floating.show()
    panel._tab_floating.raise_()


def hide_ai_settings_tab_bar(panel) -> None:
    if panel._tab_floating is None:
        return
    panel._tab_floating.hide()


def layout_ai_settings_tab_panels(panel) -> None:
    if not hasattr(panel, "_ai_panel") or panel._ai_panel is None:
        return

    geometry = panel._ai_panel.geometry()
    for page in panel._tab_pages[1:]:
        if page is None:
            continue
        page.setGeometry(geometry)
    if panel._tab_floating is not None and panel._tab_floating.isVisible():
        panel._tab_floating.raise_()


def set_active_ai_settings_tab(panel, index: int) -> None:
    if not panel._tab_pages:
        return

    target_index = max(0, min(index, len(panel._tab_pages) - 1))
    for page_index, page in enumerate(panel._tab_pages):
        if page is not None:
            page.setVisible(page_index == target_index)

    layout_ai_settings_tab_panels(panel)
    if 0 <= target_index < len(panel._tab_pages):
        panel._tab_pages[target_index].raise_()
    if panel._tab_floating is not None and panel._tab_floating.isVisible():
        panel._tab_floating.raise_()
