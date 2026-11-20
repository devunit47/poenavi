from unittest.mock import MagicMock, Mock, call, patch

import pytest
from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
)

from src.poetore.exchange_catalog import exchange_catalog_by_id
from src.ui.dialog_theme import UI_METRICS
from src.ui.poetore_mode_window import (
    PoetoreModeWindow,
    _expedition_icon,
    _heist_curio_icon,
)
from src.ui.poetore_settings_dialog import PoetoreSettingsDialog
from src.update.qt_controller import UpdateController
from src.update.release_client import ReleaseInfo
from src.update.startup_gate import run_startup_update_gate
from src.utils.config_manager import ConfigManager
from src.utils.poe_version_data import POE1, POE2
from src.version import APP_VERSION


def test_main_title_bar_shows_title_and_short_poe_version_without_eyebrow():
    app = QApplication.instance() or QApplication([])

    for poe_version, expected in (
        (POE1, "（PoE1）"),
        (POE2, "（PoE2）"),
    ):
        with patch(
            "src.ui.poetore_mode_window.ConfigManager.load_config",
            return_value={"poe_version": poe_version, "hotkeys": {}},
        ), patch(
            "src.ui.poetore_mode_window.GlobalHotkeyService",
        ), patch.object(PoetoreModeWindow, "refresh_currency_rate"):
            window = PoetoreModeWindow()

        window.show()
        app.processEvents()
        assert window.title_label.parentWidget() is window.title_bar
        assert window.mode_label.parentWidget() is window.title_bar
        assert window.title_label.text() == "ぽえとれ"
        assert window.mode_label.text() == expected
        assert window.windowTitle() == "ぽえとれ"
        assert all(
            label.text() != "価格チェック・トレード支援"
            for label in window.findChildren(QLabel)
        )
        assert window.mode_label.width() >= window.mode_label.sizeHint().width()
        assert (
            window.mode_label.font().pixelSize()
            == window.title_label.font().pixelSize() - 4
        )
        assert window.mode_label.palette().color(
            window.mode_label.foregroundRole()
        ) == window.title_label.palette().color(
            window.title_label.foregroundRole()
        )
        window.close()
        app.processEvents()


@pytest.fixture
def hold_update_checks(monkeypatch):
    def hold(controller):
        workers = []

        def make_thread(work):
            workers.append(work)
            return Mock()

        monkeypatch.setattr(controller, "_thread_factory", make_thread)
        return workers

    return hold


def test_poetore_download_action_uses_notified_version_and_hourly_check(hold_update_checks):
    app = QApplication.instance() or QApplication([])
    config = {
        "poe_version": POE1,
        "hotkeys": {},
        "notified_update_version": "9.9.9",
    }

    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config",
        return_value=config,
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService",
    ), patch.object(PoetoreModeWindow, "refresh_currency_rate"):
        window = PoetoreModeWindow()

    window.show()
    app.processEvents()
    assert window.update_button.isVisible()
    assert not window.update_button.text()
    assert not window.update_button.icon().isNull()
    assert window.update_button.toolTip() == "v9.9.9 に更新"
    assert window.update_button.parentWidget() is window.title_bar
    assert window.update_button.geometry().right() < window.title_bar.minimize_button.x()
    assert window.findChild(QPushButton, "poetoreUpdateButton") is None
    assert not window.capture_warning.isVisible()
    assert window._update_check_timer.interval() == 60 * 60 * 1000
    assert window._update_check_timer.isActive()

    controller = window._update_controller
    workers = hold_update_checks(controller)
    with patch.object(controller, "check", wraps=controller.check) as check:
        window._update_check_timer.timeout.emit()
    check.assert_called_once_with(False)
    assert not window.update_button.isEnabled()
    with patch("src.update.qt_controller.fetch_latest_release", side_effect=RuntimeError("offline")):
        workers.pop()()
    assert window.update_button.isEnabled()
    assert window.update_button.toolTip() == "v9.9.9 に更新"

    release = ReleaseInfo("9.9.9", "", "https://example.com", "", "")
    with patch("src.update.qt_controller.fetch_latest_release", return_value=release), patch(
        "src.update.startup_gate.UpdateAvailableDialog",
    ) as available:
        available.return_value.exec.return_value = QDialog.Rejected
        window.update_button.click()
        workers.pop()()
    available.assert_called_once_with(release, False, window)
    assert window._update_check_timer.isActive()

    window.close()
    app.processEvents()


@pytest.mark.parametrize("manual", [False, True])
def test_poetore_update_action_changes_when_check_finds_release(manual, hold_update_checks):
    app = QApplication.instance() or QApplication([])
    config = {
        "poe_version": POE1,
        "hotkeys": {},
        "notified_update_version": APP_VERSION,
    }

    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config",
        return_value=config,
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService",
    ), patch.object(PoetoreModeWindow, "refresh_currency_rate"):
        window = PoetoreModeWindow()

    button = window.update_button
    assert button.toolTip() == "アプリの更新をチェック"
    idle_icon = button.icon().pixmap(button.iconSize()).toImage()
    release = ReleaseInfo(
        version="9.9.9",
        notes="test",
        page_url="https://example.com/release",
        zip_url="https://example.com/PoENavi.zip",
        checksum_url="https://example.com/PoENavi.zip.sha256",
    )
    controller = window._update_controller
    workers = hold_update_checks(controller)
    with patch.object(controller, "check", wraps=controller.check) as check:
        if manual:
            button.click()
        else:
            window._update_check_timer.timeout.emit()
        window._update_check_timer.timeout.emit()
    check.assert_called_once_with(manual)
    assert not button.isEnabled()
    assert button.toolTip() == "アプリの更新を確認中…"
    assert button.icon().pixmap(button.iconSize()).toImage() != idle_icon
    with patch("src.ui.poetore_mode_window.ConfigManager.save_config") as save_config, patch(
        "src.update.qt_controller.fetch_latest_release", return_value=release,
    ):
        workers.pop()()

    assert config["notified_update_version"] == "9.9.9"
    save_config.assert_called_once_with(config)
    assert button.isEnabled()
    assert button.toolTip() == "v9.9.9 に更新"
    assert button.icon().pixmap(button.iconSize()).toImage() != idle_icon

    window.close()
    app.processEvents()


