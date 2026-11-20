"""Custom Currency Exchange rate rows for the ぽえとれ main window."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from src.ui.appearance import resolve_app_theme, theme_color, theme_font_size
from src.poetore.exchange_catalog import exchange_catalog_by_id
from src.poetore.exchange_icon_cache import ExchangeIconCache
from src.poetore.exchange_rate_cache import ExchangeRateValueCache
from src.poetore.exchange_rate_settings import ExchangeRatePairStore
from src.poetore.official_exchange import OfficialExchangeShadowService, SyncCheckResult
from src.ui.app_theme import POETORE_THEME
from src.ui.dialog_theme import UI_METRICS
from src.ui.toolbar_button import ToolbarButton
from src.ui.toolbar_icons import list_add_icon, reload_icon, trash_icon

RATE_CHECK_INTERVAL_MSEC = 10 * 60 * 1000
_JST = timezone(timedelta(hours=9))
_OFFICIAL_DATA_HELP = (
    "公式サイトの取引データを自動で取り込みます。\n"
    "データは1時間分ずつ、集計後に公開されます。"
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
    checked = Signal(object, object)
    icon_ready = Signal(str, str, str)


class ElidedLabel(QLabel):
    """Keep the full accessible text while painting an elided single line."""

    def set_rate_column_width(self, column_width: int) -> None:
        # Let the scroll area's actual viewport width drive the elision.
        self.setMinimumWidth(theme_font_size(13))
        # Keep the compact default and give common six-character currency
        # names more space when the whole panel can fit at a larger font size.
        self._preferred_width = max(column_width, 6 * theme_font_size(13))
        self.setMaximumWidth(self._preferred_width)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        hint.setWidth(getattr(self, "_preferred_width", hint.width()))
        return hint

    def _display_text(self, width: int) -> str:
        return self.fontMetrics().elidedText(self.text(), Qt.ElideRight, width)

    def _text_rect(self) -> QRect:
        return self.contentsRect()

    def event(self, event):
        if event.type() == QEvent.ToolTip:
            if self._display_text(self._text_rect().width()) != self.text():
                QToolTip.showText(event.globalPos(), self.text(), self, self.rect())
            else:
                QToolTip.hideText()
                event.ignore()
            return True
        return super().event(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self._text_rect()
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.drawText(rect, int(self.alignment()), self._display_text(rect.width()))
        painter.end()


class RateValueLabel(ElidedLabel):
    """Elide a rate at decimal digits or thousands separators."""

    def __init__(self, rate: str):
        super().__init__(f"1 ＝ {rate}")
        self._shared_text_width: int | None = None
        self.setAlignment(Qt.AlignCenter)
        self.setProperty("elideText", True)

    def set_shared_text_width(self, width: int) -> None:
        self._shared_text_width = width
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter | Qt.AlignAbsolute)
        self.update()

    def _text_rect(self) -> QRect:
        rect = self.contentsRect()
        if self._shared_text_width is not None and self._shared_text_width < rect.width():
            left_margin = (rect.width() - self._shared_text_width) // 2
            rect.translate(left_margin, 0)
            rect.setWidth(self._shared_text_width)
        return rect

    def compact_width(self) -> int:
        self.ensurePolished()
        metrics = self.fontMetrics()
        return min(
            metrics.size(Qt.TextSingleLine, self.text()).width(),
            metrics.size(Qt.TextSingleLine, "1 ＝ 999,999.000000").width(),
        )

    def _display_text(self, width: int) -> str:
        metrics = self.fontMetrics()

        def fits(text: str) -> bool:
            return metrics.size(Qt.TextSingleLine, text).width() <= width

        text = self.text()
        if fits(text):
            return text

        integer, separator, fraction = text.partition(".")
        if separator:
            # Keep as many fractional digits as fit alongside the ellipsis.
            shortened = integer + "…"
            for end in range(1, len(fraction)):
                candidate = integer + separator + fraction[:end] + "…"
                if not fits(candidate):
                    break
                shortened = candidate
            if fits(shortened):
                return shortened

        while "," in integer:
            integer = integer.rsplit(",", 1)[0]
            if fits(integer + ",…"):
                return integer + ",…"
        return "1 ＝ …" if fits("1 ＝ …") else "…"


class _RateDeleteButton(ToolbarButton):
    """Keep the button in the layout and tab order while its row is idle."""

    def __init__(self, row: QWidget):
        super().__init__(parent=row)
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
        actions_layout: QHBoxLayout | None = None,
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
        self._signals.checked.connect(self._sync_checked)
        # A disk-cache hit can complete before the row has been attached to this
        # panel. Queue delivery so the label is discoverable when the icon is
        # applied, regardless of whether the Future completed synchronously.
        self._signals.icon_ready.connect(self._apply_icon, Qt.QueuedConnection)
        self._manual_check = False
        self._active_check: object | None = None
        self._last_check: SyncCheckResult | None = None
        self._build_ui(actions_layout)
        self.render_rows()
        self.check_timer = QTimer(self)
        self.check_timer.setInterval(RATE_CHECK_INTERVAL_MSEC)
        self.check_timer.timeout.connect(self.refresh_callback)
        self.check_timer.start()

    def _build_ui(self, actions_layout: QHBoxLayout | None) -> None:
        theme = resolve_app_theme(POETORE_THEME)
        tooltip_style = f"""
            QToolTip {{
                color: {theme.text};
                background-color: {theme.background};
                border: 1px solid {theme_color('border', '#66706C')};
                padding: 5px;
            }}
        """
        self.setStyleSheet(tooltip_style)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        if actions_layout is None:
            root.setSpacing(UI_METRICS.control_gap)
            actions_layout = QHBoxLayout()
            actions_layout.setSpacing(UI_METRICS.inline_gap)
            actions_layout.addStretch()
            root.addLayout(actions_layout)
        self.manage_button = ToolbarButton()
        self.manage_button.setObjectName("customRateManageButton")
        self.manage_button.setIcon(list_add_icon(theme.muted_text))
        self.manage_button.setIconSize(QSize(22, 22))
        self.manage_button.setFixedSize(UI_METRICS.toolbar_size, UI_METRICS.toolbar_size)
        self.manage_button.setAccessibleName("交換レートの表示を管理")
        self.manage_button.setToolTip("交換レートの表示を管理（追加・削除・並べ替え）")
        self.manage_button.clicked.connect(self.on_manage)

        self.refresh_button = ToolbarButton()
        self.refresh_button.setIcon(reload_icon(theme.muted_text))
        self.refresh_button.setIconSize(QSize(24, 24))
        self.refresh_button.setFixedSize(UI_METRICS.toolbar_size, UI_METRICS.toolbar_size)
        self.refresh_button.setAccessibleName("公式取引データを再取得")
        self.refresh_button.clicked.connect(
            lambda: self.refresh_callback(manual=True)
        )
        for button in (self.manage_button, self.refresh_button):
            actions_layout.addWidget(button)

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
        QWidget.setTabOrder(self.manage_button, self.refresh_button)
        previous_button = self.refresh_button
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
                        if self._active_check is not None
                        else "最新データを取得できません"
                    )
            row, value, delete = self._make_row(
                index,
                pair.left_item_id,
                pair.right_item_id,
                display,
                display_is_rate=display_is_rate,
            )
            self.rows_layout.addWidget(row)
            QWidget.setTabOrder(previous_button, delete)
            previous_button = delete
            self.row_widgets.append(row)
            value_labels.append(value)

        if value_labels:
            # With the same minimum and stretch, every row allocates the
            # same width to the value column, including rows with status text.
            value_width = max(
                label.compact_width() if isinstance(label, RateValueLabel) else theme_font_size(12)
                for label in value_labels
            )
            for label in value_labels:
                label.setMinimumWidth(value_width)
        rates = [label for label in value_labels if isinstance(label, RateValueLabel)]
        if len(rates) > 1:
            # Draw all numeric rows from the same start so their "1 ＝" prefixes align.
            width = max(rate.sizeHint().width() for rate in rates)
            for rate in rates:
                rate.set_shared_text_width(width)
        self.card.setVisible(bool(pairs))

        self._render_refresh_status(league, latest_cached_at)
        self.on_rows_changed()

    def _render_refresh_status(self, league: str, latest_cached_at: int | None) -> None:
        if self._active_check is not None:
            self._set_refresh_tooltip(league, "更新を確認中…")
            return

        messages = []
        if self._last_check is not None and self._last_check.league == league:
            match self._last_check.status:
                case "no_market_data":
                    messages.append("このリーグにはまだ取引データがありません。")
                case "no_new_data":
                    messages.append("新しいデータはまだ公開されていません。")
                case "failed":
                    messages.extend((
                        "取引データを取得できませんでした。",
                        "しばらくしてから再度お試しください。",
                    ))

        state = self.service.sync_state(self.poe_version, league)
        if state.available and state.end_hour is not None:
            hour = datetime.fromtimestamp(state.end_hour, _JST)
            messages.append(
                f"取得済みデータは{hour.month}月{hour.day}日 {hour.hour}時台まで（日本時間）"
            )
        if latest_cached_at is not None:
            age_hours = max(0, int((time.time() - latest_cached_at) // 3600))
            age = f"{age_hours}時間前" if age_hours else "1時間以内"
            messages.extend((
                "保存済みのレートを表示しています。",
                f"最後に保存したレートは{age}に確認しました。",
            ))
        self._set_refresh_tooltip(
            league, "\n".join(messages) or "取引データはまだ取得していません。"
        )

    def _set_refresh_tooltip(self, league: str, message: str) -> None:
        description = f"リーグ　{league}\n{message}"
        action = (
            "交換レートの更新"
            if self._active_check is not None
            else "クリックで交換レートを今すぐ更新"
        )
        tooltip = f"{action}\n\n{description}\n\n{_OFFICIAL_DATA_HELP}"
        button = self.refresh_button
        button.setToolTip(tooltip)
        button.setAccessibleDescription(description)

    def _make_row(
        self,
        index: int,
        left_id: str,
        right_id: str,
        display: str,
        *,
        display_is_rate: bool,
    ) -> tuple[QWidget, QLabel, _RateDeleteButton]:
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
        left_name.setAccessibleName(left_name.text())
        left_name.setStyleSheet(
            f"color: {resolve_app_theme(POETORE_THEME).accent}; font-size: {theme_font_size(13)}px;"
        )
        layout.addWidget(left_name, 1)
        value = RateValueLabel(display) if display_is_rate else ElidedLabel(display)
        value.setObjectName(f"customRateValue{index}")
        value.setAlignment(Qt.AlignCenter)
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
        right_name.setAccessibleName(right_name.text())
        right_name.setStyleSheet(
            f"color: {resolve_app_theme(POETORE_THEME).accent}; font-size: {theme_font_size(13)}px;"
        )
        layout.addWidget(right_name, 1)
        delete = _RateDeleteButton(row)
        delete.setObjectName(f"customRateDelete{index}")
        delete.setProperty("rateDelete", True)
        delete.setIcon(trash_icon(resolve_app_theme(POETORE_THEME).muted_text))
        delete.setIconSize(QSize(20, 20))
        delete.setFixedSize(32, 32)
        delete.setToolTip("このレートを削除")
        delete.setAccessibleName("このレートを削除")
        delete.clicked.connect(lambda _checked=False, i=index: self._remove(i))
        layout.addWidget(delete)
        return row, value, delete

    def _icon_label(self, item_id: str, side: str) -> QLabel:
        label = QLabel()
        label.setObjectName(f"customRateIcon-{side}-{item_id}")
        label.setFixedSize(28, 28)
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

    def begin_refresh(self) -> object:
        self._active_check = request = object()
        self.refresh_button.setEnabled(False)
        self._set_refresh_tooltip(self.league_getter(), "更新を確認中…")
        return request

    def refresh(self, *, manual: bool = False) -> None:
        self._manual_check = self._manual_check or manual
        request = self.begin_refresh()
        self.render_rows()
        league = self.league_getter()
        self.service.queue_sync(
            self.poe_version,
            league,
            on_checked=lambda result: self._signals.checked.emit(request, result),
        )

    def refresh_failed(self) -> None:
        result = SyncCheckResult("failed", self.poe_version, self.league_getter(), None)
        self._finish_refresh(result)

    def _sync_checked(self, request: object, result: SyncCheckResult) -> None:
        if request is self._active_check:
            self._finish_refresh(result)

    def _finish_refresh(self, result: SyncCheckResult) -> None:
        self._active_check = None
        self._last_check = (
            result if result.status != "no_new_data" or self._manual_check else None
        )
        self._manual_check = False
        self.refresh_button.setEnabled(True)
        self.render_rows()

    def available_item_ids(self) -> frozenset[str]:
        return self.service.exchange_item_ids(
            self.poe_version, self.league_getter()
        )

    def stop(self) -> None:
        self.check_timer.stop()
