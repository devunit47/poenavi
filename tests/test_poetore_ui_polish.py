"""Peer controls and anchored overlays stay usable across themes and fonts."""

from unittest.mock import Mock

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QFontDatabase, QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QPushButton, QStyleOptionViewItem, QWidget

from src.app_font import bundled_font_path
from src.ui.appearance import (
    PRESETS, apply_application_appearance, configure_appearance,
    current_appearance, requested_appearance,
)
from tests.poetore_ui_scenarios import build_scenario, offline_ui, settle


@pytest.fixture(autouse=True)
def isolated_ui(qapp):
    screens = qapp.screens()
    saved, requested = current_appearance(), requested_appearance()
    font, palette, mode = qapp.font(), qapp.palette(), qapp.property("appMode")
    font_id = QFontDatabase.addApplicationFont(str(bundled_font_path()))
    qapp.setProperty("appMode", "poetore")
    with offline_ui():
        yield
        for window in QApplication.topLevelWidgets():
            window.hide()
            window.deleteLater()
        qapp.sendPostedEvents(None, QEvent.DeferredDelete)
        qapp.processEvents()
    configure_appearance(saved, requested=requested)
    qapp.setFont(font)
    qapp.setPalette(palette)
    qapp.setProperty("appMode", mode)
    QFontDatabase.removeApplicationFont(font_id)
    assert screens


def assert_peers(buttons, *, width=True):
    assert len(buttons) >= 2
    assert len({button.height() for button in buttons}) == 1, [(b.text(), b.size()) for b in buttons]
    if width:
        # QBoxLayout distributes an odd spare pixel between expanding peers.
        assert max(b.width() for b in buttons) - min(b.width() for b in buttons) <= 1, [(b.text(), b.size()) for b in buttons]


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("size", [13, 24])
@pytest.mark.parametrize("version", ["poe1", "poe2"])
@pytest.mark.parametrize("key", ["settings", "exchange", "expedition", "desecration", "heist", "main", "trade", "category", "map_manager", "map"])
def test_peer_button_geometry(qapp, tmp_path, preset, size, version, key):
    apply_application_appearance(qapp, {"appearance": {"preset": preset, "overrides": {"base_font_size": size}}})
    window = build_scenario(key, tmp_path, version)
    settle(qapp, window)
    if key in ("settings", "expedition", "desecration", "heist"):
        assert_peers([window.cancel_button, window.save_button])
        if key == "settings":
            assert_peers([window.custom_commands_widget.add_button, window.custom_commands_widget.remove_button])
        if key == "expedition":
            assert_peers([window.set_region_button, window.reset_region_button])
        elif key == "desecration":
            for _, _, choose, reset in window._section_widgets.values():
                assert_peers([choose, reset])
    elif key == "exchange":
        assert_peers([window.add_button, window.close_button])
        assert_peers(list(window.currency_buttons.values()))
        for row in window.registered_widget._rows:
            assert_peers(row.findChildren(QPushButton))
        for listing in (window.category_list, window.candidate_list):
            assert listing.visualItemRect(listing.item(0)).height() >= listing.fontMetrics().height()
        assert window.preview_label.mapTo(window, window.preview_label.rect().topLeft()).y() > window.item_card.geometry().bottom()
    elif key == "main":
        header_buttons = [b for b in window.header_action_buttons if b.isVisibleTo(window)]
        assert_peers(header_buttons)
        assert_peers([window.focus_button, *header_buttons], width=False)
        if size == 13:
            assert window.focus_button.height() == 36
        assert_peers([window.title_bar.minimize_button, window.title_bar.close_button])
        assert_peers([window.rate_panel.manage_button, window.rate_panel.refresh_button])
    elif key == "trade":
        assert_peers(window.trade_preset_combo._buttons)
        assert_peers([window.league_popup_button, window.poetore_close_button])
        assert_peers([window.mod_conditions_toggle, window.clear_mod_conditions_button,
                      window.hidden_mods_toggle, window.mod_sources_toggle])
        assert_peers([window.price_button, window.trade_status_combo,
                      window.trade_currency_combo, window.listed_within_combo], width=False)
        window.set_obs_streaming_mode(True)
        settle(qapp, window)
        assert window.height() == 30
        assert window._title_bar.height() == 24
    elif key == "category":
        assert_peers(window.findChildren(QPushButton))
    else:
        assert_peers(window.profile_buttons)


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("size", [13, 24])
@pytest.mark.parametrize("available", [QRect(0, 0, 800, 600), QRect(-960, 40, 800, 600)])
@pytest.mark.parametrize("all_categories", [False, True])
def test_category_choices_fit_available_screen(qapp, monkeypatch, preset, size, available, all_categories):
    from src.poetore.poe2.desecration_overlay import CATEGORY_LABELS, CategoryChoiceOverlay

    apply_application_appearance(qapp, {"appearance": {"preset": preset, "overrides": {"base_font_size": size}}})
    screen = Mock(availableGeometry=lambda: available)
    screen_at = Mock(return_value=screen)
    monkeypatch.setattr("src.poetore.poe2.desecration_overlay.QGuiApplication.screenAt", screen_at)
    categories = tuple(CATEGORY_LABELS) if all_categories else ("quarterstaff", "amulet", "boots", "bow")
    window = CategoryChoiceOverlay()
    anchor = available.bottomRight()
    window.show_categories(categories, QPoint(anchor))
    settle(qapp, window)
    screen_at.assert_called_once()
    assert available.contains(window.frameGeometry()), window.frameGeometry()
    buttons = [window._buttons.itemAt(i).widget() for i in range(window._buttons.count())]
    assert_peers(buttons)
    for button in buttons:
        geometry = QRect(button.mapToGlobal(QPoint()), button.size())
        assert available.contains(geometry), (button.text(), geometry)


