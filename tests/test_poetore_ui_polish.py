"""Peer controls and anchored overlays stay usable across themes and fonts."""

from itertools import product
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QColor, QFontDatabase, QFontMetrics, QHelpEvent, QIcon, QImage, QPainter, QRegion,
    QTextLayout, QTextOption,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QLabel, QPushButton, QStyle, QStyleOptionButton, QStyleOptionSlider,
    QStyleOptionViewItem, QSystemTrayIcon, QWidget,
)

from src.app_font import bundled_font_path
from src.poetore.exchange_rate_settings import (
    CHAOS_ORB_ID, DEFAULT_RATE_PAIRS, DIVINE_ORB_ID, EXALTED_ORB_ID, MAX_RATE_PAIRS,
)
from src.poetore.official_exchange import DirectPairPrice, ExchangeSyncState
from src.ui.appearance import (
    PRESETS, apply_application_appearance, configure_appearance,
    current_appearance, requested_appearance, resolve_tokens,
)
from src.ui.dialog_theme import UI_METRICS, icon_button_stylesheet
from src.ui.toolbar_icons import chevron_icon, reload_icon
from src.update.release_client import ReleaseInfo
from tests.poetore_ui_scenarios import build_scenario, offline_ui, settle
from tests.test_theme_contrast_audit import contrast
from tests.test_theme_geometry_audit import geometry_failures
from tests.test_theme_painter_audit import inspect_paint


@pytest.mark.parametrize("font_size", [13, 24])
def test_trade_numeric_chips_fit_their_inputs_at_the_same_height(qapp, tmp_path, font_size):
    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": font_size}}})
    window = build_scenario("trade", tmp_path)
    chips = (
        window.item_level_tag, window.gem_level_tag, window.gem_quality_tag,
        window.gem_socket_tag, window.links_tag, window.map_tier_chip,
        window.unidentified_tier_chip, window.runemastered_tag,
    )
    window.item_level_tag.setValues(100, 100)
    window.gem_quality_tag.setValues(100)
    window.unidentified_tier_chip.setValue(99)
    for chip in chips:
        chip.show()
    settle(qapp, window)

    assert len({chip.height() for chip in chips}) == 1
    minimum = window.item_level_edit
    assert minimum.width() == window.item_level_max_edit.width() == window.gem_quality_edit.width()
    assert minimum.width() > window.gem_level_edit.width()
    assert window.gem_level_edit.width() > window.links_edit.width()
    assert not geometry_failures(window)

    toggle = window.item_level_toggle
    window.activateWindow()
    toggle.setFocus()
    assert toggle.hasFocus()
    toggle_with_focus = toggle.grab().toImage()
    QTest.keyClick(toggle, Qt.Key_Tab)
    assert minimum.hasFocus()
    assert toggle.grab().toImage() != toggle_with_focus
    editor_with_focus = minimum.grab().toImage()
    QTest.keyClick(minimum, Qt.Key_Tab)
    assert window.item_level_max_edit.hasFocus()
    assert minimum.grab().toImage() != editor_with_focus


def test_trade_fixed_chip_elides_at_flow_width(qapp, tmp_path):
    window = build_scenario("trade", tmp_path)
    chip = window.completion_reward_chip
    text = "完了報酬：" + "長い名前のアイテム" * 12
    chip.setText(text)
    chip.show()
    window.filter_chip_layout.setGeometry(QRect(0, 0, 190, 100))

    assert chip.width() <= 190
    assert chip._display_text(chip.contentsRect().width()).endswith("…")
    assert chip.text() == chip.toolTip() == text


def test_trade_logbook_areas_fit_the_narrow_panel(qapp, tmp_path):
    from src.poetore.window_position import PlacementContext

    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 24}}})
    window = build_scenario("trade", tmp_path, "poe1")
    selector = window.logbook_area_selector
    labels = tuple(f"エリア{index}：断たれた円環のドルイド" for index in range(1, 6))
    selector.setLabels(labels)
    window.logbook_area_container.show()
    available = QRect(0, 0, 800, 600)
    window.show_at_context(PlacementContext(available, available.center()), activate=False)
    settle(qapp, window)

    viewport = window._content_scroll.viewport()
    for button, label in zip(selector._buttons, labels):
        top_left = button.mapTo(window, QPoint()) - viewport.mapTo(window, QPoint())
        assert 0 <= top_left.x() <= viewport.width() - button.width()
        assert button.toolTip() == label
    selector._buttons[-1].click()
    assert selector._buttons[-1].isChecked()


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


@pytest.mark.parametrize("version", ["poe1", "poe2"])
@pytest.mark.parametrize("width", [500, 558])
def test_main_toolbar_groups_and_tab_order(qapp, tmp_path, version, width):
    apply_application_appearance(qapp, {})
    window = build_scenario("main", tmp_path, version)
    settle(qapp, window)
    window.resize(width, window.height())
    settle(qapp, window)

    version_buttons = (
        (window.heist_settings_button, window.map_mods_button)
        if version == "poe1"
        else (window.expedition_settings_button, window.desecration_settings_button)
    )
    left_buttons = (
        window.focus_button, window.memo_button, *version_buttons,
        window.cheat_sheets_button, window.settings_button,
    )
    panel = window.rate_panel
    assert window.rate_refresh_button is panel.refresh_button
    right_buttons = (panel.manage_button, panel.refresh_button)
    buttons = (*left_buttons, *right_buttons)
    assert tuple(button for button in window.header_action_buttons if button.isVisible()) == left_buttons[1:]
    assert window.width() == width
    assert all(button.isVisible() for button in buttons)

    rects = [QRect(button.mapTo(window, QPoint()), button.size()) for button in buttons]
    assert all(window.rect().contains(rect) for rect in rects)
    assert len({rect.center().y() for rect in rects}) == 1
    assert rects[0].left() == UI_METRICS.page_margin
    assert window.width() - rects[-1].right() - 1 == UI_METRICS.page_margin
    left_rects = rects[:-2]
    manage_rect, refresh_rect = rects[-2:]
    for first, second in zip(left_rects, left_rects[1:]):
        assert second.left() - first.right() - 1 == UI_METRICS.inline_gap
    assert refresh_rect.left() - manage_rect.right() - 1 == UI_METRICS.inline_gap
    assert manage_rect.left() - left_rects[-1].right() - 1 > UI_METRICS.inline_gap

    card_top = panel.card.mapTo(window, QPoint()).y()
    assert card_top - rects[0].bottom() - 1 == UI_METRICS.panel_padding

    def assert_tab_order(row_count):
        assert len(panel.row_widgets) == row_count
        deletes = [
            row.findChild(QPushButton, f"customRateDelete{index}")
            for index, row in enumerate(panel.row_widgets)
        ]
        tab_order = (window.title_bar.close_button, *buttons, *deletes)
        tab_order[0].setFocus(Qt.TabFocusReason)
        for current, following in zip(tab_order, tab_order[1:]):
            assert current.hasFocus()
            QTest.keyClick(current, Qt.Key_Tab)
            assert following.hasFocus(), following.accessibleName()

    assert_tab_order(1)
    ids = list(panel.catalog)
    window._rate_pair_store.add(version, ids[-2], ids[-1])
    window._rate_pairs_changed()
    settle(qapp, window)
    assert_tab_order(2)


