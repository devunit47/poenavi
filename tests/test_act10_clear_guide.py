import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.ui.main_window import MainWindow
from src.utils.guide_data import get_zone_guide, get_mini_navi_content
from src.utils.poe_version_data import POE1


def test_act10_area11_contains_integrated_clear_guide():
    guide_data = json.loads(Path("guide_data.json").read_text(encoding="utf-8"))

    guide = get_zone_guide(guide_data, "act10_area11", visit=1, config={}, active_flags=set())
    mini = get_mini_navi_content(guide)

    assert "Act10クリア" in guide["objective"]
    assert "オリアスの船着場" in guide["objective"]
    assert "カルイの海岸" in guide["objective"]
    assert "ラニ" in guide["objective"]
    assert "/passives" in guide["objective"]
    assert mini is not None
    assert "オリアスの船着場" in mini["text"]
    assert "カルイの海岸" in mini["text"]
    assert "/passives" in mini["text"]


def test_act10_clear_handler_uses_act10_area11_guide():
    window = SimpleNamespace(
        poe_version=POE1, zone_label=Mock(), advice_label=Mock(),
        _auto_lap_kitava=Mock(), _update_guide_and_map=Mock(),
    )

    MainWindow.on_act10_cleared(window)

    assert window.current_zone == "渇望の祭壇"
    window.zone_label.setText.assert_called_once_with("📍 Act 10 — 渇望の祭壇")
    window._update_guide_and_map.assert_called_once_with(
        "渇望の祭壇", "act10_area11", 1, zone_changed=True,
    )
