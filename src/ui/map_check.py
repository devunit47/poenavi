from __future__ import annotations

from functools import partial

from PySide6.QtCore import (
    QEvent, QPointF, QRect, QRegularExpression, QSignalBlocker, QSize, Qt, QTimer, Signal,
)
from PySide6.QtGui import QColor, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from src.app_mode import POENAVI_MODE
from src.ui.appearance import resolve_dialog_theme, suspend_theme_fixed_geometry, theme_font_size
from src.poetore.clipboard import clipboard_change_token, read_item_clipboard
from src.poetore.map_check import (
    DEFAULT_DECISIONS_BY_REF,
    MapModEntry,
    decision_for,
    entries_by_stat_id,
    is_map_check_item,
    load_map_mod_catalog,
    next_color_decision,
    normalized_map_check_config,
    set_decision,
)
from src.poetore.parser import ItemParseError, parse_item_text
from src.poetore.window_position import (
    capture_placement_context,
    position_for_context_at_cursor_y,
)
from src.ui.dialog_theme import (
    POETORE_DIALOG_THEME,
    UI_METRICS,
    apply_dialog_theme,
    dialog_theme_for_mode,
    equalize_button_sizes,
)
from src.ui.toolbar_button import ToolbarButton
from src.ui.toolbar_icons import (
    close_icon, finish_line_icon, line_icon_canvas, map_mod_manager_icon,
)
from src.utils.window_focus import (
    focus_window,
    get_foreground_window,
    is_path_of_exile_window,
)

_CHECK_TITLE = "Map Modチェック"
_PROFILE_HELP = "プロファイルごとに、ビルド別の判定を保存できます。"
_DECISIONS = {
    "d": ("危険", "danger"),
    "w": ("警告", "warning"),
    "g": ("有利", "success"),
    "-": ("未設定", "muted_text"),
}
_FONT_SIZES = {"small": 11, "medium": 13, "large": 16}
_SCOPE_LABELS = {
    "ubermap_exclusive": "Uber Map限定",
    "heist_exclusive": "Heist限定",
    "outdated": "更新確認が必要",
}


def _decision_icon(value, color):
    pixmap, painter = line_icon_canvas(color)
    if value == "g":
        painter.drawPolyline(QPolygonF([QPointF(5, 12), QPointF(10, 17), QPointF(19, 7)]))
    elif value == "-":
        painter.drawLine(QPointF(6, 12), QPointF(18, 12))
    else:
        if value == "d":
            painter.drawEllipse(QPointF(12, 12), 8, 8)
        else:
            painter.drawPolygon(QPolygonF([QPointF(12, 4), QPointF(21, 20), QPointF(3, 20)]))
        painter.drawLine(QPointF(12, 9), QPointF(12, 13))
        painter.drawPoint(QPointF(12, 16))
    return finish_line_icon(pixmap, painter)


def _decision_icons(theme):
    return {value: _decision_icon(value, getattr(theme, role))
            for value, (_, role) in _DECISIONS.items()}


def _profile_selector(parent, layout, on_select):
    profiles = QWidget(parent)
    profiles.setToolTip(_PROFILE_HELP)
    controls = QHBoxLayout(profiles)
    controls.setContentsMargins(0, 0, 0, 0)
    controls.setSpacing(UI_METRICS.inline_gap)
    controls.addWidget(QLabel("プロファイル"))
    group = QButtonGroup(profiles)
    for profile in (1, 2, 3):
        button = QPushButton(str(profile), profiles)
        button.setAccessibleName(f"プロファイル {profile}")
        button.setAutoDefault(False)
        button.setCheckable(True)
        button.setProperty("buttonRole", "profile")
        controls.addWidget(button)
        group.addButton(button, profile)
    group.idClicked.connect(on_select)
    layout.addWidget(profiles)
    parent.ensurePolished()
    equalize_button_sizes(
        group.buttons(), minimum_width=UI_METRICS.overlay_control_height,
        minimum_height=UI_METRICS.overlay_control_height,
    )
    return group


