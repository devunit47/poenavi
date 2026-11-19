import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QGroupBox

from src.ui.settings_dialog import (
    GuideEditorDialog,
    _flag_guide_header,
    _mini_navi_flag_section_title,
)
from src.utils.guide_data import get_zone_guide


TEMPLE_FLAGS = "act8_lunaristemple2_enter+act8_solaristemple2_enter"
BLOOD_AQUEDUCT = "act8_bloodaqueduct_enter"
CONTROL_BLOCKS = "act10_controlblocks_enter"
OSSUARY = "act10_ossuary_enter"
DESECRATED_CHAMBERS = "act10_desecratedchambers_enter"
ACT1_FLAGS = [
    ("act1_area2", "act1_submergedpassage_enter"),
    ("act1_area4", "act1_floodeddepths_enter"),
]


@pytest.fixture(scope="module")
def guide_data():
    path = Path(__file__).resolve().parents[1] / "guide_data.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("zone_id,flag", ACT1_FLAGS)
def test_act1_guide_has_exactly_one_flag_frame(guide_data, zone_id, flag):
    flags = guide_data[zone_id]["visits"]["1"]["flags"]
    assert set(flags) == {flag}
    assert isinstance(flags[flag], dict)


def test_act6_coast_has_no_submerged_passage_flag_frame(guide_data):
    assert "flags" not in guide_data["act6_area2"]["visits"]["1"]


@pytest.mark.parametrize("zone_id,flag", ACT1_FLAGS)
def test_act1_guide_editor_displays_flag_section(qapp, guide_data, zone_id, flag):
    guide = guide_data[zone_id]["visits"]["1"]
    dialog = GuideEditorDialog(
        None, zone_id, guide, zone_id=zone_id, flag_guides=guide["flags"],
    )
    try:
        titles = [group.title() for group in dialog.findChildren(QGroupBox)]
        assert flag in titles
        assert "act1_lowerprison_enter" not in titles
    finally:
        dialog.close()


@pytest.mark.parametrize(
    "zone_id,flag",
    [
        ("act2_area7", "act2_westernforest_enter"),
        ("act2_area8", "act2_weaverschambers_enter+act2_wetlands_enter"),
        ("act3_area11", "act3_solaris_enter+act3_lunaris_enter"),
        ("act4_area6", "act4_grandarena_enter"),
        ("act4_area6", "act4_kaomstronghold_enter"),
        ("act4_area6", "act4_grandarena_enter+act4_kaomstronghold_enter"),
        ("act5_area7", "act5_reliquary_enter"),
        ("act6_area8", "act7_maligarosanctum_enter"),
        ("act6_area10", "act6_wetlands_enter"),
        ("act7_area2", "act7_crypt_enter"),
        ("act7_area10", "act7_dreadthicket_enter"),
        ("act8_area13", TEMPLE_FLAGS),
        ("act9_area2", "act9_oasis_enter"),
        ("act10_area3", CONTROL_BLOCKS),
        ("act10_area3", f"{CONTROL_BLOCKS}+{OSSUARY}"),
        ("act10_area3", f"{CONTROL_BLOCKS}+{OSSUARY}+{DESECRATED_CHAMBERS}"),
    ],
)
def test_first_visit_has_flag_frame(guide_data, zone_id, flag):
    flags = guide_data[zone_id]["visits"]["1"]["flags"]
    assert isinstance(flags[flag], dict)


@pytest.mark.parametrize("visit", ["1", "2"])
def test_underbelly_route_has_temple_flag_frame(guide_data, visit):
    route = guide_data["act8_area14"]["routes"]["underbelly"]
    assert isinstance(route["visits"][visit]["flags"][TEMPLE_FLAGS], dict)


def test_blood_aqueduct_frame_guides_player_to_bath_house(guide_data):
    frame = guide_data["act8_area14"]["visits"]["1"]["flags"][BLOOD_AQUEDUCT]
    assert "浴場" in frame["objective"]
    assert "浴場" in frame["mini_navi"]["text"]


@pytest.mark.parametrize("zone_id,flag", [("act8_area13", TEMPLE_FLAGS), ("act8_area14", BLOOD_AQUEDUCT)])
def test_editors_label_act8_flag_guides_as_standard_route_only(zone_id, flag):
    assert _flag_guide_header(zone_id) == "🚩 フラグ別ガイド（通常ルート、かつ以下のフラグ成立時）"
    assert _mini_navi_flag_section_title(zone_id, flag) == f"通常ルート、かつフラグ成立時: {flag}"


