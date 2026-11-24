from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from src.ui.appearance import resolve_dialog_theme
from src.ui.dialog_theme import (
    POENAVI_DIALOG_THEME, POETORE_DIALOG_THEME, apply_dialog_theme, dialog_theme_for_mode,
)
from src.ui.styles import Styles
from src.ui.toolbar_icons import checking_icon, download_icon, update_check_icon
from src.update.release_client import ReleaseInfo, parse_version
from src.version import APP_VERSION


def available_update_version(config):
    version = str(config.get("notified_update_version", "")).strip()
    try:
        if parse_version(version) > parse_version(APP_VERSION):
            return version.removeprefix("v")
    except ValueError:
        pass
    return ""


def sync_update_action(button, theme, config, *, busy):
    version = available_update_version(config)
    if busy:
        tooltip = "アプリの更新を確認中…"
        icon = checking_icon(theme.muted_text)
    elif version:
        tooltip = f"v{version} に更新"
        icon = download_icon(theme.accent)
    else:
        tooltip = "アプリの更新をチェック"
        icon = update_check_icon(theme.muted_text)
    button.setIcon(icon)
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    button.setEnabled(not busy)


def _update_message_theme(parent):
    """更新メッセージを呼び出した設定画面のテーマへ合わせる。"""
    widget = parent
    while widget is not None:
        if widget.property("dialogTheme") == resolve_dialog_theme(POETORE_DIALOG_THEME).name:
            return resolve_dialog_theme(POETORE_DIALOG_THEME)
        if widget.property("dialogTheme") == resolve_dialog_theme(POENAVI_DIALOG_THEME).name:
            return resolve_dialog_theme(POENAVI_DIALOG_THEME)
        widget = widget.parentWidget()
    app = QApplication.instance()
    return dialog_theme_for_mode(app.property("appMode") if app is not None else None)


def build_update_message_box(
    parent,
    icon: QMessageBox.Icon,
    title: str,
    text: str,
    buttons: QMessageBox.StandardButtons = QMessageBox.Ok,
    default_button: QMessageBox.StandardButton = QMessageBox.NoButton,
) -> QMessageBox:
    """親画面のQSSに影響されず読める更新メッセージを構築する。"""
    theme = _update_message_theme(parent)
    message = QMessageBox(parent)
    message.setWindowTitle(title)
    message.setIcon(icon)
    message.setText(text)
    message.setStandardButtons(buttons)
    if default_button != QMessageBox.NoButton:
        message.setDefaultButton(default_button)
    message.setStyleSheet(
        f"""
        QMessageBox {{
            background-color: {theme.background};
        }}
        QMessageBox QLabel {{
            background-color: transparent;
            color: {theme.text};
        }}
        QMessageBox QPushButton {{
            min-width: 72px;
            padding: 5px 12px;
            background-color: {theme.control};
            color: {theme.text};
            border: 1px solid {theme.border_strong};
            border-radius: 4px;
        }}
        QMessageBox QPushButton:hover {{
            background-color: {theme.surface};
            border-color: {theme.accent};
        }}
        QMessageBox QPushButton:pressed {{
            background-color: {theme.background};
        }}
        """
    )
    return message


def show_update_message(*args, **kwargs) -> int:
    """可読性を固定した更新メッセージを表示する。"""
    return build_update_message_box(*args, **kwargs).exec()


class UpdateAvailableDialog(QDialog):
    def __init__(
        self,
        release: ReleaseInfo,
        auto_update_supported: bool,
        parent=None,
    ):
        super().__init__(parent)
        self.release = release
        self.setWindowTitle("ぽえなび アップデート")
        self.setMinimumSize(480, 360)
        self.setStyleSheet(Styles.MAIN_WINDOW)

        layout = QVBoxLayout(self)
        title = QLabel(
            f"新しいバージョン v{release.version} を利用できます。"
        )
        title.setWordWrap(True)
        layout.addWidget(title)

        notes = QTextBrowser()
        notes.setPlainText(release.notes)
        layout.addWidget(notes)

        buttons = QDialogButtonBox()
        update = buttons.addButton(
            "今すぐアップデート"
            if auto_update_supported
            else "リリースページを開く",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        later = buttons.addButton(
            "後で",
            QDialogButtonBox.ButtonRole.RejectRole,
        )
        update.clicked.connect(self.accept)
        later.clicked.connect(self.reject)
        layout.addWidget(buttons)


class UpdateProgressDialog(QDialog):
    cancel_requested = Signal()

    def __init__(self, version: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ぽえなび アップデート")
        self.setModal(True)
        apply_dialog_theme(self, _update_message_theme(parent))

        layout = QVBoxLayout(self)
        self.label = QLabel(f"v{version} をダウンロードしています…")
        self.progress = QProgressBar()
        self.cancel_button = QPushButton("キャンセル")
        self.cancel_button.clicked.connect(self._request_cancel)
        layout.addWidget(self.label)
        layout.addWidget(self.progress)
        layout.addWidget(self.cancel_button)

    def _request_cancel(self):
        if self.cancel_button.isEnabled():
            self.cancel_button.setEnabled(False)
            self.cancel_requested.emit()

    def closeEvent(self, event):
        # The callers use close() after the download loop finishes.
        if event.spontaneous():
            self._request_cancel()
        super().closeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._request_cancel()
        super().keyPressEvent(event)

    def set_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, total if total > 0 else 0)
        self.progress.setValue(done)
        if total:
            text = (
                f"ダウンロード中: {done / 1024 / 1024:.1f} / "
                f"{total / 1024 / 1024:.1f} MB"
            )
        else:
            text = f"ダウンロード中: {done / 1024 / 1024:.1f} MB"
        self.label.setText(text)