def test_category_choices_scroll_on_short_screen_and_reflow_when_reopened(qapp, monkeypatch):
    from src.poetore.poe2.desecration_overlay import CATEGORY_LABELS, CategoryChoiceOverlay

    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 24}}})
    available = QRect(-640, 40, 640, 240)
    screen = Mock(availableGeometry=lambda: available)
    monkeypatch.setattr("src.poetore.poe2.desecration_overlay.QGuiApplication.screenAt", lambda _point: screen)
    window = CategoryChoiceOverlay()
    window.show_categories(tuple(CATEGORY_LABELS), available.bottomRight())
    settle(qapp, window)
    assert available.contains(window.frameGeometry())
    assert window._button_area.verticalScrollBar().isVisible()
    viewport = window._button_area.viewport()
    for index in range(window._buttons.count()):
        button = window._buttons.itemAt(index).widget()
        window._button_area.ensureWidgetVisible(button, 0, 0)
        qapp.processEvents()
        assert viewport.rect().contains(QRect(button.mapTo(viewport, QPoint()), button.size())), button.text()

    window.hide()
    available = QRect(0, 0, 1920, 1080)
    window.show_categories(("quarterstaff", "amulet", "boots", "bow"), available.center())
    settle(qapp, window)
    assert available.contains(window.frameGeometry())
    assert not window._button_area.verticalScrollBar().isVisible()
    assert len({window._buttons.getItemPosition(i)[1] for i in range(window._buttons.count())}) == 4
    assert window._buttons.count() == 5


@pytest.mark.parametrize("available", [QRect(0, 0, 800, 600), QRect(-960, 40, 800, 600)])
@pytest.mark.parametrize("corner", ["topLeft", "bottomRight"])
def test_ocr_status_and_map_popup_fit_small_screen(qapp, tmp_path, monkeypatch, available, corner):
    from src.poetore.models import ItemModifier, ParsedItem
    from src.poetore.poe2.desecration_overlay import HighAccuracyOcrStatusOverlay
    from src.poetore.window_position import PlacementContext

    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 24}}})
    anchor = getattr(available, corner)()
    capture = QRect(anchor.x(), anchor.y(), 1, 1)
    status = HighAccuracyOcrStatusOverlay()
    status.show_status(available, capture, [
        "通常の読み取りで一部の数値を確認できませんでした",
        "高精度OCRを準備しています…",
        "初回のみ10～15秒ほどかかります",
    ])
    settle(qapp, status)
    assert available.contains(status.frameGeometry()), status.frameGeometry()
    for widget in (status._spinner, status._message):
        assert status.rect().contains(QRect(widget.mapTo(status, QPoint()), widget.size()))
    assert status._message.height() >= status._message.sizeHint().height()

    popup = build_scenario("map", tmp_path)
    item = ParsedItem("Maps", "Rare", "深淵の地図", "Map", "map", modifiers=(
        ItemModifier("未知のMod", stat_id="missing"),
    ))
    monkeypatch.setattr("src.ui.map_check.read_item_clipboard", lambda _clipboard: "")
    monkeypatch.setattr("src.ui.map_check.parse_item_text", lambda _text: item)
    popup._placement_context = PlacementContext(available, anchor)
    popup._consume_clipboard()
    settle(qapp, popup)
    assert available.contains(popup.frameGeometry()), popup.frameGeometry()