def test_other_zone_flag_labels_are_unchanged():
    assert _flag_guide_header("act2_area7") == "🚩 フラグ別ガイド"
    assert _mini_navi_flag_section_title("act2_area7", "some_flag") == "フラグ別: some_flag"


@pytest.mark.parametrize(
    "zone_id,flag,inactive_flags,mini_direction",
    [
        ("act5_area7", "act5_reliquary_enter", set(), "nw"),
        ("act6_area10", "act6_wetlands_enter", {"act2_wetlands_enter"}, "sw"),
        ("act7_area2", "act7_crypt_enter", {"act2_crypt_enter"}, "se"),
        ("act7_area10", "act7_dreadthicket_enter", {"act2_dreadthicket_enter"}, "n"),
        ("act9_area2", "act9_oasis_enter", set(), "n"),
    ],
)
def test_single_flag_overrides_second_visit_guide(zone_id, flag, inactive_flags, mini_direction):
    mini = {"text": "flag mini", "direction": mini_direction}
    guide_data = {
        zone_id: {
            "visits": {
                "1": {
                    "objective": "first visit",
                    "flags": {flag: {"objective": "flag objective", "mini_navi": mini}},
                },
                "2": {"objective": "second visit"},
            },
        },
    }

    default = get_zone_guide(guide_data, zone_id, visit=2, active_flags=inactive_flags)
    selected = get_zone_guide(guide_data, zone_id, visit=2, active_flags={flag})
    assert default["objective"] == "second visit"
    assert selected["objective"] == "flag objective"
    assert selected["mini_navi"] == {"text": "flag mini", "direction": mini_direction}


@pytest.mark.parametrize(
    "zone_id,visit,partial_flag,second_flag,mini_direction",
    [
        ("act2_area8", 1, "act2_weaverschambers_enter", "act2_wetlands_enter", "sw"),
        ("act3_area11", 2, "act3_solaris_enter", "act3_lunaris_enter", "ne"),
    ],
)
def test_composite_guide_requires_both_flags(zone_id, visit, partial_flag, second_flag, mini_direction):
    mini = {"text": "both flags mini", "direction": mini_direction}
    guide_data = {
        zone_id: {
            "visits": {
                "1": {
                    "objective": "first visit",
                    "flags": {
                        f"{partial_flag}+{second_flag}": {"objective": "both flags", "mini_navi": mini},
                    },
                },
                "2": {"objective": "second visit"},
            },
        },
    }

    partial = get_zone_guide(guide_data, zone_id, visit=visit, active_flags={partial_flag})
    selected = get_zone_guide(
        guide_data, zone_id, visit=visit, active_flags={partial_flag, second_flag},
    )
    assert partial["objective"] == {1: "first visit", 2: "second visit"}[visit]
    assert selected["objective"] == "both flags"
    assert selected["mini_navi"] == {"text": "both flags mini", "direction": mini_direction}


def test_first_visit_flag_guide_inherits_base_direction():
    zone_id = "act2_area7"
    flag = "act2_westernforest_enter"
    guide_data = {
        zone_id: {
            "visits": {
                "1": {
                    "objective": "first visit",
                    "direction": "sw",
                    "mini_navi": {"text": "default mini", "direction": "sw"},
                    "flags": {
                        flag: {
                            "objective": "flag objective",
                            "mini_navi": {"text": "flag mini", "direction": "nw"},
                        },
                    },
                },
            },
        },
    }

    selected = get_zone_guide(guide_data, zone_id, visit=1, active_flags={flag})
    assert selected["objective"] == "flag objective"
    assert selected["direction"] == "sw"
    assert selected["mini_navi"] == {"text": "flag mini", "direction": "nw"}


def test_maligaro_flag_selects_authored_prisoners_gate_guide(guide_data):
    zone_id = "act6_area8"
    default = get_zone_guide(guide_data, zone_id, visit=1, active_flags=set())
    selected = get_zone_guide(
        guide_data, zone_id, visit=1, active_flags={"act7_maligarosanctum_enter"},
    )
    assert selected != default
    assert selected.get("direction") == "none"


@pytest.mark.parametrize(
    "zone_id,flag,standard_visit",
    [("act8_area13", TEMPLE_FLAGS, 1), ("act8_area14", BLOOD_AQUEDUCT, 2)],
)
def test_standard_route_flag_does_not_override_underbelly_guide(zone_id, flag, standard_visit):
    guide_data = {
        zone_id: {
            "visits": {
                "1": {
                    "objective": "standard default",
                    "flags": {flag: {"objective": "standard with flags"}},
                },
                "2": {"objective": "standard second visit"},
            },
            "routes": {
                "underbelly": {"visits": {"1": {"objective": "underbelly default"}}},
            },
        },
    }
    active_flags = set(flag.split("+"))

    standard = get_zone_guide(
        guide_data, zone_id, visit=standard_visit,
        config={"poe1_route_act8": "standard"}, active_flags=active_flags,
    )
    underbelly = get_zone_guide(
        guide_data, zone_id, config={"poe1_route_act8": "underbelly"}, active_flags=active_flags,
    )
    assert standard["objective"] == "standard with flags"
    assert underbelly["objective"] == "underbelly default"


