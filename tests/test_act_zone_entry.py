from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QLabel, QMainWindow

from src.ui.main_window import MainWindow
from src.utils.poe_version_data import POE1, POE2
from src.utils.zone_master_data import load_town_zones_by_version, load_zone_data_by_version


@pytest.fixture
def zone_window(qapp, monkeypatch):
    def build(version, *, part2=False):
        # Exercise zone handling with a real window and labels, without starting
        # log watchers, tray and hotkeys as the normal constructor would.
        window = MainWindow.__new__(MainWindow)
        QMainWindow.__init__(window)
        window.poe_version = version
        window.zone_data = load_zone_data_by_version()[version]
        window.town_zones_by_version = load_town_zones_by_version()
        window.part2_mode = part2
        window.part2_only_zones = []
        window.is_running = False
        window._restoring = False
        window._in_lab = False
        window.visit_override = None
        window.zone_visit_counts = {}
        window.progress_flags = set()
        window.config = {}
        window.guide_data = {}
        window.monster_levels = {}
        window.player_level = 1
        window.zone_label = QLabel(window)
        window.advice_label = QLabel(window)
        for method in (
            "_update_act4_checklist_for_zone",
            "_track_live_new_character_candidate",
            "_record_last_non_town_zone",
            "_handle_interlude_lap_progress",
            "_try_auto_lap",
            "_save_progress_flags",
            "_sync_gem_tracker_act_from_zone_act",
            "_update_guide_and_map",
        ):
            monkeypatch.setattr(window, method, Mock())
        return window

    return build


@pytest.mark.parametrize(
    "version,zone_name,part2,flag",
    [
        pytest.param(POE1, "海底通路", False, "act1_submergedpassage_enter", id="act1_area4"),
        pytest.param(POE1, "水没した海底洞窟", False, "act1_floodeddepths_enter", id="act1_area9"),
        pytest.param(POE1, "血の水道橋", True, "act8_bloodaqueduct_enter", id="act8_area17"),
        pytest.param(POE2, "アザク湿原", False, "act3_azakbog_enter", id="poe2_act3_area05"),
    ],
)
def test_entering_zone_sets_progress_flag(zone_window, version, zone_name, part2, flag):
    window = zone_window(version, part2=part2)

    window.on_zone_entered(zone_name, actual_entry=False)
    assert window.progress_flags == set()

    window.on_zone_entered(zone_name)
    assert window.progress_flags == {flag}


def test_vastiri_desert_is_always_count_zone_for_town_reentry(zone_window):
    window = zone_window(POE1, part2=True)
    desert = "ヴァスティリ砂漠"

    window.on_zone_entered(desert)
    window.on_zone_entered(desert)
    assert window.zone_visit_counts == {"act9_area2": 1}

    window.on_zone_entered("ハイゲート")
    window.on_zone_entered(desert)
    assert window.zone_visit_counts == {"act9_area2": 2}