@pytest.mark.parametrize("failed", [False, True])
def test_manual_app_update_check_reports_result_and_allows_retry(failed, hold_update_checks):
    app = QApplication.instance() or QApplication([])
    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config",
        return_value={"poe_version": POE1, "hotkeys": {}},
    ), patch("src.ui.poetore_mode_window.GlobalHotkeyService"), patch.object(
        PoetoreModeWindow, "refresh_currency_rate",
    ):
        window = PoetoreModeWindow()
    workers = hold_update_checks(window._update_controller)
    with patch(
        "src.update.qt_controller.fetch_latest_release",
        return_value=None, side_effect=RuntimeError("offline") if failed else None,
    ) as fetch, patch(
        "src.ui.update_dialogs.show_update_message",
    ) as message:
        window.update_button.click()
        assert len(workers) == 1
        workers.pop()()
        if failed:
            message.assert_called_once_with(
                window, QMessageBox.Warning, "アップデート", "更新を確認できませんでした。\noffline",
            )
        else:
            message.assert_called_once_with(
                window, QMessageBox.Information, "アップデート", "最新バージョンです。",
            )
        assert window.update_button.isEnabled()
        assert window.update_button.toolTip() == "アプリの更新をチェック"
        window.update_button.click()
        assert len(workers) == 1
        workers.pop()()
        assert fetch.call_count == 2

    window.close()
    app.processEvents()


@pytest.mark.parametrize("source, result", [
    ("toolbar", "latest"),
    ("toolbar", "failed"),
    ("toolbar", "timeout"),
    ("hourly", "failed"),
    ("download", "failed"),
    ("download", "available"),
])
def test_app_information_joins_toolbar_or_hourly_update_check(source, result, monkeypatch):
    app = QApplication.instance() or QApplication([])
    config = {"poe_version": POE1, "hotkeys": {}}
    if source == "download":
        config["notified_update_version"] = "9.9.9"
    release = ReleaseInfo("10.0.0", "", "https://example.com", "", "")
    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config", return_value=config,
    ), patch("src.ui.poetore_mode_window.GlobalHotkeyService"), patch.object(
        PoetoreModeWindow, "refresh_currency_rate",
    ):
        window = PoetoreModeWindow()

    original_check = UpdateController.check

    def check_on_event_loop(controller, manual):
        def make_thread(target):
            if result == "timeout":
                return Mock()
            return Mock(start=lambda: QTimer.singleShot(0, target))

        with patch.object(
            controller, "_thread_factory", make_thread,
        ):
            original_check(controller, manual)

    settings = []

    def check_from_app_information(dialog):
        settings.append(dialog)
        dialog.app_info_widget.update_button.click()
        return QDialog.Rejected

    watchdog = QTimer(window)
    watchdog.setSingleShot(True)
    watchdog.timeout.connect(lambda: window._update_controller.check_failed.emit("watchdog", False))
    if result == "timeout":
        monkeypatch.setattr("src.update.qt_controller.CHECK_TIMEOUT_MS", 25, raising=False)
        watchdog.start(1000)

    try:
        with patch.object(UpdateController, "check", check_on_event_loop), patch.object(
            PoetoreSettingsDialog, "exec", check_from_app_information,
        ), patch(
            "src.update.qt_controller.fetch_latest_release",
            return_value=release if result == "available" else None,
            side_effect=RuntimeError("offline") if result == "failed" else None,
        ) as fetch, patch(
            "src.ui.update_dialogs.show_update_message",
        ) as toolbar_message, patch(
            "src.update.startup_gate.show_update_message",
        ) as settings_message, patch(
            "src.update.startup_gate.UpdateAvailableDialog",
        ) as available, patch("src.utils.config_manager.ConfigManager.save_config"):
            available.return_value.exec.return_value = QDialog.Rejected
            if source == "hourly":
                window._update_check_timer.timeout.emit()
            else:
                window.update_button.click()
            assert not window.update_button.isEnabled()
            window.settings_button.click()
            app.processEvents()

        if result == "timeout":
            fetch.assert_not_called()
        else:
            fetch.assert_called_once_with(APP_VERSION)
        if result == "available":
            available.assert_called_once_with(release, False, settings[0])
            toolbar_message.assert_not_called()
            settings_message.assert_not_called()
        else:
            available.assert_not_called()
            if result == "latest":
                icon, message = QMessageBox.Information, "最新バージョンです。"
            else:
                error = "offline" if result == "failed" else "更新確認がタイムアウトしました。"
                icon, message = QMessageBox.Warning, f"更新を確認できませんでした。\n{error}"
            settings_message.assert_called_once_with(settings[0], icon, "アップデート", message)
            if source == "hourly":
                toolbar_message.assert_not_called()
            else:
                toolbar_message.assert_called_once_with(window, icon, "アップデート", message)
        assert window.update_button.isEnabled()
        version = config.get("notified_update_version")
        assert window.update_button.toolTip() == (
            f"v{version} に更新" if version else "アプリの更新をチェック"
        )
    finally:
        watchdog.stop()
        window.close()
        app.processEvents()


def test_startup_gate_and_hourly_check_share_release_result(hold_update_checks):
    app = QApplication.instance() or QApplication([])
    config = {"poe_version": POE1, "hotkeys": {}}
    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config", return_value=config,
    ), patch("src.ui.poetore_mode_window.GlobalHotkeyService"), patch.object(
        PoetoreModeWindow, "refresh_currency_rate",
    ):
        window = PoetoreModeWindow()

    release = ReleaseInfo("9.9.9", "", "https://example.com", "", "")
    workers = hold_update_checks(window._update_controller)
    try:
        with patch(
            "src.update.qt_controller.fetch_latest_release", return_value=release,
        ) as fetch, patch(
            "src.update.startup_gate.UpdateAvailableDialog",
        ) as available, patch("src.utils.config_manager.ConfigManager.save_config") as save:
            available.return_value.exec.return_value = QDialog.Rejected
            window._update_check_timer.timeout.emit()
            QTimer.singleShot(0, workers.pop())
            assert run_startup_update_gate(config) is True

        fetch.assert_called_once_with(APP_VERSION)
        available.assert_called_once()
        assert available.call_args.args[0] is release
        assert config["notified_update_version"] == release.version
        save.assert_called_once_with(config)
        assert window.update_button.isEnabled()
        assert window.update_button.toolTip() == "v9.9.9 に更新"
    finally:
        window.close()
        app.processEvents()


def test_download_action_clears_withdrawn_release_and_returns_to_manual_check(
    tmp_path, monkeypatch, hold_update_checks,
):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("POENAVI_USER_DATA_DIR", str(tmp_path))
    ConfigManager.save_config({"poe_version": POE1, "notified_update_version": "9.9.9"})
    with patch("src.ui.poetore_mode_window.GlobalHotkeyService"), patch.object(
        PoetoreModeWindow, "refresh_currency_rate",
    ):
        window = PoetoreModeWindow()

    workers = hold_update_checks(window._update_controller)
    try:
        assert window.update_button.toolTip() == "v9.9.9 に更新"
        with patch(
            "src.update.qt_controller.fetch_latest_release", return_value=None,
        ) as fetch, patch(
            "src.ui.update_dialogs.show_update_message",
        ) as message:
            window.update_button.click()
            workers.pop()()

        fetch.assert_called_once_with(APP_VERSION)
        message.assert_called_once_with(
            window, QMessageBox.Information, "アップデート", "最新バージョンです。",
        )
        assert ConfigManager.load_config()["notified_update_version"] == ""
        assert window.update_button.isEnabled()
        assert window.update_button.toolTip() == "アプリの更新をチェック"
    finally:
        window.close()
        app.processEvents()


