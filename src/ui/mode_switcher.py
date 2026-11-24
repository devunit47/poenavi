"""Shared title-bar and tray controls for switching application targets."""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QWidget

from src.app_mode import POENAVI_MODE, POETORE_MODE
from src.ui.app_theme import theme_for_mode
from src.ui.appearance import theme_color, theme_font_size, theme_rgba
from src.ui.toolbar_icons import poenavi_mode_icon, poetore_mode_icon
from src.utils.feature_support import POETORE, is_feature_supported
from src.utils.poe_version_data import POE1, POE2, get_poe_label
from src.version import FORK_LABEL, IS_FORK


MODE_OPTIONS = (
    (POENAVI_MODE, "ぽえなび", poenavi_mode_icon),
    (POETORE_MODE, "ぽえとれ", poetore_mode_icon),
)
_VERSIONS = (POE1, POE2)


def _unavailable_reason(mode, version):
    if mode == POETORE_MODE and not is_feature_supported(POETORE, version):
        return f"ぽえとれは{get_poe_label(version)}に対応していません"
    return ""


def _style_menu(menu, mode):
    theme = theme_for_mode(mode)
    menu.setToolTipsVisible(True)
    menu.setStyleSheet(f"""
        QMenu {{
            background-color: {theme.background}; color: {theme.text};
            border: 1px solid {theme_color('border', '#59655D')};
            border-radius: 8px; padding: 5px;
            font-size: {theme_font_size(13)}px;
        }}
        QMenu::item {{ padding: 7px 26px 7px 14px; border-radius: 6px; }}
        QMenu::separator {{
            height: 1px; margin: 4px 8px;
            background-color: {theme_color('border', '#59655D')};
        }}
        QMenu::item:selected {{ background-color: {theme.panel}; }}
        QMenu::item:disabled {{ color: {theme_color('disabled', '#869187')}; }}
    """)


def _populate_target_menu(menu, current_mode, current_version, options, on_switch):
    _style_menu(menu, current_mode)
    group = QActionGroup(menu)
    targets = {}
    for option in options:
        if option is None:
            menu.addSeparator()
            continue
        mode, version, label, icon = option
        selected = (mode, version) == (current_mode, current_version)
        if icon is not None:
            # Qtのメニューではアイコンとチェックが左側の同じ領域を使う。
            action = menu.addAction(icon, f"{label}\t✓" if selected else label)
        else:
            action = menu.addAction(label)
        action.setCheckable(True)
        unavailable = _unavailable_reason(mode, version)
        action.setEnabled(not unavailable)
        action.setToolTip(unavailable or label)
        group.addAction(action)
        targets[action] = (mode, version)
        if selected:
            action.setChecked(True)
    current = group.checkedAction()

    def handle_selection(action):
        if action != current:
            if current is not None:
                current.setChecked(True)
            on_switch(*targets[action])

    group.triggered.connect(handle_selection)


def add_mode_switch_menu(menu, mode, version, on_switch):
    """Add the same four targets used by the compact title bar to a tray menu."""
    submenu = QMenu("モード・PoE版を切り替え", menu)
    menu.addMenu(submenu)
    _populate_mode_switch_menu(submenu, mode, version, on_switch)
    return submenu


def _populate_mode_switch_menu(menu, mode, version, on_switch):
    color = theme_for_mode(mode).text
    options = [
        (target_mode, target_version, f"{get_poe_label(target_version)} · {label}", icon(color))
        for target_version in _VERSIONS
        for target_mode, label, icon in MODE_OPTIONS
    ]
    options.insert(len(MODE_OPTIONS), None)
    _populate_target_menu(menu, mode, version, options, on_switch)


