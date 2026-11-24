import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
import pytest

import main
from src.app_mode import POENAVI_MODE, POETORE_MODE

try:
    from src.ui.main_window import MainWindow
except ModuleNotFoundError as exc:  # pragma: no cover - local dev without GUI deps
    MainWindow = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None

from src.utils.poe_version_data import POE1, POE2


@pytest.mark.parametrize("version_mode", ["", "ask", POE1])
def test_switch_restart_uses_saved_target_even_when_normal_startup_would_prompt(version_mode):
    config = {
        "poe_version": POE2,
        "poe_version_mode": version_mode,
        "startup": {"preferred_mode": POETORE_MODE, "show_mode_selector": True},
    }
    with patch("src.ui.startup_dialogs.StartupSelectionDialog") as dialog:
        assert main.select_startup_options(config, skip_selector=True) == (config, POETORE_MODE)
    dialog.assert_not_called()


def test_default_startup_uses_last_selection_without_a_dialog():
    config = {"poe_version": POE2, "startup": {"preferred_mode": POETORE_MODE}}
    with patch("src.ui.startup_dialogs.StartupSelectionDialog") as dialog:
        assert main.select_startup_options(config) == (config, POETORE_MODE)
    dialog.assert_not_called()


def test_poetore_autostart_takes_priority_over_one_shot_skip():
    config = {"poe_version": POE2, "startup": {"preferred_mode": POENAVI_MODE}}
    assert main.select_startup_options(config, force_poetore=True, skip_selector=True) == (
        config, POETORE_MODE,
    )


@unittest.skipIf(MainWindow is None, f"GUI dependencies unavailable: {IMPORT_ERROR}")
class StartupSelectionFlowTest(unittest.TestCase):
    def test_main_window_does_not_open_a_second_version_dialog(self):
        window = MainWindow.__new__(MainWindow)
        window.config = {
            "poe_version": POE2,
            "poe_version_mode": "ask",
        }

        self.assertTrue(window._ensure_poe_version_selected())

        self.assertEqual(window.config["poe_version"], POE2)

    def test_main_window_does_not_repeat_version_dialog_after_common_startup_selection(self):
        app = QApplication.instance() or QApplication([])
        previous = app.property("startupPoeVersionSelected")
        app.setProperty("startupPoeVersionSelected", True)
        window = MainWindow.__new__(MainWindow)
        window.config = {
            "poe_version": POE1,
            "poe_version_mode": "ask",
        }

        try:
            self.assertTrue(window._ensure_poe_version_selected())
        finally:
            app.setProperty("startupPoeVersionSelected", previous)


if __name__ == "__main__":
    unittest.main()