@pytest.mark.parametrize("available", [QRect(0, 0, 800, 600), QRect(-960, 40, 800, 600)])
@pytest.mark.parametrize("kind", ["desecration", "expedition", "heist"])
def test_game_client_overlays_fit_small_screen(qapp, available, kind):
    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 24}}})
    if kind == "desecration":
        from src.poetore.poe2.desecration_ocr import ChoiceBand
        from src.poetore.poe2.desecration_overlay import DesecrationTierOverlay

        window = DesecrationTierOverlay()
        window.show_tiers(available, available, (800, 600), (ChoiceBand(100, 200),), (1,))
    elif kind == "expedition":
        from src.poetore.expedition_rewards import ExpeditionPriceOverlay, RewardPriceRow

        window = ExpeditionPriceOverlay()
        window.show_prices(available, 800, 600, 120, [RewardPriceRow(100, 200, "5 高貴/個", 5)])
    else:
        from src.poetore.heist_curio import CurioRegionSelector

        window = CurioRegionSelector(available)
    settle(qapp, window)
    assert available.contains(window.frameGeometry()), window.frameGeometry()


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("size", [13, 24])
def test_cheat_sheet_button_groups(qapp, preset, size):
    from src.ui.cheat_sheets import CheatSheetManagerDialog
    from src.ui.dialog_theme import POETORE_DIALOG_THEME
    from tests.test_theme_geometry_audit import _audit_pages

    apply_application_appearance(qapp, {"appearance": {"preset": preset, "overrides": {"base_font_size": size}}})
    window = CheatSheetManagerDialog({}, theme=POETORE_DIALOG_THEME)
    settle(qapp, window)
    assert_peers([window.cancel_button, window.save_button])
    assert_peers([window.up_button, window.down_button])
    assert not _audit_pages(qapp, window)


@pytest.mark.parametrize("profile", ["small", "medium", "large"])
@pytest.mark.parametrize("version", ["poe1", "poe2"])
@pytest.mark.parametrize("size", [13, 24])
def test_trade_mod_height_tracks_visible_content(qapp, tmp_path, profile, version, size):
    from src.poetore.trade import TradeStatFilter

    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": size}}})
    window = build_scenario("trade", tmp_path, version)
    window._app_config.setdefault("poetore", {})["result_font_size"] = profile
    window.apply_result_display_size()
    settle(qapp, window)
    tree = window.mod_filter_tree
    three_rows = tree.height()
    last = tree.topLevelItem(tree.topLevelItemCount() - 1)
    assert 0 <= tree.viewport().height() - tree.visualItemRect(last).bottom() - 1 <= 6
    tree_bottom = tree.mapTo(window, QPoint(0, tree.height())).y()
    actions_top = window.mod_conditions_toggle.mapTo(window, QPoint()).y()
    assert 0 <= actions_top - tree_bottom <= 8

    window._populate_stat_filters((TradeStatFilter("explicit.one", "最大ライフ +#", 100, "prefix", True),))
    settle(qapp, window)
    assert tree.height() < three_rows
    window._populate_stat_filters(tuple(
        TradeStatFilter(f"explicit.{i}", f"耐性Mod {i} +#%", i, "suffix", True)
        for i in range(40)
    ))
    settle(qapp, window)
    many_height = window.height()
    many_content_height = window._obs_content.height()
    assert tree.height() < window._visible_mod_content_height()
    assert tree.verticalScrollBar().isVisible()
    tree.scrollToBottom()
    qapp.processEvents()
    assert tree.viewport().rect().contains(tree.visualItemRect(tree.topLevelItem(39)))
    window._populate_stat_filters(())
    window._reset_mod_conditions_for_item()
    settle(qapp, window)
    assert tree.isHidden()
    assert window.height() <= many_height
    assert window._obs_content.height() < many_content_height


