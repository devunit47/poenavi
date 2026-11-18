"""Custom Currency Exchange rate rows for the ぽえとれ main window."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.ui.appearance import resolve_app_theme, theme_color, theme_font_size
from src.poetore.exchange_catalog import exchange_catalog_by_id
from src.poetore.exchange_icon_cache import ExchangeIconCache
from src.poetore.exchange_rate_cache import ExchangeRateValueCache
from src.poetore.exchange_rate_settings import ExchangeRatePairStore
from src.poetore.official_exchange import OfficialExchangeShadowService
from src.ui.app_theme import POETORE_THEME
from src.ui.dialog_theme import UI_METRICS, equalize_button_sizes
from src.ui.toolbar_icons import list_add_icon, trash_icon

RATE_CHECK_INTERVAL_MSEC = 10 * 60 * 1000
OFFICIAL_DATA_TOOLTIP = (
    "公式Currency Exchange APIは、完了した1時間ごとの取引データを提供する仕様です。"
    "ぽえとれは新しい時間データの公開を自動確認します。"
)


def format_display_rate(value: float) -> str:
    """Format readable rates without discarding meaningful sub-unit precision."""
    if not math.isfinite(value) or value <= 0:
        raise ValueError("rate must be finite and positive")
    decimal = Decimal(str(value))
    quantum = Decimal("0.1") if decimal >= 1 else Decimal(1).scaleb(
        decimal.adjusted() - 3
    )
    rounded = decimal.quantize(quantum, rounding=ROUND_HALF_UP)
    text = format(rounded, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    integer, separator, fraction = text.partition(".")
    grouped = f"{int(integer):,}"
    return grouped + (separator + fraction if separator else "")


class _PanelSignals(QObject):
    table_ready = Signal()
    checked = Signal(object)
    icon_ready = Signal(str, str, str)


class ElidedLabel(QLabel):
    """Keep the full accessible text while painting an elided single line."""

    def set_rate_column_width(self, column_width: int) -> None:
        self.setMinimumWidth(column_width)
        # Keep the compact default and give common six-character currency
        # names more space when the whole panel can fit at a larger font size.
        self._preferred_width = max(column_width, 6 * theme_font_size(13))
        self.setMaximumWidth(self._preferred_width)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        hint.setWidth(getattr(self, "_preferred_width", hint.width()))
        return hint

    def paintEvent(self, event):
        painter = QPainter(self)
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, self.width())
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(self.rect(), int(self.alignment()), text)
        painter.end()


class DecimalAlignedRateLabel(QLabel):
    """Center the equals sign and use the same decimal column across rows."""

    HORIZONTAL_MARGIN = 2

    def __init__(self, rate: str):
        super().__init__(f"1 ＝ {rate}")
        self._integer, separator, fraction = rate.partition(".")
        self._fraction = separator + fraction
        self._integer_width = self._fraction_width = 0

    def measured_columns(self) -> tuple[int, int]:
        self.ensurePolished()
        metrics = self.fontMetrics()
        return metrics.horizontalAdvance(self._integer), metrics.horizontalAdvance(self._fraction)

    def set_column_widths(self, integer: int, fraction: int) -> None:
        self._integer_width, self._fraction_width = integer, fraction
        compact_width = self.fontMetrics().horizontalAdvance("1 ＝ 999,999.000000") + 4
        self.setMinimumWidth(min(self.centered_width(), compact_width))

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        hint.setWidth(self.minimumWidth())
        return hint

    def _centered_width(self, quote_width: int) -> int:
        metrics = self.fontMetrics()
        half_width = max(metrics.horizontalAdvance("1"), quote_width) + (
            metrics.horizontalAdvance(" ") + self.HORIZONTAL_MARGIN
        )
        return 2 * half_width + metrics.horizontalAdvance("＝")

    def centered_width(self) -> int:
        return self._centered_width(self._integer_width + self._fraction_width)

    def _column_rects(self) -> tuple[QRect, QRect, QRect, QRect]:
        rect = self.contentsRect()
        metrics = self.fontMetrics()
        gap = metrics.horizontalAdvance(" ")
        top, height = rect.top(), rect.height()
        equals = QRect(0, top, metrics.horizontalAdvance("＝"), height)
        equals.moveCenter(rect.center())
        unit_width = metrics.horizontalAdvance("1")
        unit = QRect(equals.left() - gap - unit_width, top, unit_width, height)
        integer_left = equals.right() + 1 + gap
        available = max(0, rect.right() + 1 - integer_left - self.HORIZONTAL_MARGIN)
        integer_reserve = min(self._integer_width, metrics.horizontalAdvance("0…"))
        fraction_width = min(metrics.horizontalAdvance(self._fraction), max(0, available - integer_reserve))
        integer_width = min(self._integer_width, available - fraction_width)
        integer = QRect(integer_left, top, integer_width, height)
        fraction = QRect(integer.right() + 1, top, fraction_width, height)
        return unit, equals, integer, fraction

    def paintEvent(self, event) -> None:
        unit, equals, integer, fraction = self._column_rects()
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.setFont(self.font())
        vertical = Qt.AlignVCenter
        metrics = painter.fontMetrics()
        painter.drawText(unit, vertical | Qt.AlignRight, "1")
        painter.drawText(equals, vertical | Qt.AlignHCenter, "＝")
        painter.drawText(integer, vertical | Qt.AlignRight,
                         metrics.elidedText(self._integer, Qt.ElideRight, integer.width()))
        painter.drawText(fraction, vertical | Qt.AlignLeft,
                         metrics.elidedText(self._fraction, Qt.ElideRight, fraction.width()))
        painter.end()


class _RateDeleteButton(QPushButton):
    """Keep the button in the layout and tab order while its row is idle."""

    def __init__(self, row: QWidget):
        super().__init__(row)
        self.setFocusPolicy(Qt.TabFocus)
        row.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Enter, QEvent.Leave):
            self.update()
        return super().eventFilter(watched, event)

    def _revealed(self) -> bool:
        return self.parentWidget().underMouse() or self.hasFocus()

    def paintEvent(self, event) -> None:
        if self._revealed():
            super().paintEvent(event)

    def hitButton(self, position) -> bool:
        return self._revealed() and super().hitButton(position)


class CustomExchangeRatePanel(QWidget):
    def __init__(
        self,
        parent: QWidget | None,
        *,
        poe_version: str,
        store: ExchangeRatePairStore,
        league_getter: Callable[[], str],
        service: OfficialExchangeShadowService,
        value_cache: ExchangeRateValueCache,
        icon_cache: ExchangeIconCache,
        on_manage: Callable[[], None],
        on_rows_changed: Callable[[], None] | None = None,
        refresh_callback: Callable[..., None] | None = None,
    ):
        super().__init__(parent)
        self.poe_version = poe_version
        self.store = store
        self.league_getter = league_getter
        self.service = service
        self.value_cache = value_cache
        self.icon_cache = icon_cache
        self.on_manage = on_manage
        self.on_rows_changed = on_rows_changed or (lambda: None)
        self.refresh_callback = refresh_callback or self.refresh
        self.catalog = exchange_catalog_by_id(poe_version)
        self.row_widgets: list[QWidget] = []
        self._signals = _PanelSignals(self)
        self._signals.table_ready.connect(self._table_ready)
        self._signals.checked.connect(self._sync_checked)
        # A disk-cache hit can complete before the row has been attached to this
        # panel. Queue delivery so the label is discoverable when the icon is
        # applied, regardless of whether the Future completed synchronously.
        self._signals.icon_ready.connect(self._apply_icon, Qt.QueuedConnection)
        self._manual_check = False
        self._sync_in_progress = False
        self._build_ui()
        self.render_rows()
        self.check_timer = QTimer(self)
        self.check_timer.setInterval(RATE_CHECK_INTERVAL_MSEC)
        self.check_timer.timeout.connect(self.refresh_callback)
        self.check_timer.start()

    def _build_ui(self) -> None:
        theme = resolve_app_theme(POETORE_THEME)
        self.setStyleSheet(f"""
            QToolTip {{
                color: {theme.text};
                background-color: {theme.background};
                border: 1px solid {theme_color('border', '#66706C')};
                padding: 5px;
            }}
            QPushButton#customRateManageButton {{ padding: 0; }}
            QPushButton#customRateManageButton:focus {{ border-color: {theme.accent}; }}
            QPushButton[rateDelete="true"] {{ padding: 0; background: transparent; border: 1px solid transparent; }}
            QPushButton[rateDelete="true"]:hover, QPushButton[rateDelete="true"]:focus {{
                background: {theme_color('control', '#25332F')}; border-color: {theme.accent};
            }}
            QPushButton[rateDelete="true"]:pressed {{ background: {theme_color('accent_soft', '#276B5A')}; }}
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(UI_METRICS.control_gap)
        title_row = QHBoxLayout()
        self.title_label = QLabel("カレンシー交換レート")
        self.title_label.setStyleSheet(
            f"color: {resolve_app_theme(POETORE_THEME).accent}; font-size: {theme_font_size(15)}px; font-weight: bold;"
        )
        self.title_label.setToolTip(OFFICIAL_DATA_TOOLTIP)
        title_row.addWidget(self.title_label)
        title_row.addStretch()
        self.manage_button = QPushButton()
        self.manage_button.setObjectName("customRateManageButton")
        self.manage_button.setIcon(list_add_icon(theme.accent))
        self.manage_button.setIconSize(QSize(22, 22))
        self.manage_button.setFixedSize(UI_METRICS.toolbar_size, UI_METRICS.toolbar_size)
        self.manage_button.setAccessibleName("交換レートの表示を管理")
        self.manage_button.setToolTip("交換レートの表示を管理（追加・削除・並べ替え）")
        self.manage_button.clicked.connect(self.on_manage)
        title_row.addWidget(self.manage_button)
        root.addLayout(title_row)

        content = QWidget()
        content.setProperty("themeLayoutManaged", True)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(UI_METRICS.control_gap)
        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("poetoreRateScroll")
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setFocusPolicy(Qt.ClickFocus)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setWidget(content)
        content.setAutoFillBackground(False)
        root.addWidget(self.scroll_area, 1)

        self.card = QFrame()
        self.card.setObjectName("customExchangeRateCard")
        self.card.setStyleSheet(f"""
            QFrame#customExchangeRateCard {{
                background: {resolve_app_theme(POETORE_THEME).panel}; border: 1px solid {theme_color('border', '#343B3E')};
                border-radius: 10px;
            }}
        """)
        self.rows_layout = QVBoxLayout(self.card)
        self.rows_layout.setContentsMargins(UI_METRICS.overlay_margin, UI_METRICS.control_gap,
                                           UI_METRICS.overlay_margin, UI_METRICS.control_gap)
        self.rows_layout.setSpacing(UI_METRICS.inline_gap)
        content_layout.addWidget(self.card)

        footer = QHBoxLayout()
        self.status_label = QLabel("最新データを確認中…")
        self.status_label.setStyleSheet(f"color: {theme_color('muted_text', '#98A39F')}; font-size: {theme_font_size(11)}px;")
        self.status_label.setWordWrap(True)
        self.status_label.setToolTip(OFFICIAL_DATA_TOOLTIP)
        footer.addWidget(self.status_label, 1)
        self.refresh_button = QPushButton("最新データ確認")
        self.refresh_button.setStyleSheet(
            f"padding: {UI_METRICS.inline_gap}px {UI_METRICS.button_padding}px;"
        )
        self.refresh_button.setFocusPolicy(Qt.NoFocus)
        self.refresh_button.setToolTip(OFFICIAL_DATA_TOOLTIP)
        self.refresh_button.clicked.connect(
            lambda: self.refresh_callback(manual=True)
        )
        footer.addWidget(self.refresh_button)
        content_layout.addLayout(footer)
        equalize_button_sizes((self.refresh_button,), minimum_width=UI_METRICS.action_width)

    def render_rows(self) -> None:
        while self.rows_layout.count():
            child = self.rows_layout.takeAt(0)
            if child.widget() is not None:
                child.widget().hide()
                child.widget().deleteLater()
        self.row_widgets.clear()
        league = self.league_getter()
        pairs = self.store.pairs(self.poe_version)
        value_labels = []
        latest_cached_at = None
        for index, pair in enumerate(pairs):
            display_is_rate = False
            result = self.service.direct_pair(
                self.poe_version, league, pair.left_item_id, pair.right_item_id
            )
            if result.status == "available" and result.price is not None:
                display = format_display_rate(result.price)
                display_is_rate = True
                self.value_cache.put(
                    self.poe_version,
                    league,
                    pair.left_item_id,
                    pair.right_item_id,
                    result.price,
                    result.end_hour or 0,
                )
            elif result.status == "no_trades":
                display = "取引データなし"
            elif result.status == "unconfirmed":
                display = "価格未確定"
            else:
                cached = self.value_cache.get(
                    self.poe_version, league, pair.left_item_id, pair.right_item_id
                )
                if cached is not None:
                    display = format_display_rate(cached.price)
                    display_is_rate = True
                    latest_cached_at = max(latest_cached_at or 0, cached.confirmed_at)
                else:
                    display = (
                        "最新データ取得中…"
                        if self._sync_in_progress
                        else "最新データを取得できません"
                    )
            row, value = self._make_row(
                index,
                pair.left_item_id,
                pair.right_item_id,
                display,
                display_is_rate=display_is_rate,
            )
            self.rows_layout.addWidget(row)
            self.row_widgets.append(row)
            value_labels.append(value)

        rate_labels = [value for value in value_labels if isinstance(value, DecimalAlignedRateLabel)]
        if rate_labels:
            widths = [label.measured_columns() for label in rate_labels]
            integer_width = max(integer for integer, _ in widths)
            fraction_width = max(fraction for _, fraction in widths)
            for label in rate_labels:
                label.set_column_widths(integer_width, fraction_width)
        self._centering_space = 0
        if value_labels:
            # Give every row the same stretch budgets even when some values
            # are showing longer status messages instead of numbers.
            value_width = max(max(label.minimumWidth(), label.minimumSizeHint().width())
                              for label in value_labels)
            for label in value_labels:
                label.setMinimumWidth(value_width)
            if rate_labels:
                self._centering_space = max(0, rate_labels[0].centered_width() - value_width)
        self.card.setVisible(bool(pairs))

        state = self.service.sync_state(self.poe_version, league)
        if self._sync_in_progress:
            self.status_label.setText("最新データを確認中…")
        elif state.available:
            self.status_label.setText(
                f"{league} ・ 公式取引データ（1時間単位・自動取得）"
            )
        elif latest_cached_at is not None:
            age_hours = max(0, int((time.time() - latest_cached_at) // 3600))
            self.status_label.setText(f"最終確認 {age_hours}時間前")
        self.on_rows_changed()

    def preferred_card_width(self) -> int:
        return self.card.sizeHint().width() + self._centering_space

    def _make_row(
        self,
        index: int,
        left_id: str,
        right_id: str,
        display: str,
        *,
        display_is_rate: bool,
    ) -> tuple[QWidget, QLabel]:
        row = QWidget()
        row.setObjectName(f"customRateRow{index}")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(7)
        left_icon = self._icon_label(left_id, "left")
        layout.addWidget(left_icon)
        left_name = ElidedLabel(self.catalog[left_id].japanese_name)
        left_name.set_rate_column_width(125)
        left_name.setObjectName(f"customRateLeftName{index}")
        left_name.setToolTip(left_name.text())
        left_name.setAccessibleName(left_name.text())
        left_name.setStyleSheet(
            f"color: {resolve_app_theme(POETORE_THEME).accent}; font-size: {theme_font_size(13)}px;"
        )
        layout.addWidget(left_name, 1)
        value = DecimalAlignedRateLabel(display) if display_is_rate else QLabel(display)
        value.setObjectName(f"customRateValue{index}")
        value.setAlignment(Qt.AlignCenter)
        value.setToolTip(value.text())
        value_font_size = 15 if display_is_rate else 12
        value.setStyleSheet(
            f"color: {resolve_app_theme(POETORE_THEME).text}; font-size: {theme_font_size(value_font_size)}px; font-weight: bold;"
        )
        layout.addWidget(value, 1)
        right_icon = self._icon_label(right_id, "right")
        layout.addWidget(right_icon)
        right_name = ElidedLabel(self.catalog[right_id].japanese_name)
        right_name.set_rate_column_width(88)
        right_name.setObjectName(f"customRateRightName{index}")
        right_name.setToolTip(right_name.text())
        right_name.setAccessibleName(right_name.text())
        right_name.setStyleSheet(
            f"color: {resolve_app_theme(POETORE_THEME).accent}; font-size: {theme_font_size(13)}px;"
        )
        layout.addWidget(right_name, 1)
        delete = _RateDeleteButton(row)
        delete.setObjectName(f"customRateDelete{index}")
        delete.setProperty("rateDelete", True)
        delete.setIcon(trash_icon(resolve_app_theme(POETORE_THEME).text))
        delete.setIconSize(QSize(20, 20))
        delete.setFixedSize(32, 32)
        delete.setToolTip("このレートを削除")
        delete.setAccessibleName("このレートを削除")
        delete.clicked.connect(lambda _checked=False, i=index: self._remove(i))
        layout.addWidget(delete)
        return row, value

    def _icon_label(self, item_id: str, side: str) -> QLabel:
        label = QLabel()
        label.setObjectName(f"customRateIcon-{side}-{item_id}")
        label.setFixedSize(28, 28)
        label.setToolTip(self.catalog[item_id].japanese_name)
        item = self.catalog[item_id]
        future = self.icon_cache.request(
            item.icon_kind, item.icon_url, item.icon_filename,
        )

        def completed(result_future, selected=item_id, selected_side=side):
            try:
                result = result_future.result()
            except Exception:  # noqa: BLE001  # cache worker contains failures
                return
            self._signals.icon_ready.emit(selected, selected_side, str(result.path))

        future.add_done_callback(completed)
        return label

    def _apply_icon(self, item_id: str, side: str, path: str) -> None:
        icon = QIcon(path)
        pixmap = icon.pixmap(QSize(28, 28))
        for label in self.findChildren(QLabel, f"customRateIcon-{side}-{item_id}"):
            label.setPixmap(pixmap)

    def _remove(self, index: int) -> None:
        self.store.remove(self.poe_version, index)
        self.render_rows()

    def refresh(self, *, manual: bool = False) -> None:
        self._manual_check = self._manual_check or manual
        self._sync_in_progress = True
        self.status_label.setText("最新データを確認中…")
        self.refresh_button.setEnabled(False)
        self.render_rows()
        league = self.league_getter()
        self.service.queue_sync(
            self.poe_version,
            league,
            on_complete=lambda _result: self._signals.table_ready.emit(),
            on_checked=lambda result: self._signals.checked.emit(result),
        )

    def _table_ready(self) -> None:
        self.render_rows()

    def _sync_checked(self, result) -> None:
        self._sync_in_progress = False
        self.refresh_button.setEnabled(True)
        manual = self._manual_check
        self._manual_check = False
        self.render_rows()
        if result.status == "updated":
            self.status_label.setText("最新の公式データへ更新しました")
        elif result.status == "no_market_data":
            self.status_label.setText(
                "このリーグの取引データはまだありません（自動確認中）"
            )
        elif result.status == "no_new_data" and manual:
            self.status_label.setText("新しい公式データはまだありません")
        elif result.status == "failed":
            has_cached = any(
                self.value_cache.get(
                    self.poe_version,
                    self.league_getter(),
                    pair.left_item_id,
                    pair.right_item_id,
                ) is not None
                for pair in self.store.pairs(self.poe_version)
            )
            if not has_cached:
                self.status_label.setText("公式データを取得できませんでした")

    def available_item_ids(self) -> frozenset[str]:
        return self.service.exchange_item_ids(
            self.poe_version, self.league_getter()
        )

    def league_changed(self) -> None:
        self.render_rows()

    def stop(self) -> None:
        self.check_timer.stop()