def assert_peers(buttons, *, width=True):
    assert len(buttons) >= 2
    assert len({button.height() for button in buttons}) == 1, [(b.text(), b.size()) for b in buttons]
    if width:
        # QBoxLayout distributes an odd spare pixel between expanding peers.
        assert max(b.width() for b in buttons) - min(b.width() for b in buttons) <= 1, [(b.text(), b.size()) for b in buttons]


def _button_pixels(button):
    image = QImage(button.size(), QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    with QPainter(image) as painter:
        button.render(painter, QPoint(), QRegion(), QWidget.DrawChildren)
    return image


def _composite(ink, background):
    alpha = ink.alphaF()
    return QColor(*(round(ink.getRgb()[i] * alpha + background.getRgb()[i] * (1 - alpha))
                    for i in range(3)))


@pytest.mark.parametrize("appearance", [{"preset": name} for name in PRESETS] + [
    {"overrides": {"muted_text": "#BAA4D4"}},
])
def test_poetore_toolbar_icons_use_a_single_theme_ink(qapp, tmp_path, appearance):
    apply_application_appearance(qapp, {"appearance": appearance})
    window = build_scenario("main", tmp_path)
    window.config.pop("notified_update_version")
    window._sync_update_button_from_config()
    ink = QColor(resolve_tokens(appearance, "poetore").muted_text).getRgb()[:3]
    for button in (
        window.focus_button, *window.header_action_buttons,
        window.rate_panel.manage_button, window.rate_refresh_button, window.update_button,
    ):
        icon = button.icon()
        normal = icon.pixmap(button.iconSize()).toImage()
        pixels = [normal.pixelColor(x, y) for x in range(normal.width()) for y in range(normal.height())]
        visible = [pixel for pixel in pixels if pixel.alpha() >= 128]
        assert visible and all(
            all(abs(actual - expected) <= 3 for actual, expected in zip(pixel.getRgb()[:3], ink))
            for pixel in visible
        ), button.toolTip()
        assert sum(pixel.alphaF() for pixel in pixels) < len(pixels) * 0.28, button.toolTip()
        disabled = icon.pixmap(button.iconSize(), QIcon.Disabled).toImage()
        assert max(disabled.pixelColor(x, y).alpha() for x in range(disabled.width())
                   for y in range(disabled.height())) < max(pixel.alpha() for pixel in visible)


@pytest.mark.parametrize("preset", PRESETS)
def test_update_checking_status_has_contrast_while_disabled(qapp, tmp_path, monkeypatch, preset):
    appearance = {"preset": preset}
    apply_application_appearance(qapp, {"appearance": appearance})
    window = build_scenario("main", tmp_path)
    settle(qapp, window)
    monkeypatch.setattr(type(window._update_controller), "checking", True)
    window._sync_update_button_from_config()
    button = window.update_button
    assert not button.isEnabled()
    assert button.toolTip() == "アプリの更新を確認中…"
    image = _button_pixels(button)
    background = QColor(resolve_tokens(appearance, "poetore").background)
    assert max(
        contrast(_composite(image.pixelColor(x, y), background), background)
        for x in range(image.width()) for y in range(image.height())
    ) >= 3


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("version", ["poe1", "poe2"])
def test_toolbar_icons_render_interaction_states_without_resizing(qapp, tmp_path, preset, version):
    apply_application_appearance(qapp, {"appearance": {"preset": preset, "overrides": {"base_font_size": 13}}})
    main = build_scenario("main", tmp_path, version)
    main.config.pop("notified_update_version")
    main._sync_update_button_from_config()
    trade = build_scenario("trade", tmp_path, version)
    tokens = resolve_tokens({"preset": preset}, "poetore")
    focus_color = QColor(tokens.accent)
    rate_row = main.rate_panel.row_widgets[0]
    rate_delete = rate_row.findChild(QPushButton, "customRateDelete0")
    for window, buttons in (
        (main, (
            (main.focus_button, (36, 36)),
            *((button, (36, 36)) for button in main.header_action_buttons if not button.isHidden()),
            (main.update_button, (32, 20)),
            (main.title_bar.minimize_button, (32, 20)),
            (main.title_bar.close_button, (32, 20)),
            (main.rate_panel.manage_button, (36, 36)),
            (main.rate_refresh_button, (36, 36)),
            (rate_delete, (32, 32)),
        )),
        (trade, (
            (trade.league_popup_button, (33, 33)),
            (trade.league_refresh_button, (33, 33)),
            (trade.poetore_close_button, (33, 33)),
        )),
    ):
        settle(qapp, window)
        handle = window.windowHandle()
        for button, expected_size in buttons:
            original = button.geometry()
            assert (original.width(), original.height()) == expected_size

            def move_to(position):
                QTest.mouseMove(handle, position)
                qapp.processEvents()

            away = (rate_row.mapTo(main, QPoint(10, rate_row.height() // 2))
                    if button is rate_delete else QPoint(5, 5))
            button.clearFocus()
            move_to(away)
            idle = _button_pixels(button)
            edge = QPoint(button.width() // 2, 0)
            assert idle.pixelColor(edge).alpha() == 0, button.toolTip()
            icon_ink = [idle.pixelColor(p) for p in (
                button.rect().center() + QPoint(x, y) for x in range(-5, 6) for y in range(-5, 6)
            )]
            assert any(pixel.alpha() for pixel in icon_ink), button.toolTip()

            move_to(button.mapTo(window, button.rect().center()))
            assert button.underMouse()
            hovered = _button_pixels(button)
            hover_fill = hovered.pixelColor(edge)
            assert hover_fill.alpha() > 0, button.toolTip()
            assert hover_fill.red() == hover_fill.green() == hover_fill.blue()
            assert hovered.pixelColor(0, 0).alpha() == 0
            button.setDown(True)
            assert _button_pixels(button).pixelColor(edge).alpha() > hover_fill.alpha()
            button.setDown(False)

            surface = QColor(tokens.control if button is rate_delete else tokens.background)
            hover_background = _composite(hovered.pixelColor(edge + QPoint(0, 2)), surface)
            for background in (surface, hover_background):
                assert max(contrast(_composite(pixel, background), background) for pixel in icon_ink) >= 3
                assert contrast(focus_color, background) >= 3

            move_to(away)
            assert button.focusPolicy() & Qt.TabFocus
            button.setFocus(Qt.TabFocusReason)
            assert button.hasFocus()
            focused = _button_pixels(button)
            assert any(
                focused.pixelColor(edge + QPoint(0, y)) == focus_color
                and idle.pixelColor(edge + QPoint(0, y)).alpha() == 0
                for y in range(button.height() // 2)
            ), button.toolTip()
            assert button.geometry() == original
        window.hide()


def test_trade_title_bar_uses_theme_ink_and_anchors_tooltips_above_buttons(qapp, tmp_path):
    apply_application_appearance(qapp, {"appearance": {"preset": "poetore"}})
    window = build_scenario("trade", tmp_path)
    settle(qapp, window)
    buttons = (window.league_popup_button, window.league_refresh_button, window.poetore_close_button)
    initial_icons = [button.icon().pixmap(button.iconSize()).toImage() for button in buttons[:2]]

    apply_application_appearance(qapp, {"appearance": {"preset": "tokyo_night"}})
    window.apply_result_display_size()
    window.move(0, 80)
    qapp.processEvents()
    ink = resolve_tokens({"preset": "tokyo_night"}, "poetore").muted_text
    for button, initial, icon in zip(buttons, initial_icons, (chevron_icon, reload_icon)):
        image = button.icon().pixmap(button.iconSize()).toImage()
        assert image != initial
        assert image == icon(ink).pixmap(button.iconSize()).toImage()

    for button in buttons:
        center = button.rect().center()
        qapp.sendEvent(button, QHelpEvent(QEvent.ToolTip, center, button.mapToGlobal(center)))
        tooltip = button.findChild(QLabel, "toolbarTooltip")
        assert tooltip.isVisible() and tooltip.text() == button.toolTip()
        assert tooltip.geometry().bottom() < button.mapToGlobal(QPoint()).y()
        assert button.screen().availableGeometry().contains(tooltip.geometry())
        qapp.sendEvent(button, QEvent(QEvent.Leave))


def test_trade_numeric_chip_indicators_scale_with_font_and_display_size(qapp, tmp_path):
    def indicator_size(checkbox):
        option = QStyleOptionButton()
        checkbox.initStyleOption(option)
        return checkbox.style().subElementRect(QStyle.SE_CheckBoxIndicator, option, checkbox).size()

    native_size = indicator_size(QCheckBox())
    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 13}}})
    window = build_scenario("trade", tmp_path)
    toggles = (
        window.item_level_toggle, window.links_toggle, window.gem_level_toggle,
        window.gem_quality_toggle, window.gem_socket_toggle, window.map_tier_chip.toggle,
        window.runemastered_chip,
    )
    assert all(indicator_size(toggle) == native_size for toggle in toggles)

    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 24}}})
    previous_size = native_size
    for profile in ("small", "medium", "large"):
        window._app_config.setdefault("poetore", {})["result_font_size"] = profile
        window.apply_result_display_size()
        size = indicator_size(toggles[0])
        assert all(indicator_size(toggle) == size for toggle in toggles)
        assert size.width() > previous_size.width()
        assert size.height() > previous_size.height()
        previous_size = size

    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 13}}})
    window.apply_result_display_size()
    assert all(indicator_size(toggle) == native_size for toggle in toggles)


