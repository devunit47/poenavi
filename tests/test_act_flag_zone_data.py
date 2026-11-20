import json
from pathlib import Path
from types import SimpleNamespace

from src.ui.main_window import MainWindow
from src.utils.guide_data import get_zone_guide
from src.utils.poe_version_data import POE1
from src.utils.zone_master_data import load_zone_data_by_version


def test_act5_and_act10_duplicate_names_have_distinct_zone_ids():
    zone_data = load_zone_data_by_version()[POE1]
    act5_control = [z for z in zone_data["Act 5"] if z["zone"] == "奴隷管理区画"]
    act10_control = [z for z in zone_data["Act 10"] if z["zone"] == "奴隷管理区画"]
    act5_ossuary = [z for z in zone_data["Act 5"] if z["zone"] == "納骨堂"]
    act10_ossuary = [z for z in zone_data["Act 10"] if z["zone"] == "納骨堂"]
    act5_reliquary = [z for z in zone_data["Act 5"] if z["zone"] == "聖廟"]
    act10_reliquary = [z for z in zone_data["Act 10"] if z["zone"] == "聖廟"]
    desecrated = [z for z in zone_data["Act 10"] if z["zone"] == "冒涜された広間"]

    assert act5_control[0]["id"] == "act5_area2"
    assert act10_control[0]["id"] == "act10_area4"
    assert act5_ossuary[0]["id"] == "act5_area8"
    assert act10_ossuary[0]["id"] == "act10_area5"
    assert act5_reliquary[0]["id"] == "act5_area9"
    assert act10_reliquary[0]["id"] == "act10_area12"
    assert desecrated[0]["id"] == "act10_area7"


def test_part2_mode_resolves_reliquary_to_act10_authored_guide():
    window = SimpleNamespace(
        zone_data=load_zone_data_by_version()[POE1],
        part2_mode=True,
        _in_act10=True,
    )
    guide_data = json.loads(Path("guide_data.json").read_text(encoding="utf-8"))

    zone_id = MainWindow._get_zone_id(window, "聖廟")
    guide = get_zone_guide(guide_data, zone_id, visit=1)

    assert zone_id == "act10_area12"
    assert "このエリアの攻略は不要です" in guide["objective"]
    assert guide["mini_navi"]["text"] == guide["objective"]


def test_maligaro_sanctum_zone_id():
    zone_data = load_zone_data_by_version()[POE1]
    sanctum = [z for z in zone_data["Act 7"] if z["zone"] == "マリガロの聖域"]

    assert sanctum[0]["id"] == "act7_area6"
    assert sanctum[0]["zone_en"] == "Maligaro's Sanctum"


def test_act2_and_act6_wetlands_have_distinct_zone_ids():
    act2_wetlands = [z for z in load_zone_data_by_version()[POE1]["Act 2"] if z["zone"] == "湿地"]
    act6_wetlands = [z for z in load_zone_data_by_version()[POE1]["Act 6"] if z["zone"] == "湿地"]

    assert act2_wetlands[0]["id"] == "act2_area14"
    assert act6_wetlands[0]["id"] == "act6_area11"


def test_act2_and_act7_crypt_have_distinct_zone_ids():
    act2_crypt_ids = [z["id"] for z in load_zone_data_by_version()[POE1]["Act 2"] if z["zone"].startswith("地下聖堂")]
    act7_crypt = [z for z in load_zone_data_by_version()[POE1]["Act 7"] if z["zone"] == "地下聖堂"]

    assert act2_crypt_ids == ["act2_area12", "act2_area13"]
    assert act7_crypt[0]["id"] == "act7_area4"


def test_act2_and_act7_northern_forest_have_distinct_zone_ids():
    act2_northern = [z for z in load_zone_data_by_version()[POE1]["Act 2"] if z["zone"] == "北の森"]
    act7_northern = [z for z in load_zone_data_by_version()[POE1]["Act 7"] if z["zone"] == "北の森"]
    act7_dread = [z for z in load_zone_data_by_version()[POE1]["Act 7"] if z["zone"] == "恐怖の密林"]

    assert act2_northern[0]["id"] == "act2_area16"
    assert act7_northern[0]["id"] == "act7_area10"
    assert act7_dread[0]["id"] == "act7_area12"


def test_act2_and_act7_dread_thicket_have_distinct_zone_ids_in_runtime_master():
    zone_data = load_zone_data_by_version()[POE1]
    act2_dread = [z for z in zone_data["Act 2"] if z.get("zone") == "恐怖の密林" or z.get("zone_en") == "The Dread Thicket"]
    act7_dread = [z for z in zone_data["Act 7"] if z.get("zone") == "恐怖の密林" or z.get("zone_en") == "The Dread Thicket"]

    assert act2_dread[0]["id"] == "act2_area19"
    assert act7_dread[0]["id"] == "act7_area12"


def test_act9_vastiri_desert_and_oasis_zone_ids():
    zone_data = load_zone_data_by_version()[POE1]
    vastiri = [z for z in zone_data["Act 9"] if z["zone"] == "ヴァスティリ砂漠"]
    oasis = [z for z in zone_data["Act 9"] if z["zone"] == "オアシス"]

    assert vastiri[0]["id"] == "act9_area2"
    assert oasis[0]["id"] == "act9_area3"
