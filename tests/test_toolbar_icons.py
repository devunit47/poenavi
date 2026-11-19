import pytest
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow
from src.ui.toolbar_icons import (
    image_manager_icon,
    memo_icon,
    settings_icon,
    vendor_presets_icon,
)


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

        for button in (window.memo_btn, window.vendor_search_btn, window.cheat_sheets_btn, window.settings_btn):
            assert not button.icon().isNull(), button.toolTip()
        assert not hasattr(window, "poetore_btn")
    finally:
        window.deleteLater()
