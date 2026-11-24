from unittest.mock import Mock

import pytest
import shiboken6
from PySide6.QtCore import QEvent, QSize, QTimer, Qt
from PySide6.QtWidgets import QDialog

from src import app_composition, app_session
from src.app_mode import POENAVI_MODE, POETORE_MODE
from src.app_session import AppSessionController
from src.ui.main_window import MainWindow
from src.ui.poetore_mode_window import PoetoreModeWindow
from src.ui.toolbar_button import ToolbarButton
from src.update.release_client import ReleaseInfo
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


def test_navi_titlebar_updates_share_controller_and_follow_release_state(session, qtbot, monkeypatch):
    window = session.start(POENAVI_MODE, POE1)
    release = ReleaseInfo("99.99.99", "notes", "https://example.com", "https://example.com/a.zip",
                          "https://example.com/a.sha256")
    button = window.update_button
    assert isinstance(button, ToolbarButton)
    assert button.objectName() == "poenaviAppUpdateAction"
    assert button.iconSize() == QSize(20, 20)
    assert button.size() == window.minimize_button.size() == window.close_button.size()
    assert button.toolTip() == "アプリの更新をチェック"
    initial_icon = button.icon().cacheKey()
    assert window._update_check_timer.isActive()
    assert window._update_check_timer.interval() == 3600000
    from src.update.startup_gate import shared_update_controller
    assert window.update_controller is shared_update_controller()

    # Hold the worker task so the disabled state is observable before it finishes.
    worker_tasks = []
    monkeypatch.setattr(window.update_controller, "_thread_factory", lambda target: Mock(
        start=lambda: worker_tasks.append(target),
    ))
    monkeypatch.setattr("src.update.qt_controller.fetch_latest_release", lambda _version: release)
    offer = Mock()
    monkeypatch.setattr(window, "_show_update_available", offer)

    qtbot.mouseClick(button, Qt.LeftButton)
    assert len(worker_tasks) == 1
    assert not button.isEnabled()
    assert button.toolTip() == "アプリの更新を確認中…"
    worker_tasks.pop()()
    assert button.isEnabled()
    assert button.toolTip() == button.accessibleName() == "v99.99.99 に更新"
    assert button.icon().cacheKey() != initial_icon
    offer.assert_not_called()

    qtbot.mouseClick(button, Qt.LeftButton)
    worker_tasks.pop()()
    offer.assert_called_once_with(release)
    offer.reset_mock()

    monkeypatch.setattr("src.update.qt_controller.fetch_latest_release", lambda _version: None)
    window._update_check_timer.timeout.emit()
    worker_tasks.pop()()
    assert button.toolTip() == "アプリの更新をチェック"
    assert ConfigManager.load_config()["notified_update_version"] == ""
    offer.assert_not_called()

    # Settings may open while a periodic check is in flight.
    from src.update import startup_gate
    settings_offer = Mock(return_value=True)
    monkeypatch.setattr(startup_gate, "offer_update", settings_offer)
    monkeypatch.setattr("src.update.qt_controller.fetch_latest_release", lambda _version: release)
    window._update_check_timer.timeout.emit()
    settings = QDialog(window)
    QTimer.singleShot(0, worker_tasks.pop())
    window._check_for_updates_from_settings(settings)
    settings_offer.assert_called_once_with(release, settings, window.update_controller)
    offer.assert_not_called()
    assert button.isEnabled()
    assert button.toolTip() == "v99.99.99 に更新"


def test_navi_panel_buttons_and_toolbar_remain_reachable_when_all_panels_are_minimized(
    session, qtbot, qapp,
):
    window = session.start(POENAVI_MODE, POE1)
    toolbar = window.global_controls_widget
    for panel_id in ("map", "gem", "guide", "timer"):
        button = window.panel_registry[panel_id]["minimize_button"]
        qtbot.mouseClick(button, Qt.LeftButton)
        assert window.config["detached_panels"][panel_id]["minimized"]
    qapp.processEvents()
    assert toolbar.isVisible()
    assert toolbar.geometry().bottom() < toolbar.parentWidget().height()
    assert window.update_button.geometry().bottom() < toolbar.mapTo(window, toolbar.rect().topLeft()).y()
    qtbot.mouseClick(window.restore_all_panels_btn, Qt.LeftButton)
    assert not window.restore_all_panels_btn.isVisible()
    assert all(not state["minimized"] for state in window.config["detached_panels"].values())


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
    save_timer = Mock(wraps=navi1._save_timer_state_payload)
    monkeypatch.setattr(navi1, "_save_timer_state_payload", save_timer)
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
    assert save_timer.call_count == 1

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


