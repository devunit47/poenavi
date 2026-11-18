from concurrent.futures import Future
from copy import deepcopy

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from src.poetore.exchange_catalog import (
    divination_card_icon_path,
    exchange_catalog_by_id,
)
from src.poetore.exchange_icon_cache import ExchangeIconCache, IconResult
from src.poetore.exchange_rate_cache import ExchangeRateValueCache
from src.poetore.exchange_rate_settings import (
    CHAOS_ORB_ID,
    DIVINE_ORB_ID,
    EXALTED_ORB_ID,
    ExchangeRatePairStore,
    RatePair,
)
from src.poetore.official_exchange import (
    DirectPairPrice,
    ExchangeSyncState,
    SyncCheckResult,
)
from src.ui.app_theme import POETORE_THEME
from src.ui.custom_exchange_rate_panel import (
    OFFICIAL_DATA_TOOLTIP,
    RATE_CHECK_INTERVAL_MSEC,
    CustomExchangeRatePanel,
    DecimalAlignedRateLabel,
    format_display_rate,
)
from src.ui.dialog_theme import UI_METRICS
from src.utils.poe_version_data import POE1, POE2


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class FakeIconCache:
    def __init__(self, path):
        self.path = path

    def request(self, _kind, _url=None, _filename=None):
        future = Future()
        future.set_result(IconResult(self.path, "placeholder", "svg"))
        return future


class FakeService:
    def __init__(self, results=None, ids=()):
        self.results = results or {}
        self.ids = frozenset(ids)
        self.state = ExchangeSyncState(POE1, "League", None, 0, None, False, False)
        self.queued = []
        self.direct_calls = []

    def direct_pair(self, _version, _league, left, right):
        self.direct_calls.append((left, right))
        return self.results.get(
            (left, right), DirectPairPrice("unavailable", left, right, None, None)
        )

    def sync_state(self, *_args):
        return self.state

    def exchange_item_ids(self, *_args):
        return self.ids

    def queue_sync(self, version, league, *, on_complete, on_checked):
        self.queued.append((version, league, on_complete, on_checked))
        return True


def make_panel(
    qapp, tmp_path, *, pairs=None, service=None, version=POE1, icon_cache=None,
):
    default_right = EXALTED_ORB_ID if version == POE2 else CHAOS_ORB_ID
    pairs = pairs if pairs is not None else [RatePair(DIVINE_ORB_ID, default_right)]
    config = {"poetore": {"exchange_rate_pairs": {
        POE1: [pair.to_config() for pair in pairs] if version == POE1 else [],
        POE2: [pair.to_config() for pair in pairs] if version == POE2 else [],
    }}}
    saved = []
    store = ExchangeRatePairStore(config, lambda value: saved.append(deepcopy(value)))
    icon = divination_card_icon_path()
    panel = CustomExchangeRatePanel(
        None,
        poe_version=version,
        store=store,
        league_getter=lambda: "League",
        service=service or FakeService(),
        value_cache=ExchangeRateValueCache(tmp_path / "rates.json", clock=lambda: 1000),
        icon_cache=icon_cache or FakeIconCache(icon),
        on_manage=lambda: None,
    )
    panel.resize(800, 600)
    panel.show()
    qapp.processEvents()
    return panel, store, saved


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (174.36, "174.4"),
        (12.345, "12.3"),
        (1.25, "1.3"),
        (1.04, "1"),
        (0.99994, "0.9999"),
        (0.005735260, "0.005735"),
        (12345, "12,345"),
        (1.5000, "1.5"),
        (372.5, "372.5"),
        (372.8, "372.8"),
    ],
)
def test_rates_use_one_decimal_at_or_above_one_and_significant_digits_below_one(
    value,
    expected,
):
    assert format_display_rate(value) == expected


