import pytest
from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QLabel, QWidget

from src.ui.toolbar_button import ToolbarButton, _tooltip_position


@pytest.mark.parametrize(("x", "y", "expected"), [
    (-70, 80, QPoint(-90, 50)),
    (-70, 44, QPoint(-90, 70)),
    (-96, 80, QPoint(-100, 50)),
    (176, 80, QPoint(140, 50)),
])
def test_tooltip_position(x, y, expected):
    available = QRect(-100, 40, 300, 200)
    assert _tooltip_position(QRect(x, y, 20, 20), QSize(60, 24), available) == expected


@pytest.mark.parametrize("dismiss", ["leave", "press", "hide", "clear"])
def test_toolbar_tooltip_is_anchored_and_tracks_text(qapp, qtbot, dismiss):
    window = QWidget()
    qtbot.addWidget(window)
    window.setGeometry(150, 150, 220, 120)
    button = ToolbarButton(parent=window)
    button.setGeometry(60, 45, 32, 32)
    button.setToolTip("使用量")
    window.show()
    qapp.processEvents()

    pos = QPoint(2, 3)
    qapp.sendEvent(button, QHelpEvent(QEvent.ToolTip, pos, button.mapToGlobal(pos)))
    popup = button.findChild(QLabel, "toolbarTooltip")
    assert popup.isVisible()
    assert popup.text() == "使用量"
    pixels = popup.grab().toImage()
    assert pixels.pixelColor(0, 0).alpha() == 0
    assert pixels.pixelColor(pixels.width() // 2, 2).name() == "#3a3a3e"

    button_top = button.mapToGlobal(QPoint())
    assert popup.y() + popup.height() == button_top.y() - 6
    assert abs(popup.x() + popup.width() / 2 - (button_top.x() + button.width() / 2)) <= 1
    button.setToolTip("使用量を更新\n詳細")
    assert popup.isVisible()
    assert popup.text() == button.toolTip()
    assert popup.y() + popup.height() == button_top.y() - 6
    assert abs(popup.x() + popup.width() / 2 - (button_top.x() + button.width() / 2)) <= 1

    if dismiss == "leave":
        qapp.sendEvent(button, QEvent(QEvent.Leave))
    elif dismiss == "press":
        qtbot.mousePress(button, Qt.LeftButton)
        assert not popup.isVisible()
        qtbot.mouseRelease(button, Qt.LeftButton)
    elif dismiss == "hide":
        window.hide()
    else:
        button.setToolTip("")
    assert not popup.isVisible()
