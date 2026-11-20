"""ぽえとれモードの軽量メイン画面。"""

import sys
import threading
import time
from math import cos, radians, sin
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QIcon, QPainterPath, QPolygonF
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QStyle,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from src.app_mode import POETORE_MODE
from src.ui.appearance import resolve_app_theme, theme_color, theme_font_size
from src.poetore.exchange_icon_cache import ExchangeIconCache
from src.poetore.exchange_rate_cache import ExchangeRateValueCache
from src.poetore.exchange_rate_settings import (
    ExchangeRatePairStore,
    ensure_rate_pair_config,
)
from src.ui.app_theme import POETORE_THEME
from src.ui.dialog_theme import UI_METRICS, equalize_button_sizes
from src.ui.custom_command_settings import (
    custom_command_hotkeys,
    normalized_custom_commands,
)
from src.ui.toolbar_button import ToolbarButton
from src.ui.toolbar_icons import (
    checking_icon, download_icon, finish_line_icon, hideout_notification_icon,
    line_icon_canvas, map_mod_manager_icon, update_check_icon,
)
from src.ui.window_screen import SCREEN_CHANGE_DEBOUNCE_MS, WindowScreenWatcher
from src.update.release_client import parse_version
from src.update.startup_gate import record_update_check_result, shared_update_controller
from src.utils.chat_command import send_chat_command
from src.utils.config_manager import ConfigManager
from src.utils.feature_support import (
    MAP_CHECK,
    POETORE,
    is_feature_hotkey_supported,
    is_feature_supported,
)
from src.utils.global_hotkeys import (
    ForegroundSuppressedHotkeyService,
    GlobalHotkeyService,
    find_duplicate_hotkeys,
    is_hotkey_action_allowed,
    suppressed_hotkeys_supported,
)
from src.utils.log_path_detector import fill_missing_client_log_paths
from src.utils.poe_version_data import POE1, POE2
from src.utils.stash_tab_scroll import StashTabScrollController
from src.version import APP_VERSION


UPDATE_CHECK_INTERVAL_MS = 60 * 60 * 1000


def _icon_canvas():
    return line_icon_canvas(resolve_app_theme(POETORE_THEME).muted_text)


def _memo_icon() -> QIcon:
    """A note page with a folded corner."""
    pixmap, painter = _icon_canvas()
    page = QPainterPath(QPointF(5.5, 3.5))
    page.lineTo(14.5, 3.5)
    page.lineTo(18.5, 7.5)
    page.lineTo(18.5, 20.5)
    page.lineTo(5.5, 20.5)
    page.closeSubpath()
    page.moveTo(14.5, 3.5)
    page.lineTo(14.5, 7.5)
    page.lineTo(18.5, 7.5)
    painter.drawPath(page)
    painter.drawLine(QPointF(8.5, 12.0), QPointF(15.5, 12.0))
    painter.drawLine(QPointF(8.5, 16.0), QPointF(13.5, 16.0))
    return finish_line_icon(pixmap, painter)


def _heist_curio_icon() -> QIcon:
    """The curio's circular dial and latch."""
    pixmap, painter = _icon_canvas()
    painter.drawArc(QRectF(4.0, 3.5, 16.0, 15.0), 230 * 16, 320 * 16)
    painter.drawEllipse(QPointF(12.0, 11.0), 4.6, 4.6)
    painter.drawEllipse(QPointF(12.0, 11.0), 1.3, 1.3)
    painter.drawPolygon(QPolygonF([
        QPointF(4.3, 13.9), QPointF(7.6, 16.1),
        QPointF(5.7, 19.3), QPointF(2.4, 17.1),
    ]))
    return finish_line_icon(pixmap, painter)


def _expedition_icon() -> QIcon:
    """The Expedition spiral with two upper curls and one lower curl."""
    pixmap, painter = _icon_canvas()
    painter.translate(0.0, 24.0)
    painter.scale(1.0, -1.0)

    arm = QPainterPath(QPointF(12.0, 11.2))
    arm.cubicTo(QPointF(10.9, 10.2), QPointF(9.7, 9.1), QPointF(9.3, 7.5))
    arm.cubicTo(QPointF(8.9, 5.9), QPointF(9.6, 4.2), QPointF(11.1, 3.4))
    arm.cubicTo(QPointF(12.6, 2.5), QPointF(14.4, 3.0), QPointF(15.2, 4.5))
    arm.cubicTo(QPointF(15.8, 5.9), QPointF(15.2, 7.5), QPointF(13.8, 7.9))
    arm.cubicTo(QPointF(12.5, 8.3), QPointF(11.3, 7.3), QPointF(11.5, 6.1))
    arm.cubicTo(QPointF(11.7, 5.2), QPointF(12.8, 4.7), QPointF(13.5, 5.3))
    arm.cubicTo(QPointF(14.1, 5.7), QPointF(13.7, 6.6), QPointF(13.0, 6.6))

    for angle in (0, 120, 240):
        painter.save()
        painter.translate(12.0, 12.0)
        painter.rotate(angle)
        painter.translate(-12.0, -12.0)
        painter.drawPath(arm)
        painter.restore()

    painter.drawEllipse(QPointF(12.0, 12.0), 1.0, 1.0)
    return finish_line_icon(pixmap, painter)


def _abyss_desecration_icon() -> QIcon:
    """An eye engraved in the Abyss stone."""
    pixmap, painter = _icon_canvas()
    painter.drawPolygon(QPolygonF([
        QPointF(6.0, 3.5), QPointF(18.0, 3.5), QPointF(20.5, 6.0),
        QPointF(20.5, 18.0), QPointF(18.0, 20.5), QPointF(6.0, 20.5),
        QPointF(3.5, 18.0), QPointF(3.5, 6.0),
    ]))
    eye = QPainterPath(QPointF(5.5, 12.0))
    eye.quadTo(12.0, 4.8, 18.5, 12.0)
    eye.quadTo(12.0, 19.2, 5.5, 12.0)
    painter.drawPath(eye)
    painter.drawEllipse(QPointF(12.0, 12.0), 1.9, 1.9)
    return finish_line_icon(pixmap, painter)


def _image_manager_icon() -> QIcon:
    """Stacked picture cards."""
    pixmap, painter = _icon_canvas()
    back = QPainterPath(QPointF(3.5, 15.5))
    back.lineTo(3.5, 5.5)
    back.quadTo(3.5, 3.5, 5.5, 3.5)
    back.lineTo(16.5, 3.5)
    painter.drawPath(back)
    painter.drawRoundedRect(QRectF(7.0, 7.0, 13.5, 13.5), 1.6, 1.6)
    painter.drawEllipse(QPointF(16.5, 11.2), 1.0, 1.0)
    mountain = QPainterPath(QPointF(7.4, 18.5))
    mountain.lineTo(12.0, 13.8)
    mountain.lineTo(17.1, 18.5)
    painter.drawPath(mountain)
    return finish_line_icon(pixmap, painter)


def _settings_icon() -> QIcon:
    """A six-tooth gear."""
    pixmap, painter = _icon_canvas()
    tooth = ((-28, 6.6), (-13, 6.6), (-10, 8.8), (10, 8.8), (13, 6.6), (28, 6.6))
    outline = QPolygonF()
    for center_angle in range(-90, 270, 60):
        for offset, radius in tooth:
            angle = radians(center_angle + offset)
            outline.append(QPointF(12.0 + radius * cos(angle), 12.0 + radius * sin(angle)))
    painter.drawPolygon(outline)
    painter.drawEllipse(QPointF(12.0, 12.0), 2.6, 2.6)
    return finish_line_icon(pixmap, painter)


class _LeagueSignals(QObject):
    ready = Signal(str, bool)
    failed = Signal(str)


class _HideoutNotificationButton(ToolbarButton):
    def nextCheckState(self):
        # Only the controller can confirm that monitoring actually started.
        pass