@pytest.mark.parametrize("version", ["poe1", "poe2"])
@pytest.mark.parametrize("size", [13, 24])
def test_trade_corruption_shares_item_name_row(qapp, tmp_path, version, size):
    from src.poetore.models import ParsedItem

    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": size}}})
    window = build_scenario("trade", tmp_path, version)
    long_name = "とても長いユニークアイテムの名前" * 8
    window._update_item_header(ParsedItem("Body Armours", "Unique", long_name, "Vaal Regalia", "armour.chest"))
    settle(qapp, window)
    name, chip = window.item_name_label, window.corrupted_combo
    name_rect = QRect(name.mapTo(window.item_header, QPoint()), name.size())
    chip_rect = QRect(chip.mapTo(window.item_header, QPoint()), chip.size())
    assert abs(name_rect.center().y() - chip_rect.center().y()) <= 1
    assert name_rect.right() + 6 <= chip_rect.left()
    assert name.toolTip() == long_name
    assert name.width() < name.fontMetrics().horizontalAdvance(long_name)
    assert window.item_header.height() <= max(name.height(), chip.height()) + 16

    # Nonunique equipment uses a segmented base-scope control in the same row.
    window._update_item_header(ParsedItem("Body Armours", "Rare", "レア装備", long_name, "body_armour"))
    settle(qapp, window)
    scope = window.base_scope_toggle
    scope_rect = QRect(scope.mapTo(window.item_header, QPoint()), scope.size())
    chip_rect = QRect(chip.mapTo(window.item_header, QPoint()), chip.size())
    assert abs(scope_rect.center().y() - chip_rect.center().y()) <= 1
    assert scope_rect.right() + 6 <= chip_rect.left()
    assert scope._buttons[0].toolTip() == long_name


@pytest.mark.parametrize("version", ["poe1", "poe2"])
@pytest.mark.parametrize("profile", ["small", "medium", "large"])
def test_trade_large_font_conditions_wrap_with_right_margin(qapp, tmp_path, version, profile):
    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 24}}})
    window = build_scenario("trade", tmp_path, version)
    window._app_config.setdefault("poetore", {})["result_font_size"] = profile
    window.apply_result_display_size()
    settle(qapp, window)
    window.resize(760, window.height())
    settle(qapp, window)
    controls = [window.price_button, window.trade_status_combo, window.trade_currency_combo,
                window.listed_within_combo, window.remember_trade_options_checkbox]
    for control in controls:
        rect = QRect(control.mapTo(window, QPoint()), control.size())
        assert window.width() - rect.right() - 1 >= 10, (control, rect, window.size())
        if isinstance(control, QComboBox):
            assert control.width() >= control.fontMetrics().horizontalAdvance(control.currentText()) + 12
        else:
            assert control.width() >= control.minimumSizeHint().width()
    assert len({control.mapTo(window, QPoint()).y() for control in controls}) >= 2


@pytest.mark.parametrize("version", ["poe1", "poe2"])
@pytest.mark.parametrize("profile", ["small", "medium", "large"])
@pytest.mark.parametrize("available", [QRect(0, 0, 800, 600), QRect(-960, 40, 800, 600)])
def test_trade_large_font_fits_small_screen_and_all_controls_remain_reachable(
    qapp, tmp_path, version, profile, available,
):
    from src.poetore.window_position import PlacementContext

    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 24}}})
    window = build_scenario("trade", tmp_path, version)
    window._app_config.setdefault("poetore", {})["result_font_size"] = profile
    window.apply_result_display_size()
    context = PlacementContext(available, available.bottomRight())
    window.show_at_context(context, activate=False)
    settle(qapp, window)
    assert available.contains(window.frameGeometry()), window.frameGeometry()
    scroll = window._content_scroll
    assert scroll.horizontalScrollBar().maximum() == 0
    assert scroll.verticalScrollBar().maximum() > 0
    for control in (window.item_header, window.mod_conditions_toggle, window.price_button,
                    window.remember_trade_options_checkbox, window.trade_url_button, window.price_list):
        scroll.ensureWidgetVisible(control, 0, 0)
        qapp.processEvents()
        rect = QRect(control.mapTo(scroll.viewport(), QPoint()), control.size())
        assert scroll.viewport().rect().contains(rect), (control, rect)
        assert not window._title_bar.isHidden()
    # Restoring a larger game client releases the old 600px height cap.
    larger = QRect(0, 0, 1920, 1080)
    window.show_at_context(PlacementContext(larger, larger.center()), activate=False)
    settle(qapp, window)
    assert larger.contains(window.frameGeometry())
    assert window.maximumHeight() > 600
    window.set_obs_streaming_mode(True)
    settle(qapp, window)
    assert window.height() == 30
    window.show_at_context(context, activate=False)
    settle(qapp, window)
    assert available.contains(window.frameGeometry())


