import sys
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from src.ui.dialog_theme import POENAVI_DIALOG_THEME
from src.ui.update_dialogs import build_update_message_box
from src.update.qt_controller import UpdateController
from src.update.startup_gate import (
    run_manual_update_check,
    run_startup_update_gate,
)


class ImmediateThread:
    def __init__(self, target):
        self.target = target

    def start(self):
        self.target()


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