@pytest.mark.parametrize("key", [Qt.Key_Space, Qt.Key_Enter, Qt.Key_Return])
def test_focused_update_action_activates_by_keyboard(key):
    app = QApplication.instance() or QApplication([])
    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config",
        return_value={"poe_version": POE1, "hotkeys": {}},
    ), patch("src.ui.poetore_mode_window.GlobalHotkeyService"), patch.object(
        PoetoreModeWindow, "refresh_currency_rate",
    ):
        window = PoetoreModeWindow()

    try:
        window.show()
        window.activateWindow()
        button = window.update_button
        button.setFocus(Qt.TabFocusReason)
        app.processEvents()
        assert button.hasFocus()
        with patch.object(window, "_start_update_check") as check:
            QTest.keyClick(button, key)
        check.assert_called_once_with(manual=True)
    finally:
        window.close()
        app.processEvents()


def test_hideout_notification_action_tracks_controller_and_keeps_elapsed_time(tmp_path):
    app = QApplication.instance() or QApplication([])
    log = tmp_path / "Client.txt"
    log.touch()
    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config",
        return_value={"poe_version": POE1, "client_log_paths": {POE1: str(log)}},
    ), patch("src.ui.poetore_mode_window.GlobalHotkeyService"), patch.object(
        PoetoreModeWindow, "refresh_currency_rate",
    ):
        window = PoetoreModeWindow()
    window.show()
    app.processEvents()
    button = window.focus_button
    off_icon = button.icon().pixmap(button.iconSize()).toImage()
    assert button.isCheckable() and not button.isChecked()
    assert button.toolTip() == "隠れ家滞在通知：OFF（クリックで切替）"
    assert window.focus_status.isHidden()

    controller = window._ensure_hideout_notification()
    with patch.object(controller, "_process_finder", return_value=None), patch(
        "src.ui.poetore_mode_window.QMessageBox.information",
    ) as message:
        button.click()
    message.assert_called_once()
    assert not button.isChecked()

    process = Mock()
    watcher = Mock()
    with patch.object(controller, "_process_finder", return_value=process), patch.object(
        controller, "_watcher_factory", return_value=watcher,
    ), patch.object(controller, "_monotonic", return_value=10.0) as clock, patch(
        "src.poetore.hideout_notification_controller.latest_zone_since_process_start",
        return_value="Coastal Hideout",
    ):
        button.click()
        assert controller.active and button.isChecked()
        assert button.toolTip() == "隠れ家滞在通知：ON（クリックで切替）"
        assert button.accessibleName() == "隠れ家滞在通知：ON"
        assert button.icon().pixmap(button.iconSize()).toImage() != off_icon
        clock.return_value = 13.0
        controller._tick()
        assert window.focus_status.isVisible()
        assert window.focus_status.text() == "0:03"

        controller.flash_requested.emit()
        assert button.property("notificationFlash")
        window._focus_flash_timer.timeout.emit()
        assert not button.property("notificationFlash")
        assert button.isChecked()

        button.click()
        assert not controller.active and not button.isChecked()
        assert window.focus_status.isHidden()
        assert button.icon().pixmap(button.iconSize()).toImage() == off_icon

    window.close()
    app.processEvents()


def test_poetore_mode_starts_only_common_and_poetore_services():
    app = QApplication.instance() or QApplication([])
    config = {
        "hotkeys": {
            "exit": "F5",
            "monastery": "F12",
            "poetore_capture": "alt+d",
            "poetore_auto_hide": "ctrl+d",
            "map_check": "alt+f",
            "cheat_sheets_toggle": "shift+space",
            "start_stop": "F7",
        },
    }

    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config",
        return_value=config,
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService"
    ) as hotkey_class, patch(
        "src.ui.poetore_mode_window.StashTabScrollController"
    ) as stash_class, patch(
        "src.ui.poetore_mode_window.ForegroundSuppressedHotkeyService"
    ) as suppressed_class, patch(
        "src.ui.poetore_mode_window.suppressed_hotkeys_supported",
        return_value=True,
    ):
        hotkey_service = MagicMock()
        hotkey_service.command.connect = MagicMock()
        hotkey_class.return_value = hotkey_service
        with patch.object(PoetoreModeWindow, "refresh_currency_rate"):
            window = PoetoreModeWindow()

    supplied_hotkeys = hotkey_class.call_args.args[0]
    assert hotkey_class.call_args.kwargs["action_filter"] is not None
    assert supplied_hotkeys == {
        "exit": "F5",
        "monastery": "F12",
        "poetore_auto_hide": "ctrl+d",
        "map_check": "alt+f",
        "cheat_sheets_toggle": "shift+space",
    }
    suppressed_class.assert_called_once()
    args = suppressed_class.call_args.args
    kwargs = suppressed_class.call_args.kwargs
    assert args == ("poetore_capture", "alt+d")
    assert kwargs["parent"] is window
    assert callable(kwargs["result_window_checker"])
    assert callable(kwargs["poe_target_getter"])
    suppressed_class.return_value.start.assert_called_once_with()
    stash_class.assert_called_once_with(enabled=True)
    stash_class.return_value.start.assert_called_once_with()
    assert not hasattr(window, "log_watcher")
    assert not hasattr(window, "mini_navi_overlay")
    assert not hasattr(window, "timer")
    assert "currency_rate_refresh" in window.active_service_names
    assert "stash_tab_scroll" in window.active_service_names
    header_buttons = (
        window.memo_button,
        window.heist_settings_button,
        window.expedition_settings_button,
        window.desecration_settings_button,
        window.map_mods_button,
        window.cheat_sheets_button,
        window.settings_button,
    )
    assert window.header_action_buttons == header_buttons
    window.show()
    app.processEvents()
    assert not window.focus_button.text()
    assert not window.focus_button.icon().isNull()
    assert window.focus_button.size() == QSize(36, 36)
    assert window._hideout_notification is None
    assert all(button.text() == "" for button in header_buttons)
    assert all(not button.icon().isNull() for button in header_buttons)
    assert all(button.iconSize() == QSize(24, 24) for button in header_buttons)
    assert all(button.focusPolicy() == Qt.TabFocus for button in header_buttons)
    icon_images = [
        button.icon().pixmap(QSize(24, 24)).toImage() for button in header_buttons
    ]
    assert all(image != icon_images[0] for image in icon_images[1:])
    assert window.memo_button.size().width() == 36
    assert window.memo_button.size().height() == 36
    assert all(
        button.height() == window.focus_button.height()
        for button in header_buttons
    )
    assert window.divine_rate_value.text() == "最新データを取得できません"
    assert window.divine_rate_value.alignment() == Qt.AlignCenter
    assert window.minimumWidth() == 500
    assert window.width() == 558
    assert window.windowFlags() & Qt.FramelessWindowHint
    assert not window.capture_warning.isVisible()
    minimize_button = window.findChild(QPushButton, "poetoreMinimizeButton")
    close_button = window.findChild(QPushButton, "poetoreCloseButton")
    assert minimize_button.text() == "─"
    assert close_button.text() == "×"
    assert minimize_button.focusPolicy() == Qt.TabFocus
    assert close_button.focusPolicy() == Qt.TabFocus
    assert not window.rate_refresh_button.text()
    assert not window.rate_refresh_button.icon().isNull()
    assert window.rate_refresh_button.focusPolicy() == Qt.TabFocus
    assert window.tray_icon.toolTip() == "ぽえとれ"
    assert [
        action.text() for action in window.tray_icon.contextMenu().actions()
        if not action.isSeparator()
    ] == ["ぽえとれを表示", "設定", "終了"]
    hotkey_service.start.assert_called_once()
    window.close()
    app.processEvents()
    stash_class.return_value.stop.assert_called_once_with()