def test_trade_title_bar_icons_scale_with_font_and_display_size(qapp, tmp_path):
    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 13}}})
    window = build_scenario("trade", tmp_path)
    buttons = (window.league_popup_button, window.league_refresh_button)
    assert [button.iconSize().width() for button in buttons] == [20, 20]

    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 24}}})
    widths = []
    for profile in ("small", "medium", "large"):
        window._app_config.setdefault("poetore", {})["result_font_size"] = profile
        window.apply_result_display_size()
        settle(qapp, window)
        icon_size = buttons[0].iconSize()
        assert icon_size.width() > 24
        widths.append(icon_size.width())
        for button in buttons:
            assert button.iconSize() == icon_size
            assert icon_size.width() < button.width()
            assert button.icon().actualSize(icon_size) == icon_size
            pixmap = button.icon().pixmap(icon_size, 2)
            assert pixmap.devicePixelRatio() == 2
            assert pixmap.size() == icon_size * 2
    assert widths[0] < widths[1] < widths[2]

    window._league_refresh_started = True
    window._sync_league_refresh_button()
    refresh = window.league_refresh_button
    assert not refresh.isEnabled()
    assert refresh.icon().actualSize(refresh.iconSize(), QIcon.Disabled) == refresh.iconSize()

    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 13}}})
    window.apply_result_display_size()
    assert [button.iconSize().width() for button in buttons] == [20, 20]


