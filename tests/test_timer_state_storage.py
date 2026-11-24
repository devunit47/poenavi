import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

try:
    from PySide6.QtCore import QRect, QTimer
    from PySide6.QtWidgets import QMainWindow
    from src.ui.main_window import MainWindow
except ModuleNotFoundError as exc:  # pragma: no cover - local dev without GUI deps
    MainWindow = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None

from src.utils.config_manager import ConfigManager
from src.utils.poe_version_data import POE1, POE2
from src.utils.segment_recorder import SegmentRecorder


@unittest.skipIf(MainWindow is None, f"GUI dependencies unavailable: {IMPORT_ERROR}")
class TimerStateStorageTest(unittest.TestCase):
    def make_window(self, poe_version=POE1):
        window = MainWindow.__new__(MainWindow)
        window.poe_version = poe_version
        window.config = {"poe_version": poe_version}
        window.accumulated_time = 12.5
        window.lap_times = [1.0, None]
        window.lap_record_order = [1]
        window.current_act = 2
        return window

    def test_timer_state_is_saved_to_user_data_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {ConfigManager.ENV_USER_DATA_DIR: tmp}):
                window = self.make_window(POE2)

                window._save_timer_state()

                path = Path(tmp) / "timer_poe2.json"
                self.assertTrue(path.exists())
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["accumulated_time"], 12.5)
                self.assertEqual(data["current_act"], 2)
                self.assertNotIn("saved_timer::timer_poe2.json", window.config)

    def test_legacy_config_timer_state_is_migrated_and_removed_from_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {ConfigManager.ENV_USER_DATA_DIR: tmp}):
                legacy_key = "saved_timer::timer_poe1.json"
                legacy_payload = {
                    "accumulated_time": 34.0,
                    "lap_times": [2.0],
                    "lap_record_order": [1],
                    "current_act": 1,
                }
                window = self.make_window(POE1)
                window.config = {
                    "poe_version": POE1,
                    legacy_key: legacy_payload,
                }

                migrated = window._migrate_legacy_timer_state_from_config()

                self.assertEqual(migrated, legacy_payload)
                self.assertNotIn(legacy_key, window.config)
                path = Path(tmp) / "timer_poe1.json"
                self.assertTrue(path.exists())
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), legacy_payload)
                saved_config = ConfigManager.load_config()
                self.assertNotIn(legacy_key, saved_config)


@pytest.fixture
def timer_window(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv(ConfigManager.ENV_USER_DATA_DIR, str(tmp_path))
    window = MainWindow.__new__(MainWindow)
    QMainWindow.__init__(window)
    qtbot.addWidget(window)
    window._main_window_initialized = True
    window.poe_version = POE1
    window.accumulated_time = 12.5
    window.lap_times = [1.0, None]
    window.lap_record_order = [1]
    window.current_act = 2
    window.segment_recorder = SegmentRecorder()
    window.is_running = False
    window.timer = QTimer(window)
    return window


@pytest.mark.skipif(MainWindow is None, reason=f"GUI dependencies unavailable: {IMPORT_ERROR}")
@pytest.mark.parametrize("exit_method", ["close", "_shutdown"])
def test_exiting_while_timer_is_running_saves_elapsed_time_and_laps(timer_window, exit_method):
    window = timer_window
    window.start_time = time.time() - 7
    window.is_running = True
    window.timer.start(10)

    getattr(window, exit_method)()

    saved = json.loads(window._timer_state_path().read_text(encoding="utf-8"))
    assert saved["accumulated_time"] >= 19.5
    assert saved["accumulated_time"] == window.accumulated_time
    assert saved["lap_times"] == [1.0, None]
    assert saved["lap_record_order"] == [1]
    assert saved["current_act"] == 2
    assert not window.is_running
    assert not window.timer.isActive()


@pytest.mark.skipif(MainWindow is None, reason=f"GUI dependencies unavailable: {IMPORT_ERROR}")
def test_timer_write_failure_does_not_prevent_shutdown(timer_window, caplog):
    window = timer_window
    window.start_time = time.time()
    window.is_running = True
    window.timer.start(10)

    with patch.object(window, "_save_timer_state_payload", side_effect=PermissionError("timer write denied")):
        assert window.close()

    assert "timer write denied" in caplog.text
    assert not window.is_running
    assert not window.timer.isActive()


@pytest.mark.skipif(MainWindow is None, reason=f"GUI dependencies unavailable: {IMPORT_ERROR}")
@pytest.mark.parametrize("valid_normal_geometry", [True, False])
def test_shutdown_while_minimized_preserves_normal_geometry(
    timer_window, monkeypatch, valid_normal_geometry,
):
    window = timer_window
    previous_geometry = {"x": 10, "y": 20, "width": 300, "height": 400}
    normal_geometry = {"x": 12, "y": 34, "width": 600, "height": 500}
    ConfigManager.save_config({"window_geometry": previous_geometry})
    window.setGeometry(*normal_geometry.values())
    window._initial_positioned = True
    window.showMinimized()
    assert window.isMinimized()
    monkeypatch.setattr(window, "geometry", lambda: QRect(-32000, -32000, 160, 30))
    if not valid_normal_geometry:
        monkeypatch.setattr(window, "normalGeometry", QRect)

    window._shutdown()

    expected = normal_geometry if valid_normal_geometry else previous_geometry
    assert ConfigManager.load_config()["window_geometry"] == expected


if __name__ == "__main__":
    unittest.main()
