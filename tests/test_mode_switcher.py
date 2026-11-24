from unittest.mock import Mock

import pytest
from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtWidgets import QMenu

from src.app_mode import POENAVI_MODE, POETORE_MODE
from src.ui.main_window import MainWindow
from src.ui.mode_switcher import ModeSwitcherWidget, add_mode_switch_menu
from src.utils.poe_version_data import POE1, POE2
from src.version import FORK_LABEL


def _choices(menu):
    return [action for action in menu.actions() if not action.isSeparator()]


@pytest.mark.parametrize("mode", [POENAVI_MODE, POETORE_MODE])
def test_menu_indicator_has_room_and_fork_badge_fits_both_layouts(mode, qtbot):
    switcher = ModeSwitcherWidget(mode, POE1)
    qtbot.addWidget(switcher)
    switcher.show()
    assert switcher.expanded.layout().spacing() == 10

    for available, button in ((240, switcher.compact_button), (500, switcher.version_button)):
        switcher.set_available_width(600, available)
        switcher.adjustSize()
        assert button.isVisible()
        badge = switcher.fork_badge
        assert badge.isVisible()
        assert badge.text() == FORK_LABEL
        assert badge.toolTip() == "非公式Fork版"
        assert switcher.rect().contains(badge.geometry())
        assert badge.width() >= badge.sizeHint().width()

        label_width = button.fontMetrics().horizontalAdvance(button.text())
        icon_width = 0 if button.icon().isNull() else button.iconSize().width()
        assert button.width() - label_width - icon_width >= 32

        menu = button.menu()
        menu.adjustSize()
        rects = [menu.actionGeometry(action) for action in _choices(menu)]
        assert all(rect.height() >= menu.fontMetrics().height() + 12 for rect in rects)
        assert all(rect.left() >= 4 for rect in rects)
        for separator in (action for action in menu.actions() if action.isSeparator()):
            assert menu.actionGeometry(separator).height() >= 9


def test_title_bar_switches_layout_and_emits_from_mode_and_version(qtbot):
    switcher = ModeSwitcherWidget(POENAVI_MODE, POE1)
    qtbot.addWidget(switcher)
    switcher.set_available_width(600, 480)
    switcher.show()

    assert switcher.expanded.isVisible()
    assert switcher.compact_button.isHidden()
    assert switcher.version_button.text() == "PoE1"
    with qtbot.waitSignal(switcher.switch_requested, timeout=0) as request:
        qtbot.mouseClick(switcher.mode_buttons[POETORE_MODE], Qt.LeftButton)
    assert request.args == [POETORE_MODE, POE1]

    version_menu = switcher.version_button.menu()
    first, second = _choices(version_menu)
    assert first.isChecked()
    with qtbot.assertNotEmitted(switcher.switch_requested):
        first.trigger()

    def choose_version():
        second.trigger()
        version_menu.close()

    with qtbot.waitSignal(switcher.switch_requested, timeout=500) as request:
        QTimer.singleShot(0, choose_version)
        qtbot.mouseClick(switcher.version_button, Qt.LeftButton)
    assert request.args == [POENAVI_MODE, POE2]
    assert first.isChecked()

    switcher.set_available_width(439, 330)
    assert switcher.expanded.isHidden()
    assert switcher.compact_button.isVisible()
    assert switcher.compact_button.text() == "ぽえなび · PoE1"
    switcher.set_available_width(600, 150)
    assert switcher.compact_button.isVisible()
    switcher.set_available_width(600, 480)
    assert switcher.expanded.isVisible()


def test_compact_and_tray_menus_offer_same_four_targets_with_support_check(qtbot, monkeypatch):
    monkeypatch.setattr("src.ui.mode_switcher.is_feature_supported", lambda feature, version: version == POE1)
    switcher = ModeSwitcherWidget(POETORE_MODE, POE1)
    tray = QMenu()
    qtbot.addWidget(switcher)
    qtbot.addWidget(tray)
    tray_switch = Mock()
    tray_menu = add_mode_switch_menu(tray, POETORE_MODE, POE1, tray_switch)

    for menu in (switcher.compact_button.menu(), tray_menu):
        actions = _choices(menu)
        assert [action.text() for action in actions] == [
            "PoE1 · ぽえなび", "PoE1 · ぽえとれ\t✓", "PoE2 · ぽえなび", "PoE2 · ぽえとれ",
        ]
        assert all(not action.icon().isNull() for action in actions)
        assert [action.isChecked() for action in actions] == [False, True, False, False]
        assert not actions[-1].isEnabled()
        assert "対応していません" in actions[-1].toolTip()

    with qtbot.waitSignal(switcher.switch_requested, timeout=0) as request:
        _choices(switcher.compact_button.menu())[2].trigger()
    assert request.args == [POENAVI_MODE, POE2]
    _choices(tray_menu)[2].trigger()
    tray_switch.assert_called_once_with(POENAVI_MODE, POE2)
    assert not _choices(switcher.version_button.menu())[1].isEnabled()
    unsupported = ModeSwitcherWidget(POENAVI_MODE, POE2)
    qtbot.addWidget(unsupported)
    assert not unsupported.mode_buttons[POETORE_MODE].isEnabled()


def test_main_window_emits_switch_requests_from_title_and_tray(qtbot, monkeypatch):
    class UiBuilt(Exception):
        pass

    setup_ui = MainWindow.setup_ui

    def build_ui(window):
        setup_ui(window)
        raise UiBuilt

    monkeypatch.setattr("src.ui.main_window.ConfigManager.load_config", lambda: {
        "poe_version": POE1, "timer_size": "off", "guide_expanded": False, "lap_expanded": False,
    })
    monkeypatch.setattr(MainWindow, "_run_startup_update_gate", lambda self: True)
    monkeypatch.setattr(MainWindow, "_sync_voicevox_service", lambda self: None)
    monkeypatch.setattr(MainWindow, "_restore_progress_flags", lambda self: None)
    monkeypatch.setattr(MainWindow, "setup_ui", build_ui)
    window = MainWindow.__new__(MainWindow)
    with pytest.raises(UiBuilt):
        window.__init__()
    qtbot.addWidget(window)
    window._build_tray_icon()
    switches = []
    window.switch_requested.connect(lambda mode, version: switches.append((mode, version)))
    window.resize(420, window.height())
    window.show()
    assert window.mode_switcher.compact_button.isVisible(), (window.width(), window.minimumWidth())
    window.resize(640, window.height())
    assert window.mode_switcher.expanded.isVisible()
    button = window.mode_switcher.mode_buttons[POETORE_MODE]
    assert window._detect_edge(button.mapTo(window, QPoint(0, 0))) is None
    assert window.click_through_label.geometry().top() > button.mapTo(window, button.rect().bottomLeft()).y()

    qtbot.mouseClick(button, Qt.LeftButton)
    tray_menu = window.tray_icon.contextMenu()
    submenu, = [action.menu() for action in tray_menu.actions() if action.menu()]
    assert _choices(submenu)[0].isChecked()
    _choices(submenu)[3].trigger()
    assert switches == [(POETORE_MODE, POE1), (POETORE_MODE, POE2)]