def test_expedition_settings_button_is_immediately_right_of_memo_for_poe2():
    app = QApplication.instance() or QApplication([])
    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config",
        return_value={"poe_version": POE2, "hotkeys": {}},
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService",
    ), patch.object(PoetoreModeWindow, "refresh_currency_rate"):
        window = PoetoreModeWindow()

    assert window.header_action_buttons[:2] == (
        window.memo_button,
        window.expedition_settings_button,
    )
    assert window.expedition_settings_button.isVisibleTo(window)
    assert window.expedition_settings_button.toolTip() == (
        "エクスペ報酬チェック設定を開く"
    )
    window.close()
    app.processEvents()


def test_heist_settings_button_is_immediately_right_of_memo_for_poe1():
    app = QApplication.instance() or QApplication([])
    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config",
        return_value={"poe_version": POE1, "hotkeys": {}},
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService",
    ), patch.object(PoetoreModeWindow, "refresh_currency_rate"):
        window = PoetoreModeWindow()

    window.show()
    app.processEvents()
    assert window.header_action_buttons[:2] == (
        window.memo_button,
        window.heist_settings_button,
    )
    assert window.heist_settings_button.isVisibleTo(window)
    assert not window.heist_settings_button.icon().isNull()
    assert window.heist_settings_button.toolTip() == "ハイスト報酬OCR設定を開く"
    assert not _heist_curio_icon().isNull()
    window.close()
    app.processEvents()


def test_expedition_icon_has_two_upper_curls_and_one_lower_curl():
    QApplication.instance() or QApplication([])
    image = _expedition_icon().pixmap(QSize(24, 24)).toImage()

    def opaque_pixels(left, top, right, bottom):
        return sum(
            image.pixelColor(x, y).alpha() > 20
            for y in range(top, bottom)
            for x in range(left, right)
        )

    top_center = opaque_pixels(8, 0, 16, 8)
    bottom_center = opaque_pixels(8, 16, 16, 24)
    assert bottom_center > top_center * 2


def test_poetore_mode_starts_capture_and_stash_scroll_services_for_poe2():
    app = QApplication.instance() or QApplication([])
    config = {
        "poe_version": POE2,
        "hotkeys": {
            "poetore_capture": "alt+d",
            "poetore_auto_hide": "ctrl+d",
            "map_check": "alt+f",
        },
    }

    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config",
        return_value=config,
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService"
    ) as hotkey_class, patch(
        "src.ui.poetore_mode_window.StashTabScrollController"
    ) as stash_class, patch.object(
        PoetoreModeWindow, "refresh_currency_rate"
    ), patch(
        "src.poetore.ui.prepare_poetore_window"
    ) as prepare_window, patch(
        "src.ui.poetore_mode_window.is_feature_supported",
        side_effect=lambda feature, _version: feature != "map_check",
    ), patch(
        "src.ui.poetore_mode_window.suppressed_hotkeys_supported", return_value=False,
    ):
        window = PoetoreModeWindow()

    supplied_hotkeys = hotkey_class.call_args.args[0]
    assert "poetore_capture" in supplied_hotkeys
    assert "poetore_auto_hide" in supplied_hotkeys
    assert "map_check" not in supplied_hotkeys
    assert not window.map_mods_button.isVisibleTo(window)
    stash_class.assert_called_once_with(enabled=True)
    prepare_window.assert_called_once_with(window)
    assert all(
        label.text() != "カレンシー交換レート" for label in window.findChildren(QLabel)
    )
    assert len(window.rate_panel.row_widgets) == 1
    window.close()
    app.processEvents()


def test_poe2_expedition_hotkey_starts_only_when_feature_is_enabled():
    app = QApplication.instance() or QApplication([])
    config = {
        "poe_version": POE2,
        "hotkeys": {"expedition_reward_ocr": "alt+e"},
        "poetore": {
            "screen_reading": {"enabled": True},
            "expedition_reward_overlay": {
                "region": {"left": 0.1, "top": 0.1, "right": 0.5, "bottom": 0.9},
            },
        },
    }
    controller = MagicMock()
    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config", return_value=config,
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService",
    ) as hotkey_class, patch(
        "src.ui.poetore_mode_window.ForegroundSuppressedHotkeyService",
    ) as suppressed_class, patch(
        "src.ui.poetore_mode_window.suppressed_hotkeys_supported", return_value=True,
    ), patch(
        "src.ui.poetore_mode_window.sys",
        platform="win32",
    ), patch.object(
        PoetoreModeWindow,
        "_ensure_expedition_reward_controller",
        return_value=controller,
    ), patch.object(PoetoreModeWindow, "refresh_currency_rate"):
        window = PoetoreModeWindow()

    assert "expedition_reward_ocr" not in hotkey_class.call_args.args[0]
    assert [call.args[:2] for call in suppressed_class.call_args_list] == [
        ("poetore_capture", "alt+d"),
        ("expedition_reward_ocr", "alt+e"),
    ]
    assert suppressed_class.call_args_list[1].kwargs["allow_unmodified"] is True
    controller.warm_up.assert_called_once_with()
    window.close()
    app.processEvents()


def test_poe1_heist_ocr_starts_only_when_feature_is_enabled():
    app = QApplication.instance() or QApplication([])
    config = {
        "poe_version": POE1,
        "hotkeys": {"heist_curio_ocr": "alt+shift+h"},
        "poetore": {"heist_curio_ocr": {"enabled": True}},
    }
    controller = MagicMock()
    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config", return_value=config,
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService",
    ) as hotkey_class, patch(
        "src.ui.poetore_mode_window.suppressed_hotkeys_supported", return_value=False,
    ), patch(
        "src.ui.poetore_mode_window.sys", platform="win32",
    ), patch.object(
        PoetoreModeWindow, "_ensure_heist_curio_controller", return_value=controller,
    ), patch.object(PoetoreModeWindow, "refresh_currency_rate"):
        window = PoetoreModeWindow()

    assert hotkey_class.call_args.args[0]["heist_curio_ocr"] == "alt+shift+h"
    controller.warm_up.assert_called_once_with()
    window.close()
    app.processEvents()