def test_rate_rows_center_equals_and_share_decimal_anchor(qapp, tmp_path):
    ids = list(exchange_catalog_by_id(POE1))[:4]
    pairs = [RatePair(ids[0], ids[2]), RatePair(ids[1], ids[3])]
    results = {
        (pairs[0].left_item_id, pairs[0].right_item_id): DirectPairPrice(
            "available", pairs[0].left_item_id, pairs[0].right_item_id, 681, 720
        ),
        (pairs[1].left_item_id, pairs[1].right_item_id): DirectPairPrice(
            "available", pairs[1].left_item_id, pairs[1].right_item_id, 7.398, 720
        ),
    }
    panel, *_ = make_panel(qapp, tmp_path, pairs=pairs, service=FakeService(results))
    try:
        values = [
            panel.findChild(DecimalAlignedRateLabel, f"customRateValue{index}")
            for index in range(2)
        ]
        assert [value.text() for value in values] == ["1 ＝ 681", "1 ＝ 7.4"]
        equals_centers = []
        decimal_anchors = []
        for value in values:
            unit, equals, integer, fraction = value._column_rects()
            assert abs(equals.center().x() - value.contentsRect().center().x()) <= 1
            assert unit.right() < equals.left() < integer.left()
            assert integer.right() + 1 == fraction.left()
            equals_centers.append(value.mapTo(panel, equals.center()).x())
            decimal_anchors.append(value.mapTo(panel, fraction.topLeft()).x())
        assert len(set(equals_centers)) == len(set(decimal_anchors)) == 1
        cached = panel.value_cache.get(
            POE1,
            "League",
            pairs[1].left_item_id,
            pairs[1].right_item_id,
        )
        assert cached is not None
        assert cached.price == 7.398
    finally:
        panel.stop()
        panel.close()


@pytest.mark.parametrize("count", (0, 1, 9, 10))
def test_zero_through_ten_rows_have_one_management_entry(
    qapp, tmp_path, count,
):
    ids = list(exchange_catalog_by_id(POE1))
    pairs = [RatePair(ids[index], ids[index + 10]) for index in range(count)]
    panel, *_ = make_panel(qapp, tmp_path, pairs=pairs)
    try:
        assert len(panel.row_widgets) == count
        actions = [button for button in panel.findChildren(QPushButton) if not button.property("rateDelete")]
        assert set(actions) == {panel.manage_button, panel.refresh_button}
        assert len(panel.findChildren(QPushButton)) == count + 2
        assert panel.manage_button.isVisible()
        assert panel.manage_button.text() == ""
        assert not panel.manage_button.icon().isNull()
        assert panel.manage_button.toolTip() and panel.manage_button.accessibleName()
        assert panel.card.isVisible() == bool(count)
    finally:
        panel.stop()
        panel.close()


def test_refresh_button_sits_next_to_manage_button_in_title_row(qapp, tmp_path):
    panel, *_ = make_panel(qapp, tmp_path)
    try:
        title_row = panel.layout().itemAt(0).layout()
        manage = panel.manage_button
        refresh = panel.refresh_button
        assert title_row.indexOf(refresh) == title_row.indexOf(manage) + 1
        assert refresh.y() == manage.y()
        assert refresh.size() == manage.size()
        assert refresh.x() - manage.geometry().right() - 1 == UI_METRICS.inline_gap
        footer = panel.scroll_area.widget().layout().itemAt(1).layout()
        assert footer.count() == 1
        assert footer.itemAt(0).widget() is panel.status_label
    finally:
        panel.stop()
        panel.close()


def test_available_no_trade_unconfirmed_and_unavailable_are_distinct(qapp, tmp_path):
    ids = list(exchange_catalog_by_id(POE1))[:8]
    pairs = [RatePair(ids[index], ids[index + 4]) for index in range(4)]
    statuses = ("available", "no_trades", "unconfirmed", "unavailable")
    results = {
        (pair.left_item_id, pair.right_item_id): DirectPairPrice(
            status,
            pair.left_item_id,
            pair.right_item_id,
            2.5 if status == "available" else None,
            720,
        )
        for pair, status in zip(pairs, statuses, strict=True)
    }
    panel, *_ = make_panel(qapp, tmp_path, pairs=pairs, service=FakeService(results))
    try:
        values = [
            panel.findChild(QLabel, f"customRateValue{index}").text()
            for index in range(4)
        ]
        assert values == [
            "1 ＝ 2.5", "取引データなし", "価格未確定",
            "最新データを取得できません",
        ]
        assert all(
            panel.findChild(QLabel, f"customRateValue{index}").alignment()
            == Qt.AlignCenter
            for index in range(4)
        )
    finally:
        panel.stop()
        panel.close()


