from unittest.mock import Mock

import pytest
import shiboken6
from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtWidgets import QDialog

from src import app_composition, app_session
from src.app_mode import POENAVI_MODE, POETORE_MODE
from src.app_session import AppSessionController
from src.ui.main_window import MainWindow
from src.ui.poetore_mode_window import PoetoreModeWindow
from src.utils.config_manager import ConfigManager
from src.utils.poe_version_data import POE1, POE2


@pytest.fixture
def session(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("POENAVI_USER_DATA_DIR", str(tmp_path))
    log_paths = {}
    for version in (POE1, POE2):
        log_path = tmp_path / version / "Client.txt"
        log_path.parent.mkdir()
        log_path.touch()
        log_paths[version] = str(log_path)
    ConfigManager.save_config({
        "poe_version": POE1,
        "poe_version_mode": "ask",
        "client_log_paths": log_paths,
        "startup": {"preferred_mode": POENAVI_MODE, "show_mode_selector": True},
        "stash_tab_scroll_enabled": False,
    })
    monkeypatch.setattr(MainWindow, "_show_missing_log_notice", lambda self: None)
    monkeypatch.setattr(MainWindow, "_show_area_note_migration_notice_once", lambda self: None)
    monkeypatch.setattr(MainWindow, "register_hotkeys", lambda self: None)
    monkeypatch.setattr("src.ui.poetore_mode_window.GlobalHotkeyService", Mock())
    monkeypatch.setattr("src.ui.poetore_mode_window.suppressed_hotkeys_supported", lambda: False)
    monkeypatch.setattr(PoetoreModeWindow, "_currency_rate_league", lambda self: "Standard")
    monkeypatch.setattr("src.poetore.prewarm.start_search_metadata_prewarm", lambda version: None)
    monkeypatch.setattr("src.ui.custom_exchange_rate_panel.CustomExchangeRatePanel.refresh", Mock())

    properties = {
        key: qapp.property(key) for key in ("appMode", "startupPoeVersionSelected", "startupUpdateChecked")
    }
    qapp.setProperty("startupPoeVersionSelected", True)
    qapp.setProperty("startupUpdateChecked", True)
    quit_on_close = qapp.quitOnLastWindowClosed()
    qapp.setQuitOnLastWindowClosed(True)
    guard = Mock()
    controller = AppSessionController(qapp, guard)
    yield controller
    if controller.window is not None:
        controller.window.close()
        controller.window.deleteLater()
    controller.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)
    qapp.setQuitOnLastWindowClosed(quit_on_close)
    for key, value in properties.items():
        qapp.setProperty(key, value)


def _trigger_tray(window, label):
    submenu, = [action.menu() for action in window.tray_icon.contextMenu().actions() if action.menu()]
    next(action for action in submenu.actions() if action.text() == label).trigger()


def test_round_trip_through_title_and_tray_saves_timer_and_retires_windows(
    session, qtbot, qapp, monkeypatch,
):
    fallback = Mock()
    monkeypatch.setattr(app_session, "switch_app_target_and_restart", fallback)
    navi1 = session.start(POENAVI_MODE, POE1)
    assert navi1.windowTitle() == "ぽえなび [PoE1] (Fork)"
    assert navi1.tray_icon.toolTip() == navi1.windowTitle()
    old_result = navi1._poetore_window
    result_signals = old_result._trade_signals
    history_signals = navi1._worker_signals
    old_resources = {
        name: Mock() for name in ("keyboard_listener", "suppressed_capture_hotkey")
    }
    assert navi1.log_watcher.is_active
    for name, resource in old_resources.items():
        setattr(navi1, name, resource)
    for resource in (navi1.stash_tab_scroll, navi1.log_watcher):
        monkeypatch.setattr(resource, "stop", Mock(wraps=resource.stop))
    stash_stop = navi1.stash_tab_scroll.stop
    log_stop = navi1.log_watcher.stop
    dialog = QDialog(navi1)
    dialog.show()
    navi1.detach_panel("timer")
    detached = navi1.detached_panel_windows["timer"]
    navi1.start_timer()
    assert navi1.timer.isActive()
    timer_path = navi1._timer_state_path()
    navi1.resize(700, navi1.height())
    navi1.mode_switcher.mode_buttons[POETORE_MODE].click()
    # A second queued request from the retired window must not switch again.
    navi1.switch_requested.emit(POENAVI_MODE, POE2)

    qtbot.waitUntil(lambda: session.target == (POETORE_MODE, POE1))
    qtbot.waitUntil(lambda: not shiboken6.isValid(navi1))
    assert not shiboken6.isValid(detached)
    assert not shiboken6.isValid(dialog)
    assert not shiboken6.isValid(old_result)
    for resource in old_resources.values():
        resource.stop.assert_called_once_with()
    stash_stop.assert_called_once_with()
    log_stop.assert_called_once_with()
    # Late worker results can still be emitted after their widgets are gone.
    history_signals.history_checked.emit(None)
    result_signals.leagues_ready.emit(())
    assert timer_path.is_file()

    trade1 = session.window
    trade1._hideout_notification = hideout = Mock()
    trade1._heist_curio_controller = ocr = Mock()
    rate_signals = trade1._league_signals
    hotkeys = trade1.hotkey_service
    update_timer = trade1._update_check_timer
    about_to_quit = Mock()
    qapp.aboutToQuit.connect(about_to_quit)
    try:
        _trigger_tray(trade1, "PoE2 · ぽえとれ")
        # Dispatch exactly one switch while the old object's deferred delete is pending.
        qapp.sendPostedEvents(session, QEvent.MetaCall)
        assert not trade1.tray_icon.isVisible()
        assert not update_timer.isActive()
        qtbot.waitUntil(lambda: not shiboken6.isValid(trade1))
        hideout.close.assert_called_once_with()
        ocr.close.assert_called_once_with()
        assert hotkeys.stop.called
        rate_signals.ready.emit("Standard", False)
        assert session.target == (POETORE_MODE, POE2)

        trade2 = session.window
        trade2.title_bar.mode_switcher.mode_buttons[POENAVI_MODE].click()
        qtbot.waitUntil(lambda: session.target == (POENAVI_MODE, POE2))
        assert session.window.windowTitle() == "ぽえなび [PoE2] (Fork)"
        assert session.window.tray_icon.toolTip() == session.window.windowTitle()
        assert session.window.accumulated_time == 0

        session.window.resize(700, session.window.height())
        version_button = session.window.mode_switcher.version_button
        menu = version_button.menu()

        def select_poe1():
            menu.actions()[0].trigger()
            menu.close()

        QTimer.singleShot(0, select_poe1)
        qtbot.mouseClick(version_button, Qt.LeftButton)
        qtbot.waitUntil(lambda: session.target == (POENAVI_MODE, POE1))
        assert session.window.accumulated_time > 0
        assert not session.window.is_running
        assert session.window.isVisible()
        assert qapp.quitOnLastWindowClosed()
        about_to_quit.assert_not_called()
    finally:
        qapp.aboutToQuit.disconnect(about_to_quit)
    session.single_instance.set_window.assert_called_with(session.window)
    assert qapp.property("appMode") == POENAVI_MODE
    config = ConfigManager.load_config()
    assert config["poe_version"] == POE1
    assert config["poe_version_mode"] == "ask"
    assert config["startup"]["preferred_mode"] == POENAVI_MODE
    assert config["startup"]["show_mode_selector"] is True
    fallback.assert_not_called()