def test_main_icon_focus_ring_appears_for_tab_and_clears_for_mouse(qapp, tmp_path):
    window = build_scenario("main", tmp_path)
    settle(qapp, window)
    window.activateWindow()
    qapp.processEvents()
    accent = QColor(resolve_tokens(current_appearance(), "poetore").accent)

    def has_ring(button):
        image = _button_pixels(button)
        return any(image.pixelColor(button.width() // 2, y) == accent for y in range(4))

    update = window.update_button
    minimize = window.title_bar.minimize_button
    assert window.isActiveWindow()
    assert not has_ring(update)
    assert not has_ring(minimize)

    update.setFocus(Qt.ActiveWindowFocusReason)
    assert update.hasFocus() and not has_ring(update)
    QTest.keyClick(update, Qt.Key_Tab)
    assert minimize.hasFocus() and has_ring(minimize)
    QTest.keyClick(minimize, Qt.Key_Backtab)
    assert update.hasFocus() and has_ring(update)

    refresh = window.rate_refresh_button
    refresh.setFocus(Qt.TabFocusReason)
    assert has_ring(refresh)
    window.rate_panel.refresh_callback = Mock()
    QTest.mouseClick(refresh, Qt.LeftButton)
    window.rate_panel.refresh_callback.assert_called_once_with(manual=True)
    assert refresh.hasFocus() and not has_ring(refresh)


def test_auxiliary_poetore_icon_buttons_render_transparently(qapp, tmp_path):
    from src.app_mode import POETORE_MODE
    from src.ui.app_theme import POETORE_THEME
    from src.ui.cheat_sheets import CheatSheetOverlay
    from src.ui.map_check import MapCheckWindow
    from src.ui.memo_dialog import MemoDialog

    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 13}}})
    exchange = build_scenario("exchange", tmp_path)
    settings = build_scenario("settings", tmp_path)
    map_check = MapCheckWindow({}, app_mode=POETORE_MODE)
    memo = MemoDialog(notes_path=str(tmp_path / "memo.json"), theme=POETORE_THEME, app_mode=POETORE_MODE)
    cheat_sheets = CheatSheetOverlay({}, theme=POETORE_THEME, app_mode=POETORE_MODE)
    for window, buttons in (
        (exchange, exchange.registered_widget._rows[0].findChildren(QPushButton)),
        (settings, (settings.hideout_minutes_up_button, settings.hideout_minutes_down_button,
                    settings.hideout_seconds_up_button, settings.hideout_seconds_down_button)),
        (map_check, [map_check.close_button]),
        (memo, [button for button in memo.findChildren(QPushButton) if button.text() == "✕"]),
        (cheat_sheets, [button for button in cheat_sheets.findChildren(QPushButton) if button.text() == "×"]),
    ):
        settle(qapp, window)
        QTest.mouseMove(window.windowHandle(), QPoint(1, 1))
        for button in buttons:
            button.clearFocus()
            idle = _button_pixels(button)
            assert idle.pixelColor(button.width() // 2, 0).alpha() == 0
            assert idle.pixelColor(0, button.height() // 2).alpha() == 0
        window.hide()


def test_icon_button_fill_uses_custom_appearance_and_preserves_checked_state(qapp):
    appearance = {"overrides": {"text": "#08A8DD"}}
    apply_application_appearance(qapp, {"appearance": appearance})
    button = QPushButton("×")
    button.setFixedSize(36, 36)
    button.setCheckable(True)
    button.setStyleSheet(icon_button_stylesheet())
    settle(qapp, button)
    point = QPoint(18, 2)
    button.clearFocus()
    assert _button_pixels(button).pixelColor(point).alpha() == 0
    button.setChecked(True)
    fill = _button_pixels(button).pixelColor(point)
    gray = resolve_tokens(appearance).icon_button_gray
    assert fill.alpha() > 0
    assert all(abs(channel - gray) <= 5 for channel in fill.getRgb()[:3])
    assert gray != resolve_tokens(None, "poetore").icon_button_gray
    button.setEnabled(False)
    disabled = _button_pixels(button)
    assert disabled.pixelColor(point).alpha() == 0
    ink = max(
        (disabled.pixelColor(x, y) for x in range(button.width()) for y in range(button.height())),
        key=QColor.alpha,
    )
    expected = QColor(resolve_tokens(appearance).disabled)
    assert ink.alpha() > 0
    assert all(abs(actual - target) <= 2 for actual, target in zip(ink.getRgb()[:3], expected.getRgb()[:3]))


@pytest.mark.parametrize("locked", [False, True])
def test_main_title_text_drag_respects_window_lock(qapp, tmp_path, locked):
    window = build_scenario("main", tmp_path)
    window.config["window_locked"] = locked
    settle(qapp, window)
    window.move(32, 40)
    handle = window.windowHandle()
    delta = QPoint(28, 16)

    for label in (window.title_label, window.mode_label):
        start = label.mapTo(window, label.rect().center())
        assert window.childAt(start) is window.title_bar
        original_pos = window.pos()
        QTest.mousePress(handle, Qt.LeftButton, Qt.NoModifier, start)
        QTest.mouseMove(handle, start + delta)
        assert window.pos() == original_pos + (QPoint() if locked else delta)
        release = start + delta if locked else start
        QTest.mouseRelease(handle, Qt.LeftButton, Qt.NoModifier, release)
        assert window.title_bar._drag_offset is None

    QTest.mouseDClick(handle, Qt.LeftButton, Qt.NoModifier, start)
    assert window.isVisible()
    assert not window.isMaximized()


@pytest.mark.parametrize("transition", ["drag", "drag_without_signal", "screen_changed"])
@pytest.mark.parametrize("start_small", [False, True])
def test_main_rates_reflow_after_screen_move(
    qapp, qtbot, tmp_path, monkeypatch, transition, start_small,
):
    large = _Screen(QRect(0, 0, 1920, 1080))
    small = _Screen(QRect(1920, 0, 800, 480))
    origin, destination = (small, large) if start_small else (large, small)
    handle = _WindowHandle(origin)
    monkeypatch.setattr(QApplication, "screenAt", lambda _point: handle.screen())
    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 24}}})
    window = build_scenario("main", tmp_path)
    monkeypatch.setattr(window, "windowHandle", lambda: handle)
    monkeypatch.setattr(window, "screen", handle.screen)
    window.move(origin.geometry.topLeft() + QPoint(24, 24))
    window._sync_update_button_from_config()
    ids = list(window.rate_panel.catalog)
    for index in range(MAX_RATE_PAIRS - 1):
        window._rate_pair_store.add(window.poe_version, ids[index], ids[index + MAX_RATE_PAIRS])
    window._rate_pairs_changed()
    settle(qapp, window)
    assert len(window.rate_panel.row_widgets) == MAX_RATE_PAIRS
    original_height = window.height()
    scroll = window._rate_scroll
    assert (scroll.verticalScrollBar().maximum() > 0) == start_small

    dragging = transition != "screen_changed"
    if dragging:
        qtbot.mousePress(window.title_bar, Qt.LeftButton, pos=QPoint(8, 8))
    handle.current_screen = destination
    window.move(destination.geometry.topLeft() + QPoint(24, 24))
    if transition != "drag_without_signal":
        handle.screenChanged.emit(destination)
    if dragging:
        QTest.qWait(200)
        assert window.height() == original_height
        qtbot.mouseRelease(window.title_bar, Qt.LeftButton, pos=QPoint(8, 8))

    qtbot.waitUntil(lambda: window.maximumHeight() == destination.geometry.height())
    assert_geometry_converges(qapp, window)
    assert destination.geometry.contains(window.frameGeometry()), window.frameGeometry()
    assert (scroll.verticalScrollBar().maximum() > 0) == (not start_small)
    assert scroll.horizontalScrollBar().maximum() == 0
    assert window.maximumHeight() == destination.geometry.height()
    assert (window.height() > original_height) == start_small
    assert window.rect().contains(QRect(window.update_button.mapTo(window, QPoint()), window.update_button.size()))
    refresh = window.rate_refresh_button
    assert window.rect().contains(QRect(refresh.mapTo(window, QPoint()), refresh.size()))
    last_delete = window.rate_panel.row_widgets[-1].findChild(
        QPushButton, f"customRateDelete{MAX_RATE_PAIRS - 1}"
    )
    scroll.ensureWidgetVisible(last_delete, 0, 0)
    viewport = scroll.viewport()
    assert viewport.rect().contains(QRect(last_delete.mapTo(viewport, QPoint()), last_delete.size()))


@pytest.mark.parametrize("notification", ["available", "logical_dpi", "physical_dpi", "device_ratio"])
def test_main_rates_reflow_when_current_screen_metrics_change(
    qapp, qtbot, tmp_path, monkeypatch, notification,
):
    screen = _Screen(QRect(0, 0, 1920, 1080))
    handle = _WindowHandle(screen)
    window = build_scenario("main", tmp_path)
    monkeypatch.setattr(window, "windowHandle", lambda: handle)
    monkeypatch.setattr(window, "screen", handle.screen)
    settle(qapp, window)
    width = window.width()

    position = QPoint(-60, 40)
    window.move(position)
    if notification == "available":
        screen.geometry = QRect(0, 0, 1920, 600)
        screen.availableGeometryChanged.emit(screen.geometry)
    elif notification == "logical_dpi":
        screen.logical_dpi = 144
        screen.logicalDotsPerInchChanged.emit(144)
    elif notification == "physical_dpi":
        screen.physical_dpi = 144
        screen.physicalDotsPerInchChanged.emit(144)
    else:
        new_ratio = window.devicePixelRatioF() * 1.25
        monkeypatch.setattr(window, "devicePixelRatioF", lambda: new_ratio)
        qapp.sendEvent(window, QEvent(QEvent.DevicePixelRatioChange))
    qtbot.waitUntil(lambda: screen.geometry.contains(window.frameGeometry()))
    assert window.maximumHeight() == screen.geometry.height()
    assert window.width() == width