@pytest.mark.parametrize("close_result", ["accepted", "rejected", "exception"])
def test_geometry_save_failure_stops_services_and_restores_previous_window(
    session, monkeypatch, qapp, caplog, close_result,
):
    old = session.start(POENAVI_MODE, POE1)
    old.detach_panel("timer")
    detached = old.detached_panel_windows["timer"]
    dialog = QDialog(old)
    dialog.show()
    old.start_timer()

    stops = []
    for name in ("keyboard_listener", "suppressed_capture_hotkey", "voicevox_tts"):
        stop = Mock()
        monkeypatch.setattr(old, name, Mock(stop=stop))
        stops.append(stop)
    for name in ("log_watcher", "stash_tab_scroll"):
        resource = getattr(old, name)
        stop = Mock(wraps=resource.stop)
        monkeypatch.setattr(resource, "stop", stop)
        stops.append(stop)
    remove_filter = Mock(wraps=qapp.removeEventFilter)
    monkeypatch.setattr(qapp, "removeEventFilter", remove_filter)

    close = old.close

    old.resize(old.width() + 50, old.height())

    def close_old_window():
        with monkeypatch.context() as patch:
            patch.setattr(ConfigManager, "save_config", Mock(side_effect=PermissionError("config write denied")))
            assert close()
        if close_result == "exception":
            raise RuntimeError("close failed after shutdown")
        return close_result == "accepted"

    monkeypatch.setattr(old, "close", close_old_window)
    create = app_composition.create_mode_window

    def fail_target_creation(mode, version):
        if version == POE2:
            raise RuntimeError("target window could not start")
        return create(mode, version)

    monkeypatch.setattr(app_composition, "create_mode_window", fail_target_creation)
    fallback = Mock(return_value=False)
    if close_result == "exception":
        fallback.side_effect = RuntimeError("fallback process could not start")
    monkeypatch.setattr(app_session, "switch_app_target_and_restart", fallback)
    critical = Mock()
    monkeypatch.setattr(app_session.QMessageBox, "critical", critical)

    assert not session.switch_target(POENAVI_MODE, POE2)

    assert "ウィンドウの位置とサイズを保存できませんでした" in caplog.text
    assert "config write denied" in caplog.text
    fallback.assert_called_once_with(old, POENAVI_MODE, POE2)
    critical.assert_not_called()
    assert not old.isVisible()
    assert not old.tray_icon.isVisible()
    assert not old._update_check_timer.isActive()
    assert not old.timer.isActive()
    assert not detached.isVisible()
    assert not dialog.isVisible()
    remove_filter.assert_any_call(old)
    for stop in stops:
        stop.assert_called_once_with()
    assert session.target == (POENAVI_MODE, POE1)
    assert session.window is not old
    assert session.window.isVisible()
    assert session.window.accumulated_time > 0
    assert ConfigManager.load_config()["poe_version"] == POE1
    session.single_instance.set_window.assert_called_with(session.window)
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)
    assert not shiboken6.isValid(old)


@pytest.mark.parametrize("raises", [False, True])
def test_failed_close_without_shutdown_restores_hidden_window(session, monkeypatch, raises):
    old = session.start(POENAVI_MODE, POE1)

    def fail_close():
        old.hide()
        if raises:
            raise RuntimeError("close failed before shutdown")
        return False

    with monkeypatch.context() as patch:
        patch.setattr(old, "close", fail_close)
        patch.setattr(app_session, "switch_app_target_and_restart", Mock(return_value=False))
        assert not session.switch_target(POENAVI_MODE, POE2)

    assert session.target == (POENAVI_MODE, POE1)
    assert session.window is old
    assert old.isVisible()
    assert not old._session_closed
    assert old._update_check_timer.isActive()
    session.single_instance.set_window.assert_called_with(old)
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