def test_base_currency_quote_keeps_fractional_direct_rate(qapp, tmp_path):
    pair = RatePair(DIVINE_ORB_ID, CHAOS_ORB_ID)
    result = DirectPairPrice(
        "available", DIVINE_ORB_ID, CHAOS_ORB_ID, 372.5, 720
    )
    panel, *_ = make_panel(
        qapp,
        tmp_path,
        pairs=[pair],
        service=FakeService({(DIVINE_ORB_ID, CHAOS_ORB_ID): result}),
    )
    try:
        assert panel.findChild(QLabel, "customRateValue0").text() == "1 ＝ 372.5"
    finally:
        panel.stop()
        panel.close()


def test_delete_reveals_on_row_hover_without_moving_columns(qapp, tmp_path):
    panel, store, saved = make_panel(qapp, tmp_path)
    try:
        row = panel.row_widgets[0]
        delete = row.findChild(QPushButton, "customRateDelete0")
        name = row.findChild(QLabel, "customRateLeftName0")
        value = row.findChild(QLabel, "customRateValue0")
        area = QRect(delete.mapTo(panel, QPoint()), delete.size())
        handle = panel.windowHandle()

        def move_to(widget):
            QTest.mouseMove(handle, widget.mapTo(panel, widget.rect().center()))
            qapp.processEvents()

        def delete_pixels():
            return panel.grab().toImage().copy(area)

        assert delete.toolTip() and delete.accessibleName()
        move_to(panel.title_label)
        idle = delete_pixels()
        blank = idle.copy()
        blank.fill(idle.pixelColor(0, 0))
        assert idle == blank
        original_value_geometry = value.geometry()
        move_to(name)
        revealed = delete_pixels()
        assert revealed != idle
        move_to(value)
        assert delete_pixels() == revealed
        assert value.geometry() == original_value_geometry
        move_to(panel.title_label)
        assert delete_pixels() == idle

        panel.manage_button.setFocus(Qt.TabFocusReason)
        QTest.keyClick(panel.manage_button, Qt.Key_Tab)
        assert panel.refresh_button.hasFocus()
        QTest.keyClick(panel.refresh_button, Qt.Key_Tab)
        assert delete.hasFocus()
        assert delete_pixels() != idle
        QTest.keyClick(delete, Qt.Key_Backtab)
        assert panel.refresh_button.hasFocus()
        assert delete_pixels() == idle

        move_to(delete)
        QTest.mouseClick(handle, Qt.LeftButton, Qt.NoModifier, area.center())
        assert store.pairs(POE1) == ()
        assert len(saved) == 1
        assert panel.manage_button.isVisible()
    finally:
        panel.stop()
        panel.close()


def test_removed_scarab_pair_is_not_rendered_or_queried(qapp, tmp_path):
    scarab_id = "Metadata/Items/Scarabs/Example"
    service = FakeService()
    panel, store, saved = make_panel(
        qapp,
        tmp_path,
        pairs=[RatePair(scarab_id, CHAOS_ORB_ID)],
        service=service,
    )
    try:
        assert store.pairs(POE1) == ()
        assert panel.row_widgets == []
        assert service.direct_calls == []
        assert saved == []
    finally:
        panel.stop()
        panel.close()


def test_refresh_icon_queues_official_data_and_manual_result_text_is_specific(qapp, tmp_path):
    service = FakeService()
    panel, *_ = make_panel(qapp, tmp_path, service=service)
    try:
        previous_row = panel.row_widgets[0]
        QTest.mouseClick(panel.refresh_button, Qt.LeftButton)
        assert len(service.queued) == 1
        assert service.queued[0][:2] == (POE1, "League")
        assert not previous_row.isVisible()
        assert panel.status_label.text() == "最新データを確認中…"
        loading_value = panel.row_widgets[0].findChild(QLabel, "customRateValue0")
        assert loading_value.text() == "最新データ取得中…"
        assert loading_value.toolTip() == "最新データ取得中…"
        assert "font-size: 12px" in loading_value.styleSheet()
        assert loading_value.sizeHint().width() <= loading_value.width()
        assert not panel.refresh_button.isEnabled()
        callback = service.queued[-1][3]
        callback(SyncCheckResult("no_new_data", POE1, "League", 720))
        qapp.processEvents()
        assert panel.status_label.text() == "新しい公式データはまだありません"
        failed_value = panel.row_widgets[0].findChild(QLabel, "customRateValue0")
        assert failed_value.text() == "最新データを取得できません"
        assert failed_value.toolTip() == "最新データを取得できません"
        assert panel.refresh_button.isEnabled()
        assert panel.check_timer.interval() == RATE_CHECK_INTERVAL_MSEC
    finally:
        panel.stop()
        panel.close()