@pytest.mark.parametrize("locked", [False, True])
def test_main_periodic_update_preserves_offscreen_position(qapp, tmp_path, locked):
    window = build_scenario("main", tmp_path)
    window.config.pop("notified_update_version")
    window._sync_update_button_from_config()
    window.config["window_locked"] = locked
    settle(qapp, window)
    assert window.update_button.toolTip() == "アプリの更新をチェック"
    position = QPoint(-60, 40)
    window.move(position)
    release = ReleaseInfo("99.99.99", "test", "https://example.com", "", "")

    window._handle_update_check_result(release, False)
    assert_geometry_converges(qapp, window)
    assert window.update_button.isVisible()
    assert window.update_button.toolTip() == "v99.99.99 に更新"
    assert window.pos() == position


@pytest.mark.parametrize("locked", [False, True])
def test_main_update_fits_at_screen_bottom_without_moving(qapp, tmp_path, monkeypatch, locked):
    screen = _Screen(QRect(0, 0, 800, 600))
    handle = _WindowHandle(screen)
    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 13}}})
    window = build_scenario("main", tmp_path)
    window.config.pop("notified_update_version")
    window._sync_update_button_from_config()
    monkeypatch.setattr(window, "windowHandle", lambda: handle)
    window.config["window_locked"] = locked
    settle(qapp, window)
    assert len(window.rate_panel.row_widgets) == 1
    original_size = window.size()
    assert window.update_button.toolTip() == "アプリの更新をチェック"
    position = QPoint(0, screen.geometry.bottom() - window.height() + 1)
    window.move(position)
    assert window.frameGeometry().bottom() == screen.geometry.bottom()
    release = ReleaseInfo("99.99.99", "test", "https://example.com", "", "")

    window._handle_update_check_result(release, False)
    assert_geometry_converges(qapp, window)

    assert window.pos() == position
    for button in (window.update_button, window.rate_panel.manage_button, window.title_bar.close_button):
        assert button.isVisible()
        assert screen.geometry.contains(QRect(button.mapToGlobal(QPoint()), button.size()))
    assert window.size() == original_size
    assert window._rate_scroll.verticalScrollBar().maximum() == 0


@pytest.mark.parametrize("locked", [False, True])
@pytest.mark.parametrize("action", ["tray", "rows", "unchanged_screen_notification"])
def test_main_same_screen_relayout_preserves_left_overlap(qapp, tmp_path, monkeypatch, locked, action):
    screen = _Screen(QRect(0, 0, 800, 600))
    handle = _WindowHandle(screen)
    window = build_scenario("main", tmp_path)
    monkeypatch.setattr(window, "windowHandle", lambda: handle)
    window.config["window_locked"] = locked
    settle(qapp, window)
    position = QPoint(-60, 40)
    window.move(position)

    if action == "tray":
        window._build_tray_icon()
        window._tray_notification_shown = True
        monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
        window.minimize_to_tray()
        assert not window.isVisible()
        window.restore_from_tray()
    elif action == "rows":
        window.rate_panel.render_rows()
    else:
        handle.screenChanged.emit(screen)
        screen.availableGeometryChanged.emit(screen.geometry)
        qapp.sendEvent(window, QEvent(QEvent.DevicePixelRatioChange))
        QTest.qWait(200)
    assert_geometry_converges(qapp, window)

    assert window.isVisible()
    assert window.pos() == position


@pytest.mark.parametrize("locked", [False, True])
@pytest.mark.parametrize("action", ["tray", "rows"])
def test_main_same_screen_relayout_recovers_offscreen_controls(qapp, tmp_path, monkeypatch, locked, action):
    available = QRect(0, 0, 800, 600)
    handle = _WindowHandle(_Screen(available))
    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 13}}})
    window = build_scenario("main", tmp_path)
    monkeypatch.setattr(window, "windowHandle", lambda: handle)
    window.config["window_locked"] = locked
    window._sync_update_button_from_config()
    settle(qapp, window)
    manage = window.rate_panel.manage_button
    position = QPoint(0, available.bottom() + 1 - manage.mapTo(window, QPoint()).y())
    window.move(position)
    controls = (
        window.title_bar.close_button, window.title_bar.minimize_button,
        window.rate_panel.manage_button, window.rate_refresh_button, window.update_button,
    )
    assert all(button.isVisible() for button in controls)
    close = window.title_bar.close_button
    assert available.intersects(QRect(close.mapToGlobal(QPoint()), close.size()))
    assert not available.intersects(QRect(manage.mapToGlobal(QPoint()), manage.size()))

    if action == "tray":
        window._build_tray_icon()
        window._tray_notification_shown = True
        monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: True)
        window.minimize_to_tray()
        assert not window.isVisible()
        window.restore_from_tray()
    else:
        window.rate_panel.render_rows()
    assert_geometry_converges(qapp, window)

    assert window.isVisible()
    assert window.x() == position.x()
    assert window.y() < position.y()
    assert window.frameGeometry().bottom() == available.bottom()
    assert window._rate_scroll.viewport().height() > 0
    for button in controls:
        assert available.contains(QRect(button.mapToGlobal(QPoint()), button.size()))


def test_main_same_screen_relayout_preserves_partially_visible_management(qapp, tmp_path, monkeypatch):
    available = QRect(0, 0, 800, 600)
    handle = _WindowHandle(_Screen(available))
    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 13}}})
    window = build_scenario("main", tmp_path)
    monkeypatch.setattr(window, "windowHandle", lambda: handle)
    settle(qapp, window)
    manage = window.rate_panel.manage_button
    position = QPoint(0, available.bottom() - manage.mapTo(window, manage.rect().center()).y())
    window.move(position)

    window.rate_panel.render_rows()
    assert_geometry_converges(qapp, window)

    rect = QRect(manage.mapToGlobal(QPoint()), manage.size())
    assert available.intersects(rect) and not available.contains(rect)
    assert window.pos() == position


def test_main_update_action_states_keep_compact_height(qapp, tmp_path, monkeypatch):
    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 13}}})
    window = build_scenario("main", tmp_path)
    settle(qapp, window)
    button = window.update_button
    assert button.isVisible()
    assert window.findChild(QPushButton, "poetoreUpdateButton") is None
    compact_height = window.height()
    compact_viewport_height = window._rate_scroll.viewport().height()
    for version, checking, title in (
        ("", False, "アプリの更新をチェック"),
        ("", True, "アプリの更新を確認中…"),
        ("99.99.99", False, "v99.99.99 に更新"),
    ):
        window.config["notified_update_version"] = version
        monkeypatch.setattr(type(window._update_controller), "checking", checking)
        window._sync_update_button_from_config()
        assert_geometry_converges(qapp, window)
        assert button.isVisible() and button.toolTip() == title
        assert window.height() == compact_height
        assert window._rate_scroll.viewport().height() == compact_viewport_height


