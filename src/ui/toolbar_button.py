"""Compact buttons with keyboard focus rings and anchored tooltips."""

from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QLabel, QPushButton, QToolTip

from src.ui.appearance import theme_font_size
from src.ui.dialog_theme import DialogTheme, icon_button_stylesheet


def _tooltip_position(anchor, size, available):
    gap = 6
    x = anchor.x() + (anchor.width() - size.width()) // 2
    y = anchor.top() - gap - size.height()
    if y < available.top():
        y = anchor.bottom() + 1 + gap
    return QPoint(
        max(available.left(), min(x, available.right() + 1 - size.width())),
        max(available.top(), min(y, available.bottom() + 1 - size.height())),
    )


class _ToolbarTooltip(QLabel):
    def __init__(self, parent):
        super().__init__(
            parent, Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowTransparentForInput
        )
        self.setObjectName("toolbarTooltip")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setTextFormat(Qt.PlainText)

    def paintEvent(self, event):
        # The translucent tooltip window needs its background painted explicitly.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#3a3a3e"))
        painter.drawRoundedRect(self.rect(), 7, 7)
        painter.end()
        super().paintEvent(event)


_POPUP_EVENTS = (
    QEvent.Leave, QEvent.Hide, QEvent.MouseButtonPress,
    QEvent.MouseButtonDblClick, QEvent.WindowDeactivate, QEvent.ToolTipChange,
)


class ToolbarButton(QPushButton):
    def __init__(self, text="", parent=None, *, border_width=1, content="padding: 0;"):
        super().__init__(text, parent)
        self._tooltip_popup = None
        self.setFocusPolicy(Qt.TabFocus)
        self.setStyleSheet(icon_button_stylesheet(
            border_width=border_width, content=content,
            focus_selector='[keyboardFocus="true"]:focus',
        ))

    def event(self, event):
        kind = event.type()
        if kind == QEvent.ToolTip and self.toolTip() and self.isVisible():
            QToolTip.hideText()
            self._show_tooltip()
            return True

        if kind not in _POPUP_EVENTS:
            # ChildRemoved etc. can arrive while the popup's C++ object is being destroyed.
            return super().event(event)
        popup = getattr(self, "_tooltip_popup", None)
        if popup is not None and popup.isVisible():
            if kind != QEvent.ToolTipChange:
                popup.hide()
            else:
                if self.toolTip():
                    self._show_tooltip()
                else:
                    popup.hide()
        return super().event(event)

    def _show_tooltip(self):
        popup = self._tooltip_popup
        if popup is None:
            popup = _ToolbarTooltip(self)
            self._tooltip_popup = popup

        popup.setStyleSheet(f"""
            QLabel#toolbarTooltip {{
                color: #f5f5f5;
                border: none;
                padding: 4px 8px;
                font-size: {theme_font_size(DialogTheme.caption_size)}px;
                font-weight: normal;
            }}
        """)
        popup.setText(self.toolTip())
        anchor = QRect(self.mapToGlobal(QPoint()), self.size())
        screen = QGuiApplication.screenAt(anchor.center()) or self.screen()
        available = screen.availableGeometry()
        popup.setWordWrap(False)
        size = popup.sizeHint()
        if size.width() > available.width():
            popup.setWordWrap(True)
            size.setWidth(available.width())
            size.setHeight(popup.heightForWidth(size.width()))
        popup.resize(size)
        popup.move(_tooltip_position(anchor, size, available))
        popup.show()

    def set_style_property(self, name, value):
        if self.property(name) == value:
            return
        self.setProperty(name, value)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.set_style_property("keyboardFocus", event.reason() in (
            Qt.TabFocusReason, Qt.BacktabFocusReason,
        ))

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.set_style_property("keyboardFocus", False)

    def mousePressEvent(self, event):
        self.set_style_property("keyboardFocus", False)
        super().mousePressEvent(event)
