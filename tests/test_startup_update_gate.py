import io
import json
import sys
from unittest.mock import Mock, patch

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from src.ui.dialog_theme import POENAVI_DIALOG_THEME
from src.ui.update_dialogs import build_update_message_box
from src.update.qt_controller import UpdateController
from src.update.release_client import ReleaseInfo, TEST_RELEASE_TAG_ENV, fetch_latest_release
from src.update.startup_gate import (
    run_manual_update_check,
    run_startup_update_gate,
)


class ImmediateThread:
    def __init__(self, target):
        self.target = target

    def start(self):
        self.target()


@patch("src.version.IS_FORK", False)
def test_common_startup_gate_continues_without_update():
    QApplication.instance() or QApplication([])
    config = {"notified_update_version": "9.9.9"}

    def controller_factory(parent=None):
        return UpdateController(parent, thread_factory=lambda target: ImmediateThread(target))

    with patch(
        "src.update.startup_gate.UpdateController",
        side_effect=controller_factory,
    ), patch(
        "src.update.qt_controller.fetch_latest_release",
        return_value=None,
    ), patch(
        "src.update.startup_gate.ConfigManager.save_config",
    ) as save_config:
        assert run_startup_update_gate(config) is True

    assert config["notified_update_version"] == ""
    save_config.assert_called_once_with(config)