@pytest.mark.parametrize("preset", [*PRESETS, "custom"])
@pytest.mark.parametrize("version", ["poe1", "poe2"])
def test_main_large_font_fits_small_screen(qapp, tmp_path, monkeypatch, request, preset, version):
    available = QRect(0, 0, 800, 480)
    handle = _WindowHandle(_Screen(available))
    overrides = {"base_font_size": 24}
    if preset == "custom":
        font_id = QFontDatabase.addApplicationFont(
            str(bundled_font_path().with_name("visitor1.ttf"))
        )
        request.addfinalizer(lambda: QFontDatabase.removeApplicationFont(font_id))
        overrides.update({
            "font_family": QFontDatabase.applicationFontFamilies(font_id)[0],
            "accent": "#C68CFF",
        })
    apply_application_appearance(qapp, {
        "appearance": {"preset": "default" if preset == "custom" else preset, "overrides": overrides},
    })
    window = build_scenario("main", tmp_path, version)
    monkeypatch.setattr(window, "windowHandle", lambda: handle)
    window._sync_update_button_from_config()
    window._update_focus_button_state(True)
    window._update_focus_status("隠れ家滞在通知\nON（エリア待ち）")
    settle(qapp, window)

    buttons = [button for button in window.header_action_buttons if button.isVisibleTo(window)]
    assert all(button.width() == button.height() == window.focus_button.height() for button in buttons)
    assert available.contains(window.frameGeometry())
    assert window.title_bar.rect().contains(window.title_label.geometry())
    assert window.title_bar.rect().contains(window.mode_label.geometry())
    assert window._rate_scroll.verticalScrollBar().maximum() == 0
    assert not geometry_failures(window)

    store = window._rate_pair_store
    ids = list(window.rate_panel.catalog)
    for index in range(MAX_RATE_PAIRS - 1):
        store.add(version, ids[index], ids[index + MAX_RATE_PAIRS])
    window._rate_pairs_changed()
    settle(qapp, window)

    assert available.contains(window.frameGeometry())
    scroll = window._rate_scroll
    assert scroll.verticalScrollBar().maximum() > 0
    assert scroll.horizontalScrollBar().maximum() == 0
    for control in (window.focus_button, *buttons, window.update_button):
        assert window.rect().contains(QRect(control.mapTo(window, QPoint()), control.size()))
    last_row = window.rate_panel.row_widgets[-1]
    scroll.ensureWidgetVisible(last_row, 0, 0)
    viewport = scroll.viewport()
    assert viewport.rect().contains(QRect(last_row.mapTo(viewport, QPoint()), last_row.size()))

    for _ in range(MAX_RATE_PAIRS - 1):
        store.remove(version, 1)
    window._rate_pairs_changed()
    settle(qapp, window)
    assert window.height() < available.height()
    assert scroll.verticalScrollBar().maximum() == 0

    if preset == "custom":
        assert window.title_label.palette().color(window.title_label.foregroundRole()).name() == "#c68cff"


def _available_sync_state(version, league):
    return ExchangeSyncState(version, league, 720, 720, 0, False, True)


@pytest.mark.parametrize("size", [13, 24])
@pytest.mark.parametrize("version", ["poe1", "poe2"])
@pytest.mark.parametrize("long_quotes", [False, True])
def test_main_rates_fit_small_screen(qapp, tmp_path, monkeypatch, size, version, long_quotes):
    available = QRect(0, 0, 800, 600)
    handle = _WindowHandle(_Screen(available))
    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": size}}})
    window = build_scenario("main", tmp_path, version)
    monkeypatch.setattr(window, "windowHandle", lambda: handle)
    right = DEFAULT_RATE_PAIRS[version].right_item_id
    other = EXALTED_ORB_ID if right == CHAOS_ORB_ID else CHAOS_ORB_ID
    prices = {
        (DIVINE_ORB_ID, right): 54_000.2 if long_quotes else 197.2,
        (other, right): 7.4,
        (right, DIVINE_ORB_ID): 0.00001852 if long_quotes else 0.0057,
    }
    window.rate_panel.service = Mock(
        sync_state=_available_sync_state,
        direct_pair=lambda _version, _league, left, right: DirectPairPrice(
            "available", left, right, prices[left, right], 720,
        ),
    )
    for left, right in list(prices)[1:]:
        window._rate_pair_store.add(version, left, right)
    window._rate_pairs_changed()
    settle(qapp, window)

    assert available.contains(window.frameGeometry())
    assert window._rate_scroll.horizontalScrollBar().maximum() == 0
    assert window._rate_scroll.verticalScrollBar().maximum() == 0
    assert not geometry_failures(window)
    value_columns = set()
    prefix_starts = set()
    for index, row in enumerate(window.rate_panel.row_widgets):
        for side in ("Left", "Right"):
            label = row.findChild(QLabel, f"customRate{side}Name{index}")
            assert label.toolTip() == "" and label.accessibleName() == label.text()
            if not long_quotes:
                assert label.fontMetrics().horizontalAdvance(label.text()) <= label.width()
        value = row.findChild(QLabel, f"customRateValue{index}")
        bounds = []
        assert not inspect_paint(value, (value.text(),), text_bounds=bounds)
        (text_rect,) = bounds
        prefix_starts.add(value.mapTo(window, text_rect.topLeft()).x())
        value_columns.add((value.mapTo(window, QPoint()).x(), value.width()))
    assert len(value_columns) == 1
    assert len(prefix_starts) == 1


def test_main_large_rate_keeps_window_and_controls_within_small_screen(qapp, tmp_path, monkeypatch):
    screen = _Screen(QRect(0, 0, 800, 600))
    handle = _WindowHandle(screen)
    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 24}}})
    window = build_scenario("main", tmp_path, "poe1")
    monkeypatch.setattr(window, "windowHandle", lambda: handle)
    window.move(screen.geometry.topLeft())
    ids = list(window.rate_panel.catalog)
    for index in range(MAX_RATE_PAIRS - 1):
        window._rate_pair_store.add(window.poe_version, ids[index], ids[index + MAX_RATE_PAIRS])
    window.rate_panel.service = Mock(
        sync_state=_available_sync_state,
        direct_pair=lambda _version, _league, left, right: DirectPairPrice(
            "available", left, right, 100_000_000.1, 720,
        ),
    )
    window._rate_pairs_changed()
    settle(qapp, window)
    assert_geometry_converges(qapp, window)

    assert len(window.rate_panel.row_widgets) == MAX_RATE_PAIRS
    value = window.rate_panel.row_widgets[0].findChild(QLabel, "customRateValue0")
    assert "100,000,000.1" in value.text() and value.toolTip() == ""
    assert window.width() <= screen.geometry.width()
    for button in (window.title_bar.close_button, window.title_bar.minimize_button, window.rate_panel.manage_button):
        assert button.isVisible()
        assert screen.geometry.contains(QRect(button.mapToGlobal(QPoint()), button.size()))
    assert window._rate_scroll.horizontalScrollBar().maximum() == 0
    scroll = window._rate_scroll.verticalScrollBar()
    assert scroll.maximum() > 0
    scroll.setValue(scroll.maximum())
    manage = window.rate_panel.manage_button
    assert manage.visibleRegion().contains(manage.rect())
    assert screen.geometry.contains(QRect(manage.mapToGlobal(QPoint()), manage.size()))

    rows = window.rate_panel.row_widgets
    previous = rows[-2].findChild(QPushButton, f"customRateDelete{MAX_RATE_PAIRS - 2}")
    delete = rows[-1].findChild(QPushButton, f"customRateDelete{MAX_RATE_PAIRS - 1}")
    previous.setFocus(Qt.TabFocusReason)
    QTest.keyClick(previous, Qt.Key_Tab)
    assert delete.hasFocus() and delete.visibleRegion().contains(delete.rect())
    pairs = window._rate_pair_store.pairs(window.poe_version)
    QTest.keyClick(delete, Qt.Key_Space)
    assert window._rate_pair_store.pairs(window.poe_version) == pairs[:-1]
    assert len(window.rate_panel.row_widgets) == MAX_RATE_PAIRS - 1