def test_poe1_heist_ocr_stays_stopped_when_feature_is_disabled():
    app = QApplication.instance() or QApplication([])
    config = {
        "poe_version": POE1,
        "hotkeys": {"heist_curio_ocr": "alt+shift+h"},
        "poetore": {"heist_curio_ocr": {"enabled": False}},
    }
    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config", return_value=config,
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService"
    ) as hotkey_class, patch(
        "src.ui.poetore_mode_window.sys", platform="win32",
    ), patch.object(
        PoetoreModeWindow, "_ensure_heist_curio_controller"
    ) as ensure_controller, patch.object(PoetoreModeWindow, "refresh_currency_rate"):
        window = PoetoreModeWindow()

    assert "heist_curio_ocr" not in hotkey_class.call_args.args[0]
    ensure_controller.assert_not_called()
    window.close()
    app.processEvents()


def test_separate_ocr_services_receive_multi_modifier_hotkeys():
    app = QApplication.instance() or QApplication([])
    config = {
        "poe_version": POE2,
        "hotkeys": {
            "expedition_reward_ocr": "ctrl+shift+e",
            "desecration_tier_ocr": "ctrl+alt+shift+r",
        },
        "poetore": {
            "screen_reading": {"enabled": True},
            "expedition_reward_overlay": {
                "region": {"left": 0.1, "top": 0.1, "right": 0.5, "bottom": 0.9},
            },
            "desecration_tier_overlay": {
                "inventory_open_region": {
                    "left": 0.2, "top": 0.2, "right": 0.7, "bottom": 0.8,
                },
            },
        },
    }
    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config", return_value=config,
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService",
    ), patch(
        "src.ui.poetore_mode_window.ForegroundSuppressedHotkeyService",
    ) as suppressed_class, patch(
        "src.ui.poetore_mode_window.suppressed_hotkeys_supported", return_value=True,
    ), patch.object(
        PoetoreModeWindow, "_ensure_expedition_reward_controller",
    ), patch.object(
        PoetoreModeWindow, "_ensure_desecration_tier_controller",
    ), patch.object(PoetoreModeWindow, "refresh_currency_rate"):
        window = PoetoreModeWindow()

    assert [call.args[:2] for call in suppressed_class.call_args_list] == [
        ("poetore_capture", "alt+d"),
        ("expedition_reward_ocr", "ctrl+shift+e"),
        ("desecration_tier_ocr", "ctrl+alt+shift+r"),
    ]
    window.close()
    app.processEvents()


def test_poe2_expedition_ocr_does_not_warm_up_before_region_is_set():
    app = QApplication.instance() or QApplication([])
    config = {
        "poe_version": POE2,
        "hotkeys": {"expedition_reward_ocr": "alt+e"},
        "poetore": {
            "screen_reading": {"enabled": True},
            "expedition_reward_overlay": {},
        },
    }
    controller = MagicMock()
    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config", return_value=config,
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService",
    ), patch(
        "src.ui.poetore_mode_window.ForegroundSuppressedHotkeyService",
    ), patch(
        "src.ui.poetore_mode_window.suppressed_hotkeys_supported", return_value=True,
    ), patch(
        "src.ui.poetore_mode_window.sys", platform="win32",
    ), patch.object(
        PoetoreModeWindow,
        "_ensure_expedition_reward_controller",
        return_value=controller,
    ), patch.object(PoetoreModeWindow, "refresh_currency_rate"):
        window = PoetoreModeWindow()

    controller.warm_up.assert_not_called()
    window.close()
    app.processEvents()


def test_expedition_hotkey_dispatches_single_scan():
    window = MagicMock()
    PoetoreModeWindow.handle_hotkey(window, "expedition_reward_ocr")
    window.capture_expedition_rewards.assert_called_once_with()


def test_desecration_hotkey_dispatches_single_scan():
    window = MagicMock()
    PoetoreModeWindow.handle_hotkey(window, "desecration_tier_ocr")
    window.capture_desecration_tiers.assert_called_once_with()


def test_heist_curio_hotkey_dispatches_manual_selection_scan():
    window = MagicMock()

    PoetoreModeWindow.handle_hotkey(window, "heist_curio_ocr")

    window.capture_heist_curio.assert_called_once_with()


def test_heist_curio_scan_is_poe1_only():
    window = MagicMock()
    window.poe_version = POE2
    window._heist_curio_enabled.return_value = False

    assert not PoetoreModeWindow.capture_heist_curio(window)
    window._ensure_heist_curio_controller.assert_not_called()


def test_heist_settings_save_enables_only_heist_reader_and_warms_ocr():
    window = MagicMock()
    window.poe_version = POE1
    window.config = {
        "hotkeys": {"heist_curio_ocr": "alt+shift+h"},
        "poetore": {"heist_curio_ocr": {"enabled": False}},
    }
    window._heist_curio_enabled.return_value = False
    controller = MagicMock()
    window._ensure_heist_curio_controller.return_value = controller
    pack_controller = MagicMock()
    window._ensure_ndlocr_pack_controller.return_value = pack_controller

    with patch(
        "src.ui.heist_settings_dialog.HeistSettingsDialog"
    ) as dialog_class, patch(
        "src.ui.poetore_mode_window.ConfigManager.save_config"
    ) as save_config:
        dialog = dialog_class.return_value
        dialog.exec.return_value = True
        dialog.settings.return_value = ("ctrl+shift+h", True)

        PoetoreModeWindow.open_heist_settings(window)

    assert window.config["hotkeys"]["heist_curio_ocr"] == "ctrl+shift+h"
    assert window.config["poetore"]["heist_curio_ocr"] == {"enabled": True}
    assert dialog_class.call_args.kwargs["ocr_pack_controller"] is pack_controller
    pack_controller.ensure_started.assert_called_once_with()
    save_config.assert_called_once_with(window.config)
    window._restart_hotkeys.assert_called_once_with()
    controller.warm_up.assert_called_once_with()