class MapModManagerDialog(QDialog):
    config_changed = Signal(dict)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = normalized_map_check_config(config)
        self.catalog = load_map_mod_catalog()
        self.setWindowTitle("Map Mod管理")
        self.resize(820, 680)
        self.setProperty("density", "compact")
        theme = resolve_dialog_theme(POETORE_DIALOG_THEME)
        apply_dialog_theme(self, theme)
        segment = 'QDialog[dialogTheme="poetore"] QTableWidget QPushButton[decisionSegment="true"]'
        badge = 'QDialog[dialogTheme="poetore"] QLabel[uiRole="mapModScope"]'
        selected_styles = []
        for value, (_, role) in _DECISIONS.items():
            ink = getattr(theme, role)
            color = QColor(ink)
            selected_styles.append(f"""
                {segment}[decision="{value}"]:checked {{
                    color: {theme.text if value == "-" else ink};
                    border-color: {ink};
                    background-color: rgba({color.red()}, {color.green()}, {color.blue()}, 48);
                }}
            """)
        self.setStyleSheet(self.styleSheet() + f"""
            QDialog[dialogTheme="poetore"] QTableWidget QHeaderView::section:last {{
                border-right: none;
            }}
            QWidget#mapModHeaderEnd {{
                background-color: {theme.surface};
                border-bottom: 1px solid {theme.border};
                border-top-right-radius: {theme.radius - 1}px;
            }}
            {badge} {{
                color: {theme.muted_text};
                background-color: {theme.control};
                border: 1px solid {theme.border_strong};
                border-radius: {theme.compact_radius}px;
                font-size: {theme.caption_size}px;
                padding: 0 {UI_METRICS.inline_gap}px;
            }}
            {segment} {{
                color: {theme.muted_text};
                border-color: {theme.border};
                border-radius: 0;
                padding: 0 {UI_METRICS.inline_gap}px;
            }}
            {segment}[segmentEdge="first"] {{
                border-top-left-radius: {theme.compact_radius}px;
                border-bottom-left-radius: {theme.compact_radius}px;
            }}
            {segment}[segmentEdge="last"] {{
                border-top-right-radius: {theme.compact_radius}px;
                border-bottom-right-radius: {theme.compact_radius}px;
            }}
            {segment}:!checked:hover {{
                color: {theme.text};
                background-color: {theme.surface};
                border-color: {theme.border_strong};
            }}
            {''.join(selected_styles)}
            {segment}[decision]:focus, {segment}[decision]:checked:focus {{
                border-color: {theme.accent};
            }}
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(*([UI_METRICS.page_margin] * 4))
        root.setSpacing(UI_METRICS.control_gap)
        header = QHBoxLayout()
        header.setSpacing(UI_METRICS.control_gap)
        icon = QLabel()
        icon.setPixmap(map_mod_manager_icon(theme.accent).pixmap(QSize(24, 24)))
        header.addWidget(icon)
        self.title_label = QLabel(self.windowTitle())
        self.title_label.setProperty("uiRole", "title")
        header.addWidget(self.title_label, 1)
        self._profiles = _profile_selector(self, header, self._select_profile)
        self.profile_buttons = self._profiles.buttons()
        self._profiles.button(self.config["profile"]).setChecked(True)
        root.addLayout(header)
        help_label = QLabel("ビルドごとに判定を保存できます。判定は選んだ時点で保存されます。")
        help_label.setProperty("uiRole", "muted")
        help_label.setWordWrap(True)
        root.addWidget(help_label)
        root.addSpacing(UI_METRICS.control_gap)

        controls = QHBoxLayout()
        controls.setSpacing(UI_METRICS.control_gap)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Map Modを検索…")
        self.search.setAccessibleName("Map Modを検索")
        controls.addWidget(self.search, 1)
        self.regex_search = QCheckBox("Regex")
        self.regex_search.setAccessibleName("正規表現で検索")
        self.regex_search.setToolTip("正規表現で検索します（例：反射|耐性）")
        controls.addWidget(self.regex_search)
        self.selected_only = QCheckBox("判定済みのみ表示")
        controls.addWidget(self.selected_only)
        self.count_label = QLabel()
        self.count_label.setProperty("uiRole", "muted")
        controls.addWidget(self.count_label)
        root.addLayout(controls)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Map Mod", "判定"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self._scrollbar_header = QWidget(self.table.verticalScrollBar())
        self._scrollbar_header.setObjectName("mapModHeaderEnd")
        self._scrollbar_header.setAttribute(Qt.WA_StyledBackground)
        self._scrollbar_header.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._scrollbar_header.setFixedWidth(theme.scrollbar_width)
        columns = self.table.horizontalHeader()
        columns.setSectionResizeMode(0, QHeaderView.Stretch)
        root.addWidget(self.table, 1)
        self._entries = self._catalog_entries()
        self._populate_table(theme)
        self.table.resizeColumnToContents(1)
        columns.setSectionResizeMode(1, QHeaderView.Fixed)
        # Qt insets index widgets using the item stylesheet's horizontal padding.
        columns.resizeSection(1, columns.sectionSize(1) + UI_METRICS.control_gap * 2)
        columns.sectionResized.connect(self._resize_mod_rows)
        columns.geometriesChanged.connect(self._align_table_scrollbar)
        self._resize_mod_rows(0, 0, columns.sectionSize(0))
        self._align_table_scrollbar()
        self.search.textChanged.connect(self._apply_filters)
        self.regex_search.toggled.connect(self._apply_filters)
        self.selected_only.toggled.connect(self._apply_filters)
        self._apply_filters()

        footer = QHBoxLayout()
        footer.setSpacing(UI_METRICS.control_gap)
        self.show_new = QCheckBox("チェック画面で確認状態を表示")
        self.show_new.setToolTip("Map Modチェックで未設定のModを「未確認」「確認済み」に切り替えられます。")
        self.show_new.setChecked(self.config["show_new_stats"])
        self.show_new.toggled.connect(self._set_show_new)
        footer.addWidget(self.show_new)
        footer.addStretch()
        self.close_button = QPushButton("閉じる")
        self.close_button.setProperty("buttonRole", "secondary")
        self.close_button.setAutoDefault(False)
        self.close_button.clicked.connect(self.accept)
        footer.addWidget(self.close_button)
        root.addLayout(footer)
        equalize_button_sizes([self.close_button], minimum_width=UI_METRICS.action_width)
        self.search.setFocus()

    def reload_config(self, config: dict):
        self.config = normalized_map_check_config(config)
        self._profiles.button(self.config["profile"]).setChecked(True)
        with QSignalBlocker(self.show_new):
            self.show_new.setChecked(self.config["show_new_stats"])
        self._refresh_decisions()
        with (
            QSignalBlocker(self.search),
            QSignalBlocker(self.regex_search),
            QSignalBlocker(self.selected_only),
        ):
            self.search.clear()
            self.regex_search.setChecked(False)
            self.selected_only.setChecked(False)
        self._apply_filters()
        self.table.scrollToTop()
        self.search.setFocus()

    def _set_show_new(self, checked):
        self.config["show_new_stats"] = bool(checked)
        self._save()

    def _select_profile(self, profile):
        if self.config["profile"] == profile:
            return
        self.config["profile"] = profile
        self._refresh_decisions()
        self._apply_filters()
        self._save()

    def _refresh_decisions(self):
        for entry, group in zip(self._entries, self._decisions):
            self._sync_decision(entry.key, group)

    def _catalog_entries(self):
        known_refs = {entry.ref for entry in self.catalog}
        outdated = [
            MapModEntry(f"legacy:{ref}", ref, ref, "outdated", ())
            for ref in DEFAULT_DECISIONS_BY_REF if ref not in known_refs
        ]
        scope_order = {"normal": 0, "ubermap_exclusive": 1, "heist_exclusive": 2}
        return sorted((*self.catalog, *outdated), key=lambda entry: scope_order.get(entry.scope, 3))

    def _populate_table(self, theme):
        self.table.setRowCount(len(self._entries))
        self._decisions = []
        icons = _decision_icons(theme)
        button_size = None
        for row, entry in enumerate(self._entries):
            description_cell = QWidget()
            # The table owns the height of this cell at the current column width.
            suspend_theme_fixed_geometry(description_cell, True)
            description_layout = QVBoxLayout(description_cell)
            gap = UI_METRICS.inline_gap
            description_layout.setContentsMargins(gap, gap, gap, gap)
            description_layout.setSpacing(gap)
            if tag := _SCOPE_LABELS.get(entry.scope):
                badge = QLabel(tag)
                badge.setProperty("uiRole", "mapModScope")
                badge.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
                description_layout.addWidget(badge, 0, Qt.AlignLeft)
            description = QLabel(entry.japanese)
            description.setObjectName("mapManagerModText")
            description.setTextFormat(Qt.PlainText)
            description.setWordWrap(True)
            description.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
            description_layout.addWidget(description)
            self.table.setCellWidget(row, 0, description_cell)
            description.ensurePolished()

            container = QWidget()
            segments = QHBoxLayout(container)
            segments.setContentsMargins(gap, gap // 2, gap, gap // 2)
            segments.setSpacing(0)
            group = QButtonGroup(container)
            for value, (label, _role) in _DECISIONS.items():
                button = QPushButton(label)
                button.setAutoDefault(False)
                button.setCheckable(True)
                button.setProperty("decisionSegment", True)
                button.setProperty("decision", value)
                button.setAccessibleName(f"{entry.japanese}：{label}")
                button.setIcon(icons[value])
                button.setIconSize(QSize(theme.icon_size, theme.icon_size))
                group.addButton(button)
                segments.addWidget(button)
            buttons = group.buttons()
            buttons[0].setProperty("segmentEdge", "first")
            buttons[-1].setProperty("segmentEdge", "last")
            buttons[-1].setToolTip("判定を未設定にし、確認状態を未確認に戻す")
            self.table.setCellWidget(row, 1, container)
            if button_size is None:
                equalize_button_sizes(buttons, minimum_height=UI_METRICS.overlay_control_height)
                button_size = buttons[0].minimumSize()
            for button in buttons:
                button.setFixedSize(button_size)
            segments.setAlignment(Qt.AlignCenter)
            self._sync_decision(entry.key, group)
            group.buttonClicked.connect(partial(self._choose, row))
            self._decisions.append(group)

    def _align_table_scrollbar(self):
        # Qt lays out the scrollbar alongside both the header and the rows.
        scrollbar = self.table.verticalScrollBar()
        header_height = self.table.horizontalHeader().height()
        self._scrollbar_header.setFixedHeight(header_height)
        style = f"QScrollBar:vertical {{ margin-top: {header_height}px; }}"
        if scrollbar.styleSheet() != style:
            scrollbar.setStyleSheet(style)

    def _resize_mod_rows(self, column, _old_width, width):
        if column != 0:
            return
        # The delegate insets cell widgets by the shared item padding and border.
        gap = UI_METRICS.inline_gap
        text_width = max(1, width - (UI_METRICS.control_gap + gap) * 2)
        for row in range(self.table.rowCount()):
            cell = self.table.cellWidget(row, 0)
            description = cell.findChild(QLabel, "mapManagerModText")
            bounds = description.fontMetrics().boundingRect(
                QRect(0, 0, text_width, 0), Qt.TextWordWrap, description.text(),
            )
            content_height = bounds.height() + gap * 2
            if cell.layout().count() > 1:
                content_height += cell.layout().itemAt(0).sizeHint().height() + gap
            segments = self.table.cellWidget(row, 1)
            self.table.setRowHeight(row, max(content_height, segments.sizeHint().height()) + 2)

    def _sync_decision(self, key, group):
        value = decision_for(self.config, key)
        if value == "s":
            value = "-"
        for button in group.buttons():
            if button.property("decision") == value:
                button.setChecked(True)
                break

    def _apply_filters(self):
        text = self.search.text()
        regex = None
        if text and self.regex_search.isChecked():
            regex = QRegularExpression(
                text,
                QRegularExpression.CaseInsensitiveOption | QRegularExpression.UseUnicodePropertiesOption,
            )
        invalid = regex is not None and not regex.isValid()
        if self.search.property("error") != invalid:
            self.search.setProperty("error", invalid)
            self.search.style().unpolish(self.search)
            self.search.style().polish(self.search)
            self.search.update()
        if invalid:
            self.count_label.setText("Regexの構文エラー")
            self.count_label.setToolTip(regex.errorString())
            return

        self.count_label.setToolTip("")
        query = text.strip().casefold()
        selected_only = self.selected_only.isChecked()
        scrollbar = self.table.verticalScrollBar()
        scroll_position = scrollbar.value()
        visible = 0
        for row, entry in enumerate(self._entries):
            fields = (entry.japanese, entry.ref, _SCOPE_LABELS.get(entry.scope, ""))
            if regex is None:
                matches_search = query in " ".join(fields).casefold()
            else:
                matches_search = any(regex.match(field).hasMatch() for field in fields if field)
            matched = matches_search and (
                not selected_only or decision_for(self.config, entry.key) in {"d", "w", "g"}
            )
            self.table.setRowHidden(row, not matched)
            visible += matched
        scrollbar.setValue(scroll_position)
        self.count_label.setText(
            f"表示 {visible}件 / 全{len(self._entries)}件" if visible else "該当するMap Modなし"
        )

    def _choose(self, row, button):
        key = self._entries[row].key
        value = button.property("decision")
        if value == decision_for(self.config, key):
            return
        set_decision(self.config, key, value)
        if self.selected_only.isChecked() and value == "-":
            self._apply_filters()
        self._save()

    def _save(self):
        self.config_changed.emit(dict(self.config))


class _ModButton(QPushButton):
    """A clickable Mod row with a fixed verdict slot and wrapping description."""

    def __init__(self, text, verdict_width, icon_size):
        super().__init__()
        self.setAutoDefault(False)
        self.setProperty("buttonRole", "mapMod")
        contents = QHBoxLayout(self)
        contents.setContentsMargins(
            UI_METRICS.control_gap, UI_METRICS.inline_gap,
            UI_METRICS.control_gap, UI_METRICS.inline_gap,
        )
        contents.setSpacing(UI_METRICS.control_gap)
        self.verdict_icon = QLabel()
        self.verdict_icon.setFixedSize(icon_size, icon_size)
        self.verdict_icon.setAttribute(Qt.WA_TransparentForMouseEvents)
        contents.addWidget(self.verdict_icon)
        self.verdict = QLabel()
        self.verdict.setObjectName("mapVerdict")
        self.verdict.setFixedWidth(verdict_width)
        self.verdict.setAttribute(Qt.WA_TransparentForMouseEvents)
        contents.addWidget(self.verdict)
        description = QLabel(text)
        description.setObjectName("mapModText")
        description.setTextFormat(Qt.PlainText)
        description.setWordWrap(True)
        description.setAttribute(Qt.WA_TransparentForMouseEvents)
        contents.addWidget(description, 1)
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def sizeHint(self):
        return super().sizeHint().expandedTo(self.layout().sizeHint())

    def minimumSizeHint(self):
        return self.layout().minimumSize()


class MapCheckWindow(QDialog):
    config_changed = Signal(dict)

    DEFAULT_WIDTH = 560
    DEFAULT_HEIGHT = 360
    MIN_HEIGHT = 180
    SCREEN_EDGE_MARGIN = 16

    def __init__(self, config: dict, parent=None, *, app_mode=POENAVI_MODE):
        super().__init__(parent)
        self.config = normalized_map_check_config(config)
        self._font_size_name = str(config.get("_font_size", "medium")).casefold()
        self._capture_generation = 0
        self._copy_started = False
        self._keyboard = None
        self._placement_context = None
        self._theme = dialog_theme_for_mode(app_mode)
        self._decision_icons = _decision_icons(self._theme)
        self.setWindowTitle(_CHECK_TITLE)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.resize(self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        self.setProperty("density", "compact")
        apply_dialog_theme(self, self._theme)
        self._base_stylesheet = self.styleSheet()
        self._apply_font_size()
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(*([UI_METRICS.overlay_margin] * 4))
        self.root.setSpacing(UI_METRICS.overlay_gap)
        self._header = QHBoxLayout()
        self._header.setSpacing(UI_METRICS.control_gap)
        self.title = QLabel(_CHECK_TITLE)
        self.title.setTextFormat(Qt.PlainText)
        self.title.setWordWrap(True)
        self.title.setProperty("uiRole", "section")
        self._header.addWidget(self.title, 1)
        self._profiles = _profile_selector(self, self._header, self._select_profile)
        self.profile_buttons = self._profiles.buttons()
        self.close_button = ToolbarButton()
        self.close_button.setAccessibleName("閉じる")
        self.close_button.setToolTip("閉じる（Esc）")
        self.close_button.setAutoDefault(False)
        icon_size = self._theme.icon_size
        self.close_button.setIcon(close_icon(self._theme.text))
        self.close_button.setIconSize(QSize(icon_size, icon_size))
        side = self.profile_buttons[0].height()
        self.close_button.setFixedSize(side, side)
        self.close_button.clicked.connect(self.close)
        self._header.addWidget(self.close_button)
        self.root.addLayout(self._header)
        self._hint = QLabel("クリックで判定を切替　未設定 → 危険 → 警告 → 有利")
        self._hint.setWordWrap(True)
        self._hint.setProperty("uiRole", "muted")
        self.root.addWidget(self._hint)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(UI_METRICS.inline_gap)
        self.scroll.setWidget(self.body)
        self.root.addWidget(self.scroll, 1)
        self._select_profile(self.config["profile"], save=False)

    def reload_config(self, config):
        self.config = normalized_map_check_config(config)
        self._font_size_name = str(config.get("_font_size", "medium")).casefold()
        self._apply_font_size()
        self._select_profile(self.config["profile"], save=False)

    def _apply_font_size(self):
        size = _FONT_SIZES.get(self._font_size_name, _FONT_SIZES["medium"])
        theme = self._theme
        root = f'QDialog[dialogTheme="{theme.name}"]'
        row = f'{root} QPushButton[buttonRole="mapMod"]'
        self.setStyleSheet(self._base_stylesheet + f"""
            {root} QLabel#mapModText, {root} QLabel#mapVerdict, {root} QLabel#mapUnknown,
            {root} QPushButton[buttonRole="mapSeen"] {{ font-size: {theme_font_size(size)}px; }}
            QLabel#mapVerdict {{ font-weight: 700; }}
            {row} {{ padding: 0; }}
        """ + "".join(
            f'{row}[decision="{value}"] QLabel#mapVerdict {{ color: {getattr(theme, role)}; }}'
            for value, (_label, role) in _DECISIONS.items()
        ))

    def capture_from_poe(self):
        from pynput.keyboard import Controller, Key
        self._placement_context = capture_placement_context()
        foreground = get_foreground_window()
        self._poe_window_hwnd = (
            foreground if is_path_of_exile_window(foreground) else None
        )
        self._keyboard = Controller()
        self._capture_generation += 1
        generation = self._capture_generation
        self._copy_started = False
        self._copy_keys = (Key.ctrl, "c")
        QTimer.singleShot(250, lambda: self._start_copy(generation))

    def capture_hotkey_released(self):
        self._start_copy(self._capture_generation)

    def _start_copy(self, generation):
        from src.utils.internal_key_input import internal_key_input

        if generation != self._capture_generation or self._copy_started:
            return
        self._copy_started = True
        before = clipboard_change_token(QApplication.clipboard())
        with internal_key_input():
            for key in self._copy_keys:
                self._keyboard.press(key)
            for key in reversed(self._copy_keys):
                self._keyboard.release(key)
        self._wait_clipboard(before, generation, 0)

    def _wait_clipboard(self, before, generation, elapsed):
        if generation != self._capture_generation:
            return
        if clipboard_change_token(QApplication.clipboard()) != before or elapsed >= 300:
            self._consume_clipboard()
            return
        QTimer.singleShot(10, lambda: self._wait_clipboard(before, generation, elapsed + 10))

    def _consume_clipboard(self):
        try:
            item = parse_item_text(read_item_clipboard(QApplication.clipboard()))
        except ItemParseError:
            QMessageBox.warning(self.parentWidget(), _CHECK_TITLE, "アイテムを取得できませんでした。")
            return
        if not is_map_check_item(item):
            QMessageBox.information(self.parentWidget(), _CHECK_TITLE, "Map系アイテムではありません。")
            return
        self._item = item
        self._render(item)
        context = self._placement_context or capture_placement_context()
        self._resize_to_content(context)
        self.move(position_for_context_at_cursor_y(context, self.size()))
        self.show()
        self.raise_()
        self.activateWindow()

    def _clear_body(self):
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

    def _render(self, item):
        self.title.setText(item.name or item.base_type or _CHECK_TITLE)
        self._clear_body()
        lookup = entries_by_stat_id()
        verdict_probe = QLabel("未設定", self.body)
        verdict_probe.hide()
        verdict_probe.setObjectName("mapVerdict")
        verdict_probe.ensurePolished()
        verdict_width = verdict_probe.sizeHint().width()
        verdict_probe.deleteLater()
        # Parser上のDesecratedはNightmare MapのExplicit affixに相当する。
        explicit_modifiers = tuple(
            modifier for modifier in item.modifiers
            if modifier.kind in {"prefix", "suffix", "explicit", "desecrated"}
        )
        seen_buttons = []
        for modifier in explicit_modifiers:
            entry = lookup.get(modifier.stat_id or "")
            if entry is None:
                row = QLabel(f"未認識のMod：{modifier.text}")
                row.setTextFormat(Qt.PlainText)
                row.setWordWrap(True)
                row.setObjectName("mapUnknown")
                row.setProperty("state", "warning")
                row.setContentsMargins(*([UI_METRICS.control_gap] * 4))
                self.body_layout.addWidget(row)
                continue
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(UI_METRICS.inline_gap)
            button = _ModButton(modifier.text, verdict_width, self._theme.icon_size)
            button.setProperty("map_mod_key", entry.key)
            button.setProperty("map_mod_text", modifier.text)
            button.clicked.connect(partial(self._cycle_entry, entry.key))
            row_layout.addWidget(button, 1)
            if self.config.get("show_new_stats"):
                seen = QPushButton()
                seen.setAutoDefault(False)
                seen.setProperty("buttonRole", "mapSeen")
                seen.setProperty("map_seen_key", entry.key)
                seen.clicked.connect(partial(self._toggle_seen, entry.key))
                row_layout.addWidget(seen, 0, Qt.AlignVCenter)
                self._style_seen_button(seen, entry.key)
                seen_buttons.append(seen)
            self.body_layout.addWidget(row_widget)
            self._style_mod_button(button, entry.key, modifier.text)
        if not explicit_modifiers:
            self.body_layout.addWidget(QLabel("判定対象のMap Modがありません。"))
        if seen_buttons:
            # Build for the longest label, including when every current row is unconfirmed.
            first = seen_buttons[0]
            original = first.text()
            first.setText("確認済み")
            equalize_button_sizes(seen_buttons, minimum_height=UI_METRICS.overlay_control_height)
            first.setText(original)
        self.body_layout.addStretch()

    def _resize_to_content(self, context):
        """Grow to show all rows, retaining scrolling only at the screen limit."""
        self.body_layout.activate()
        root_margins = self.root.contentsMargins()
        inner_width = self.DEFAULT_WIDTH - root_margins.left() - root_margins.right()
        frame = self.scroll.frameWidth() * 2
        chrome_height = (
            root_margins.top()
            + root_margins.bottom()
            + max(self._header.sizeHint().height(), self._header.heightForWidth(inner_width))
            + self._hint.heightForWidth(inner_width)
            + 2 * self.root.spacing()
            + frame
        )
        body_height = max(self.body_layout.minimumSize().height(),
                          self.body_layout.heightForWidth(inner_width - frame))
        desired_height = max(self.MIN_HEIGHT, chrome_height + body_height)
        available_height = max(
            self.MIN_HEIGHT,
            context.target_rect.height() - self.SCREEN_EDGE_MARGIN * 2,
        )
        self.resize(self.DEFAULT_WIDTH, min(desired_height, available_height))

    def _style_mod_button(self, button, key, text):
        decision = decision_for(self.config, key)
        value = "-" if decision == "s" else decision
        label, _ = _DECISIONS[value]
        button.verdict_icon.setPixmap(self._decision_icons[value].pixmap(button.verdict_icon.size()))
        button.verdict.setText(label)
        button.setAccessibleName(f"{text}：{label}")
        button.setProperty("decision", value)
        button.verdict.style().unpolish(button.verdict)
        button.verdict.style().polish(button.verdict)

    def _cycle_entry(self, key, _checked=False):
        set_decision(self.config, key, next_color_decision(decision_for(self.config, key)))
        self.config_changed.emit(dict(self.config))
        for button in self.body.findChildren(QPushButton):
            if button.property("map_mod_key") == key:
                self._style_mod_button(button, key, button.property("map_mod_text"))
        self._refresh_seen_buttons(key)

    def _toggle_seen(self, key, _checked=False):
        if not self.config.get("show_new_stats"):
            return
        current = decision_for(self.config, key)
        if current not in {"-", "s"}:
            return
        set_decision(self.config, key, "s" if current == "-" else "-")
        self.config_changed.emit(dict(self.config))
        self._refresh_seen_buttons(key)

    def _refresh_seen_buttons(self, key):
        for button in self.body.findChildren(QPushButton):
            if button.property("map_seen_key") == key:
                self._style_seen_button(button, key)

    def _style_seen_button(self, button, key):
        decision = decision_for(self.config, key)
        if decision == "-":
            button.setText("未確認")
            button.setToolTip("クリックして、このModを確認済みにします")
            button.setEnabled(True)
        elif decision == "s":
            button.setText("確認済み")
            button.setToolTip("クリックして、未確認の状態に戻します")
            button.setEnabled(True)
        else:
            button.setText("判定済み")
            button.setToolTip("")
            button.setEnabled(False)

    def _select_profile(self, profile, save=True):
        if save and self.config["profile"] == profile:
            return
        self.config["profile"] = profile
        self._profiles.button(profile).setChecked(True)
        if save:
            self.config_changed.emit(dict(self.config))
        if hasattr(self, "_item"):
            self._render(self._item)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            target = getattr(self, "_poe_window_hwnd", None)
            self.close()
            if target is not None:
                QTimer.singleShot(0, lambda: focus_window(target))
            return
        super().keyPressEvent(event)

    def event(self, event):
        if event.type() == QEvent.WindowDeactivate and self.isVisible():
            QTimer.singleShot(0, self.close)
        return super().event(event)
