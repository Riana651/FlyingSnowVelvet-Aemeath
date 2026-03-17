"""翻页按钮 - 上一页 / 下一页

宽度 120px，高度 20px（与各面板行高一致）。
样式与音响控制按钮一致：2px 黑外框 + 2px 青色中框 + 粉色背景 + 黑色箭头图标。

定位规则：
  - 上一页按钮：左上锚点对齐宿主面板的左下锚点
  - 下一页按钮：右上锚点对齐宿主面板的右下锚点
"""

from __future__ import annotations

from PyQt5.QtWidgets import QWidget, QGraphicsOpacityEffect
from PyQt5.QtCore import Qt, QPropertyAnimation, QEasingCurve, QPointF, QRectF
from PyQt5.QtGui import QPainter, QPolygonF

from config.config import UI_THEME
from config.scale import scale_px
from lib.core.event.center import get_event_center, EventType
from lib.core.topmost_manager import get_topmost_manager
from lib.core.screen_utils import clamp_rect_position
from lib.core.anchor_utils import apply_ui_opacity


# ── 配色（从 UI_THEME 获取）────────────────────────────────────────
_C_BORDER = UI_THEME['border']
_C_MID    = UI_THEME['mid']
_C_BG     = UI_THEME['bg']
_C_ICON   = UI_THEME['icon']

# ── 尺寸 ──────────────────────────────────────────────────────────────
BTN_W  = scale_px(120, min_abs=1)  # 宽度（px）
BTN_H  = scale_px(20, min_abs=1)   # 高度（px），与面板行高一致
_LAYER = scale_px(2, min_abs=1)
_BORDER = _LAYER * 2


class _PageTurnButton(QWidget):
    """翻页按钮基类。"""

    def __init__(self, direction: int, callback) -> None:
        """
        direction: -1 = 上一页，+1 = 下一页
        callback:  点击时调用的无参函数
        """
        super().__init__()
        self._direction = direction
        self._callback  = callback

        self.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(BTN_W, BTN_H)
        self.setCursor(Qt.PointingHandCursor)
        # 不抢夺键盘焦点（避免点击时导致输入框失焦）
        self.setFocusPolicy(Qt.NoFocus)
        get_topmost_manager().register(self)

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)

        self._anim = QPropertyAnimation(self._opacity, b'opacity', self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)

        self._visible = False
        self._pressed = False

        ec = get_event_center()
        ec.subscribe(EventType.UI_CLICKTHROUGH_TOGGLE, self._on_clickthrough_toggle)

    # ── 显示/隐藏 ─────────────────────────────────────────────────────

    def show_btn(self) -> None:
        if self._visible:
            return
        self._visible = True
        self.show()
        self._animate(1.0)

    def hide_btn(self) -> None:
        if not self._visible:
            return
        self._visible = False
        self._anim.finished.connect(self._on_fade_done)
        self._animate(0.0)

    def _on_fade_done(self) -> None:
        try:
            self._anim.finished.disconnect(self._on_fade_done)
        except (RuntimeError, TypeError):
            pass
        if not self._visible:
            self.hide()

    def _animate(self, target: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._opacity.opacity())
        self._anim.setEndValue(apply_ui_opacity(target))
        self._anim.start()

    # ── 事件 ──────────────────────────────────────────────────────────

    def _on_clickthrough_toggle(self, event) -> None:
        self.setAttribute(Qt.WA_TransparentForMouseEvents,
                          event.data.get('enabled', False))

    def mousePressEvent(self, event) -> None:
        from lib.script.ui._particle_helper import publish_click_particle
        publish_click_particle(self, event)
        if event.button() == Qt.LeftButton:
            self._pressed = True
            self.update()
        event.accept()  # 阻止事件传播，防止输入框失焦

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._pressed:
            self._pressed = False
            self.update()
            if self._callback:
                self._callback()
        event.accept()  # 阻止事件传播，防止输入框失焦

    # ── 绘制 ──────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)

        # 三层边框
        p.fillRect(self.rect(), _C_BORDER)
        p.fillRect(self.rect().adjusted(_LAYER, _LAYER, -_LAYER, -_LAYER), _C_MID)
        content = self.rect().adjusted(_BORDER, _BORDER, -_BORDER, -_BORDER)
        p.fillRect(content, _C_BG)

        # 箭头图标
        p.setRenderHint(QPainter.Antialiasing, True)
        cx = float(content.center().x())
        cy = float(content.center().y())
        s  = min(content.width(), content.height()) * 0.35

        p.setPen(Qt.NoPen)
        p.setBrush(_C_ICON)

        if self._direction == -1:
            # 左箭头 ◀
            arrow = QPolygonF([
                QPointF(cx + s * 0.4, cy - s * 0.7),
                QPointF(cx + s * 0.4, cy + s * 0.7),
                QPointF(cx - s * 0.4, cy),
            ])
        else:
            # 右箭头 ▶
            arrow = QPolygonF([
                QPointF(cx - s * 0.4, cy - s * 0.7),
                QPointF(cx - s * 0.4, cy + s * 0.7),
                QPointF(cx + s * 0.4, cy),
            ])
        p.drawPolygon(arrow)
        p.end()


def make_page_buttons(prev_cb, next_cb) -> tuple['_PageTurnButton', '_PageTurnButton']:
    """
    创建一对翻页按钮。
    返回 (prev_btn, next_btn)。
    """
    return _PageTurnButton(-1, prev_cb), _PageTurnButton(1, next_cb)


def update_page_buttons_position(
    panel: QWidget,
    prev_btn: '_PageTurnButton',
    next_btn: '_PageTurnButton',
    has_pages: bool,
) -> None:
    """
    根据宿主面板位置更新翻页按钮位置，并按需显示/隐藏。

    - prev_btn 左上锚点 = 面板左下锚点
    - next_btn 右上锚点 = 面板右下锚点（即 next_btn.x = panel.right - BTN_W）
    """
    panel_x = panel.x()
    panel_y = panel.y()
    panel_b = panel_y + panel.height()   # 面板底部 y
    anchor_point = panel.geometry().center()

    # 上一页：左上对齐面板左下
    px, py, _ = clamp_rect_position(
        panel_x,
        panel_b,
        BTN_W,
        BTN_H,
        point=anchor_point,
        fallback_widget=panel,
    )
    prev_btn.move(px, py)

    # 下一页：右上对齐面板右下（right_top.x = panel.right - BTN_W）
    nx, _, _ = clamp_rect_position(
        panel_x + panel.width() - BTN_W,
        py,
        BTN_W,
        BTN_H,
        point=anchor_point,
        fallback_widget=panel,
    )
    ny = py
    next_btn.move(nx, ny)

    if has_pages:
        prev_btn.show_btn()
        next_btn.show_btn()
    else:
        prev_btn.hide_btn()
        next_btn.hide_btn()
