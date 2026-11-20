"""Offline widget scenarios shared by layout tests and manual PNG captures.

Run: python -m tests.poetore_ui_scenarios before|after OUTPUT_DIRECTORY
"""

from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from PySide6.QtCore import QEvent, QPoint
from PySide6.QtWidgets import QApplication, QDialog

from tests.test_theme_geometry_audit import _window


SCENARIOS = (
    ("main", "poetore_mode_window", "PoetoreModeWindow"),
    ("settings", "poetore_settings_dialog", "PoetoreSettingsDialog"),
    ("exchange", "exchange_rate_management_dialog", "ExchangeRateManagementDialog"),
    ("expedition", "expedition_settings_dialog", "ExpeditionSettingsDialog"),
    ("desecration", "desecration_settings_dialog", "DesecrationSettingsDialog"),
    ("heist", "heist_settings_dialog", "HeistSettingsDialog"),
    ("map_manager", "map_check", "MapModManagerDialog"),
    ("map", "map_check", "MapCheckWindow"),
    ("trade", None, None),
    ("category", None, None),
)

MAP_ITEM_TEXT = """アイテムクラス: マップ
レアリティ: レア
深淵の地図
Map (Tier 16)
--------
アイテムレベル: 83
--------
{ プレフィックスモッド (ティア: 1) }
レアモンスターの数が25%増加する
{ サフィックスモッド (ティア: 1) }
全てのプレイヤーの命中力が25%低下する
{ サフィックスモッド (ティア: 1) }
モンスターはアタックによるヒット時に重傷を付与する
{ サフィックスモッド (ティア: 1) }
モンスターはヒット時に盲目を付与する
{ サフィックスモッド (ティア: 1) }
この地図にだけ存在する未知の効果
"""


@contextmanager
def offline_ui():
    with ExitStack() as stack:
        for target in (
            "src.ui.poetore_settings_dialog.PoetoreSettingsDialog._refresh_trade_leagues",
            "src.poetore.ui.PoetoreWindow._close_if_focus_is_still_outside",
            "src.poetore.ui.PoetoreWindow._start_outside_click_listener",
            "src.poetore.exchange_icon_cache.ExchangeIconCache.request",
            "src.utils.config_manager.ConfigManager.save_config",
        ):
            stack.enter_context(patch(target, return_value=Mock()))
        stack.enter_context(patch("src.ui.map_check.MapCheckWindow.event", QDialog.event))
        yield


def build_scenario(key, tmp_path, version="poe2", *, app_mode="poetore"):
    if key == "map":
        from src.poetore.map_check import default_map_check_config, entries_by_stat_id, set_decision
        from src.poetore.parser import parse_item_text
        from src.poetore.window_position import PlacementContext
        from src.ui.map_check import MapCheckWindow

        config = default_map_check_config()
        config["show_new_stats"] = True
        lookup = entries_by_stat_id()
        modifiers = parse_item_text(MAP_ITEM_TEXT).modifiers
        recognized = [lookup[mod.stat_id].key for mod in modifiers if mod.stat_id in lookup]
        for mod_key, decision in zip(recognized, ("d", "w", "g", "s"), strict=True):
            set_decision(config, mod_key, decision)
        window = MapCheckWindow(config, app_mode=app_mode)
        available = window.screen().availableGeometry()
        window._placement_context = PlacementContext(available, available.center())
        with patch("src.ui.map_check.read_item_clipboard", return_value=MAP_ITEM_TEXT):
            window._consume_clipboard()
        return window
    if key == "trade":
        from src.poetore.ui import PoetoreWindow
        from src.poetore.trade import PriceListing, PriceResult, TradeStatFilter
        from src.poetore.models import ParsedItem
        window = PoetoreWindow(app_config={"poe_version": version})
        window._update_item_header(ParsedItem("Body Armours", "Rare", "黄昏の守り", "Vaal Regalia", "armour.chest"))
        window._populate_stat_filters((
            TradeStatFilter("explicit.stat_1", "最大ライフ +#", 120, "prefix", True, tier_tags=(1,)),
            TradeStatFilter("explicit.stat_2", "火耐性 +#%", 45, "suffix", True, tier_tags=(2,)),
            TradeStatFilter("explicit.stat_3", "冷気耐性 +#%", 40, "suffix", False, tier_tags=(3,)),
        ))
        window._show_price_result(PriceResult("Standard", "sample", 3, (
            PriceListing(80, "chaos"), PriceListing(100, "chaos"), PriceListing(120, "chaos"),
        )))
        return window
    if key == "category":
        from src.poetore.poe2.desecration_overlay import CategoryChoiceOverlay, CATEGORY_LABELS
        window = CategoryChoiceOverlay()
        window.show_categories(tuple(CATEGORY_LABELS), QPoint(0, 0))
        return window
    module, name = next((module, name) for scenario, module, name in SCENARIOS if scenario == key)
    return _window(module, name, version, tmp_path)