def test_shared_screen_reading_off_stops_both_features_and_keeps_regions():
    window = MagicMock()
    window.poe_version = POE2
    expedition_region = {"left": .1, "top": .1, "right": .5, "bottom": .8}
    desecration_region = {"left": .2, "top": .2, "right": .7, "bottom": .7}
    window.config = {
        "hotkeys": {
            "expedition_reward_ocr": "alt+e",
            "desecration_tier_ocr": "alt+r",
        },
        "poetore": {
            "screen_reading": {"enabled": True},
            "expedition_reward_overlay": {"region": expedition_region},
            "desecration_tier_overlay": {"inventory_open_region": desecration_region},
        },
    }
    with patch("src.ui.poetore_mode_window.ConfigManager.save_config"):
        assert PoetoreModeWindow._save_screen_reading_settings(
            window, "expedition_reward_overlay", {"region": expedition_region},
            "expedition_reward_ocr", "alt+e", False,
        )
    assert window.config["poetore"]["screen_reading"] == {"enabled": False}
    assert window.config["poetore"]["desecration_tier_overlay"]["inventory_open_region"] == desecration_region
    window._shutdown_screen_reading.assert_called_once_with()
    window._restart_hotkeys.assert_called_once_with()


def test_screen_reading_shutdown_closes_desecration_ndlocr_owner():
    window = MagicMock()
    expedition = MagicMock()
    desecration = MagicMock()
    coordinator = MagicMock()
    window._expedition_reward_controller = expedition
    window._desecration_tier_controller = desecration
    window._screen_reading_coordinator = coordinator

    PoetoreModeWindow._shutdown_screen_reading(window)

    expedition.close.assert_called_once_with()
    desecration.close.assert_called_once_with()
    coordinator.close.assert_called_once_with()
    assert window._expedition_reward_controller is None
    assert window._desecration_tier_controller is None
    assert window._screen_reading_coordinator is None


def test_desecration_hotkey_requires_shared_enabled_and_open_region():
    window = MagicMock()
    window.poe_version = POE2
    window.config = {
        "poetore": {
            "screen_reading": {"enabled": True},
            "desecration_tier_overlay": {},
        }
    }
    window._screen_reading_enabled.return_value = True
    window._desecration_ready.return_value = False
    assert not PoetoreModeWindow.capture_desecration_tiers(window)
    window._ensure_desecration_tier_controller.assert_not_called()


def test_expedition_header_button_saves_settings_and_restarts_hotkeys():
    window = MagicMock()
    window.poe_version = POE2
    window.config = {
        "hotkeys": {"expedition_reward_ocr": "alt+e"},
        "poetore": {"screen_reading": {"enabled": False}, "expedition_reward_overlay": {}},
    }
    window._expedition_reward_controller = None
    region = {"left": 0.1, "top": 0.2, "right": 0.6, "bottom": 0.9}
    controller = MagicMock()

    with patch(
        "src.ui.expedition_settings_dialog.ExpeditionSettingsDialog"
    ) as dialog_class, patch(
        "src.ui.poetore_mode_window.ConfigManager.save_config"
    ) as save_config:
        dialog = dialog_class.return_value
        dialog.exec.return_value = True
        dialog.settings.return_value = (
            {"region": region},
            "ctrl+r",
            True,
        )
        window._ensure_expedition_reward_controller.return_value = controller

        PoetoreModeWindow.open_expedition_settings(window)

    assert window.config["hotkeys"]["expedition_reward_ocr"] == "ctrl+r"
    assert window.config["poetore"]["expedition_reward_overlay"] == {
        "region": region,
    }
    assert window.config["poetore"]["screen_reading"] == {"enabled": True}
    save_config.assert_called_once_with(window.config)
    window._restart_hotkeys.assert_called_once_with()
    controller.warm_up.assert_called_once_with()


def test_expedition_header_button_rejects_duplicate_hotkey():
    window = MagicMock()
    window.poe_version = POE2
    window.config = {
        "hotkeys": {
            "poetore_capture": "alt+d",
            "expedition_reward_ocr": "alt+e",
        },
        "poetore": {"screen_reading": {"enabled": False}, "expedition_reward_overlay": {}},
    }

    with patch(
        "src.ui.expedition_settings_dialog.ExpeditionSettingsDialog"
    ) as dialog_class, patch(
        "src.ui.poetore_mode_window.ConfigManager.save_config"
    ) as save_config, patch(
        "src.ui.poetore_mode_window.QMessageBox.warning"
    ) as warning:
        dialog = dialog_class.return_value
        dialog.exec.return_value = True
        dialog.settings.return_value = ({}, "alt+d", True)

        PoetoreModeWindow.open_expedition_settings(window)

    save_config.assert_not_called()
    window._restart_hotkeys.assert_not_called()
    warning.assert_called_once()


def test_desecration_settings_starts_pack_download_even_when_dialog_is_cancelled():
    window = MagicMock()
    window.poe_version = POE2
    window.config = {
        "hotkeys": {"desecration_tier_ocr": "alt+r"},
        "poetore": {
            "screen_reading": {"enabled": True},
            "desecration_tier_overlay": {},
        },
    }
    pack_controller = MagicMock()
    window._ensure_ndlocr_pack_controller.return_value = pack_controller

    with patch(
        "src.ui.desecration_settings_dialog.DesecrationSettingsDialog"
    ) as dialog_class, patch(
        "src.ui.poetore_mode_window.ConfigManager.save_config"
    ) as save_config:
        dialog_class.return_value.exec.return_value = False

        PoetoreModeWindow.open_desecration_settings(window)

    assert dialog_class.call_args.kwargs["ocr_pack_controller"] is pack_controller
    pack_controller.ensure_started.assert_called_once_with()
    save_config.assert_not_called()


def test_expedition_controller_receives_current_saved_region():
    window = MagicMock()
    window._expedition_reward_controller = None
    region = {"left": 0.1, "top": 0.2, "right": 0.5, "bottom": 0.9}
    window.config = {
        "poetore": {"expedition_reward_overlay": {"region": region}}
    }
    window._currency_rate_league = MagicMock()
    with patch(
        "src.poetore.expedition_rewards.ExpeditionRewardController"
    ) as controller_class:
        controller = controller_class.return_value

        result = PoetoreModeWindow._ensure_expedition_reward_controller(window)

    assert result is controller
    region_getter = controller_class.call_args.kwargs["region_getter"]
    assert region_getter() == region


def test_expedition_diagnostic_report_uses_single_message_box():
    window = MagicMock()
    with patch(
        "src.ui.poetore_mode_window.QMessageBox.information"
    ) as information:
        PoetoreModeWindow._show_expedition_diagnostic(window, "diagnostic report")

    information.assert_called_once_with(
        window, "エクスペディションOCR診断", "diagnostic report"
    )


def test_poetore_mode_respects_disabled_stash_scroll_for_poe2():
    app = QApplication.instance() or QApplication([])
    config = {
        "poe_version": POE2,
        "stash_tab_scroll_enabled": False,
        "hotkeys": {},
    }

    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config",
        return_value=config,
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService"
    ), patch(
        "src.ui.poetore_mode_window.StashTabScrollController"
    ) as stash_class, patch.object(
        PoetoreModeWindow, "refresh_currency_rate"
    ), patch(
        "src.ui.poetore_mode_window.is_feature_supported", return_value=True,
    ):
        window = PoetoreModeWindow()

    stash_class.assert_called_once_with(enabled=False)
    window.close()
    app.processEvents()