def test_official_hourly_explanation_is_exact(qapp, tmp_path):
    panel, *_ = make_panel(qapp, tmp_path)
    try:
        assert panel.title_label.toolTip() == OFFICIAL_DATA_TOOLTIP
        assert not panel.refresh_button.text()
        assert not panel.refresh_button.icon().isNull()
        assert panel.refresh_button.accessibleName() == "公式取引データを再取得"
        assert panel.refresh_button.toolTip() == f"公式取引データを再取得\n\n{OFFICIAL_DATA_TOOLTIP}"
    finally:
        panel.stop()
        panel.close()


def test_successful_refresh_keeps_hourly_status(qapp, tmp_path):
    service = FakeService()
    panel, *_ = make_panel(qapp, tmp_path, service=service)
    try:
        QTest.mouseClick(panel.refresh_button, Qt.LeftButton)
        assert not panel.refresh_button.isEnabled()
        service.state = ExchangeSyncState(POE1, "League", 720, 720, 0, False, True)
        _, _, on_complete, on_checked = service.queued[-1]
        result = SyncCheckResult("updated", POE1, "League", 720)
        on_complete(result)
        on_checked(result)
        qapp.processEvents()
        assert panel.status_label.text() == "League ・ 公式取引データ（1時間単位・自動取得）"
        assert panel.refresh_button.isEnabled()
    finally:
        panel.stop()
        panel.close()


def test_pending_new_league_status_explains_automatic_retry(qapp, tmp_path):
    service = FakeService()
    panel, *_ = make_panel(qapp, tmp_path, service=service)
    try:
        panel.refresh()
        callback = service.queued[-1][3]
        callback(SyncCheckResult("no_market_data", POE1, "League", 720))
        qapp.processEvents()
        assert panel.status_label.text() == (
            "このリーグの取引データはまだありません（自動確認中）"
        )
        assert panel.check_timer.isActive()
    finally:
        panel.stop()
        panel.close()


def test_tooltips_use_high_contrast_dark_theme(qapp, tmp_path):
    panel, *_ = make_panel(qapp, tmp_path)
    try:
        style = panel.styleSheet()
        assert "QToolTip" in style
        assert f"color: {POETORE_THEME.text}" in style
        assert f"background-color: {POETORE_THEME.background}" in style
        assert "border: 1px solid" in style
    finally:
        panel.stop()
        panel.close()


def test_long_names_keep_full_tooltip(qapp, tmp_path):
    panel, *_ = make_panel(qapp, tmp_path)
    try:
        label = panel.findChild(QLabel, "customRateLeftName0")
        assert label.toolTip() == label.text()
        assert label.width() == 125
    finally:
        panel.stop()
        panel.close()


def test_names_use_heading_accent_and_cached_icons_render(qapp, tmp_path):
    panel, *_ = make_panel(qapp, tmp_path)
    try:
        qapp.processEvents()
        for side in ("Left", "Right"):
            name = panel.findChild(QLabel, f"customRate{side}Name0")
            assert POETORE_THEME.accent in name.styleSheet()
        icon_labels = [
            label
            for label in panel.findChildren(QLabel)
            if label.objectName().startswith("customRateIcon-")
        ]
        assert len(icon_labels) == 2
        assert all(label.pixmap() is not None and not label.pixmap().isNull()
                   for label in icon_labels)
    finally:
        panel.stop()
        panel.close()


def test_message_in_a_bottle_uses_bundled_icon_in_main_rate_row(qapp, tmp_path):
    item_id = "Metadata/Items/Deepwater/DeepwaterBottledItem"
    cache = ExchangeIconCache(
        tmp_path / "icons",
        fetcher=lambda _url: (_ for _ in ()).throw(
            AssertionError("bundled icon must not fetch")
        ),
    )
    panel, *_ = make_panel(
        qapp,
        tmp_path,
        pairs=[RatePair(item_id, CHAOS_ORB_ID)],
        icon_cache=cache,
    )
    try:
        qapp.processEvents()
        qapp.processEvents()
        icon = panel.findChild(QLabel, f"customRateIcon-left-{item_id}")
        assert icon is not None
        assert icon.pixmap() is not None and not icon.pixmap().isNull()
    finally:
        panel.stop()
        panel.close()
        cache.close()
