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

    created = {}

    def record(factory):
        def build(**colors):
            icon = factory(**colors)
            created[factory.__name__] = icon
            return icon
        return build

    for factory in (memo_icon, vendor_presets_icon, image_manager_icon, settings_icon):
        monkeypatch.setattr(f"src.ui.main_window.{factory.__name__}", record(factory))

    window = MainWindow.__new__(MainWindow)
    try:
        with pytest.raises(UiBuilt):
            window.__init__()

        expected = {
            "memo_btn": "memo_icon",
            "vendor_search_btn": "vendor_presets_icon",
            "cheat_sheets_btn": "image_manager_icon",
            "settings_btn": "settings_icon",
        }
        size = QSize(24, 24)
        for attr, factory_name in expected.items():
            actual = getattr(window, attr).icon().pixmap(size).toImage()
            assert actual == created[factory_name].pixmap(size).toImage(), attr
        assert not hasattr(window, "poetore_btn")
    finally:
        window.deleteLater()
