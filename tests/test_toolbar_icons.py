import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from src.app_mode import POENAVI_MODE
from src.ui.app_theme import theme_for_mode
from src.ui.main_window import MainWindow
from src.ui.toolbar_button import ToolbarButton
from src.ui.toolbar_icons import (
    image_manager_icon,
    image_manager_line_icon,
    map_mod_manager_icon,
    memo_icon,
    memo_line_icon,
    poenavi_mode_icon,
    poetore_mode_icon,
    settings_icon,
    settings_line_icon,
    vendor_presets_icon,
    vendor_presets_line_icon,
)


@pytest.mark.parametrize("size", [15, 18, 24, 32])
def test_mode_icons_render_distinct_line_art_at_small_sizes(qapp, size):
    color = "#b0ff7b"
    dimensions = QSize(size, size)
    compass = poenavi_mode_icon(color, size=size)
    scale = poetore_mode_icon(color, size=size)
    images = [icon.pixmap(dimensions).toImage() for icon in (compass, scale)]

    for icon, normal in zip((compass, scale), images):
        disabled = icon.pixmap(dimensions, QIcon.Disabled).toImage()
        assert normal.size() == dimensions
        assert normal.pixelColor(0, 0).alpha() == 0
        assert any(normal.pixelColor(x, y).alpha() > 180
                   for x in range(size) for y in range(size))
        assert max(disabled.pixelColor(x, y).alpha()
                   for x in range(size) for y in range(size)) <= 115
    assert images[0] != images[1]
    assert images[0] != map_mod_manager_icon(color).pixmap(dimensions).toImage()


def test_poennavi_toolbar_icons_are_distinct_and_render_at_compact_size():
    QApplication.instance() or QApplication([])
    colors = {
        "accent_color": "#b0ff7b",
        "panel_color": "#263A20",
        "dark_color": "#142111",
    }
    icons = [
        memo_icon(**colors),
        vendor_presets_icon(**colors),
        image_manager_icon(**colors),
        settings_icon(**colors),
    ]
    images = [icon.pixmap(QSize(24, 24)).toImage() for icon in icons]

    assert all(not icon.isNull() for icon in icons)
    assert len({image.cacheKey() for image in images}) == len(images)


def test_poennavi_toolbar_uses_custom_icons_and_has_no_poetore_button(qapp, monkeypatch):
    class UiBuilt(Exception):
        pass

    setup_ui = MainWindow.setup_ui

    def build_ui(window):
        setup_ui(window)
        # Stop before starting tray, log watchers and hotkeys.
        raise UiBuilt

    monkeypatch.setattr("src.ui.main_window.ConfigManager.load_config", lambda: {})
    monkeypatch.setattr(MainWindow, "_run_startup_update_gate", lambda self: True)
    monkeypatch.setattr(MainWindow, "_ensure_poe_version_selected", lambda self: True)
    monkeypatch.setattr(MainWindow, "_sync_voicevox_service", lambda self: None)
    monkeypatch.setattr(MainWindow, "_restore_progress_flags", lambda self: None)
    monkeypatch.setattr(MainWindow, "setup_ui", build_ui)


    window = MainWindow.__new__(MainWindow)
    try:
        with pytest.raises(UiBuilt):
            window.__init__()

        expected = (
            (window.memo_btn, memo_line_icon),
            (window.vendor_search_btn, vendor_presets_line_icon),
            (window.cheat_sheets_btn, image_manager_line_icon),
            (window.settings_btn, settings_line_icon),
        )
        toolbar = window.global_controls_widget
        assert toolbar.parentWidget().layout().indexOf(toolbar) == 0
        color = theme_for_mode(POENAVI_MODE).muted_text
        icon_size = QSize(24, 24)
        for index, (button, factory) in enumerate(expected):
            assert isinstance(button, ToolbarButton)
            assert toolbar.layout().itemAt(index).widget() is button
            assert button.size() == QSize(36, 36)
            assert button.iconSize() == icon_size
            assert button.icon().pixmap(icon_size).toImage() == factory(color).pixmap(icon_size).toImage()
            assert button.toolTip() == button.accessibleName()
            assert button.toolTip()
        assert window.settings_btn.toolTip() == "設定画面を開く"
        assert "Shift+Space" in window.cheat_sheets_btn.toolTip()
        window._apply_bg_opacity(45)
        assert "border-radius: 10px" in window.centralWidget().styleSheet()
        assert "border: 1px solid" in window.centralWidget().styleSheet()
        for frame, name in (
            (window.guide_info_frame, "guideInfoFrame"),
            (window.guide_text_frame, "guideTextFrame"),
            (window.area_note_frame, "areaNoteFrame"),
            (window.gem_tracker_frame, "gemTrackerFrame"),
        ):
            assert frame.objectName() == name
            assert frame.styleSheet().strip().startswith(f"QFrame#{name} {{")
        assert window.zone_label.frameWidth() == 0
        assert window.guide_text_label.frameWidth() == 0
        assert not hasattr(window, "poetore_btn")
    finally:
        window.deleteLater()