@pytest.mark.parametrize(
    "route,visit,active_flags,objective,mini",
    [
        ("underbelly", 1, {"act8_lunaristemple2_enter"}, "underbelly default", None),
        ("underbelly", 1, set(TEMPLE_FLAGS.split("+")), "both temples",
         {"text": "both temples mini", "direction": "se"}),
        ("underbelly", 2, set(TEMPLE_FLAGS.split("+")), "both temples second visit", None),
        ("standard", 1, set(TEMPLE_FLAGS.split("+")), "standard default", None),
    ],
)
def test_underbelly_flag_guide_selection(route, visit, active_flags, objective, mini):
    zone_id = "act8_area14"
    guide_data = {
        zone_id: {
            "visits": {"1": {"objective": "standard default", "direction": "nw"}},
            "routes": {
                "underbelly": {
                    "visits": {
                        "1": {
                            "objective": "underbelly default",
                            "direction": "ne",
                            "flags": {
                                TEMPLE_FLAGS: {
                                    "objective": "both temples",
                                    "mini_navi": {"text": "both temples mini", "direction": "se"},
                                },
                            },
                        },
                        "2": {
                            "objective": "underbelly second visit",
                            "direction": "sw",
                            "flags": {TEMPLE_FLAGS: {"objective": "both temples second visit"}},
                        },
                    },
                },
            },
        },
    }

    selected = get_zone_guide(
        guide_data, zone_id, visit=visit,
        config={"poe1_route_act8": route}, active_flags=active_flags,
    )
    assert selected["objective"] == objective
    if mini is not None:
        assert selected["mini_navi"] == mini


@pytest.mark.parametrize(
    "active_flags,objective",
    [
        ({"act4_grandarena_enter"}, "grand arena only"),
        ({"act4_kaomstronghold_enter"}, "kaom only"),
        ({"act4_grandarena_enter", "act4_kaomstronghold_enter"}, "both flags"),
    ],
    ids=["grand-arena", "kaom", "both"],
)
def test_most_specific_crystal_veins_guide(active_flags, objective):
    zone_id = "act4_area6"
    guide_data = {
        zone_id: {
            "visits": {
                "1": {
                    "objective": "first visit",
                    "flags": {
                        "act4_grandarena_enter": {"objective": "grand arena only"},
                        "act4_kaomstronghold_enter": {"objective": "kaom only"},
                        "act4_grandarena_enter+act4_kaomstronghold_enter": {"objective": "both flags"},
                    },
                },
                "2": {"objective": "second visit"},
            },
        },
    }

    selected = get_zone_guide(guide_data, zone_id, visit=2, active_flags=active_flags)
    assert selected["objective"] == objective


@pytest.mark.parametrize(
    "active_flags,objective,mini",
    [
        ({CONTROL_BLOCKS}, "control only", None),
        ({CONTROL_BLOCKS, OSSUARY}, "control ossuary", None),
        ({CONTROL_BLOCKS, OSSUARY, DESECRATED_CHAMBERS}, "all three",
         {"text": "all three mini", "direction": "se"}),
        ({OSSUARY}, "second visit", None),
    ],
)
def test_most_specific_ravaged_square_guide(active_flags, objective, mini):
    zone_id = "act10_area3"
    guide_data = {
        zone_id: {
            "visits": {
                "1": {
                    "objective": "first visit",
                    "flags": {
                        CONTROL_BLOCKS: {"objective": "control only"},
                        f"{CONTROL_BLOCKS}+{OSSUARY}": {"objective": "control ossuary"},
                        f"{CONTROL_BLOCKS}+{OSSUARY}+{DESECRATED_CHAMBERS}": {
                            "objective": "all three",
                            "mini_navi": {"text": "all three mini", "direction": "se"},
                        },
                    },
                },
                "2": {"objective": "second visit", "direction": "se"},
            },
        },
    }

    selected = get_zone_guide(guide_data, zone_id, visit=2, active_flags=active_flags)
    assert selected["objective"] == objective
    if mini is not None:
        assert selected["mini_navi"] == mini