@pytest.mark.parametrize("version", ["poe1", "poe2"])
@pytest.mark.parametrize("profile", ["small", "medium", "large"])
def test_trade_narrow_large_font_prioritizes_mod_names_and_keeps_range_on_tab_row(qapp, tmp_path, version, profile):
    from src.poetore.window_position import PlacementContext

    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 24}}})
    window = build_scenario("trade", tmp_path, version)
    window._app_config.setdefault("poetore", {})["result_font_size"] = profile
    window.apply_result_display_size()
    available = QRect(0, 0, 800, 600)
    window.show_at_context(PlacementContext(available, available.center()), activate=False)
    settle(qapp, window)
    tree = window.mod_filter_tree
    for index in range(tree.topLevelItemCount()):
        row = tree.topLevelItem(index)
        assert tree.columnWidth(3) - 12 >= tree.fontMetrics().horizontalAdvance(row.text(3))
        assert tree.columnWidth(3) > tree.columnWidth(1)
        assert row.toolTip(1) in ("プレフィックス", "サフィックス")
        assert row.toolTip(3) == row.text(3)
    assert window.search_range_combo.mapTo(window, QPoint()).y() == window.trade_preset_combo.mapTo(window, QPoint()).y()
    assert "Mod数値：-10%まで許容" in window.search_range_combo.toolTip()
    assert window.search_range_combo.currentData() == 10


@pytest.mark.parametrize("version", ["poe1", "poe2"])
@pytest.mark.parametrize("kind", ["prefix", "suffix", "prefix_suffix"])
@pytest.mark.parametrize("repeat", [1, 4])
@pytest.mark.parametrize("base_text", ["最大ライフとエナジーシールドが増加する", "MaximumLifeAndEnergyShieldIncreased"])
def test_trade_narrow_mod_name_wraps_before_eliding_and_restores_on_widening(qapp, tmp_path, version, kind, repeat, base_text):
    from src.poetore.trade import TradeStatFilter
    from src.poetore.window_position import PlacementContext

    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 24}}})
    window = build_scenario("trade", tmp_path, version)
    window._app_config.setdefault("poetore", {})["result_font_size"] = "large"
    window.apply_result_display_size()
    text = base_text * repeat
    window._populate_stat_filters((TradeStatFilter("explicit.long", text, 120, kind, True, tier_tags=(1,)),))
    available = QRect(0, 0, 800, 600)
    window.show_at_context(PlacementContext(available, available.center()), activate=False)
    settle(qapp, window)
    tree, metrics = window.mod_filter_tree, window.mod_filter_tree.fontMetrics()
    row = tree.topLevelItem(0)
    assert row.text(1) == {"prefix": "P", "suffix": "S", "prefix_suffix": "P/S"}[kind]
    assert tree.columnWidth(1) >= QFontMetrics(row.font(1)).horizontalAdvance(row.text(1)) + 10
    hover_point = QPoint(tree.header().sectionViewportPosition(1) + tree.columnWidth(1) // 2,
                         tree.visualItemRect(row).center().y())
    assert tree.indexAt(hover_point).column() == 1
    assert row.toolTip(1) == {"prefix": "プレフィックス", "suffix": "サフィックス",
                             "prefix_suffix": "プレフィックス／サフィックス"}[kind]
    assert tree.wordWrap()
    assert tree.columnWidth(3) - 12 < metrics.horizontalAdvance(text)
    wrapped = metrics.boundingRect(QRect(0, 0, tree.columnWidth(3) - 12, 10000), Qt.TextWrapAnywhere, text)
    two_lines = metrics.height() + metrics.lineSpacing()
    assert metrics.height() < wrapped.height()
    assert tree.visualItemRect(row).height() == min(wrapped.height(), two_lines) + 12
    assert row.toolTip(3) == text
    # Inspect real painted text: a tall row alone does not prove that Qt drew
    # two lines (the standard styled delegate can still elide a single line).
    cell = tree.viewport().grab(QRect(tree.header().sectionViewportPosition(3),
                                     tree.visualItemRect(row).top(), tree.columnWidth(3),
                                     tree.visualItemRect(row).height())).toImage()
    ink_rows = [y for y in range(cell.height()) if any(
        cell.pixelColor(x, y).lightness() > 160 for x in range(6, cell.width() - 6)
    )]
    assert ink_rows and max(ink_rows) - min(ink_rows) + 1 > metrics.height()
    assert max(ink_rows) <= cell.height() - 9
    option = QStyleOptionViewItem()
    option.initFrom(tree)
    option.rect = QRect(0, 0, tree.columnWidth(3), tree.visualItemRect(row).height())
    tree.itemDelegateForColumn(3).initStyleOption(option, tree.indexFromItem(row, 3))
    if repeat > 1:
        assert option.text.count("\n") == 1
        assert option.text.endswith("…")

    wider = QRect(0, 0, 1920, 1080)
    window.show_at_context(PlacementContext(wider, wider.center()), activate=False)
    window.resize(1600, window.height())
    settle(qapp, window)
    assert row.text(1) == row.toolTip(1)
    if repeat == 1:
        assert tree.columnWidth(3) - 12 >= metrics.horizontalAdvance(text)
        assert tree.visualItemRect(row).height() == window._mod_row_height()
    assert window.search_range_combo.currentText() == "Mod数値：-10%まで許容"