@pytest.mark.parametrize("restart_succeeds", [True, False])
def test_failed_window_creation_falls_back_or_restores_previous_mode(
    session, monkeypatch, qapp, restart_succeeds, caplog,
):
    old = session.start(POETORE_MODE, POE1)
    real_create = app_composition.create_mode_window

    def create(mode, version):
        if version == POE2:
            # Re-entry while constructing a window has no effect.
            assert not session.switch_target(POENAVI_MODE, POE1)
            raise RuntimeError("test window creation failure")
        return real_create(mode, version)

    monkeypatch.setattr(app_composition, "create_mode_window", create)
    restart = Mock(return_value=restart_succeeds)
    monkeypatch.setattr(app_session, "switch_app_target_and_restart", restart)
    assert session.switch_target(POETORE_MODE, POE2) is restart_succeeds
    restart.assert_called_once_with(old, POETORE_MODE, POE2)
    assert "test window creation failure" in caplog.text
    assert qapp.quitOnLastWindowClosed()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not shiboken6.isValid(old)
    if not restart_succeeds:
        assert session.target == (POETORE_MODE, POE1)
        assert session.window.isVisible()
        assert ConfigManager.load_config()["poe_version"] == POE1


def test_no_op_and_unsupported_targets_leave_current_window_and_settings(session, monkeypatch):
    window = session.start(POENAVI_MODE, POE1)
    save = Mock()
    monkeypatch.setattr(app_session, "save_app_target", save)
    monkeypatch.setattr("src.app_restart.is_feature_supported", lambda *_: False)
    for target in ((POENAVI_MODE, POE1), (POETORE_MODE, POE2), ("unknown", POE2)):
        assert not session.switch_target(*target)
    assert session.window is window
    assert window.isVisible()
    save.assert_not_called()


def test_partial_window_initialization_stops_services_before_fallback(session, monkeypatch):
    session.start(POENAVI_MODE, POE1)
    trade_hotkeys = Mock()
    monkeypatch.setattr("src.ui.poetore_mode_window.GlobalHotkeyService", lambda *_a, **_kw: trade_hotkeys)
    failed_window = None

    def fail(window):
        nonlocal failed_window
        failed_window = window
        raise RuntimeError("trade result window failed")

    monkeypatch.setattr(PoetoreModeWindow, "_prepare_poetore_window", fail)
    fallback = Mock(return_value=False)
    monkeypatch.setattr(app_session, "switch_app_target_and_restart", fallback)

    assert not session.switch_target(POETORE_MODE, POE2)
    trade_hotkeys.start.assert_called_once_with()
    trade_hotkeys.stop.assert_called_once_with()
    assert not failed_window._update_check_timer.isActive()
    assert not failed_window.tray_icon.isVisible()
    failed_window.deleteLater()
    assert session.target == (POENAVI_MODE, POE1)
    assert session.window.isVisible()


def test_save_failure_keeps_current_window_running(session, monkeypatch, qapp):
    window = session.start(POETORE_MODE, POE1)
    warning = Mock()
    monkeypatch.setattr(app_session.QMessageBox, "warning", warning)
    monkeypatch.setattr(app_session, "save_app_target", Mock(side_effect=OSError("disk full")))
    fallback = Mock()
    monkeypatch.setattr(app_session, "switch_app_target_and_restart", fallback)

    assert not session.switch_target(POETORE_MODE, POE2)
    assert session.window is window
    assert window.isVisible()
    assert window._update_check_timer.isActive()
    assert qapp.quitOnLastWindowClosed()
    assert ConfigManager.load_config()["poe_version"] == POE1
    warning.assert_called_once()
    fallback.assert_not_called()