def test_poetore_mode_starts_obs_window_collapsed_when_enabled():
    app = QApplication.instance() or QApplication([])
    config = {
        "poe_version": "poe1",
        "hotkeys": {},
        "poetore": {"obs_streaming": {"enabled": True, "geometry": {}}},
    }
    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config",
        return_value=config,
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService"
    ), patch(
        "src.ui.poetore_mode_window.StashTabScrollController"
    ), patch.object(PoetoreModeWindow, "refresh_currency_rate"):
        window = PoetoreModeWindow()
        app.processEvents()

    result = window._poetore_window
    assert result.isVisible()
    assert result._obs_collapsed
    assert result.windowTitle() == "ぽえとれ - 検索結果ウィンドウ"
    window.close()
    app.processEvents()


def test_poetore_mode_minimize_hides_to_tray_and_notifies_once():
    app = QApplication.instance() or QApplication([])
    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config",
        return_value={"hotkeys": {}},
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService"
    ), patch.object(
        PoetoreModeWindow, "refresh_currency_rate"
    ), patch.object(
        QSystemTrayIcon, "isSystemTrayAvailable", return_value=True
    ):
        window = PoetoreModeWindow()
        window.show()
        app.processEvents()
        with patch.object(window.tray_icon, "show") as show_tray, patch.object(
            window.tray_icon, "showMessage"
        ) as show_message:
            window.title_bar.minimize_button.click()
            window.minimize_to_tray()

    assert not window.isVisible()
    assert show_tray.call_count == 2
    show_message.assert_called_once()
    window.close()
    app.processEvents()


def test_poetore_mode_minimize_falls_back_when_tray_is_unavailable():
    window = MagicMock()
    with patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=False):
        PoetoreModeWindow.minimize_to_tray(window)

    window.showMinimized.assert_called_once_with()
    window.hide.assert_not_called()


def test_poetore_mode_tray_settings_restores_before_opening_dialog():
    window = MagicMock()
    with patch.object(QTimer, "singleShot", side_effect=lambda _delay, callback: callback()):
        PoetoreModeWindow.open_settings_from_tray(window)

    assert window.method_calls[:2] == [
        call.restore_from_tray(),
        call.open_settings(),
    ]


def test_poetore_mode_tray_activation_restores_on_click_and_double_click():
    window = MagicMock()

    PoetoreModeWindow._handle_tray_activation(window, QSystemTrayIcon.Trigger)
    PoetoreModeWindow._handle_tray_activation(window, QSystemTrayIcon.DoubleClick)
    PoetoreModeWindow._handle_tray_activation(window, QSystemTrayIcon.Context)

    assert window.restore_from_tray.call_count == 2


def test_poetore_mode_tray_exit_closes_window_and_quits_application():
    window = MagicMock()
    app = MagicMock()
    with patch.object(QApplication, "instance", return_value=app):
        PoetoreModeWindow.quit_from_tray(window)

    window.close.assert_called_once_with()
    app.quit.assert_called_once_with()


def test_poetore_mode_monastery_hotkey_sends_chat_command():
    app = QApplication.instance() or QApplication([])
    config = {"hotkeys": {"monastery": "F12"}}

    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config",
        return_value=config,
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService"
    ), patch.object(PoetoreModeWindow, "refresh_currency_rate"), patch(
        "src.ui.poetore_mode_window.send_chat_command"
    ) as send_command:
        window = PoetoreModeWindow()
        window.handle_hotkey("monastery")

    send_command.assert_called_once_with("/monastery")
    window.close()
    app.processEvents()


def test_poetore_mode_forwards_capture_hotkey_release():
    window = MagicMock()
    window._poetore_window = MagicMock()

    PoetoreModeWindow.handle_hotkey(window, "poetore_capture_released")

    window._poetore_window.capture_hotkey_released.assert_called_once_with()


def test_poetore_mode_starts_auto_hide_capture_and_forwards_release():
    window = MagicMock()
    window._poetore_window = MagicMock()

    PoetoreModeWindow.handle_hotkey(window, "poetore_auto_hide")
    PoetoreModeWindow.handle_hotkey(window, "poetore_auto_hide_released")

    window.capture_poetore_item.assert_called_once_with(auto_hide=True)
    window._poetore_window.capture_hotkey_released.assert_called_once_with()


def test_poetore_mode_warns_only_when_both_price_check_hotkeys_are_disabled():
    app = QApplication.instance() or QApplication([])
    config = {"hotkeys": {
        "poetore_capture": "Ctrl+Shift+P",
        "poetore_auto_hide": "Alt+Q",
    }}

    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config",
        return_value=config,
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService"
    ), patch.object(PoetoreModeWindow, "refresh_currency_rate"):
        window = PoetoreModeWindow()

    window.show()
    app.processEvents()
    assert not window.capture_warning.isVisible()
    window.config["hotkeys"]["poetore_capture"] = "none"
    window._update_capture_hotkey_warning()
    assert not window.capture_warning.isVisible()
    window.config["hotkeys"]["poetore_auto_hide"] = "none"
    window._update_capture_hotkey_warning()
    assert window.capture_warning.isVisible()
    assert window.capture_warning.text() == "価格チェックのホットキーが設定されていません。"
    window.config["hotkeys"]["poetore_capture"] = "alt+d"
    window._update_capture_hotkey_warning()
    assert not window.capture_warning.isVisible()
    window.close()
    app.processEvents()


def test_poetore_mode_passes_configured_interactive_hotkey_to_capture():
    owner = MagicMock()
    owner.config = {
        "poe_version": POE2,
        "hotkeys": {"poetore_capture": "Ctrl+Shift+P"},
    }
    poetore_window = MagicMock()
    trace = MagicMock()

    with patch(
        "src.poetore.performance.start_search_trace", return_value=trace,
    ), patch(
        "src.poetore.ui.show_poetore_window", return_value=poetore_window,
    ), patch(
        "src.ui.poetore_mode_window.is_feature_supported", return_value=True,
    ):
        PoetoreModeWindow.capture_poetore_item(owner)

    poetore_window.capture_from_poe.assert_called_once_with(
        trace, capture_hotkey="Ctrl+Shift+P",
    )


def test_poetore_mode_enables_desecration_performance_trace():
    owner = MagicMock()
    owner._desecration_tier_controller = None
    owner.config = {"poetore": {"desecration_tier_overlay": {}}}
    shared = MagicMock()
    owner._ensure_screen_reading_coordinator.return_value = shared
    trace = MagicMock()

    with patch(
        "src.poetore.poe2.desecration_overlay.DesecrationTierController",
    ) as controller_class, patch(
        "src.poetore.performance.start_search_trace", return_value=trace,
    ) as start_trace:
        controller = controller_class.return_value
        result = PoetoreModeWindow._ensure_desecration_tier_controller(owner)
        trace_factory = controller_class.call_args.kwargs["trace_factory"]
        assert trace_factory() is trace

    assert result is controller
    start_trace.assert_called_once_with("desecration_tier_scan")
    controller_class.assert_called_once()
    assert controller_class.call_args.kwargs["ocr_server"] is shared
    assert controller_class.call_args.kwargs["scan_coordinator"] is shared