@pytest.mark.parametrize("version", ["poe1", "poe2"])
@pytest.mark.parametrize("profile", ["small", "medium", "large"])
def test_trade_default_font_keeps_full_labels_and_single_line_rows(qapp, tmp_path, version, profile):
    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 13}}})
    window = build_scenario("trade", tmp_path, version)
    window._app_config.setdefault("poetore", {})["result_font_size"] = profile
    window.apply_result_display_size()
    settle(qapp, window)
    tree = window.mod_filter_tree
    assert tree.topLevelItem(0).text(1) == "プレフィックス"
    assert tree.topLevelItem(1).text(1) == "サフィックス"
    assert tree.columnWidth(2) == window._scaled_display_value(62)
    assert tree.visualItemRect(tree.topLevelItem(0)).height() == window._mod_row_height()
    assert window.search_range_combo.currentText() == "Mod数値：-10%まで許容"


@pytest.mark.parametrize("version", ["poe1", "poe2"])
def test_trade_narrow_unique_roll_name_wraps_without_losing_slider(qapp, tmp_path, version):
    from src.poetore.models import ParsedItem
    from src.poetore.trade import TradeStatFilter
    from src.poetore.ui import _UniqueRollSlider
    from src.poetore.window_position import PlacementContext

    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 24}}})
    window = build_scenario("trade", tmp_path, version)
    window._app_config.setdefault("poetore", {})["result_font_size"] = "large"
    window.apply_result_display_size()
    window._parsed_item = ParsedItem("Amulets", "Unique", "Example", "Gold Amulet", "accessory")
    text = "最大ライフとエナジーシールドが増加する" * 4
    window._populate_stat_filters((TradeStatFilter(
        "explicit.long", text, 38, "prefix", True, tier_tags=(1,),
        read_value=40, roll_min=30, roll_max=50, better=1,
    ),))
    available = QRect(0, 0, 800, 600)
    window.show_at_context(PlacementContext(available, available.center()), activate=False)
    settle(qapp, window)
    tree = window.mod_filter_tree
    row = tree.topLevelItem(0)
    cell = tree.itemWidget(row, 3)
    label = cell.findChild(QLabel, "modDescription")
    slider = cell.findChild(_UniqueRollSlider)
    assert label.wordWrap() and label.text().endswith("…")
    assert label.text().count("\n") == 1
    assert label.toolTip() == row.text(3) == text
    assert label.geometry().bottom() < slider.geometry().top()
    assert cell.rect().contains(slider.geometry())
    assert tree.visualItemRect(row).height() >= cell.minimumSizeHint().height() + 9


def assert_geometry_converges(app, window, refresh=None):
    """Require a stable tail, including queued layout work, after every resize."""
    def state():
        return (
            window.geometry().getRect(),
            tuple((widget.geometry().getRect(), widget.isHidden())
                  for widget in window.findChildren(QWidget)),
            refresh.call_count if refresh is not None else 0,
        )

    samples = []
    stable = 0
    previous = None
    for _ in range(40):
        app.sendPostedEvents(None, QEvent.LayoutRequest)
        app.processEvents()
        current = state()
        samples.append((current[0], refresh.call_count if refresh is not None else 0))
        stable = stable + 1 if current == previous else 0
        if stable == 8:
            break
        previous = current
    else:
        pytest.fail(f"Layout did not converge in 40 event rounds: {samples[-12:]}")
    # An intermediate equal pair is insufficient: continue pumping events to
    # catch deferred scrollbar/reflow callbacks, including a two-state cycle.
    for _ in range(8):
        app.sendPostedEvents(None, QEvent.LayoutRequest)
        app.processEvents()
        assert state() == current