def settle(app, window):
    window.show()
    for _ in range(8):
        app.sendPostedEvents(None, QEvent.LayoutRequest)
        app.processEvents()


def save_contact_sheet(captures, path):
    from PySide6.QtGui import QImage, QPainter, QColor

    column_width = max(image.width() for _, image in captures)
    row_height = max(image.height() for _, image in captures) + 32
    sheet = QImage(column_width * 3, row_height * 2, QImage.Format_ARGB32)
    sheet.fill(QColor("#242424"))
    painter = QPainter(sheet)
    for index, (label, image) in enumerate(captures):
        x, y = (index % 3) * column_width, (index // 3) * row_height
        painter.setPen(QColor("white"))
        painter.drawText(x + 8, y + 22, label)
        painter.drawImage(x, y + 32, image)
    painter.end()
    assert sheet.save(str(path))
    print(f"{path.name} ({sheet.width()}x{sheet.height()})", flush=True)


def capture_trade_edges(app, destination, temporary, *, cases=("many_mods", "24px_800x600")):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QImage, QPainter, QColor
    from src.poetore.trade import TradeStatFilter
    from src.poetore.window_position import PlacementContext
    from src.ui.appearance import apply_application_appearance

    for case in cases:
        captures = []
        for version in ("poe1", "poe2"):
            for profile in ("small", "medium", "large"):
                size = 24 if case == "24px_800x600" else 13
                apply_application_appearance(app, {"appearance": {"overrides": {"base_font_size": size}}})
                window = build_scenario("trade", temporary, version)
                window._app_config.setdefault("poetore", {})["result_font_size"] = profile
                window.apply_result_display_size()
                if case == "many_mods":
                    window._populate_stat_filters(tuple(
                        TradeStatFilter(f"explicit.{i}", f"耐性Mod {i + 1} +#%", 45,
                                        "prefix" if i % 2 else "suffix", i < 3, tier_tags=(i % 6 + 1,))
                        for i in range(40)
                    ))
                else:
                    window._populate_stat_filters(tuple(
                        TradeStatFilter(f"explicit.long_{i}", "最大ライフとエナジーシールドが増加する",
                                        120, kind, True, tier_tags=(i + 1,))
                        for i, kind in enumerate(("prefix", "suffix", "prefix_suffix"))
                    ))
                    available = QRect(0, 0, 800, 600)
                    window.show_at_context(PlacementContext(available, available.center()), activate=False)
                settle(app, window)
                rendered = window.grab().toImage()
                if case == "24px_800x600":
                    assert available.contains(window.frameGeometry())
                    frame = QImage(800, 600, QImage.Format_ARGB32)
                    frame.fill(QColor("#242424"))
                    painter = QPainter(frame)
                    painter.drawImage(window.pos(), rendered)
                    painter.end()
                    rendered = frame
                captures.append((f"{version} / {profile} / {size}px", rendered))
                window.hide()
                window.deleteLater()
                app.sendPostedEvents(None, QEvent.DeferredDelete)
        save_contact_sheet(captures, destination / f"after_trade_{case}.png")


def capture(prefix, destination, keys=None):
    import tempfile
    from PySide6.QtGui import QFontDatabase
    from src.app_font import bundled_font_path
    from src.ui.appearance import apply_application_appearance
    app = QApplication.instance() or QApplication([])
    screens = app.screens()
    QFontDatabase.addApplicationFont(str(bundled_font_path()))
    app.setProperty("appMode", "poetore")
    destination.mkdir(parents=True, exist_ok=True)
    # Each file is a contact sheet of the same screen at the default, every
    # explicit preset, and the maximum supported base font size.
    profiles = [("default", 13), ("poenavi", 13), ("poetore", 13),
                ("tokyo_night", 13), ("vscode_dark_2026", 13), ("default", 24)]
    with tempfile.TemporaryDirectory(prefix="poetore-ui-") as temporary, offline_ui():
        for key, _, _ in SCENARIOS:
            if keys is not None and key not in keys:
                continue
            captures = []
            for preset, size in profiles:
                apply_application_appearance(app, {"appearance": {"preset": preset, "overrides": {"base_font_size": size}}})
                window = build_scenario(key, Path(temporary))
                settle(app, window)
                captures.append((f"{preset} / {size}px", window.grab().toImage()))
                window.hide()
                window.deleteLater()
                app.sendPostedEvents(None, QEvent.DeferredDelete)
            save_contact_sheet(captures, destination / f"{prefix}_{key}.png")
        if prefix == "after" and (keys is None or "trade" in keys):
            capture_trade_edges(app, destination, Path(temporary))
    assert screens


if __name__ == "__main__":
    import os
    import sys
    import tempfile
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["POETORE_DISABLE_PERFORMANCE_LOG"] = "1"
    with tempfile.TemporaryDirectory(prefix="poetore-capture-data-") as user_data:
        os.environ["POENAVI_USER_DATA_DIR"] = user_data
        capture(sys.argv[1], Path(sys.argv[2]), keys=sys.argv[3:] or None)