class _PoetoreModeTitleBar(QWidget):
    """タイトルとウィンドウ操作を並べるドラッグ可能なタイトルバー。"""

    def __init__(self, window, poe_version=POE1):
        super().__init__(window)
        self._window = window
        self._drag_offset = None
        self.setObjectName("poetoreModeTitleBar")
        self.setMinimumHeight(UI_METRICS.toolbar_size)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            UI_METRICS.page_margin, UI_METRICS.inline_gap,
            UI_METRICS.control_gap, UI_METRICS.inline_gap,
        )
        layout.setSpacing(UI_METRICS.inline_gap)
        self.title_label = QLabel("ぽえとれ", self)
        mode_name = "PoE2" if poe_version == POE2 else "PoE1"
        self.mode_label = QLabel(f"（{mode_name}）", self)
        accent = resolve_app_theme(POETORE_THEME).accent
        for label, size in ((self.title_label, 18), (self.mode_label, 14)):
            label.setStyleSheet(
                f"color: {accent}; font-size: {theme_font_size(size)}px; font-weight: bold;"
            )
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
            layout.addWidget(label)
        layout.addStretch()

        self.update_button = ToolbarButton(border_width=0)
        self.update_button.setObjectName("poetoreAppUpdateAction")
        self.update_button.setIconSize(QSize(20, 20))
        self.update_button.setAutoDefault(True)
        layout.addWidget(self.update_button)

        glyph_style = f"font-size: {theme_font_size(14)}px; font-weight: bold; padding: 0;"
        self.minimize_button = ToolbarButton("─", border_width=0, content=glyph_style)
        self.minimize_button.setObjectName("poetoreMinimizeButton")
        self.minimize_button.setFixedSize(32, 24)
        self.minimize_button.setToolTip("最小化")
        self.minimize_button.setAccessibleName(self.minimize_button.toolTip())
        self.minimize_button.clicked.connect(window.minimize_to_tray)
        layout.addWidget(self.minimize_button)

        self.close_button = ToolbarButton("×", border_width=0, content=glyph_style)
        self.close_button.setObjectName("poetoreCloseButton")
        self.close_button.setFixedSize(32, 24)
        self.close_button.setToolTip("閉じる")
        self.close_button.setAccessibleName(self.close_button.toolTip())
        self.close_button.clicked.connect(window.close)
        layout.addWidget(self.close_button)
        equalize_button_sizes((self.minimize_button, self.close_button), minimum_width=32)
        self.update_button.setFixedSize(self.minimize_button.size())

    def mousePressEvent(self, event):
        if (
            event.button() == Qt.LeftButton
            and not self._window.config.get("window_locked", False)
        ):
            self._drag_offset = (
                event.globalPosition().toPoint()
                - self._window.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self._window.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_offset is not None:
            self._drag_offset = None
            self._window._refresh_screen_geometry()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class PoetoreModeWindow(QMainWindow):
    MODE_ACTION_DEFAULTS = {
        "exit": "F5",
        "monastery": "F12",
        "poetore_capture": "alt+d",
        "poetore_auto_hide": "ctrl+d",
        "expedition_reward_ocr": "alt+e",
        "desecration_tier_ocr": "alt+r",
        "heist_curio_ocr": "alt+e",
        "map_check": "alt+f",
        "cheat_sheets_toggle": "shift+space",
    }

    def __init__(self):
        super().__init__()
        self.config = ConfigManager.load_config()
        if fill_missing_client_log_paths(self.config):
            ConfigManager.save_config(self.config)
        ensure_rate_pair_config(self.config)
        poe_version = self.config.get("poe_version", POE1)
        self.poe_version = poe_version
        if not is_feature_supported(POETORE, poe_version):
            raise RuntimeError("PoE2版ぽえとれは現在テスト中です")
        self._cheat_sheet_overlay = None
        self._map_check_window = None
        self._memo_dialog = None
        self._expedition_reward_controller = None
        self._desecration_tier_controller = None
        self._heist_curio_controller = None
        self._ndlocr_pack_controller = None
        self._screen_reading_coordinator = None
        self._rate_pair_store = ExchangeRatePairStore(
            self.config, ConfigManager.save_config,
        )
        self._rate_icon_cache = ExchangeIconCache()
        self._rate_value_cache = ExchangeRateValueCache()
        self._resolved_rate_league = self._initial_currency_rate_league()
        self._league_request_running = False
        self._update_controller = shared_update_controller()
        self._toolbar_update_action = None
        self._deferred_toolbar_update_message = None
        self._update_gate_open = False
        self._league_signals = _LeagueSignals(self)
        self._league_signals.ready.connect(self._queue_rate_sync)
        self._league_signals.failed.connect(self._show_rate_error)
        self._screen_watcher = WindowScreenWatcher(self)
        self._screen_watcher.changed.connect(self._queue_screen_geometry)
        self._screen_metrics = None
        self._screen_geometry_timer = QTimer(self)
        self._screen_geometry_timer.setSingleShot(True)
        self._screen_geometry_timer.setInterval(SCREEN_CHANGE_DEBOUNCE_MS)
        self._screen_geometry_timer.timeout.connect(self._refresh_screen_geometry)

        self.setWindowTitle("ぽえとれ")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumWidth(500)
        self.resize(558, 300)
        self._build_ui()
        self._update_connections = (
            self._update_controller.check_started.connect(self._sync_update_button_from_config),
            self._update_controller.check_finished.connect(self._handle_update_check_result),
            self._update_controller.check_failed.connect(self._handle_update_check_failure),
        )
        self._update_check_timer = QTimer(self)
        self._update_check_timer.setInterval(UPDATE_CHECK_INTERVAL_MS)
        self._update_check_timer.timeout.connect(
            self._check_for_updates_in_background
        )
        self._update_check_timer.start()
        self._hideout_notification = None
        self._build_tray_icon()
        self._apply_window_settings()
        QTimer.singleShot(0, self._apply_startup_position)

        self.stash_tab_scroll = StashTabScrollController(
            enabled=self.config.get("stash_tab_scroll_enabled", True)
        )
        self.stash_tab_scroll.start()
        self._start_hotkeys()
        if sys.platform == "win32" and self._screen_reading_enabled():
            if self._expedition_ready():
                self._ensure_expedition_reward_controller().warm_up()
            if self._desecration_ready():
                self._ensure_desecration_tier_controller().warm_up()
        if sys.platform == "win32" and self._heist_curio_enabled():
            self._ensure_heist_curio_controller().warm_up()

        QTimer.singleShot(0, self.refresh_currency_rate)
        self._prepare_poetore_window()
        self._apply_obs_streaming_mode()

    @staticmethod
    def _asset_path(filename):
        return Path(__file__).resolve().parents[2] / "assets" / "icons" / filename

    @staticmethod
    def _app_asset_path(filename):
        return Path(__file__).resolve().parents[2] / "assets" / "app" / filename

    def _build_tray_icon(self):
        icon = QIcon(str(self._app_asset_path("icon2.ico")))
        if icon.isNull():
            icon = self.style().standardIcon(QStyle.SP_ComputerIcon)
        self.setWindowIcon(icon)

        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip("ぽえとれ")
        self.tray_icon.activated.connect(self._handle_tray_activation)

        menu = QMenu(self)
        self.tray_show_action = QAction("ぽえとれを表示", menu)
        self.tray_show_action.triggered.connect(self.restore_from_tray)
        menu.addAction(self.tray_show_action)
        self.tray_settings_action = QAction("設定", menu)
        self.tray_settings_action.triggered.connect(self.open_settings_from_tray)
        menu.addAction(self.tray_settings_action)
        menu.addSeparator()
        self.tray_exit_action = QAction("終了", menu)
        self.tray_exit_action.triggered.connect(self.quit_from_tray)
        menu.addAction(self.tray_exit_action)
        self.tray_icon.setContextMenu(menu)
        self._tray_notification_shown = False

    def minimize_to_tray(self):
        """トレイ非対応環境では、従来どおりタスクバーへ最小化する。"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.showMinimized()
            return
        self.tray_icon.show()
        self.hide()
        if not self._tray_notification_shown:
            self.tray_icon.showMessage(
                "ぽえとれ",
                "タスクトレイに格納しました。",
                QSystemTrayIcon.Information,
                3000,
            )
            self._tray_notification_shown = True

    def restore_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.tray_icon.hide()

    def open_settings_from_tray(self):
        self.restore_from_tray()
        QTimer.singleShot(0, self.open_settings)

    def quit_from_tray(self):
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _handle_tray_activation(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.restore_from_tray()

    def _build_ui(self):
        self.rate_quote_currency = (
            "exalted" if self.poe_version == POE2 else "chaos"
        )
        self.rate_quote_label = self.rate_quote_currency.title()
        central = QWidget()
        central.setObjectName("poetoreModeRoot")
        central.setStyleSheet(f"""
            QWidget#poetoreModeRoot {{
                background: {resolve_app_theme(POETORE_THEME).background};
                color: {resolve_app_theme(POETORE_THEME).text};
                border: 1px solid {theme_color('border', '#343B3E')};
                border-radius: 10px;
            }}
            QWidget#poetoreModeTitleBar {{ border: none; background: transparent; }}
            QScrollArea#poetoreRateScroll, QWidget#poetoreRatePanel {{
                background: transparent;
            }}
            QScrollArea#poetoreRateScroll QScrollBar:vertical {{
                background: {theme_color('surface', '#15191B')};
                width: {UI_METRICS.overlay_margin}px;
                margin: 0;
            }}
            QScrollArea#poetoreRateScroll QScrollBar::handle:vertical {{
                background: {resolve_app_theme(POETORE_THEME).muted_text};
                min-height: {UI_METRICS.overlay_control_height}px;
                border-radius: {UI_METRICS.inline_gap}px;
            }}
            QScrollArea#poetoreRateScroll QScrollBar::add-line:vertical,
            QScrollArea#poetoreRateScroll QScrollBar::sub-line:vertical {{ height: 0; }}
            QFrame#rateCard {{
                background: {resolve_app_theme(POETORE_THEME).panel};
                border: 1px solid {theme_color('border', '#343B3E')};
                border-radius: 10px;
            }}
            QPushButton {{
                background: {theme_color('control', '#1A1F21')};
                color: {resolve_app_theme(POETORE_THEME).text};
                border: 1px solid {theme_color('border', '#3A4245')};
                border-radius: 7px;
                padding: 7px 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {theme_color('control', '#25332F')}; border-color: {resolve_app_theme(POETORE_THEME).accent}; }}
            QPushButton:pressed {{ background: {theme_color('accent_soft', '#276B5A')}; }}
        """)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.title_bar = _PoetoreModeTitleBar(self, self.poe_version)
        self.title_label = self.title_bar.title_label
        self.mode_label = self.title_bar.mode_label
        self.update_button = self.title_bar.update_button
        self.update_button.clicked.connect(self._run_toolbar_update_action)
        self._sync_update_button_from_config()
        root.addWidget(self.title_bar)

        body = QWidget()
        body.setObjectName("poetoreModeBody")
        body.setStyleSheet("QWidget#poetoreModeBody { border: none; background: transparent; }")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(UI_METRICS.page_margin, UI_METRICS.inline_gap,
                                      UI_METRICS.page_margin, UI_METRICS.page_margin)
        body_layout.setSpacing(UI_METRICS.panel_padding)

        toolbar = QVBoxLayout()
        toolbar.setSpacing(UI_METRICS.inline_gap)
        header = QHBoxLayout()
        header.setSpacing(UI_METRICS.inline_gap)

        self.focus_button = _HideoutNotificationButton()
        self.focus_button.setObjectName("poetoreFocusButton")
        self.focus_button.setCheckable(True)
        self.focus_button.setIconSize(QSize(24, 24))
        self.focus_button.setStyleSheet(self.focus_button.styleSheet() + f"""
            QPushButton[notificationFlash="true"]:enabled {{
                background: {resolve_app_theme(POETORE_THEME).accent};
            }}
        """)
        self._update_focus_button_state(False)
        self.focus_button.clicked.connect(self.toggle_focus_mode)
        header.addWidget(self.focus_button)
        self.focus_status = QLabel()
        self.focus_status.setStyleSheet(
            f"color: {resolve_app_theme(POETORE_THEME).muted_text}; font-size: {theme_font_size(11)}px;"
        )
        self.focus_status.hide()
        header.addWidget(self.focus_status)
        self._focus_flash_timer = QTimer(self)
        self._focus_flash_timer.setSingleShot(True)
        self._focus_flash_timer.setInterval(1800)
        self._focus_flash_timer.timeout.connect(lambda: self._set_focus_button_flash(False))

        self.memo_button = self._header_button("", "共通メモを開く")
        self.memo_button.setIcon(_memo_icon())
        self.memo_button.setIconSize(QSize(24, 24))
        self.heist_settings_button = self._header_button(
            "", "ハイスト報酬OCR設定を開く"
        )
        self.heist_settings_button.setIcon(_heist_curio_icon())
        self.heist_settings_button.setIconSize(QSize(24, 24))
        self.heist_settings_button.setVisible(self.poe_version == POE1)
        self.expedition_settings_button = self._header_button(
            "", "エクスペ報酬チェック設定を開く"
        )
        self.expedition_settings_button.setIcon(_expedition_icon())
        self.expedition_settings_button.setIconSize(QSize(24, 24))
        self.expedition_settings_button.setVisible(self.poe_version == POE2)
        self.desecration_settings_button = self._header_button(
            "", "アビス冒涜Modティアチェック設定を開く"
        )
        self.desecration_settings_button.setIcon(_abyss_desecration_icon())
        self.desecration_settings_button.setIconSize(QSize(24, 24))
        self.desecration_settings_button.setVisible(self.poe_version == POE2)
        self.cheat_sheets_button = self._header_button(
            "", "Cheat sheetsの画像を登録・管理"
        )
        self.cheat_sheets_button.setIcon(_image_manager_icon())
        self.cheat_sheets_button.setIconSize(QSize(24, 24))
        self.map_mods_button = self._header_button("", "Map Mod管理")
        self.map_mods_button.setIcon(map_mod_manager_icon(resolve_app_theme(POETORE_THEME).muted_text))
        self.map_mods_button.setIconSize(QSize(24, 24))
        self.map_mods_button.setVisible(
            is_feature_supported(MAP_CHECK, self.poe_version)
        )
        self.settings_button = self._header_button("", "設定画面を開く")
        self.settings_button.setIcon(_settings_icon())
        self.settings_button.setIconSize(QSize(24, 24))
        self.memo_button.clicked.connect(self.open_memo)
        self.heist_settings_button.clicked.connect(self.open_heist_settings)
        self.expedition_settings_button.clicked.connect(
            self.open_expedition_settings
        )
        self.desecration_settings_button.clicked.connect(
            self.open_desecration_settings
        )
        self.map_mods_button.clicked.connect(self.open_map_mod_manager)
        self.cheat_sheets_button.clicked.connect(self.open_cheat_sheet_manager)
        self.settings_button.clicked.connect(self.open_settings)
        version_settings_buttons = (
            (self.heist_settings_button,)
            if self.poe_version == POE1
            else (self.expedition_settings_button, self.desecration_settings_button)
        )
        hidden_version_buttons = (
            (self.expedition_settings_button, self.desecration_settings_button)
            if self.poe_version == POE1
            else (self.heist_settings_button,)
        )
        self.header_action_buttons = (
            self.memo_button,
            *version_settings_buttons,
            *hidden_version_buttons,
            self.map_mods_button,
            self.cheat_sheets_button,
            self.settings_button,
        )
        for button in self.header_action_buttons:
            header.addWidget(button)
        header.addStretch()
        toolbar.addLayout(header)

        self.toolbar_message_label = QLabel("")
        self.toolbar_message_label.setObjectName("toolbarMessageLabel")
        self.toolbar_message_label.setStyleSheet(
            f"color: {resolve_app_theme(POETORE_THEME).accent}; font-size: {theme_font_size(12)}px;"
        )
        self.toolbar_message_label.setWordWrap(True)
        self.toolbar_message_label.hide()
        toolbar.addWidget(self.toolbar_message_label)
        self._toolbar_message_timer = QTimer(self)
        self._toolbar_message_timer.setSingleShot(True)
        self._toolbar_message_timer.setInterval(6000)
        self._toolbar_message_timer.timeout.connect(self._hide_toolbar_message)
        body_layout.addLayout(toolbar)

        from src.poetore.official_exchange import (
            default_official_exchange_shadow_service,
        )
        from src.ui.custom_exchange_rate_panel import CustomExchangeRatePanel

        self.rate_panel = CustomExchangeRatePanel(
            body,
            poe_version=self.poe_version,
            store=self._rate_pair_store,
            league_getter=lambda: self._resolved_rate_league,
            service=default_official_exchange_shadow_service,
            value_cache=self._rate_value_cache,
            icon_cache=self._rate_icon_cache,
            on_manage=self.open_exchange_rate_management,
            on_rows_changed=self._queue_rate_panel_height,
            refresh_callback=self.refresh_currency_rate,
            actions_layout=header,
        )
        self.rate_panel.setObjectName("poetoreRatePanel")
        self._rate_scroll = self.rate_panel.scroll_area
        self._rate_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        body_layout.addWidget(self.rate_panel, 1)
        # Let Qt lay out the wrapping and scrolling containers at their current width.
        for widget in (self, central, body, self._rate_scroll,
                       self._rate_scroll.viewport(), self.rate_panel, self.rate_panel.card):
            widget.setProperty("themeLayoutManaged", True)
        self.rate_refresh_button = self.rate_panel.refresh_button
        self.divine_rate_value = self.rate_panel.findChild(QLabel, "customRateValue0")

        self.capture_warning = QLabel("価格チェックのホットキーが設定されていません。")
        self.capture_warning.setObjectName("poetoreCaptureWarning")
        self.capture_warning.setWordWrap(True)
        self.capture_warning.setStyleSheet(
            f"color: {resolve_app_theme(POETORE_THEME).muted_text}; font-size: {theme_font_size(12)}px;"
        )
        body_layout.addWidget(self.capture_warning)
        root.addWidget(body, 1)
        self.setCentralWidget(central)
        equalize_button_sizes(
            (self.focus_button, *self.header_action_buttons),
            minimum_height=UI_METRICS.toolbar_size,
            equal_width=False,
        )
        for button in (self.focus_button, *self.header_action_buttons):
            button.setFixedWidth(button.height())
        toolbar_tab_order = (
            self.title_bar.close_button, self.focus_button,
            *self.header_action_buttons, self.rate_panel.manage_button,
        )
        for first, second in zip(toolbar_tab_order, toolbar_tab_order[1:]):
            QWidget.setTabOrder(first, second)
        self._update_capture_hotkey_warning()

    def showEvent(self, event):
        super().showEvent(event)
        # The appearance fitter can enlarge controls as their font is polished.
        QTimer.singleShot(0, self, self._refresh_screen_geometry)

    def event(self, event):
        if event.type() == QEvent.DevicePixelRatioChange and hasattr(self, "_screen_geometry_timer"):
            self._queue_screen_geometry()
        return super().event(event)

    def _queue_screen_geometry(self):
        self._screen_geometry_timer.start()

    def _refresh_screen_geometry(self):
        if self.title_bar._drag_offset is not None:
            return  # Apply pending screen changes on release.
        self._screen_geometry_timer.stop()
        self._screen_watcher.update()
        screen = self._screen_watcher.screen
        metrics = None if screen is None else (
            screen, screen.availableGeometry(), screen.logicalDotsPerInch(),
            screen.physicalDotsPerInch(), self.devicePixelRatioF(),
        )
        keep_on_screen = self._screen_metrics is not None and metrics != self._screen_metrics
        self._screen_metrics = metrics
        self._apply_rate_panel_height(keep_on_screen=keep_on_screen)

    def _apply_window_settings(self):
        self.setWindowOpacity(
            max(0.05, min(1.0, int(self.config.get("window_opacity", 100)) / 100))
        )
        flags = Qt.Window | Qt.FramelessWindowHint
        if self.config.get("always_on_top", True):
            flags |= Qt.WindowStaysOnTopHint
        was_visible = self.isVisible()
        self.setWindowFlags(flags)
        if was_visible:
            self.show()
        if self._memo_dialog is not None:
            self._memo_dialog.apply_opacity(
                self.config.get("window_opacity", 100),
                self.config.get("text_opacity", 100),
            )

    def _apply_startup_position(self):
        if not self.config.get("snap_to_right_edge", False):
            return
        screens = QApplication.screens()
        if not screens:
            return
        index = int(self.config.get("display_monitor", 0))
        screen = screens[index] if 0 <= index < len(screens) else screens[0]
        available = screen.availableGeometry()
        self.move(available.right() - self.width() + 1, available.top())

    def _header_button(self, text, tooltip):
        button = ToolbarButton(text)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFixedSize(UI_METRICS.toolbar_size, UI_METRICS.toolbar_size)
        return button

    def toggle_focus_mode(self):
        self._ensure_hideout_notification().toggle()

    def _ensure_hideout_notification(self):
        if self._hideout_notification is not None:
            return self._hideout_notification
        from src.poetore.hideout_notification_controller import (
            HideoutNotificationController,
        )

        controller = HideoutNotificationController(
            self.config, self.poe_version, ConfigManager.save_config, self
        )
        controller.display_changed.connect(self._update_focus_status)
        controller.focus_changed.connect(self._update_focus_button_state)
        controller.flash_requested.connect(self._flash_focus_button)
        controller.message_requested.connect(self._handle_focus_message)
        self._hideout_notification = controller
        return controller

    def _update_focus_button_state(self, active):
        self.focus_button.setChecked(active)
        name = f"隠れ家滞在通知：{'ON' if active else 'OFF'}"
        self.focus_button.setAccessibleName(name)
        self.focus_button.setToolTip(f"{name}（クリックで切替）")
        self._set_focus_button_flash(bool(self.focus_button.property("notificationFlash")))

    def _update_focus_status(self, text):
        _, _, status = text.partition("\n")
        self.focus_status.setText(status)
        self.focus_status.setVisible(status not in ("", "ON", "OFF"))

    def _set_focus_button_flash(self, flashing):
        theme = resolve_app_theme(POETORE_THEME)
        self.focus_button.set_style_property("notificationFlash", flashing)
        ink = theme.background if flashing else theme.muted_text
        self.focus_button.setIcon(hideout_notification_icon(ink, self.focus_button.isChecked()))

    def _flash_focus_button(self):
        self._set_focus_button_flash(True)
        self._focus_flash_timer.start()

    def _handle_focus_message(self, kind, text):
        if kind == "log_missing":
            answer = QMessageBox.question(
                self,
                "隠れ家滞在通知",
                f"{text}\n\n設定画面を開きますか？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            if answer == QMessageBox.Yes:
                QTimer.singleShot(0, self.open_settings)
            return
        if kind == "poe_not_running":
            QMessageBox.information(self, "隠れ家滞在通知", text)
            return
        self._show_toolbar_message(text)

    def _show_toolbar_message(self, text):
        self.toolbar_message_label.setText(text)
        self.toolbar_message_label.show()
        self._apply_rate_panel_height()
        self._toolbar_message_timer.start()

    def _hide_toolbar_message(self):
        self.toolbar_message_label.hide()
        self._apply_rate_panel_height()

    def _start_hotkeys(self):
        configured = self.config.get("hotkeys", {})
        poe_version = self.poe_version
        mode_hotkeys = {
            action: configured.get(action, default)
            for action, default in self.MODE_ACTION_DEFAULTS.items()
            if is_feature_hotkey_supported(action, poe_version)
        }
        mode_hotkeys.update(custom_command_hotkeys(self.config.get("custom_commands", [])))
        capture_hotkey = mode_hotkeys.get("poetore_capture", "none")
        expedition_hotkey = mode_hotkeys.get("expedition_reward_ocr", "none")
        desecration_hotkey = mode_hotkeys.get("desecration_tier_ocr", "none")
        heist_enabled = self._heist_curio_enabled()
        expedition_enabled = self._screen_reading_enabled() and self._expedition_ready()
        desecration_enabled = self._screen_reading_enabled() and self._desecration_ready()
        if not expedition_enabled:
            mode_hotkeys.pop("expedition_reward_ocr", None)
        if not desecration_enabled:
            mode_hotkeys.pop("desecration_tier_ocr", None)
        if not heist_enabled:
            mode_hotkeys.pop("heist_curio_ocr", None)
        use_suppression = suppressed_hotkeys_supported()
        if use_suppression:
            mode_hotkeys.pop("poetore_capture", None)
            mode_hotkeys.pop("expedition_reward_ocr", None)
            mode_hotkeys.pop("desecration_tier_ocr", None)
        self.hotkey_service = GlobalHotkeyService(
            mode_hotkeys, action_filter=is_hotkey_action_allowed, parent=self,
        )
        self.hotkey_service.command.connect(self.handle_hotkey)
        self.hotkey_service.start()
        self.suppressed_capture_hotkey = None
        self.suppressed_expedition_hotkey = None
        self.suppressed_desecration_hotkey = None
        if use_suppression:
            self.suppressed_capture_hotkey = ForegroundSuppressedHotkeyService(
                "poetore_capture", capture_hotkey,
                result_window_checker=self._is_poetore_result_window,
                poe_target_getter=self._poetore_poe_target,
                allow_unmodified=True,
                parent=self,
            )
            self.suppressed_capture_hotkey.command.connect(self.handle_hotkey)
            self.suppressed_capture_hotkey.start()
            if expedition_enabled:
                self.suppressed_expedition_hotkey = ForegroundSuppressedHotkeyService(
                    "expedition_reward_ocr", expedition_hotkey,
                    result_window_checker=lambda _hwnd: False,
                    poe_target_getter=self._poetore_poe_target,
                    allow_unmodified=True,
                    parent=self,
                )
                self.suppressed_expedition_hotkey.command.connect(self.handle_hotkey)
                self.suppressed_expedition_hotkey.start()
            if desecration_enabled:
                self.suppressed_desecration_hotkey = ForegroundSuppressedHotkeyService(
                    "desecration_tier_ocr", desecration_hotkey,
                    result_window_checker=lambda _hwnd: False,
                    poe_target_getter=self._poetore_poe_target,
                    allow_unmodified=True,
                    parent=self,
                )
                self.suppressed_desecration_hotkey.command.connect(self.handle_hotkey)
                self.suppressed_desecration_hotkey.start()

    def _screen_reading_enabled(self):
        return self.poe_version == POE2 and bool(
            self.config.get("poetore", {}).get("screen_reading", {}).get("enabled", False)
        )

    def _heist_curio_enabled(self):
        return self.poe_version == POE1 and bool(
            self.config.get("poetore", {}).get("heist_curio_ocr", {}).get(
                "enabled", False
            )
        )

    def _expedition_ready(self):
        return bool(self.config.get("poetore", {}).get("expedition_reward_overlay", {}).get("region"))

    def _desecration_ready(self):
        return bool(self.config.get("poetore", {}).get("desecration_tier_overlay", {}).get("inventory_open_region"))

    def _is_poetore_result_window(self, hwnd):
        try:
            return int(getattr(self, "_poetore_result_hwnd", 0) or 0) == int(hwnd)
        except (TypeError, ValueError):
            return False

    def _poetore_poe_target(self):
        window = getattr(self, "_poetore_window", None)
        return getattr(window, "_poe_window_hwnd", None) if window is not None else None

    def _update_capture_hotkey_warning(self):
        hotkeys = self.config.get("hotkeys", {})
        assigned = any(
            str(hotkeys.get(action, self.MODE_ACTION_DEFAULTS[action]) or "").strip().casefold()
            not in {"", "none"}
            for action in ("poetore_capture", "poetore_auto_hide")
        )
        self.capture_warning.setVisible(not assigned)

    @property
    def active_service_names(self):
        names = {"global_hotkeys", "stash_tab_scroll", "currency_rate_refresh"}
        if self._cheat_sheet_overlay is not None:
            names.add("cheat_sheets")
        return frozenset(names)

    def _configured_league(self):
        key = "league_poe2" if self.poe_version == POE2 else "league"
        return str(self.config.get("poetore", {}).get(key, "auto"))

    def _currency_rate_league(self):
        configured = self._configured_league()
        if configured != "auto":
            return configured
        if self.poe_version == POE2:
            from src.poetore.poe2.trade import FALLBACK_LEAGUES, default_pc_league
            return default_pc_league(FALLBACK_LEAGUES)
        from src.poetore.trade import available_pc_leagues, default_pc_league
        return default_pc_league(available_pc_leagues())

    def _initial_currency_rate_league(self):
        configured = self._configured_league()
        if configured != "auto":
            return configured
        if self.poe_version == POE2:
            from src.poetore.poe2.trade import FALLBACK_LEAGUES, default_pc_league
            return default_pc_league(FALLBACK_LEAGUES)
        return "Standard"

    def refresh_currency_rate(self, *, manual=False):
        if self._league_request_running:
            return
        self._league_request_running = True
        self.rate_panel.begin_refresh()

        def run():
            try:
                self._league_signals.ready.emit(
                    self._currency_rate_league(), bool(manual)
                )
            except Exception as exc:  # noqa: BLE001 - daemon boundary
                self._league_signals.failed.emit(str(exc))

        threading.Thread(target=run, daemon=True).start()

    def _queue_rate_sync(self, league, manual):
        self._league_request_running = False
        self._resolved_rate_league = league
        self.rate_panel.refresh(manual=manual)

    def _show_rate_error(self, _message):
        self._league_request_running = False
        self.rate_panel.refresh_failed()

    def open_exchange_rate_management(self):
        from src.ui.exchange_rate_management_dialog import (
            ExchangeRateManagementDialog,
        )

        dialog = ExchangeRateManagementDialog(
            self,
            poe_version=self.poe_version,
            store=self._rate_pair_store,
            available_item_ids=self.rate_panel.available_item_ids(),
            icon_cache=self._rate_icon_cache,
            available_item_ids_getter=self.rate_panel.available_item_ids,
            on_changed=self._rate_pairs_changed,
        )
        dialog.exec()

    def _rate_pairs_changed(self):
        self.rate_panel.render_rows()
        self.divine_rate_value = self.rate_panel.findChild(
            QLabel, "customRateValue0"
        )

    def _queue_rate_panel_height(self):
        # Qt invalidates the layout for new rows via posted events.
        QTimer.singleShot(0, self, self._apply_rate_panel_height)

    def _apply_rate_panel_height(self, *, keep_on_screen=False):
        if not hasattr(self, "_rate_scroll") or self.title_bar._drag_offset is not None:
            return
        root = self.centralWidget().layout()
        rate_layout = self._rate_scroll.widget().layout()
        self.rate_panel.ensurePolished()
        body_insets = 2 * UI_METRICS.page_margin
        rate_minimum = rate_layout.totalMinimumSize().width() + body_insets
        chrome_minimum = max(self.minimumWidth(), root.minimumSize().width())
        preferred = max(self.width(), rate_minimum, rate_layout.totalSizeHint().width() + body_insets)
        screen = self._screen_watcher.screen or self.screen()
        available = screen.availableGeometry() if screen is not None else None
        width_limit = self.maximumWidth()
        height_limit = self.maximumHeight()
        if available is not None:
            width_limit = available.width()
            height_limit = available.height()
            self.setMaximumHeight(height_limit)
            if not keep_on_screen:
                # Fit the rate content into the space below and to the right of the current position.
                width_limit = min(width_limit, available.right() - self.x() + 1)
                height_limit = min(height_limit, available.bottom() - self.y() + 1)
        width = max(chrome_minimum, min(preferred, width_limit))
        rate_height = rate_layout.totalHeightForWidth(width - body_insets)
        if rate_height < 0:
            rate_height = rate_layout.totalSizeHint().height()
        # The fixed header and footer stay outside the scrollable rate content.
        chrome_height = root.totalHeightForWidth(width)
        if chrome_height < 0:
            chrome_height = root.totalSizeHint().height()
        natural_height = chrome_height + rate_height
        height = natural_height
        if height > height_limit:
            scrollbar_width = self._rate_scroll.verticalScrollBar().sizeHint().width()
            width = max(width, min(width_limit, rate_minimum + scrollbar_width))
            height = max(chrome_height, height_limit)
        self.resize(width, height)
        if available is None or available.contains(self.frameGeometry()):
            return
        if keep_on_screen:
            self.move(
                max(available.left(), min(self.x(), available.right() - self.width() + 1)),
                max(available.top(), min(self.y(), available.bottom() - self.height() + 1)),
            )
        elif self.isVisible():
            root.activate()
            self._recover_offscreen_controls(available, natural_height)

    def _recover_offscreen_controls(self, available, natural_height):
        controls = [
            QRect(button.mapToGlobal(button.rect().topLeft()), button.size())
            for button in (
                self.update_button, self.title_bar.minimize_button, self.title_bar.close_button,
                self.rate_panel.manage_button, self.rate_refresh_button,
            )
            if button.isVisible()
        ]
        x, y = self.x(), self.y()
        if any(rect.right() < available.left() or rect.left() > available.right() for rect in controls):
            left = min(rect.left() for rect in controls)
            right = max(rect.right() for rect in controls)
            x += max(available.left() - left, min(0, available.right() - right))
        if any(rect.bottom() < available.top() or rect.top() > available.bottom() for rect in controls):
            # Restore room for the rates before bringing the title and footer back.
            self.resize(self.width(), min(natural_height, available.height()))
            y = max(available.top(), min(y, available.bottom() - self.height() + 1))
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def handle_hotkey(self, command):
        if command.startswith("custom_command:"):
            index = int(command.split(":", 1)[1])
            commands = normalized_custom_commands(self.config.get("custom_commands", []))
            if 0 <= index < len(commands) and commands[index]["enabled"]:
                self.execute_chat_command(commands[index]["command"])
            return
        if command == "poetore_capture":
            self.capture_poetore_item()
        elif command == "poetore_capture_released":
            window = getattr(self, "_poetore_window", None)
            if window is not None:
                window.capture_hotkey_released()
        elif command == "poetore_auto_hide":
            self.capture_poetore_item(auto_hide=True)
        elif command == "poetore_auto_hide_released":
            window = getattr(self, "_poetore_window", None)
            if window is not None:
                window.capture_hotkey_released()
        elif command == "expedition_reward_ocr":
            self.capture_expedition_rewards()
        elif command == "desecration_tier_ocr":
            self.capture_desecration_tiers()
        elif command == "heist_curio_ocr":
            self.capture_heist_curio()
        elif command == "map_check":
            self.capture_map_check_item()
        elif command == "map_check_released":
            if self._map_check_window is not None:
                self._map_check_window.capture_hotkey_released()
        elif command == "cheat_sheets_toggle":
            self.toggle_cheat_sheets()
        elif command == "cheat_sheets_escape":
            if self._cheat_sheet_overlay is not None and self._cheat_sheet_overlay.isVisible():
                self._cheat_sheet_overlay.hide_and_save()
        elif command == "exit":
            self.execute_chat_command("/exit")
        elif command == "monastery":
            self.execute_chat_command("/monastery")

    def capture_poetore_item(self, auto_hide=False):
        if not is_feature_supported(
            POETORE, self.poe_version,
        ):
            return None
        started_at = time.perf_counter()
        from src.poetore.performance import start_search_trace

        trace = start_search_trace(
            "auto_hide_poetore_mode" if auto_hide else "interactive_poetore_mode",
            started_at=started_at,
        )
        trace.mark("hotkey_dispatched")
        from src.poetore.ui import show_poetore_window

        window = show_poetore_window(self, activate=False)
        trace.mark("poetore_window_ready")
        if auto_hide:
            hotkey = self.config.get("hotkeys", {}).get(
                "poetore_auto_hide", "ctrl+d"
            )
            window.capture_from_poe(
                trace, auto_hide=True, capture_hotkey=hotkey,
            )
        else:
            hotkey = self.config.get("hotkeys", {}).get(
                "poetore_capture", "alt+d"
            )
            window.capture_from_poe(trace, capture_hotkey=hotkey)

    def _ensure_expedition_reward_controller(self):
        if self._expedition_reward_controller is None:
            from src.poetore.expedition_rewards import ExpeditionRewardController

            shared = self._ensure_screen_reading_coordinator()
            controller = ExpeditionRewardController(
                self._currency_rate_league,
                self,
                region_getter=lambda: self.config.get("poetore", {}).get(
                    "expedition_reward_overlay", {}
                ).get("region"),
                ocr_server=shared,
                scan_coordinator=shared,
            )
            controller.status.connect(self._show_expedition_status)
            controller.failed.connect(self._show_expedition_error)
            controller.diagnostic.connect(self._show_expedition_diagnostic)
            self._expedition_reward_controller = controller
        return self._expedition_reward_controller

    def capture_expedition_rewards(self):
        if not self._screen_reading_enabled() or not self._expedition_ready():
            return False
        return self._ensure_expedition_reward_controller().request_scan()

    def _ensure_screen_reading_coordinator(self):
        if self._screen_reading_coordinator is None:
            from src.poetore.screen_reading import ScreenReadingCoordinator
            self._screen_reading_coordinator = ScreenReadingCoordinator()
        return self._screen_reading_coordinator

    def _ensure_heist_curio_controller(self):
        if self._heist_curio_controller is None:
            from src.poetore.heist_curio import HeistCurioController

            shared = self._ensure_screen_reading_coordinator()
            controller = HeistCurioController(
                self, ocr_server=shared, scan_coordinator=shared,
            )
            controller.status.connect(self._show_heist_curio_status)
            controller.failed.connect(self._show_heist_curio_error)
            controller.resolved.connect(self._show_heist_curio_result)
            self._heist_curio_controller = controller
        return self._heist_curio_controller

    def capture_heist_curio(self):
        if not self._heist_curio_enabled():
            return False
        return self._ensure_heist_curio_controller().request_scan()

    def _show_heist_curio_status(self, message):
        self._show_toolbar_message(message)

    def _show_heist_curio_error(self, message):
        self._show_toolbar_message(f"ハイスト報酬読取失敗：{message}")
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.showMessage(
                "ハイスト報酬価格チェック", message, QSystemTrayIcon.Warning, 5000,
            )

    def _show_heist_curio_result(self, match, placement):
        from src.poetore.ui import show_poetore_window

        window = show_poetore_window(self, activate=False)
        window.show_heist_curio_match(match, placement)
        self._show_toolbar_message(f"ハイスト報酬：{match.item.name_ja}")

    def _ensure_desecration_tier_controller(self):
        if self._desecration_tier_controller is None:
            from src.poetore.performance import start_search_trace
            from src.poetore.poe2.desecration_overlay import DesecrationTierController
            shared = self._ensure_screen_reading_coordinator()
            controller = DesecrationTierController(
                self,
                regions_getter=lambda: self.config.get("poetore", {}).get("desecration_tier_overlay", {}),
                ocr_server=shared,
                scan_coordinator=shared,
                trace_factory=lambda: start_search_trace("desecration_tier_scan"),
            )
            controller.status.connect(self._show_desecration_status)
            controller.failed.connect(self._show_desecration_error)
            self._desecration_tier_controller = controller
        return self._desecration_tier_controller

    def _ensure_ndlocr_pack_controller(self):
        if self._ndlocr_pack_controller is None:
            from src.poetore.poe2.ndlocr_pack import NdlOcrPackController

            self._ndlocr_pack_controller = NdlOcrPackController(self)
        return self._ndlocr_pack_controller

    def capture_desecration_tiers(self):
        if not self._screen_reading_enabled() or not self._desecration_ready():
            return False
        return self._ensure_desecration_tier_controller().request_scan()

    def _show_desecration_status(self, message):
        self._show_toolbar_message(message)

    def _show_desecration_error(self, message):
        self._show_toolbar_message(f"冒涜Mod読取失敗：{message}")
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.showMessage("アビス冒涜Modティア", message, QSystemTrayIcon.Warning, 5000)

    def _show_expedition_status(self, message):
        self._show_toolbar_message(message)

    def _show_expedition_error(self, message):
        self._show_toolbar_message(f"報酬読取失敗：{message}")
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.showMessage("エクスペディション報酬価格", message, QSystemTrayIcon.Warning, 5000)

    def _show_expedition_diagnostic(self, report):
        QMessageBox.information(self, "エクスペディションOCR診断", report)

    def _save_map_check_config(self, map_check_config):
        self.config["map_check"] = dict(map_check_config)
        ConfigManager.save_config(self.config)

    def _ensure_map_check_window(self):
        from src.ui.map_check import MapCheckWindow

        if self._map_check_window is None:
            map_config = dict(self.config.get("map_check", {}))
            map_config["_font_size"] = self.config.get("poetore", {}).get("result_font_size", "medium")
            self._map_check_window = MapCheckWindow(map_config, self, app_mode=POETORE_MODE)
            self._map_check_window.config_changed.connect(
                self._save_map_check_config
            )
        else:
            map_config = dict(self.config.get("map_check", {}))
            map_config["_font_size"] = self.config.get("poetore", {}).get("result_font_size", "medium")
            self._map_check_window.reload_config(map_config)
        return self._map_check_window

    def capture_map_check_item(self):
        if not is_feature_supported(MAP_CHECK, self.poe_version):
            return None
        self._ensure_map_check_window().capture_from_poe()

    def open_map_mod_manager(self):
        if not is_feature_supported(MAP_CHECK, self.poe_version):
            return None
        from src.ui.map_check import MapModManagerDialog

        dialog = MapModManagerDialog(self.config.get("map_check", {}), self)
        dialog.config_changed.connect(self._save_map_check_config)
        dialog.exec()
        if self._map_check_window is not None:
            self._map_check_window.reload_config(self.config.get("map_check", {}))

    def _prepare_poetore_window(self):
        """Build the search panel after startup without issuing Trade requests."""
        if not is_feature_supported(
            POETORE, self.poe_version,
        ):
            return None
        from src.poetore.ui import prepare_poetore_window

        return prepare_poetore_window(self)

    def _apply_obs_streaming_mode(self):
        window = getattr(self, "_poetore_window", None)
        if window is None:
            return
        obs_config = self.config.get("poetore", {}).get("obs_streaming", {})
        enabled = bool(obs_config.get("enabled", False)) if isinstance(obs_config, dict) else False
        window.set_obs_streaming_mode(enabled)

    def open_memo(self):
        if self._memo_dialog is not None:
            if self._memo_dialog.isVisible():
                self._memo_dialog._save_and_close()
            else:
                self._memo_dialog.show()
                self._memo_dialog.raise_()
            return
        from src.ui.memo_dialog import MemoDialog

        poe_version = self.poe_version
        filename = "notes_poe2.json" if poe_version == POE2 else "notes_poe1.json"
        notes_path = str(ConfigManager.get_user_data_path(filename))
        self._memo_dialog = MemoDialog(
            self, notes_path=notes_path, theme=resolve_app_theme(POETORE_THEME), app_mode=POETORE_MODE,
        )
        self._memo_dialog.apply_opacity(
            self.config.get("window_opacity", 100),
            self.config.get("text_opacity", 100),
        )
        self._memo_dialog.show()

    def _restart_hotkeys(self):
        self.hotkey_service.stop()
        if self.suppressed_capture_hotkey is not None:
            self.suppressed_capture_hotkey.stop()
        if self.suppressed_expedition_hotkey is not None:
            self.suppressed_expedition_hotkey.stop()
        if self.suppressed_desecration_hotkey is not None:
            self.suppressed_desecration_hotkey.stop()
        self._start_hotkeys()

    def _save_screen_reading_settings(self, feature_key, feature_config, action, hotkey, enabled):
        configured_hotkeys = self.config.get("hotkeys", {})
        configured_hotkeys = configured_hotkeys if isinstance(configured_hotkeys, dict) else {}
        active_hotkeys = {
            name: configured_hotkeys.get(name, default)
            for name, default in PoetoreModeWindow.MODE_ACTION_DEFAULTS.items()
            if is_feature_hotkey_supported(name, self.poe_version)
        }
        active_hotkeys[action] = hotkey
        active_hotkeys.update(custom_command_hotkeys(self.config.get("custom_commands", [])))
        duplicate = next(
            ((key, actions) for key, actions in find_duplicate_hotkeys(active_hotkeys).items() if action in actions),
            None,
        )
        if duplicate is not None:
            key, actions = duplicate
            labels = {
                "exit": "キャラクター選択へ戻る", "monastery": "修道院へ移動",
                "poetore_capture": "ぽえとれ検索（操作モード）",
                "poetore_auto_hide": "ぽえとれ検索（AUTO-HIDE）",
                "expedition_reward_ocr": "エクスペ報酬チェック",
                "desecration_tier_ocr": "アビス冒涜Modティアチェック",
                "map_check": "Map Modチェック", "cheat_sheets_toggle": "Cheat sheets表示",
            }
            others = "、".join(labels.get(name, name) for name in actions if name != action)
            QMessageBox.warning(self, "ホットキー重複", f"{key}は別の操作（{others}）にも設定されています。")
            return False
        poetore = self.config.get("poetore", {})
        poetore = dict(poetore) if isinstance(poetore, dict) else {}
        poetore[feature_key] = dict(feature_config)
        poetore["screen_reading"] = {"enabled": bool(enabled)}
        hotkeys = dict(configured_hotkeys)
        hotkeys[action] = hotkey
        self.config["poetore"] = poetore
        self.config["hotkeys"] = hotkeys
        ConfigManager.save_config(self.config)
        if not enabled:
            self._shutdown_screen_reading()
        self._restart_hotkeys()
        return True

    def _shutdown_screen_reading(self):
        self._shutdown_heist_curio()
        if self._expedition_reward_controller is not None:
            self._expedition_reward_controller.close()
            self._expedition_reward_controller = None
        if self._desecration_tier_controller is not None:
            self._desecration_tier_controller.close()
            self._desecration_tier_controller = None
        if self._screen_reading_coordinator is not None:
            self._screen_reading_coordinator.close()
            self._screen_reading_coordinator = None

    def _shutdown_heist_curio(self):
        if self._heist_curio_controller is not None:
            self._heist_curio_controller.close()
            self._heist_curio_controller = None
        if self.poe_version == POE1 and self._screen_reading_coordinator is not None:
            self._screen_reading_coordinator.close()
            self._screen_reading_coordinator = None

    def open_heist_settings(self):
        if self.poe_version != POE1:
            return
        from src.ui.heist_settings_dialog import HeistSettingsDialog

        hotkeys = self.config.get("hotkeys", {})
        hotkeys = hotkeys if isinstance(hotkeys, dict) else {}
        pack_controller = self._ensure_ndlocr_pack_controller()
        dialog = HeistSettingsDialog(
            self,
            enabled=self._heist_curio_enabled(),
            hotkey=hotkeys.get("heist_curio_ocr", "alt+e"),
            ocr_pack_controller=pack_controller,
        )
        pack_controller.ensure_started()
        if not dialog.exec():
            return
        hotkey, enabled = dialog.settings()
        if not PoetoreModeWindow._save_heist_curio_settings(
            self, hotkey, enabled
        ):
            return
        if enabled:
            self._ensure_heist_curio_controller().warm_up()

    def _save_heist_curio_settings(self, hotkey, enabled):
        configured_hotkeys = self.config.get("hotkeys", {})
        configured_hotkeys = (
            configured_hotkeys if isinstance(configured_hotkeys, dict) else {}
        )
        active_hotkeys = {
            name: configured_hotkeys.get(name, default)
            for name, default in self.MODE_ACTION_DEFAULTS.items()
            if is_feature_hotkey_supported(name, self.poe_version)
        }
        active_hotkeys["heist_curio_ocr"] = hotkey
        active_hotkeys.update(
            custom_command_hotkeys(self.config.get("custom_commands", []))
        )
        duplicate = next(
            (
                (key, actions)
                for key, actions in find_duplicate_hotkeys(active_hotkeys).items()
                if "heist_curio_ocr" in actions
            ),
            None,
        )
        if duplicate is not None:
            key, actions = duplicate
            labels = {
                "exit": "キャラクター選択へ戻る",
                "monastery": "修道院へ移動",
                "poetore_capture": "ぽえとれ検索（操作モード）",
                "poetore_auto_hide": "ぽえとれ検索（AUTO-HIDE）",
                "heist_curio_ocr": "ハイスト報酬OCR",
                "map_check": "Map Modチェック",
                "cheat_sheets_toggle": "Cheat sheets表示",
            }
            others = "、".join(
                labels.get(name, name)
                for name in actions
                if name != "heist_curio_ocr"
            )
            QMessageBox.warning(
                self,
                "ホットキー重複",
                f"{key}は別の操作（{others}）にも設定されています。",
            )
            return False

        poetore = self.config.get("poetore", {})
        poetore = dict(poetore) if isinstance(poetore, dict) else {}
        poetore["heist_curio_ocr"] = {"enabled": bool(enabled)}
        saved_hotkeys = dict(configured_hotkeys)
        saved_hotkeys["heist_curio_ocr"] = hotkey
        saved_hotkeys.pop("heist_curio_manual_ocr", None)
        self.config["poetore"] = poetore
        self.config["hotkeys"] = saved_hotkeys
        ConfigManager.save_config(self.config)
        if not enabled:
            self._shutdown_heist_curio()
        self._restart_hotkeys()
        return True

    def open_expedition_settings(self):
        if self.poe_version != POE2:
            return
        from src.ui.expedition_settings_dialog import ExpeditionSettingsDialog

        poetore = self.config.get("poetore", {})
        poetore = poetore if isinstance(poetore, dict) else {}
        expedition_config = poetore.get("expedition_reward_overlay", {})
        expedition_config = (
            expedition_config if isinstance(expedition_config, dict) else {}
        )
        hotkeys = self.config.get("hotkeys", {})
        hotkeys = hotkeys if isinstance(hotkeys, dict) else {}
        dialog = ExpeditionSettingsDialog(
            self,
            expedition_config=expedition_config,
            hotkey=hotkeys.get("expedition_reward_ocr", "alt+e"),
            screen_reading_enabled=self._screen_reading_enabled(),
        )
        if not dialog.exec():
            return
        expedition_config, expedition_hotkey, enabled = dialog.settings()
        if not PoetoreModeWindow._save_screen_reading_settings(self,
            "expedition_reward_overlay", expedition_config,
            "expedition_reward_ocr", expedition_hotkey, enabled,
        ):
            return
        if enabled and expedition_config.get("region"):
            self._ensure_expedition_reward_controller().warm_up()

    def open_desecration_settings(self):
        if self.poe_version != POE2:
            return
        from src.ui.desecration_settings_dialog import DesecrationSettingsDialog
        poetore = self.config.get("poetore", {})
        poetore = poetore if isinstance(poetore, dict) else {}
        feature_config = poetore.get("desecration_tier_overlay", {})
        feature_config = feature_config if isinstance(feature_config, dict) else {}
        hotkeys = self.config.get("hotkeys", {})
        hotkeys = hotkeys if isinstance(hotkeys, dict) else {}
        pack_controller = self._ensure_ndlocr_pack_controller()
        dialog = DesecrationSettingsDialog(
            self, desecration_config=feature_config,
            hotkey=hotkeys.get("desecration_tier_ocr", "alt+r"),
            screen_reading_enabled=self._screen_reading_enabled(),
            ocr_pack_controller=pack_controller,
        )
        pack_controller.ensure_started()
        if not dialog.exec():
            return
        feature_config, hotkey, enabled = dialog.settings()
        if not PoetoreModeWindow._save_screen_reading_settings(self,
            "desecration_tier_overlay", feature_config,
            "desecration_tier_ocr", hotkey, enabled,
        ):
            return
        if enabled and feature_config.get("inventory_open_region"):
            self._ensure_desecration_tier_controller().warm_up()

    def open_settings(self):
        from src.ui.poetore_settings_dialog import PoetoreSettingsDialog

        dialog = PoetoreSettingsDialog(
            self,
            self.config,
            update_check_callback=lambda: self._check_for_updates(dialog),
        )
        if not dialog.exec():
            return
        self.config.update(dialog.get_settings())
        ConfigManager.save_config(self.config)
        if self._hideout_notification is not None:
            self._hideout_notification.apply_settings(self.config)
        from src.windows_autostart import (
            sync_windows_poetore_autostart_with_error,
        )

        autostart_error = sync_windows_poetore_autostart_with_error(self.config)
        if autostart_error:
            QMessageBox.warning(
                self,
                "自動起動設定エラー",
                "Windowsの自動起動設定を更新できませんでした。\n"
                "設定は保存済みのため、次回起動時に再試行します。",
            )
        from src.app_restart import confirm_mode_switch_restart

        if confirm_mode_switch_restart(
            self, self.config, current_poe_version=self.poe_version
        ):
            return
        self._apply_window_settings()
        self._apply_startup_position()
        if getattr(self, "_poetore_window", None) is not None:
            self._poetore_window.apply_result_display_size()
            self._apply_obs_streaming_mode()
        self.stash_tab_scroll.set_enabled(
            self.config.get("stash_tab_scroll_enabled", True)
        )
        self._restart_hotkeys()
        self._update_capture_hotkey_warning()
        self._apply_rate_panel_height()
        self.refresh_currency_rate()

    def _check_for_updates(self, parent=None):
        """アプリ情報タブから更新確認を行い、結果に応じた画面を開く。"""
        from src.update.startup_gate import run_manual_update_check

        self._run_update_flow(lambda: run_manual_update_check(
            self.config, parent or self, controller=self._update_controller,
        ))

    def _run_update_flow(self, run_update):
        if self._update_gate_open:
            return
        self._update_check_timer.stop()
        self._update_gate_open = True
        self._sync_update_button_from_config()
        try:
            continue_running = run_update()
        finally:
            self._update_gate_open = False
            self._sync_update_button_from_config()
        if not continue_running:
            QApplication.instance().quit()
            return
        self._update_check_timer.start()
        if self._deferred_toolbar_update_message is not None:
            icon, message = self._deferred_toolbar_update_message
            self._deferred_toolbar_update_message = None
            self._show_toolbar_update_message(icon, message)

    def _available_update_version(self):
        version = str(self.config.get("notified_update_version", "")).strip()
        try:
            if parse_version(version) > parse_version(APP_VERSION):
                return version.removeprefix("v")
        except ValueError:
            pass
        return ""

    def _sync_update_button_from_config(self):
        theme = resolve_app_theme(POETORE_THEME)
        version = self._available_update_version()
        checking = self._update_controller.checking or self._update_gate_open
        if checking:
            tooltip = "アプリの更新を確認中…"
            icon = checking_icon(theme.muted_text)
        elif version:
            tooltip = f"v{version} に更新"
            icon = download_icon(theme.accent)
        else:
            tooltip = "アプリの更新をチェック"
            icon = update_check_icon(theme.muted_text)
        self.update_button.setIcon(icon)
        self.update_button.setToolTip(tooltip)
        self.update_button.setAccessibleName(tooltip)
        self.update_button.setEnabled(not checking)

    def _run_toolbar_update_action(self):
        self._start_update_check(manual=True)

    def _start_update_check(self, *, manual):
        if self._update_controller.checking or self._update_gate_open:
            return
        if manual:
            self._toolbar_update_action = (
                "download" if self._available_update_version() else "check"
            )
        self._update_controller.check(manual)

    def _check_for_updates_in_background(self):
        """常駐中はダイアログを出さずに最新版だけ確認する。"""
        self._start_update_check(manual=False)

    def _handle_update_check_result(self, release, _manual):
        record_update_check_result(self.config, release)
        self._sync_update_button_from_config()
        if release is None:
            self._notify_toolbar_update_check(QMessageBox.Information, "最新バージョンです。")
            return

        action = self._toolbar_update_action
        self._toolbar_update_action = None
        if action == "download" and not self._update_gate_open:
            from src.update.startup_gate import offer_update

            self._run_update_flow(lambda: offer_update(release, self, self._update_controller))

    def _handle_update_check_failure(self, message, _manual):
        self._sync_update_button_from_config()
        self._notify_toolbar_update_check(
            QMessageBox.Warning, f"更新を確認できませんでした。\n{message}",
        )

    def _notify_toolbar_update_check(self, icon, message):
        if self._toolbar_update_action is None:
            return
        self._toolbar_update_action = None
        if self._update_gate_open:
            # アプリ情報の確認結果を閉じた後にツールバーの結果を表示する。
            self._deferred_toolbar_update_message = icon, message
        else:
            self._show_toolbar_update_message(icon, message)

    def _show_toolbar_update_message(self, icon, message):
        from src.ui.update_dialogs import show_update_message

        show_update_message(self, icon, "アップデート", message)

    def _ensure_cheat_sheet_overlay(self):
        from src.ui.cheat_sheets import CheatSheetOverlay

        if self._cheat_sheet_overlay is None:
            overlay = CheatSheetOverlay(
                self.config.get("cheat_sheets", {}), self,
                theme=resolve_app_theme(POETORE_THEME), app_mode=POETORE_MODE,
            )
            overlay.config_changed.connect(self._save_cheat_sheet_config)
            overlay.manage_requested.connect(self.open_cheat_sheet_manager)
            self._cheat_sheet_overlay = overlay
        return self._cheat_sheet_overlay

    def _save_cheat_sheet_config(self, cheat_sheet_config):
        self.config["cheat_sheets"] = dict(cheat_sheet_config)
        ConfigManager.save_config(self.config)

    def toggle_cheat_sheets(self):
        self._ensure_cheat_sheet_overlay().toggle()

    def open_cheat_sheet_manager(self):
        from src.ui.cheat_sheets import CheatSheetManagerDialog

        overlay = self._ensure_cheat_sheet_overlay()
        was_visible = overlay.isVisible()
        if was_visible:
            overlay.hide_and_save()
        dialog = CheatSheetManagerDialog(
            self.config.get("cheat_sheets", {}), self, theme=resolve_app_theme(POETORE_THEME)
        )
        if dialog.exec():
            self._save_cheat_sheet_config(dialog.result_config())
            overlay.reload(self.config["cheat_sheets"])
            if self.config["cheat_sheets"].get("images"):
                overlay.show()
                overlay.raise_()

    def execute_chat_command(self, command):
        """共通F5操作。PoEチャットへ貼り付けて送信する。"""
        send_chat_command(command)

    def closeEvent(self, event):
        self._update_check_timer.stop()
        for connection in self._update_connections:
            QObject.disconnect(connection)
        self._update_connections = ()
        self.tray_icon.hide()
        if self._hideout_notification is not None:
            self._hideout_notification.close()
        self.rate_panel.stop()
        self._rate_icon_cache.close(wait=False)
        self.hotkey_service.stop()
        self.stash_tab_scroll.stop()
        if self.suppressed_capture_hotkey is not None:
            self.suppressed_capture_hotkey.stop()
        if self.suppressed_expedition_hotkey is not None:
            self.suppressed_expedition_hotkey.stop()
        if self.suppressed_desecration_hotkey is not None:
            self.suppressed_desecration_hotkey.stop()
        self._shutdown_screen_reading()
        if self._ndlocr_pack_controller is not None:
            self._ndlocr_pack_controller.close()
            self._ndlocr_pack_controller = None
        if self._memo_dialog is not None:
            self._memo_dialog.close()
        if self._cheat_sheet_overlay is not None:
            self._cheat_sheet_overlay.hide_and_save()
            self._cheat_sheet_overlay.close()
        if self._map_check_window is not None:
            self._map_check_window.close()
            self._map_check_window.deleteLater()
            self._map_check_window = None
        if getattr(self, "_poetore_window", None) is not None:
            self._poetore_window.close()
            self._poetore_window.deleteLater()
            self._poetore_window = None
        super().closeEvent(event)