@pytest.mark.parametrize("available", [QRect(0, 0, 800, 600), QRect(0, 0, 1920, 1080)])
@pytest.mark.parametrize("count", [0, 1, 40])
@pytest.mark.parametrize("profile", ["small", "medium", "large"])
@pytest.mark.parametrize("version", ["poe1", "poe2"])
@pytest.mark.parametrize("size", [13, 24])
def test_trade_layout_converges_after_consecutive_resizes(
    qapp, tmp_path, monkeypatch, available, count, profile, version, size,
):
    from src.poetore.trade import TradeStatFilter
    from src.poetore.window_position import PlacementContext

    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": size}}})
    window = build_scenario("trade", tmp_path, version)
    window._app_config.setdefault("poetore", {})["result_font_size"] = profile
    window.apply_result_display_size()
    window._populate_stat_filters(tuple(
        TradeStatFilter(f"explicit.{i}", f"最大ライフとエナジーシールドが増加する {i} +#%",
                        120, "prefix" if i % 2 else "suffix", True, tier_tags=(1,))
        for i in range(count)
    ))
    refresh = Mock(wraps=window._refresh_trade_layout)
    monkeypatch.setattr(window, "_refresh_trade_layout", refresh)
    window.show_at_context(PlacementContext(available, available.center()), activate=False)
    for width in (647, 827, 1100, 760, 647, 827):
        window.resize(width, window.height())
        assert_geometry_converges(qapp, window, refresh)
        assert available.contains(window.frameGeometry())
        assert window._content_scroll.horizontalScrollBar().maximum() == 0


@pytest.mark.parametrize("all_categories", [False, True])
@pytest.mark.parametrize("size", [13, 24])
def test_category_choices_converge_when_reopened_on_different_screens(qapp, monkeypatch, all_categories, size):
    from src.poetore.poe2.desecration_overlay import CATEGORY_LABELS, CategoryChoiceOverlay

    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": size}}})
    screen = Mock()
    monkeypatch.setattr("src.poetore.poe2.desecration_overlay.QGuiApplication.screenAt", lambda _point: screen)
    window = CategoryChoiceOverlay()
    categories = tuple(CATEGORY_LABELS) if all_categories else ("quarterstaff", "amulet", "boots", "bow")
    for available in (QRect(0, 0, 800, 600), QRect(0, 0, 640, 240),
                      QRect(0, 0, 1920, 1080), QRect(0, 0, 800, 600)):
        window.hide()
        qapp.sendPostedEvents(None, QEvent.DeferredDelete)
        screen.availableGeometry.return_value = available
        window.show_categories(categories, available.bottomRight())
        assert_geometry_converges(qapp, window)
        assert available.contains(window.frameGeometry())
        assert window._button_area.horizontalScrollBar().maximum() == 0


class _TradeScreen(QObject):
    availableGeometryChanged = Signal(QRect)
    logicalDotsPerInchChanged = Signal(float)
    physicalDotsPerInchChanged = Signal(float)

    def __init__(self, geometry):
        super().__init__()
        self.geometry = geometry

    def availableGeometry(self):
        return QRect(self.geometry)


class _TradeWindowHandle(QObject):
    screenChanged = Signal(object)

    def __init__(self, screen):
        super().__init__()
        self.current_screen = screen

    def screen(self):
        return self.current_screen


@pytest.mark.parametrize("notify_screen_change", [False, True])
@pytest.mark.parametrize("small", [QRect(1920, 0, 800, 600), QRect(-800, 40, 800, 600)])
def test_trade_drag_between_screens_updates_limits_and_keeps_destination(
    qapp, qtbot, tmp_path, monkeypatch, small, notify_screen_change,
):
    from src.poetore.trade import TradeStatFilter
    from src.poetore.window_position import PlacementContext

    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 24}}})
    large = QRect(0, 0, 1920, 1080)
    large_screen, small_screen = _TradeScreen(large), _TradeScreen(small)
    handle = _TradeWindowHandle(large_screen)
    window = build_scenario("trade", tmp_path, "poe2")
    monkeypatch.setattr(window, "windowHandle", lambda: handle)
    monkeypatch.setattr(window, "screen", handle.screen)
    window._app_config.setdefault("poetore", {})["result_font_size"] = "small"
    window.apply_result_display_size()
    window._populate_stat_filters(tuple(
        TradeStatFilter(f"explicit.{i}", f"耐性Mod {i} +#%", i, "suffix", True)
        for i in range(40)
    ))
    context = PlacementContext(large, large.center())
    window.show_at_context(context, activate=False)
    assert_geometry_converges(qapp, window)
    large_height = window.height()
    assert large_height > small.height()

    for screen, available in ((small_screen, small), (large_screen, large)):
        qtbot.mousePress(window._title_bar, Qt.LeftButton, pos=QPoint(8, 8))
        handle.current_screen = screen
        if notify_screen_change:
            handle.screenChanged.emit(screen)
        before_drag_height = window.height()
        window.move(available.topLeft() + QPoint(24, 24))
        # Holding a drag must not resize/clamp the panel between pointer moves.
        QTest.qWait(200)
        assert window.height() == before_drag_height
        qtbot.mouseRelease(window._title_bar, Qt.LeftButton, pos=QPoint(8, 8))
        assert_geometry_converges(qapp, window)
        assert window.maximumHeight() == available.height() - 16
        assert available.contains(window.frameGeometry()), window.frameGeometry()
        assert window._placement_context is context
        if available == small:
            assert window.height() < large_height
            for width in (700, 760, 680):
                window.resize(width, window.height())
                assert_geometry_converges(qapp, window)
                assert small.contains(window.frameGeometry()), window.frameGeometry()
        else:
            assert window.height() > small.height()


