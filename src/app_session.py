"""アプリの起動と、同一プロセスでのモード・PoE版切替を管理する。"""

import logging

from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtWidgets import QMessageBox

from src.app_restart import (
    is_valid_app_target,
    save_app_target,
    switch_app_target_and_restart,
)


logger = logging.getLogger(__name__)


class AppSessionController(QObject):
    def __init__(self, app, single_instance):
        super().__init__()
        self.app = app
        self.single_instance = single_instance
        self.window = None
        self.target = None
        self._switching = False
        app.aboutToQuit.connect(self._close_window)

    def start(self, mode, poe_version):
        from src.app_composition import create_mode_window

        self.app.setProperty("appMode", mode)
        window = create_mode_window(mode, poe_version)
        try:
            window.switch_requested.connect(self._handle_switch_request, Qt.QueuedConnection)
            self.single_instance.set_window(window)
            window.show()
        except Exception:
            self.single_instance.set_window(None)
            self._dispose_window(window)
            raise
        self.window = window
        self.target = (mode, poe_version)
        return window

    @Slot(str, str)
    def _handle_switch_request(self, mode, poe_version):
        # 旧メニューから既にキューへ入っていた要求は、新画面に引き継がない。
        if self.sender() is self.window:
            self.switch_target(mode, poe_version)

    def switch_target(self, mode, poe_version):
        target = (mode, poe_version)
        if (
            self._switching or self.window is None or target == self.target
            or not is_valid_app_target(*target)
        ):
            return False

        old_window, old_target = self.window, self.target
        self._switching = True
        quit_on_close = self.app.quitOnLastWindowClosed()
        self.app.setQuitOnLastWindowClosed(False)
        try:
            try:
                old_window.save_session_state()
                old_window.config.update(save_app_target(*target))
            except Exception:
                logger.exception("切替前の状態を保存できませんでした")
                QMessageBox.warning(old_window, "保存エラー", "切替前の状態を保存できませんでした。")
                return False

            try:
                closed = False
                try:
                    closed = old_window.close()
                finally:
                    # Qtのclose()が失敗しても、終了処理に入った画面は再利用しない。
                    if closed or old_window._session_closed:
                        if not closed:
                            old_window.hide()
                        self.window = None
                        self.single_instance.set_window(None)
                if not closed:
                    raise RuntimeError("切替前のウィンドウを閉じられませんでした")
                self.start(*target)
                return True
            except Exception:
                logger.exception("同一プロセス内で %s に切り替えられませんでした", target)
                # 旧画面は閉じていても、再起動処理が完了するまでは破棄しない。
                try:
                    if switch_app_target_and_restart(old_window, *target):
                        return True
                except Exception:
                    logger.exception("切替先のプロセスを起動できませんでした")
                self._restore_target(old_window, old_target)
                return False
            finally:
                if self.window is not old_window:
                    old_window.deleteLater()
        finally:
            self.app.setQuitOnLastWindowClosed(quit_on_close)
            self._switching = False

    def _restore_target(self, old_window, old_target):
        try:
            try:
                old_window.config.update(save_app_target(*old_target))
            except Exception:
                if self.window is None:
                    raise
                logger.exception("切替前の設定を保存できませんでした")
            if self.window is None:
                self.start(*old_target)
            else:
                self.app.setProperty("appMode", old_target[0])
                old_window.restore_from_tray()
        except Exception:
            logger.exception("切替前の画面を復元できませんでした")
            QMessageBox.critical(None, "切替エラー", "画面を復元できませんでした。アプリを起動し直してください。")
            self.app.quit()

    @staticmethod
    def _dispose_window(window):
        try:
            window.close()
        finally:
            window.deleteLater()

    @Slot()
    def _close_window(self):
        if self.window is not None:
            self.window.close()
