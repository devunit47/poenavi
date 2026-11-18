"""Compact buttons with a focus ring for keyboard navigation."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from src.ui.dialog_theme import icon_button_stylesheet


class ToolbarButton(QPushButton):
    def __init__(self, text="", parent=None, *, border_width=1, content="padding: 0;"):
        super().__init__(text, parent)
        self.setFocusPolicy(Qt.TabFocus)
        self.setStyleSheet(icon_button_stylesheet(
            border_width=border_width, content=content,
            focus_selector='[keyboardFocus="true"]:focus',
        ))

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
