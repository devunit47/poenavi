"""両起動モードで共通利用する起動時アップデート確認。"""

import sys

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox

from src.ui.update_dialogs import (
    UpdateAvailableDialog,
    UpdateProgressDialog,
    show_update_message,
)
from src.update.qt_controller import UpdateController
from src.update.release_client import ReleaseInfo
from src.utils.config_manager import ConfigManager


def shared_update_controller() -> UpdateController:
    """起動時ゲートとぽえとれで使うアプリ内共通の更新コントローラー。"""
    app = QCoreApplication.instance()
    controller = getattr(app, "_shared_update_controller", None)
    if controller is None:
        controller = UpdateController(app)
        if app is not None:
            app._shared_update_controller = controller
    return controller


def record_update_check_result(config: dict, release: ReleaseInfo | None) -> None:
    """確認に成功した時点の更新情報を保存する。"""
    version = release.version if release is not None else ""
    if config.get("notified_update_version", "") != version:
        config["notified_update_version"] = version
        ConfigManager.save_config(config)


def _run_update_gate(
    config: dict, parent=None, manual: bool = False, *, controller=None,
) -> bool:
    """更新確認を完了し、通常起動を続ける場合はTrueを返す。"""
    if controller is None:
        controller = UpdateController(parent)
    notified_version = config.get("notified_update_version")
    check_loop = QEventLoop()
    result = None

    def on_finished(release, _manual):
        nonlocal result
        result = release, None
        check_loop.quit()

    def on_failed(message, _manual):
        nonlocal result
        result = None, message
        check_loop.quit()

    controller.check_finished.connect(on_finished)
    controller.check_failed.connect(on_failed)
    try:
        controller.check(manual)
        if result is None:
            check_loop.exec()
    finally:
        controller.check_finished.disconnect(on_finished)
        controller.check_failed.disconnect(on_failed)

    if result is None:
        return True
    release, error = result
    if error is None:
        record_update_check_result(config, release)
    if release is None:
        if manual:
            if error is not None:
                show_update_message(
                    parent,
                    QMessageBox.Warning,
                    "アップデート",
                    f"更新を確認できませんでした。\n{error}",
                )
            else:
                show_update_message(
                    parent,
                    QMessageBox.Information,
                    "アップデート",
                    "最新バージョンです。",
                )
        return True
    if not manual and notified_version == release.version:
        return True

    return offer_update(release, parent, controller)


def offer_update(release: ReleaseInfo, parent, controller: UpdateController) -> bool:
    """確認済みリリースの更新画面を開き、通常起動を続ける場合はTrueを返す。"""
    supported = getattr(sys, "frozen", False) and sys.platform == "win32"
    dialog = UpdateAvailableDialog(release, supported, parent)
    if not dialog.exec():
        return True
    if not supported:
        QDesktopServices.openUrl(QUrl(release.page_url))
        return True

    progress = UpdateProgressDialog(release.version, parent)
    progress.cancel_requested.connect(controller.cancel_download)
    download_loop = QEventLoop()
    download_result = {"archive": None, "error": None, "cancelled": False}

    def on_progress(done, total):
        progress.set_progress(done, total)

    def on_ready(archive, _release):
        download_result["archive"] = archive
        download_loop.quit()

    def on_download_failed(message):
        download_result["error"] = message
        download_loop.quit()

    def on_cancelled():
        download_result["cancelled"] = True
        download_loop.quit()

    controller.download_progress.connect(on_progress)
    controller.download_ready.connect(on_ready)
    controller.download_failed.connect(on_download_failed)
    controller.download_cancelled.connect(on_cancelled)
    try:
        progress.show()
        QTimer.singleShot(0, lambda: controller.download(release))
        download_loop.exec()
    finally:
        controller.download_progress.disconnect(on_progress)
        controller.download_ready.disconnect(on_ready)
        controller.download_failed.disconnect(on_download_failed)
        controller.download_cancelled.disconnect(on_cancelled)
        progress.close()

    if download_result["cancelled"]:
        return True
    if download_result["error"]:
        show_update_message(
            parent,
            QMessageBox.Warning,
            "アップデート",
            f"更新をダウンロードできませんでした。\n{download_result['error']}",
        )
        return True

    answer = show_update_message(
        parent,
        QMessageBox.Question,
        "アップデートを適用",
        f"v{release.version} の検証が完了しました。\n"
        "アプリを終了して更新しますか？",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )
    if answer != QMessageBox.Yes:
        return True
    try:
        controller.launch_updater(download_result["archive"])
    except Exception as exc:
        show_update_message(
            parent,
            QMessageBox.Critical,
            "アップデート",
            str(exc),
        )
        return True
    return False


def run_startup_update_gate(config: dict, parent=None) -> bool:
    """起動時の自動更新確認を行う。"""
    return _run_update_gate(config, parent, controller=shared_update_controller())


def run_manual_update_check(
    config: dict, parent=None, *, controller: UpdateController | None = None,
) -> bool:
    """ユーザー操作による更新確認を行い、同じ版の再通知も許可する。"""
    return _run_update_gate(config, parent, manual=True, controller=controller)
