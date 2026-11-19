from dataclasses import replace
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox

from src.poetore.metadata import MetadataIndex, ModMetadata, TierRange, default_metadata_index
from src.poetore.parser import parse_item_text
from src.poetore.trade import build_search_query, resolve_trade_stat_filters, unresolved_modifier_warnings
from src.poetore.ui import PoetoreWindow
from src.ui.poetore_settings_dialog import PoetoreSettingsDialog
from src.utils.config_manager import ConfigManager


SHIELD = '''Item Class: Shields
Rarity: Rare
Test Shield
Spiked Bundle
--------
Item Level: 84
--------
{ Prefix Modifier "Healthy" (Tier: 1) }
+80(60-80) to maximum Life
{ Prefix Modifier "Agile" (Tier: 2) }
531(500-600)% increased Evasion and Energy Shield
{ Suffix Modifier "Blocking" (Tier: 3) }
+3(3-4)% Chance to Block
'''
STAT_IDS = (
    "explicit.stat_3299347043", "explicit.stat_1999113824", "explicit.stat_4253454700",
)
JAPANESE_TEMPLATES = (
    "最大ライフ +#", "回避力およびエナジーシールドが#%増加する (ローカル)", "ブロック率 +#% (盾)",
)


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def test_english_shield_matches_the_japanese_stat_records_and_values():
    item = parse_item_text(SHIELD)
    assert item.category == "armour"
    assert unresolved_modifier_warnings(item) == ()
    for mod, stat_id, template, (value, low, high), tier in zip(
        item.modifiers, STAT_IDS, JAPANESE_TEMPLATES,
        ((80, 60, 80), (531, 500, 600), (3, 3, 4)), (1, 2, 3), strict=True,
    ):
        japanese_text = template.replace("#", f"{value}({low}-{high})")
        index = default_metadata_index()
        japanese, _, _ = index.match_for_item_category(japanese_text, "explicit", "armour")
        english, _, _ = index.match_for_item_category(mod.text, "explicit", "armour")
        assert english is japanese
        assert mod.stat_id == japanese.stat_id == stat_id
        japanese_item = parse_item_text(SHIELD.replace(mod.text, japanese_text), english_mod_matching=False)
        japanese_mod = next(row for row in japanese_item.modifiers if row.text == japanese_text)
        assert mod == replace(japanese_mod, text=mod.text)
        assert (mod.values, mod.roll_min, mod.roll_max, mod.tier) == ((value,), low, high, tier)


def test_english_conflicts_stay_unresolved_until_category_or_affix_is_known():
    text = "+25 to Test Defence"
    armour = ModMetadata(
        "test", "explicit.armour", "explicit", ("防御 +#",),
        local=True, english=("# to Test Defence",),
    )
    global_stat = replace(armour, stat_id="explicit.global", japanese=("全体防御 +#",), local=False)
    index = MetadataIndex((armour, global_stat))
    assert index.match(text, "explicit") == (None, 0.0)
    assert index.match_for_item_category(text, "explicit", "armour") == (None, None, 0.0)
    assert index.match(text + " (Local)", "explicit") == (armour, 1.0)
    assert index.match("防御 +25", "explicit") == (armour, 1.0)

    scoped = replace(armour, category_select="ARMOUR")
    fallback = replace(global_stat, category_select="")
    index = MetadataIndex((scoped, fallback))
    assert index.match_for_item_category(text, "explicit", "armour")[0] is scoped
    assert index.match_for_item_category(text, "explicit", "weapon")[0] is fallback

    prefix = replace(armour, tiers=(TierRange(1, 20, 30, generation="prefix"),))
    suffix = replace(global_stat, tiers=(TierRange(1, 20, 30, generation="suffix"),))
    index = MetadataIndex((prefix, suffix))
    assert index.match_for_item_category(text, "prefix", "armour")[0] is prefix
    assert index.match_for_item_category(text, "suffix", "armour")[0] is suffix