@pytest.mark.parametrize("width,height", [(800, 600), (640, 480)])
@pytest.mark.parametrize("locked", [False, True])
def test_main_rows_added_at_right_edge_keep_delete_reachable(qapp, tmp_path, monkeypatch, locked, width, height):
    available = QRect(0, 0, width, height)
    handle = _WindowHandle(_Screen(available))
    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 24}}})
    window = build_scenario("main", tmp_path)
    monkeypatch.setattr(window, "windowHandle", lambda: handle)
    window.config["window_locked"] = locked
    store = window._rate_pair_store
    store.remove(window.poe_version, 0)
    window._rate_pairs_changed()
    settle(qapp, window)
    assert not window.rate_panel.row_widgets
    window.move(width - window.width(), 0)
    position = window.pos()
    assert window.frameGeometry().right() == available.right()

    ids = list(window.rate_panel.catalog)
    for index in range(MAX_RATE_PAIRS):
        store.add(window.poe_version, ids[index], ids[index + MAX_RATE_PAIRS])
    window.rate_panel.service = Mock(
        sync_state=_available_sync_state,
        direct_pair=lambda _version, _league, left, right: DirectPairPrice(
            "available", left, right, 197.2, 720,
        ),
    )
    window._rate_pairs_changed()
    assert_geometry_converges(qapp, window)

    assert window.pos() == position
    assert available.contains(window.frameGeometry())
    scroll = window._rate_scroll
    bar = scroll.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(bar.maximum())
    last_row = window.rate_panel.row_widgets[-1]
    delete = last_row.findChild(QPushButton, f"customRateDelete{MAX_RATE_PAIRS - 1}")
    viewport = scroll.viewport()
    assert scroll.widget().width() == viewport.width()
    assert viewport.rect().contains(QRect(delete.mapTo(viewport, QPoint()), delete.size()))
    assert delete.visibleRegion().contains(delete.rect())
    assert scroll.horizontalScrollBar().maximum() == 0

    target = delete.mapTo(window, delete.rect().center())
    native_handle = QWidget.windowHandle(window)
    QTest.mouseMove(native_handle, window.title_bar.rect().center())
    QTest.mouseMove(native_handle, target)
    QTest.mouseClick(native_handle, Qt.LeftButton, pos=target)
    assert len(store.pairs(window.poe_version)) == MAX_RATE_PAIRS - 1


@pytest.mark.parametrize(
    ("price", "wide_quote", "narrow_quote"),
    [
        pytest.param(0.00001234, "0.00001234", "0.00001234", id="tiny"),
        pytest.param(0.0057, "0.0057", "0.0057", id="subunit"),
        pytest.param(100_000_000_000.1, "100,000,000,000.1", "100,000,000,…", id="large"),
        pytest.param(197.2, "197.2", "197.2", id="normal"),
    ],
)
@pytest.mark.parametrize("narrow", [False, True])
def test_main_rate_paints_full_or_explicitly_elided_quote(
    qapp, tmp_path, monkeypatch, price, wide_quote, narrow_quote, narrow,
):
    available = QRect(0, 0, 800, 600) if narrow else QRect(0, 0, 1920, 1080)
    handle = _WindowHandle(_Screen(available))
    appearance = {"overrides": {"base_font_size": 24}} if narrow else {}
    apply_application_appearance(qapp, {"appearance": appearance})
    window = build_scenario("main", tmp_path)
    monkeypatch.setattr(window, "windowHandle", lambda: handle)
    window.rate_panel.service = Mock(
        sync_state=_available_sync_state,
        direct_pair=lambda _version, _league, left, right: DirectPairPrice(
            "available", left, right, price, 720,
        ),
    )
    window._rate_pairs_changed()
    settle(qapp, window)

    value = window.rate_panel.row_widgets[0].findChild(QLabel, "customRateValue0")
    assert value.text() == f"1 ＝ {wide_quote}" and value.toolTip() == ""
    if narrow:
        window.resize(500, window.height())
        assert_geometry_converges(qapp, window)
        assert window.width() == 500
        assert not inspect_paint(value, (f"1 ＝ {narrow_quote}",), centered=True)
        window.resize(available.width(), window.height())
        assert_geometry_converges(qapp, window)
        assert window.width() == available.width()
    assert not inspect_paint(value, (f"1 ＝ {wide_quote}",), centered=True)


def _peer_geometry_cases():
    keys = (
        "settings", "exchange", "expedition", "desecration", "heist",
        "main", "trade", "category", "map_manager", "map",
    )
    for key, version, size, preset in product(keys, ("poe1", "poe2"), (13, 24), PRESETS):
        # Keep both sizes and games for every screen in the default preset.
        # Keep all presets for title-bar, OBS and Map Mod regressions, and
        # sample every palette with the category buttons.
        representative = preset == "default" or key in ("main", "trade", "category", "map_manager", "map")
        yield pytest.param(
            key, version, size, preset,
            marks=() if representative else pytest.mark.qt_matrix,
        )