@pytest.mark.parametrize("notification", ["available", "logical_dpi", "physical_dpi", "device_ratio"])
def test_trade_screen_metric_changes_reflow_without_a_width_change(
    qapp, qtbot, tmp_path, monkeypatch, notification,
):
    from src.poetore.window_position import PlacementContext

    screen = _TradeScreen(QRect(0, 0, 1920, 1080))
    handle = _TradeWindowHandle(screen)
    window = build_scenario("trade", tmp_path)
    monkeypatch.setattr(window, "windowHandle", lambda: handle)
    monkeypatch.setattr(window, "screen", handle.screen)
    window.show_at_context(PlacementContext(screen.geometry, screen.geometry.center()), activate=False)
    assert_geometry_converges(qapp, window)
    width = window.width()
    screen.geometry = QRect(0, 0, 1920, 600)
    if notification == "available":
        screen.availableGeometryChanged.emit(screen.geometry)
    elif notification == "logical_dpi":
        screen.logicalDotsPerInchChanged.emit(144)
    elif notification == "physical_dpi":
        screen.physicalDotsPerInchChanged.emit(144)
    else:
        qapp.sendEvent(window, QEvent(QEvent.DevicePixelRatioChange))
    qtbot.waitUntil(lambda: window.maximumHeight() == 584)
    assert_geometry_converges(qapp, window)
    assert window.width() == width
    assert screen.geometry.contains(window.frameGeometry())


def test_trade_screen_update_survives_active_layout_and_obs_collapse(qapp, qtbot, tmp_path, monkeypatch):
    from src.poetore.window_position import PlacementContext

    screen = _TradeScreen(QRect(0, 0, 1920, 1080))
    handle = _TradeWindowHandle(screen)
    window = build_scenario("trade", tmp_path)
    monkeypatch.setattr(window, "windowHandle", lambda: handle)
    monkeypatch.setattr(window, "screen", handle.screen)
    context = PlacementContext(screen.geometry, screen.geometry.center())
    window.show_at_context(context, activate=False)
    assert_geometry_converges(qapp, window)
    measure = window._fixed_layout_height

    def shrink_during_layout():
        monkeypatch.setattr(window, "_fixed_layout_height", measure)
        screen.geometry = QRect(0, 0, 1920, 600)
        screen.availableGeometryChanged.emit(screen.geometry)
        return measure()

    monkeypatch.setattr(window, "_fixed_layout_height", shrink_during_layout)
    window._adjust_window_height_to_mod_rows()
    qtbot.waitUntil(lambda: window.maximumHeight() == 584)
    assert_geometry_converges(qapp, window)
    assert screen.geometry.contains(window.frameGeometry())
    window.set_obs_streaming_mode(True)
    assert_geometry_converges(qapp, window)
    screen.geometry = QRect(0, 0, 800, 600)
    screen.availableGeometryChanged.emit(screen.geometry)
    qtbot.waitUntil(lambda: not window._trade_screen_update_pending)
    assert_geometry_converges(qapp, window)
    assert window.height() == window.maximumHeight() == 30
    window.show_at_context(context, activate=False)
    assert_geometry_converges(qapp, window)
    assert window.maximumHeight() == context.target_rect.height() - 16
    assert context.target_rect.contains(window.frameGeometry())