def test_english_negated_matcher_and_fixed_number_in_option():
    item = parse_item_text(SHIELD.replace("increased Evasion", "reduced Evasion"))
    mod = item.modifiers[1]
    assert (mod.stat_id, mod.values, mod.better, mod.inverted) == (STAT_IDS[1], (531,), -1, True)

    index = default_metadata_index()
    english = "Added Small Passive Skills grant: +12% to Chaos Resistance"
    record, option, confidence = index.match_with_option(english, "enchant")
    assert (record.stat_id, option.value, confidence) == ("enchant.stat_3948993189", 49, 1.0)
    assert index.match_with_option(english.replace("12%", "13%"), "enchant") == (None, None, 0.0)

    jewel = parse_item_text(f"""Item Class: Cluster Jewels
Rarity: Rare
Test Jewel
Small Cluster Jewel
--------
Item Level: 84
--------
{english} (enchant)
""")
    entry = {"id": f"{record.stat_id}|49", "text": option.japanese, "type": "enchant"}
    with patch("src.poetore.trade._trade_stat_entries", return_value=(entry,)):
        condition = next(row for row in resolve_trade_stat_filters(jewel) if row.stat_id == entry["id"])
    query = build_search_query(jewel, stat_filters=(replace(condition, enabled=True),))["query"]
    assert query["stats"][0]["filters"] == [{"id": record.stat_id, "value": {"option": 49}}]


@pytest.mark.parametrize("speed", [14, 30])
def test_english_multi_value_rule_selects_percentage_in_english_word_order(speed):
    item = parse_item_text(f"""Item Class: Rings
Rarity: Rare
Test Ring
Coral Ring
--------
Item Level: 84
--------
{speed}% increased Movement Speed for 4(4-5) seconds on Throwing a Trap
""")
    mod, = item.modifiers
    assert (mod.stat_id, mod.values) == ("explicit.stat_3102860761", (speed,))


def test_english_shield_ui_loads_generates_query_and_respects_next_parse(qapp):
    config = {"poetore": {}}
    entries = tuple(
        {"id": stat_id, "text": template, "type": "explicit"}
        for stat_id, template in zip(STAT_IDS, JAPANESE_TEMPLATES, strict=True)
    )
    window = PoetoreWindow(app_config=config)
    try:
        with (
            patch("src.poetore.trade._trade_stat_entries", return_value=entries),
            patch("src.poetore.ui.read_item_clipboard", return_value=SHIELD),
            patch.object(window, "show_at_context"),
            patch.object(window, "search_current_item"),
        ):
            window._capture_item_copy()
            assert window.input_edit.toPlainText() == SHIELD
            assert window.mod_warning.isHidden()
            assert window.mod_warning.text() == ""
            for checkbox in window.mod_filter_tree.findChildren(QCheckBox, "modFilterCheckbox"):
                checkbox.setChecked(True)
            filters = window._selected_stat_filters()
            assert set(STAT_IDS) <= {row.stat_id for row in filters}
            query = build_search_query(window._parsed_item, stat_filters=filters)["query"]
            sent = {row["id"]: row for group in query["stats"] for row in group["filters"]}
            assert set(STAT_IDS) <= sent.keys()
            assert sent[STAT_IDS[0]]["value"] == {"min": 72.0}

            config["poetore"]["english_mod_matching"] = False
            window.parse_current_text()
            assert all(mod.stat_id is None for mod in window._parsed_item.modifiers)
            assert not ({row.stat_id for row in window._selected_stat_filters()} & set(STAT_IDS))
            assert not window.mod_warning.isHidden()
            assert "メタデータ未解決 3件" in window.mod_warning.text()
    finally:
        window.close()


def test_english_match_setting_defaults_on_and_round_trips(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv(ConfigManager.ENV_USER_DATA_DIR, str(tmp_path))
    config = ConfigManager.load_config()
    assert config["poetore"]["english_mod_matching"] is True
    with patch.object(PoetoreSettingsDialog, "_refresh_trade_leagues"):
        dialog = PoetoreSettingsDialog(current_config=config)
        try:
            assert dialog.english_mod_matching_cb.isChecked()
            dialog.english_mod_matching_cb.setChecked(False)
            config.update(dialog.get_settings())
            ConfigManager.save_config(config)
        finally:
            dialog.close()

        saved = ConfigManager.load_config()
        reopened = PoetoreSettingsDialog(current_config=saved)
        try:
            assert saved["poetore"]["english_mod_matching"] is False
            assert not reopened.english_mod_matching_cb.isChecked()
        finally:
            reopened.close()