@pytest.mark.parametrize("key,version,size,preset", tuple(_peer_geometry_cases()))
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
        manage = window.rate_panel.manage_button
        assert manage.width() == manage.height() == UI_METRICS.toolbar_size
        assert not manage.icon().isNull()
    elif key == "trade":
        assert_peers(window.trade_preset_combo._buttons)
        assert_peers([window.league_popup_button, window.league_refresh_button, window.poetore_close_button])
        assert_peers([window.mod_conditions_toggle, window.clear_mod_conditions_button,
                      window.hidden_mods_toggle, window.mod_sources_toggle], width=False)
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
        scroll = window.table if key == "map_manager" else window.scroll
        assert scroll.horizontalScrollBar().maximum() == 0
        if key == "map_manager":
            group = window.table.cellWidget(0, window.table.columnCount() - 1)
            buttons = group.findChildren(QPushButton)
            assert_peers(buttons)
            assert all(group.rect().contains(button.geometry()) for button in buttons)
            viewport = window.table.viewport()
            assert all(viewport.rect().contains(QRect(button.mapTo(viewport, QPoint()), button.size()))
                       for button in buttons)
            assert window.rect().contains(
                QRect(window.regex_search.mapTo(window, QPoint()), window.regex_search.size())
            )
            scrollbar = window.table.verticalScrollBar()
            assert scrollbar.isVisible()
            option = QStyleOptionSlider()
            scrollbar.initStyleOption(option)
            for part in (QStyle.SC_ScrollBarGroove, QStyle.SC_ScrollBarSlider):
                bounds = scrollbar.style().subControlRect(QStyle.CC_ScrollBar, option, part, scrollbar)
                assert scrollbar.mapTo(window.table, bounds.topLeft()).y() == viewport.geometry().top()
            header = window.table.horizontalHeader().geometry()
            fill = window.table.grab()
            pixels = fill.toImage()
            scale = fill.devicePixelRatio()
            gutter_x = scrollbar.mapTo(window.table, QPoint(scrollbar.width() // 2, 0)).x()
            for y in (header.center().y(), header.bottom()):
                expected = pixels.pixelColor(
                    round((header.right() - UI_METRICS.control_gap) * scale), round(y * scale)
                )
                assert all(pixels.pixelColor(round(x * scale), round(y * scale)) == expected
                           for x in range(header.right(), gutter_x + 1))


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


@pytest.mark.parametrize("official_amount, words", [
    (None, ("poe.ninja", "参考価格")),
    (92, ("カレンシー交換", "直近価格")),
    (12500, ("カレンシー交換", "直近価格")),
])
def test_trade_reference_price_heading_wraps_only_between_words(qapp, tmp_path, official_amount, words):
    from src.poetore.official_exchange import CHAOS
    from src.poetore.poe_ninja import PoeNinjaPrice
    from src.poetore.window_position import PlacementContext

    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 24}}})
    window = build_scenario("trade", tmp_path)
    ninja = PoeNinjaPrice("Sample", None, 100, (80, 90, 100), "https://example.invalid/ninja")
    official = None if official_amount is None else Mock(
        status="accepted_direct", display_amount=official_amount, display_currency=CHAOS,
    )
    window._show_reference_price(window._poe_ninja_item_key, ninja, official)
    available = QRect(0, 0, 800, 600)
    window.show_at_context(PlacementContext(available, available.center()), activate=False)
    settle(qapp, window)

    heading = window.poe_ninja_price_label
    text = heading.text()
    layout = QTextLayout(text, heading.font())
    option = QTextOption()
    option.setWrapMode(QTextOption.WordWrap if heading.wordWrap() else QTextOption.NoWrap)
    layout.setTextOption(option)
    lines = []
    layout.beginLayout()
    while (line := layout.createLine()).isValid():
        line.setLineWidth(heading.contentsRect().width())
        assert line.naturalTextWidth() <= heading.contentsRect().width()
        line_text = text[line.textStart():line.textStart() + line.textLength()]
        lines.append(line_text.replace("\u2060", "").strip())
    layout.endLayout()
    assert lines in [[" ".join(words)], list(words)]
    assert heading.height() >= heading.heightForWidth(heading.width())
    viewport = window._content_scroll.viewport()
    for widget in (heading, window.poe_ninja_trend_label,
                   window.poe_ninja_trend_chart, window.poe_ninja_open_button):
        assert viewport.rect().contains(QRect(widget.mapTo(viewport, QPoint()), widget.size()))


def test_trade_remember_checkbox_fits_with_scrollbar_and_right_margin(qapp, tmp_path):
    from src.poetore.trade import TradeStatFilter
    from src.poetore.window_position import PlacementContext

    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 13}}})
    window = build_scenario("trade", tmp_path)
    window._populate_stat_filters(tuple(
        TradeStatFilter(f"explicit.{index}", f"Mod {index + 1} +#%", 45, "prefix", index < 3)
        for index in range(19)
    ))
    available = QRect(0, 0, 800, 600)
    window.show_at_context(PlacementContext(available, available.center()), activate=False)
    settle(qapp, window)

    scroll = window._content_scroll
    assert scroll.verticalScrollBar().isVisible()
    checkbox = window.remember_trade_options_checkbox
    scroll.ensureWidgetVisible(checkbox, 0, 0)
    qapp.processEvents()
    viewport = scroll.viewport()
    checkbox_rect = QRect(checkbox.mapTo(viewport, QPoint()), checkbox.size())
    assert viewport.rect().contains(checkbox_rect)
    assert viewport.rect().right() - checkbox_rect.right() >= UI_METRICS.overlay_gap

    option = QStyleOptionButton()
    checkbox.initStyleOption(option)
    text_rect = checkbox.style().subElementRect(QStyle.SE_CheckBoxContents, option, checkbox)
    assert text_rect.width() >= checkbox.fontMetrics().horizontalAdvance(checkbox.text())
    assert viewport.rect().contains(text_rect.translated(checkbox_rect.topLeft()))


@pytest.mark.parametrize("version", ["poe1", "poe2"])
@pytest.mark.parametrize("profile", ["small", "medium", "large"])
@pytest.mark.parametrize("available", [QRect(0, 0, 800, 600), QRect(-960, 40, 800, 600)])
def test_trade_large_font_fits_small_screen_and_all_controls_remain_reachable(
    qapp, tmp_path, version, profile, available,
):
    from src.poetore.poe_ninja import PoeNinjaPrice
    from src.poetore.window_position import PlacementContext

    apply_application_appearance(qapp, {"appearance": {"overrides": {"base_font_size": 24}}})
    window = build_scenario("trade", tmp_path, version)
    window._app_config.setdefault("poetore", {})["result_font_size"] = profile
    window.apply_result_display_size()
    window._show_poe_ninja_price(
        window._poe_ninja_item_key,
        PoeNinjaPrice("Sample", None, 100, (80, 90, 100), "https://example.invalid/ninja"),
    )
    context = PlacementContext(available, available.bottomRight())
    window.show_at_context(context, activate=False)
    settle(qapp, window)
    assert available.contains(window.frameGeometry()), window.frameGeometry()
    scroll = window._content_scroll
    assert scroll.horizontalScrollBar().maximum() == 0
    assert scroll.verticalScrollBar().maximum() > 0
    for control in (window.item_header, window.poe_ninja_open_button,
                    window.mod_conditions_toggle, window.price_button,
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
    assert "Mod数値：−10%まで" in window.search_range_combo.toolTip()
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
    assert window.search_range_combo.currentText() == "Mod数値：−10%まで"


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
    assert window.search_range_combo.currentText() == "Mod数値：−10%まで"


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


# Keep the full resize-convergence regression across screen limits and row counts.
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


class _Screen(QObject):
    availableGeometryChanged = Signal(QRect)
    logicalDotsPerInchChanged = Signal(float)
    physicalDotsPerInchChanged = Signal(float)

    def __init__(self, geometry):
        super().__init__()
        self.geometry = geometry
        self.logical_dpi = self.physical_dpi = 96

    def availableGeometry(self):
        return QRect(self.geometry)

    def logicalDotsPerInch(self):
        return self.logical_dpi

    def physicalDotsPerInch(self):
        return self.physical_dpi


class _WindowHandle(QObject):
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
    large_screen, small_screen = _Screen(large), _Screen(small)
    handle = _WindowHandle(large_screen)
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

    screen = _Screen(QRect(0, 0, 1920, 1080))
    handle = _WindowHandle(screen)
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

    screen = _Screen(QRect(0, 0, 1920, 1080))
    handle = _WindowHandle(screen)
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