@patch("src.version.IS_FORK", False)
def test_startup_offers_update_after_slow_response(monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.delenv("POENAVI_UPDATE_TEST_TAG", raising=False)
    config = {}
    elapsed_ms = 0
    deadline_ms = None
    controller = UpdateController(
        thread_factory=lambda target: Mock(start=lambda: QTimer.singleShot(0, target)),
    )

    def start_timer(timeout_ms):
        nonlocal deadline_ms
        deadline_ms = elapsed_ms + timeout_ms

    def advance(ms):
        nonlocal elapsed_ms
        elapsed_ms += ms
        if elapsed_ms >= deadline_ms:
            controller._expire_check()

    body = json.dumps({
        "tag_name": "v99.0.0",
        "assets": [
            {"name": "PoENavi.zip", "browser_download_url": "https://github.com/app.zip"},
            {"name": "PoENavi.zip.sha256", "browser_download_url": "https://github.com/app.zip.sha256"},
        ],
    }).encode("utf-8")

    class SlowResponse(io.BytesIO):
        def read(self, size=-1):
            if self.tell() == 0:
                advance(8_000)
            return super().read(size)

        read1 = read

    def open_response(_request, timeout):
        assert timeout == 10
        advance(8_000)
        return SlowResponse(body)

    with patch.object(controller._check_timer, "start", side_effect=start_timer), patch(
        "src.update.release_client.monotonic", side_effect=lambda: elapsed_ms / 1000,
    ), patch("src.update.startup_gate.shared_update_controller", return_value=controller), patch(
        "src.update.qt_controller.fetch_latest_release",
        side_effect=lambda version: fetch_latest_release(version, opener=open_response),
    ), patch("src.update.startup_gate.ConfigManager.save_config") as save_config, patch(
        "src.update.startup_gate.UpdateAvailableDialog",
    ) as available:
        available.return_value.exec.return_value = QDialog.Rejected
        assert run_startup_update_gate(config) is True

    assert elapsed_ms == 16_000
    available.assert_called_once()
    assert available.call_args.args[0].version == "99.0.0"
    save_config.assert_called_once_with({"notified_update_version": "99.0.0"})
    assert config["notified_update_version"] == "99.0.0"


def test_manual_check_reports_latest_version():
    QApplication.instance() or QApplication([])

    def controller_factory(parent=None):
        return UpdateController(
            parent,
            thread_factory=lambda target: ImmediateThread(target),
        )

    with patch(
        "src.update.startup_gate.UpdateController",
        side_effect=controller_factory,
    ), patch(
        "src.update.qt_controller.fetch_latest_release",
        return_value=None,
    ), patch(
        "src.update.startup_gate.show_update_message",
    ) as show_message:
        assert run_manual_update_check({}) is True

    show_message.assert_called_once_with(
        None,
        QMessageBox.Information,
        "アップデート",
        "最新バージョンです。",
    )


def test_check_thread_start_failure_reports_in_settings_and_allows_retry():
    QApplication.instance() or QApplication([])
    failing_thread = Mock()
    failing_thread.start.side_effect = RuntimeError("cannot start thread")
    factory = Mock(return_value=failing_thread)
    controller = UpdateController(thread_factory=factory)

    with patch("src.update.startup_gate.show_update_message") as show_message:
        assert run_manual_update_check({}, controller=controller) is True
    show_message.assert_called_once_with(
        None, QMessageBox.Warning, "アップデート", "更新を確認できませんでした。\ncannot start thread",
    )
    assert not controller.checking

    factory.side_effect = ImmediateThread
    with patch("src.update.qt_controller.fetch_latest_release", return_value=None) as fetch, patch(
        "src.update.startup_gate.show_update_message",
    ) as show_message:
        assert run_manual_update_check({}, controller=controller) is True
    fetch.assert_called_once()
    show_message.assert_called_once_with(None, QMessageBox.Information, "アップデート", "最新バージョンです。")


@patch("src.version.IS_FORK", False)
def test_startup_continues_when_thread_cannot_start():
    app = QApplication.instance() or QApplication([])
    with patch.object(app, "_shared_update_controller", None, create=True), patch.object(
        sys, "frozen", True, create=True,
    ), patch.object(sys, "platform", "win32"), patch(
        "threading.Thread.start", side_effect=RuntimeError("cannot start thread"),
    ), patch("src.update.startup_gate.show_update_message") as show_message:
        assert run_startup_update_gate({}) is True
        assert not app._shared_update_controller.checking

    show_message.assert_not_called()


@patch("src.version.IS_FORK", False)
def test_startup_retries_saving_withdrawn_release_after_save_failure():
    QApplication.instance() or QApplication([])
    config = {"notified_update_version": "9.9.9"}
    controller = UpdateController(thread_factory=ImmediateThread)

    with patch("src.update.startup_gate.shared_update_controller", return_value=controller), patch(
        "src.update.qt_controller.fetch_latest_release", return_value=None,
    ), patch(
        "src.update.startup_gate.ConfigManager.save_config", side_effect=[PermissionError(), None],
    ) as save_config:
        assert run_startup_update_gate(config) is True
        assert config["notified_update_version"] == "9.9.9"
        assert run_startup_update_gate(config) is True

    assert config["notified_update_version"] == ""
    assert save_config.call_count == 2
    for call in save_config.call_args_list:
        assert call.args == ({"notified_update_version": ""},)


@patch("src.version.IS_FORK", True)
def test_fork_skips_startup_check_without_explicit_test_tag(monkeypatch):
    monkeypatch.delenv(TEST_RELEASE_TAG_ENV, raising=False)
    with patch("src.update.startup_gate.shared_update_controller") as controller:
        assert run_startup_update_gate({}) is True
    controller.assert_not_called()


@patch("src.version.IS_FORK", True)
def test_fork_startup_gate_checks_explicit_test_tag(monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setenv(TEST_RELEASE_TAG_ENV, "v99.0.0")
    controller = UpdateController(thread_factory=ImmediateThread)
    with patch("src.update.startup_gate.shared_update_controller", return_value=controller), patch(
        "src.update.qt_controller.fetch_latest_release", return_value=None,
    ) as fetch:
        assert run_startup_update_gate({}) is True
    fetch.assert_called_once()


@patch("src.version.IS_FORK", True)
def test_fork_manual_check_offers_release_page_without_downloading(monkeypatch):
    QApplication.instance() or QApplication([])
    controller = UpdateController(thread_factory=ImmediateThread)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    release = ReleaseInfo("99.0.0", "", "https://example.com/release", "", "")
    with patch("src.update.qt_controller.fetch_latest_release", return_value=release) as fetch, patch(
        "src.update.startup_gate.ConfigManager.save_config",
    ), patch("src.update.startup_gate.UpdateAvailableDialog") as dialog, patch(
        "src.update.startup_gate.QDesktopServices.openUrl",
    ) as open_url, patch.object(controller, "download") as download:
        dialog.return_value.exec.return_value = QDialog.Accepted
        assert run_manual_update_check({}, controller=controller) is True

    fetch.assert_called_once()
    dialog.assert_called_once_with(release, False, None)
    assert open_url.call_args.args[0].toString() == release.page_url
    open_url.assert_called_once()
    download.assert_not_called()


def test_update_message_box_overrides_inherited_light_on_light_colors():
    QApplication.instance() or QApplication([])
    parent = QDialog()
    parent.setProperty("dialogTheme", POENAVI_DIALOG_THEME.name)
    parent.setStyleSheet("QWidget { color: white; background: transparent; }")

    message = build_update_message_box(
        parent,
        QMessageBox.Information,
        "アップデート",
        "最新バージョンです。",
    )
    style = message.styleSheet()

    assert f"background-color: {POENAVI_DIALOG_THEME.background}" in style
    assert f"color: {POENAVI_DIALOG_THEME.text}" in style
    assert "QMessageBox QLabel" in style
    assert message.text() == "最新バージョンです。"
    parent.close()