def test_poetore_mode_renders_default_divine_chaos_pair():
    app = QApplication.instance() or QApplication([])
    config = {"hotkeys": {}}

    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config",
        return_value=config,
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService"
    ), patch.object(PoetoreModeWindow, "refresh_currency_rate"):
        window = PoetoreModeWindow()

    assert window.rate_panel.findChild(QLabel, "customRateLeftName0").text() == "神のオーブ"
    assert window.rate_panel.findChild(QLabel, "customRateRightName0").text() == "カオスオーブ"
    assert not window.rate_panel.manage_button.icon().isNull()
    style = window.centralWidget().styleSheet()
    assert "#65FFCA" in style
    assert "#343B3E" in style
    assert "#DB86EF" not in style.upper()
    window.close()
    app.processEvents()


def test_main_window_height_expands_with_saved_rows_without_scroll(qtbot):
    app = QApplication.instance() or QApplication([])
    catalog_ids = list(exchange_catalog_by_id(POE1))
    pairs = [
        {
            "left_item_id": catalog_ids[index],
            "right_item_id": catalog_ids[index + 10],
        }
        for index in range(10)
    ]
    config = {
        "hotkeys": {},
        "poetore": {"exchange_rate_pairs": {POE1: pairs, POE2: []}},
    }
    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config",
        return_value=config,
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService"
    ), patch.object(PoetoreModeWindow, "refresh_currency_rate"):
        window = PoetoreModeWindow()

    window.show()
    assert len(window.rate_panel.row_widgets) == 10
    assert window.rate_panel.manage_button.isVisible()
    scroll = window._rate_scroll
    qtbot.waitUntil(
        lambda: scroll.viewport().rect().contains(scroll.widget().geometry())
    )
    assert scroll.verticalScrollBar().maximum() == 0
    card = window.rate_panel.card
    assert window.height() - card.mapTo(window, QPoint(0, card.height())).y() == UI_METRICS.page_margin
    window.close()
    app.processEvents()


def test_main_window_zero_rows_is_compact_and_keeps_management_entry(qtbot):
    app = QApplication.instance() or QApplication([])
    config = {
        "hotkeys": {},
        "poetore": {"exchange_rate_pairs": {POE1: [], POE2: []}},
    }
    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config",
        return_value=config,
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService"
    ), patch.object(PoetoreModeWindow, "refresh_currency_rate"):
        window = PoetoreModeWindow()

    window.show()
    app.processEvents()
    assert window.rate_panel.row_widgets == []
    assert window.rate_panel.manage_button.isVisible()
    assert not window.rate_panel.card.isVisible()
    assert not window.capture_warning.isVisible()
    scroll = window._rate_scroll
    qtbot.waitUntil(lambda: scroll.viewport().rect().contains(scroll.widget().geometry()))
    assert window.height() - scroll.mapTo(window, QPoint(0, scroll.height())).y() == UI_METRICS.page_margin
    window.close()
    app.processEvents()


def test_saved_poe_version_change_does_not_partially_switch_running_rate_table():
    app = QApplication.instance() or QApplication([])
    config = {
        "poe_version": "poe1",
        "hotkeys": {},
        "poetore": {"league": "Mirage", "league_poe2": "Runes of Aldur"},
    }

    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config",
        return_value=config,
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService"
    ), patch.object(PoetoreModeWindow, "refresh_currency_rate"):
        window = PoetoreModeWindow()

    config["poe_version"] = "poe2"

    assert window.poe_version == "poe1"
    assert window._configured_league() == "Mirage"
    assert window.rate_quote_currency == "chaos"
    assert window.rate_panel.findChild(QLabel, "customRateRightName0").text() == "カオスオーブ"
    window.close()
    app.processEvents()


def test_poe2_poetore_mode_renders_default_divine_exalted_pair():
    app = QApplication.instance() or QApplication([])
    config = {"poe_version": POE2, "hotkeys": {}}

    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config",
        return_value=config,
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService"
    ), patch.object(PoetoreModeWindow, "refresh_currency_rate"), patch(
        "src.ui.poetore_mode_window.is_feature_supported", return_value=True,
    ):
        window = PoetoreModeWindow()

    assert window.rate_panel.findChild(QLabel, "customRateLeftName0").text() == "神のオーブ"
    assert window.rate_panel.findChild(QLabel, "customRateRightName0").text() == "高貴なオーブ"
    window.close()
    app.processEvents()


def test_poe2_currency_rate_auto_league_does_not_call_trade2_api():
    app = QApplication.instance() or QApplication([])
    config = {"poe_version": POE2, "hotkeys": {}, "poetore": {"league_poe2": "auto"}}

    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config", return_value=config,
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService"
    ), patch.object(PoetoreModeWindow, "refresh_currency_rate"), patch(
        "src.ui.poetore_mode_window.is_feature_supported", return_value=True,
    ), patch(
        "src.poetore.poe2.trade.available_pc_leagues",
        side_effect=AssertionError("Trade2 API must not be used"),
    ):
        window = PoetoreModeWindow()

    assert window._currency_rate_league() == "Forbidden Rites"
    window.close()
    app.processEvents()


def test_rate_league_lookup_failure_leaves_toolbar_messages_independent(qapp, qtbot):
    with patch(
        "src.ui.poetore_mode_window.ConfigManager.load_config",
        return_value={"poe_version": POE1, "hotkeys": {}},
    ), patch(
        "src.ui.poetore_mode_window.GlobalHotkeyService",
    ), patch.object(PoetoreModeWindow, "refresh_currency_rate"):
        window = PoetoreModeWindow()
        window.show()
        qapp.processEvents()
    qtbot.addWidget(window)

    window.rate_panel.refresh_callback = window.refresh_currency_rate
    button = window.rate_refresh_button
    with patch.object(window, "_currency_rate_league", side_effect=RuntimeError):
        QTest.mouseClick(button, Qt.LeftButton)
        assert not button.isEnabled()
        assert button.accessibleDescription() == "リーグ　Standard\n更新を確認中…"
        qtbot.waitUntil(button.isEnabled)
    assert button.accessibleDescription() == (
        "リーグ　Standard\n取引データを取得できませんでした。\n"
        "しばらくしてから再度お試しください。"
    )

    tooltip = button.toolTip()
    window._show_heist_curio_status("ハイスト報酬を読み取っています…")
    assert window.toolbar_message_label.isVisible()
    assert window.toolbar_message_label.text() == "ハイスト報酬を読み取っています…"
    assert button.toolTip() == tooltip