class ModeSwitcherWidget(QWidget):
    """Select a mode directly, or choose a version and mode from a compact menu."""

    switch_requested = Signal(str, str)
    COMPACT_THRESHOLD = 440

    def __init__(self, mode, poe_version, parent=None):
        super().__init__(parent)
        theme = theme_for_mode(mode)
        font_size = theme_font_size(13)
        badge_font_size = theme_font_size(11)
        icon_size = max(16, theme_font_size(17))
        surface = theme_color('surface', '#171B1D')
        accent_soft = theme_color('accent_soft', '#22321D')
        soft_highlight = theme_rgba('text', 230, 236, 234, 0.08)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent; color: {theme.muted_text};
                border: none; border-radius: 6px;
                padding: 4px 11px; font-size: {font_size}px; font-weight: normal;
            }}
            QPushButton:hover, QPushButton:pressed, QPushButton:focus {{
                background-color: {soft_highlight}; color: {theme.text};
            }}
            QPushButton[currentMode="true"] {{
                background-color: {accent_soft}; color: {theme.accent}; font-weight: bold;
            }}
            QPushButton[hasTargetMenu="true"] {{
                background-color: {surface}; color: {theme.text}; border-radius: 8px;
                padding: 4px 28px 4px 14px;
            }}
            QPushButton::menu-indicator {{
                subcontrol-origin: border; subcontrol-position: right center; right: 10px;
            }}
            QPushButton[currentMode="true"][hasTargetMenu="true"] {{
                background-color: {accent_soft}; color: {theme.accent};
                padding: 4px 28px 4px 12px;
            }}
            QPushButton[hasTargetMenu="true"]:hover,
            QPushButton[hasTargetMenu="true"]:pressed,
            QPushButton[hasTargetMenu="true"]:focus {{
                background-color: {accent_soft}; color: {theme.accent};
            }}
            QPushButton[currentMode="true"][hasTargetMenu="true"]:hover,
            QPushButton[currentMode="true"][hasTargetMenu="true"]:pressed {{
                background-color: {theme.panel};
            }}
            QPushButton:focus {{ text-decoration: underline; }}
            QPushButton:disabled {{ color: {theme_color('disabled', '#869187')}; }}
            QWidget#modeSegments {{
                background-color: {surface}; border: none; border-radius: 8px;
            }}
            QLabel#forkBadge {{
                color: {theme.muted_text}; background-color: {soft_highlight};
                border: none; border-radius: {(badge_font_size + 9) // 2}px; padding: 2px 9px;
                font-size: {badge_font_size}px;
            }}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.expanded = QWidget(self)
        expanded_layout = QHBoxLayout(self.expanded)
        expanded_layout.setContentsMargins(0, 0, 0, 0)
        expanded_layout.setSpacing(10)
        segments = QWidget(self.expanded)
        segments.setObjectName("modeSegments")
        segment_layout = QHBoxLayout(segments)
        segment_layout.setContentsMargins(3, 2, 3, 2)
        segment_layout.setSpacing(2)
        self.mode_buttons = {}
        for target, label, make_icon in MODE_OPTIONS:
            selected = target == mode
            button = QPushButton(make_icon(theme.accent if selected else theme.muted_text), label)
            button.setProperty("currentMode", selected)
            if selected:
                button.setCheckable(True)
                button.setChecked(True)
                button.setAutoExclusive(True)
            button.setIconSize(QSize(icon_size, icon_size))
            button.setCursor(Qt.PointingHandCursor)
            unavailable = _unavailable_reason(target, poe_version)
            button.setEnabled(not unavailable)
            button.setToolTip(unavailable or ("現在のモード" if selected else f"{label}へ切り替え"))
            if not selected:
                button.clicked.connect(
                    lambda checked=False, target=target: self.switch_requested.emit(target, poe_version)
                )
            segment_layout.addWidget(button)
            self.mode_buttons[target] = button
        expanded_layout.addWidget(segments)

        self.version_button = QPushButton(get_poe_label(poe_version))
        self.version_button.setProperty("hasTargetMenu", True)
        version_menu = QMenu(self.version_button)
        _populate_target_menu(
            version_menu, mode, poe_version,
            [(mode, version, get_poe_label(version), None) for version in _VERSIONS],
            self.switch_requested.emit,
        )
        self.version_button.setMenu(version_menu)
        self.version_button.setToolTip("PoE版を切り替え")
        self.version_button.setCursor(Qt.PointingHandCursor)
        expanded_layout.addWidget(self.version_button)
        layout.addWidget(self.expanded)

        _, label, make_icon = next(option for option in MODE_OPTIONS if option[0] == mode)
        self.compact_button = QPushButton(
            make_icon(theme.accent), f"{label} · {get_poe_label(poe_version)}"
        )
        self.compact_button.setProperty("currentMode", True)
        self.compact_button.setProperty("hasTargetMenu", True)
        self.compact_button.setIconSize(QSize(icon_size, icon_size))
        self.compact_button.setToolTip("モード・PoE版を切り替え")
        self.compact_button.setCursor(Qt.PointingHandCursor)
        compact_menu = QMenu(self.compact_button)
        _populate_mode_switch_menu(compact_menu, mode, poe_version, self.switch_requested.emit)
        self.compact_button.setMenu(compact_menu)
        layout.addWidget(self.compact_button)
        self.fork_badge = QLabel(FORK_LABEL, self)
        self.fork_badge.setObjectName("forkBadge")
        self.fork_badge.setToolTip("非公式Fork版")
        self.fork_badge.setVisible(IS_FORK)
        layout.addWidget(self.fork_badge, 0, Qt.AlignVCenter)
        self.set_available_width(0, 0)

    def _badge_width(self):
        if self.fork_badge.isHidden():
            return 0
        return self.fork_badge.sizeHint().width() + self.layout().spacing()

    def minimumSizeHint(self):
        size = self.compact_button.sizeHint()
        size.setWidth(size.width() + self._badge_width())
        # 幅に応じて表示が切り替わってもタイトルバーの高さを保つ。
        size.setHeight(max(size.height(), self.expanded.sizeHint().height()))
        return size

    def set_available_width(self, window_width, available_width):
        compact = (
            window_width < self.COMPACT_THRESHOLD
            or available_width < self.expanded.sizeHint().width() + self._badge_width()
        )
        self.expanded.setVisible(not compact)
        self.compact_button.setVisible(compact)
