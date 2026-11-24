import json
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from scripts.build_poetore_map_mods import build_catalog, source_from_lock
from src.app_font import apply_bundled_ui_font
from src.app_mode import POENAVI_MODE, POETORE_MODE
from src.poetore.map_check import (
    decision_for,
    default_map_check_config,
    is_map_check_item,
    load_map_mod_catalog,
    next_color_decision,
    normalized_map_check_config,
    set_decision,
)
from src.poetore.models import ParsedItem
from src.poetore.parser import parse_item_text
from src.poetore.window_position import (
    PlacementContext,
    position_for_context_at_cursor_y,
)
from src.ui.appearance import (
    apply_application_appearance,
    configure_appearance,
    current_appearance,
    requested_appearance,
)
from src.ui.dialog_theme import dialog_theme_for_mode
from src.ui.map_check import MapCheckWindow, MapModManagerDialog


def item(category="map", rarity="レア"):
    return ParsedItem("マップ", rarity, "テスト", "テストマップ", category)


def test_map_check_position_keeps_side_and_centers_at_cursor_y_with_clamping():
    target = QRect(100, 50, 1920, 1080)
    size = QSize(560, 360)

    middle = position_for_context_at_cursor_y(
        PlacementContext(target, QPoint(1700, 700)), size,
    )
    top = position_for_context_at_cursor_y(
        PlacementContext(target, QPoint(1700, 60)), size,
    )
    bottom = position_for_context_at_cursor_y(
        PlacementContext(target, QPoint(1700, 1120)), size,
    )

    assert middle == QPoint(794, 520)
    assert top == QPoint(794, 66)
    assert bottom == QPoint(794, 754)


def test_catalog_matches_locked_awakened_area_mod_population():
    catalog = load_map_mod_catalog()
    assert len(catalog) == 232
    assert sum(row.scope == "normal" for row in catalog) == 174
    assert sum(row.scope == "heist_exclusive" for row in catalog) == 27
    assert sum(row.scope == "ubermap_exclusive" for row in catalog) == 31
    assert all(row.stat_ids and row.japanese for row in catalog)
    assert all("stat_1953432004" not in row.stat_ids for row in catalog)


def test_catalog_is_reproducible_from_locked_awakened_and_poetore_metadata():
    archive, revision = source_from_lock()
    generated = build_catalog(
        archive,
        Path("data/poetore/mod_metadata.json"),
        revision,
    )
    stored = json.loads(
        Path("data/poetore/map_mods.json").read_text(encoding="utf-8")
    )
    assert generated == stored


def test_awakened_defaults_and_three_numeric_profiles_are_preserved():
    config = default_map_check_config()
    catalog = {entry.ref: entry.key for entry in load_map_mod_catalog()}
    assert config["profile"] == 1
    assert len(config["decisions"]) == 4
    assert sorted(config["decisions"].values()) == ["d--", "d--", "g--", "w--"]
    assert config["decisions"][catalog[
        "Rare Monsters have Physical Thorns reflecting # Physical Damage"
    ]] == "d--"
    assert config["decisions"][catalog[
        "Rare Monsters have Elemental Thorns reflecting # Elemental Damage"
    ]] == "d--"
    assert not any(key.startswith("legacy:") for key in config["decisions"])
    key = next(iter(config["decisions"]))
    set_decision(config, key, "g", profile=2)
    assert decision_for(config, key, profile=2) == "g"
    assert decision_for(config, key, profile=1) != "g" or config["decisions"][key][0] == "g"


def test_normalization_rejects_invalid_profile_and_decision():
    config = normalized_map_check_config({
        "profile": 9, "show_new_stats": True,
        "decisions": {"bad": "danger", "ok": "dwg"},
    })
    assert config["profile"] == 1
    assert config["show_new_stats"] is True
    assert "bad" not in config["decisions"]
    assert config["decisions"]["ok"] == "dwg"


def test_map_like_scope_matches_awakened_and_excludes_unique_map():
    assert is_map_check_item(item())
    assert is_map_check_item(item("invitation"))
    assert is_map_check_item(item("heist_contract"))
    assert is_map_check_item(item("heist_blueprint"))
    assert is_map_check_item(item("expedition_logbook"))
    assert not is_map_check_item(item("map", "ユニーク"))
    assert not is_map_check_item(item("armour"))


def test_color_cycle_matches_awakened_without_seen_state_in_color_button():
    assert [next_color_decision(value) for value in ("-", "d", "w", "g", "s")] == [
        "d", "w", "g", "-", "d",
    ]


def test_real_japanese_map_mods_resolve_to_area_catalog():
    parsed = parse_item_text("""アイテムクラス: マップ
レアリティ: レア
Glyph Stone
Map (Tier 16)
--------
アイテムレベル: 83
--------
{ プレフィックスモッド「装甲付き」 (ティア: 1) — 物理 }
モンスターの物理ダメージ軽減率 +40%
{ プレフィックスモッド「電撃の」 (ティア: 1) — ダメージ, 物理, 元素, 雷 }
モンスターは物理ダメージの97(90-110)%を追加雷ダメージとして与える
{ サフィックスモッド 「干魃の」 (ティア: 1) }
全てのプレイヤーの獲得フラスコチャージが50%減少する
""")
    catalog_ids = {
        stat_id for row in load_map_mod_catalog() for stat_id in row.stat_ids
    }
    assert len(parsed.modifiers) == 3
    assert all(modifier.stat_id in catalog_ids for modifier in parsed.modifiers)


def test_map_check_renders_explicit_sections_only():
    parsed = parse_item_text("""アイテムクラス: マップ
レアリティ: レア
Explicit Only Test
Map (Tier 16)
--------
アイテムレベル: 83
--------
{ 暗黙モッド }
検索対象ではない暗黙効果
{ プレフィックスモッド (ティア: 1) }
レアモンスターの数が25%増加する
""")

    QApplication.instance() or QApplication([])
    window = MapCheckWindow(default_map_check_config())
    window._render(parsed)
    buttons = [
        button for button in window.body.findChildren(QPushButton)
        if button.property("map_mod_key")
    ]
    labels = [label.text() for label in window.body.findChildren(QLabel)]
    assert len(buttons) == 1
    assert buttons[0].property("map_mod_text") == "レアモンスターの数が25%増加する"
    assert not any("検索対象ではない暗黙効果" in text for text in labels)
    assert not any(text.startswith("未認識のMod") for text in labels)
    window.close()


def test_japanese_map_copy_aliases_resolve_boss_damage_and_implicit_hinder_chance():
    parsed = parse_item_text("""アイテムクラス: マップ
レアリティ: レア
Alias Test
Map (Tier 16)
--------
アイテムレベル: 83
--------
{ プレフィックスモッド (ティア: 1) }
ユニークボスのダメージが25%増加する
{ サフィックスモッド (ティア: 1) }
モンスターはスペルによるヒット時に阻害を付与する
""")
    assert [(modifier.stat_id, modifier.values) for modifier in parsed.modifiers] == [
        ("explicit.stat_124877078", (25.0,)),
        ("explicit.stat_962720646", (100.0,)),
    ]


def test_additional_real_japanese_map_copy_aliases_resolve_to_area_mods():
    parsed = parse_item_text("""アイテムクラス: マップ
レアリティ: レア
Alias Test 2
Map (Tier 16)
--------
アイテムレベル: 83
--------
{ プレフィックスモッド (ティア: 1) }
マジックモンスターの数が23(20-30)%増加する
{ サフィックスモッド (ティア: 1) }
モンスターはヒット時にパワーチャージ、フレンジーチャージおよびエンデュランスチャージのスタックを盗む
{ サフィックスモッド (ティア: 1) }
モンスターはアタックによるヒット時に重傷を付与する
{ サフィックスモッド (ティア: 1) }
全てのプレイヤーの命中力が25%低下する
{ サフィックスモッド (ティア: 1) }
モンスターはヒット時に盲目を付与する
{ サフィックスモッド (ティア: 1) }
モンスターはヒット時にパワーチャージを1個獲得する
{ サフィックスモッド (ティア: 1) }
モンスターはヒット時にフレンジーチャージを1個獲得する
""")
    assert [(modifier.stat_id, modifier.values) for modifier in parsed.modifiers] == [
        ("explicit.stat_1821565133", (23.0, 20.0, -30.0)),
        ("explicit.stat_3222482040", (100.0,)),
        ("explicit.stat_4164174520", (100.0,)),
        ("explicit.stat_3667574329", (25.0,)),
        ("explicit.stat_1629869774", (100.0,)),
        ("explicit.stat_406353061", (100.0,)),
        ("explicit.stat_1742567045", (100.0,)),
    ]
    assert parsed.modifiers[3].inverted is True


def test_reported_japanese_map_copy_aliases_resolve_to_area_mods():
    parsed = parse_item_text("""アイテムクラス: マップ
レアリティ: レア
Reported Alias Test
Map (Tier 16)
--------
アイテムレベル: 83
--------
{ プレフィックスモッド (ティア: 1) }
レアモンスターの数が25%増加する
{ プレフィックスモッド (ティア: 1) }
ユニークボスのライフが40%増加する
{ サフィックスモッド (ティア: 1) }
全てのプレイヤーのクールダウン解消レートが25%低下する
""")
    catalog_ids = {
        stat_id for row in load_map_mod_catalog() for stat_id in row.stat_ids
    }
    assert [(modifier.stat_id, modifier.values) for modifier in parsed.modifiers] == [
        ("explicit.stat_3126771445", (25.0,)),
        ("explicit.stat_1959158336", (40.0,)),
        ("explicit.stat_941368244", (25.0,)),
    ]
    assert all(modifier.stat_id in catalog_ids for modifier in parsed.modifiers)
    assert parsed.modifiers[2].inverted is True


def test_reported_uber_map_copy_aliases_resolve_to_area_mods():
    parsed = parse_item_text("""アイテムクラス: マップ
レアリティ: レア
Uber Alias Test
Map (Tier 16)
--------
アイテムレベル: 83
--------
{ プレフィックスモッド (ティア: 1) }
それぞれのレアモンスターはモッドを追加で1個持つ
{ プレフィックスモッド (ティア: 1) }
プレイヤーは適用されるフラスコの効果が40%低下する
{ サフィックスモッド (ティア: 1) }
モンスターはヒットを受けた時にエンデュランスチャージを1個獲得する
{ サフィックスモッド (ティア: 1) }
モンスターの投射物は地形と衝突した時に連鎖することができる
""")
    catalog_ids = {
        stat_id for row in load_map_mod_catalog() for stat_id in row.stat_ids
    }
    assert [(modifier.stat_id, modifier.values) for modifier in parsed.modifiers] == [
        ("explicit.stat_2550456553", (1.0,)),
        ("explicit.stat_1207482628", (40.0,)),
        ("explicit.stat_3707756896", (100.0,)),
        ("explicit.stat_2753403220", (100.0,)),
    ]
    assert all(modifier.stat_id in catalog_ids for modifier in parsed.modifiers)
    assert parsed.modifiers[1].inverted is True
    QApplication.instance() or QApplication([])
    window = MapCheckWindow(default_map_check_config())
    window._render(parsed)
    labels = [label.text() for label in window.body.findChildren(QLabel)]
    assert not any(text.startswith("未認識のMod") for text in labels)
    window.close()


def test_reported_map_chaos_and_implicit_wither_aliases_resolve_in_ui():
    parsed = parse_item_text("""アイテムクラス: マップ
レアリティ: レア
Reported Alias Test 3
マップ (ティア 16)
--------
アイテムレベル: 83
--------
{ プレフィックスモッド (ティア: 1) — ダメージ, 物理, 混沌 }
モンスターは物理ダメージの34(31-35)%を追加混沌ダメージとして獲得する
{ サフィックスモッド (ティア: 1) — 混沌, 状態異常 }
モンスターによるヒット時に衰弱を2秒間付与する
""")
    catalog_ids = {
        stat_id for row in load_map_mod_catalog() for stat_id in row.stat_ids
    }
    assert [(modifier.stat_id, modifier.values) for modifier in parsed.modifiers] == [
        ("explicit.stat_1840747977", (34.0, 31.0, -35.0)),
        ("nightmare.stat_monsters_inflict_withered_on_hit", (2.0,)),
    ]
    assert all(modifier.stat_id in catalog_ids for modifier in parsed.modifiers)

    QApplication.instance() or QApplication([])
    window = MapCheckWindow(default_map_check_config())
    window._render(parsed)
    labels = [label.text() for label in window.body.findChildren(QLabel)]
    assert not any(text.startswith("未認識のMod") for text in labels)
    window.close()


def test_reported_nightmare_map_full_copy_resolves_chaos_and_guaranteed_wither():
    parsed = parse_item_text("""アイテムクラス: マップ
レアリティ: レア
禁断の術策
ナイトメアマップ
--------
アイテム数量: +90% (augmented)
アイテムレアリティ: +101% (augmented)
モンスターパックサイズ: +62% (augmented)
スカラベ量が上昇: +35% (augmented)
--------
アイテムレベル: 85
--------
モンスターレベル：83
--------
{ プレフィックスモッド「飢える」 (ティア: 1) }
エリアには溺死のオーブが出現する
{ プレフィックスモッド「冒涜的な」 — ダメージ, 物理, 混沌 }
モンスターはその物理ダメージの34(31-35)%を追加混沌ダメージとして獲得する
モンスターによるヒット時に衰弱を2秒間付与する
(Withered: 衰弱は、受ける混沌ダメージ6%増加させる。最大15スタックまで与えられる)
{ プレフィックスモッド「防呪された」 — キャスター, 呪い }
モンスターに対する呪いの効果が60%低下する
{ サフィックスモッド 「腐敗する」 (ティア: 1) }
エリアには不安定な触手の悪魔が出現する
{ サフィックスモッド 「呪いの」 (ティア: 1) }
プレイヤーはヴァルネラビリティの呪いを受ける
(ヴァルネラビリティは呪術の一種で、対象が受ける物理ダメージが15%増加、対象がヒットを受けた際の出血確率を+20%する。持続時間は8秒)
プレイヤーはテンポラルチェーンの呪いを受ける
(テンポラルチェーンは呪術の一種で、対象のアクションスピードを15%減少させる。レアやユニークの敵は9%減少させる。また対象の他のエフェクトの消失を40%遅くする。プレイヤーに対しては効果が50%低下する。持続時間は5秒)
プレイヤーはエレメンタルウィークネスの呪いを受ける
(エレメンタルウィークネスは呪術の一種で、全ての元素耐性を-15%する。持続時間は8秒)
{ サフィックスモッド 「裏切りの」 (ティア: 1) }
味方に影響する、プレイヤースキルによるオーラは敵にも影響する
--------
自身のマップデバイスで使用することでこのティアまたはそれよりティアの低いマップに移動する。マップは一度のみ使用できる。
--------
カオスオーブ、ヴァールオーブ、デリリウムオーブおよびチゼルでのみ修正可能
""")
    relevant = [
        (modifier.stat_id, modifier.text)
        for modifier in parsed.modifiers
        if "追加混沌ダメージ" in modifier.text or "衰弱を2秒間" in modifier.text
    ]
    assert [stat_id for stat_id, _text in relevant] == [
        "explicit.stat_1840747977",
        "nightmare.stat_monsters_inflict_withered_on_hit",
    ]
    unresolved = [modifier.text for modifier in parsed.modifiers if modifier.stat_id is None]
    assert unresolved == []

    QApplication.instance() or QApplication([])
    window = MapCheckWindow(default_map_check_config())
    window._render(parsed)
    labels = [label.text() for label in window.body.findChildren(QLabel)]
    assert not any(text.startswith("未認識のMod") for text in labels)
    window.close()


def test_manager_groups_ordered_decisions_and_displays_current_choice():
    QApplication.instance() or QApplication([])
    config = default_map_check_config()
    key = next(entry.key for entry in load_map_mod_catalog() if entry.scope == "normal")
    set_decision(config, key, "s")
    dialog = MapModManagerDialog(config)
    headers = [
        dialog.table.horizontalHeaderItem(column).text()
        for column in range(dialog.table.columnCount())
    ]
    assert headers == ["Map Mod", "判定"]
    buttons = dialog.table.cellWidget(0, 1).findChildren(QPushButton)
    assert [button.text() for button in buttons] == ["危険", "警告", "有利", "未設定"]
    assert all(not button.icon().isNull() for button in buttons)
    assert [button.text() for button in buttons if button.isChecked()] == ["未設定"]
    buttons[-1].click()
    assert decision_for(dialog.config, key) == "-"
    buttons[0].click()
    assert [button.text() for button in buttons if button.isChecked()] == ["危険"]
    buttons[0].click()
    assert buttons[0].isChecked()
    buttons[-1].click()
    assert [button.text() for button in buttons if button.isChecked()] == ["未設定"]
    dialog.close()


def test_manager_wraps_full_mod_names_at_24px(qapp, isolated_bundled_font):
    appearance, requested = current_appearance(), requested_appearance()
    assert apply_bundled_ui_font(qapp)
    apply_application_appearance(qapp, {
        "appearance": {"preset": "default", "overrides": {"base_font_size": 24}},
    })
    dialog = MapModManagerDialog(default_map_check_config())
    try:
        dialog.show()
        qapp.processEvents()
        assert dialog.width() == 820
        assert dialog.table.horizontalScrollBar().maximum() == 0

        for row, entry in enumerate(dialog._entries):
            cell = dialog.table.cellWidget(row, 0)
            label = cell.findChild(QLabel, "mapManagerModText")
            assert dialog.table.visualRect(dialog.table.model().index(row, 0)).contains(cell.geometry())
            assert cell.rect().contains(label.geometry()), entry.japanese
            assert label.text() == entry.japanese
            assert label.wordWrap()
            assert label.font().pixelSize() == 24
            metrics = label.fontMetrics()
            assert label.width() >= metrics.horizontalAdvance("マ" * 10)
            wrapped = metrics.boundingRect(label.rect(), Qt.TextWordWrap, entry.japanese)
            assert label.rect().contains(wrapped), entry.japanese

        initial_height = dialog.table.rowHeight(0)
        assert initial_height > dialog.table.rowHeight(2)
        dialog.search.setText("Heist限定")
        assert dialog.table.isRowHidden(0)
        dialog.resize(980, dialog.height())
        qapp.processEvents()
        dialog.search.clear()
        qapp.processEvents()
        assert 0 < dialog.table.rowHeight(0) < initial_height
    finally:
        dialog.close()
        configure_appearance(appearance, requested=requested)


def test_manager_updates_in_place_with_search_and_scroll_preserved(qapp):
    dialog = MapModManagerDialog(default_map_check_config())
    dialog.show()
    dialog.search.setText("モンスター")
    qapp.processEvents()
    scroll = dialog.table.verticalScrollBar()
    scroll.setValue(scroll.maximum() // 2)
    assert (position := scroll.value()) > 0
    row = dialog.table.rowAt(dialog.table.rowHeight(0))
    assert row >= 0
    entry = dialog._entries[row]
    widget = dialog.table.cellWidget(row, 1)
    warning = widget.findChildren(QPushButton)[1]
    saved = []
    dialog.config_changed.connect(lambda config: saved.append(normalized_map_check_config(config)))

    warning.click()
    assert dialog.table.cellWidget(row, 1) is widget
    assert scroll.value() == position
    assert dialog.search.text() == "モンスター"
    assert decision_for(saved[-1], entry.key) == "w"

    dialog.selected_only.setChecked(True)
    assert not dialog.table.isRowHidden(row)
    widget.findChildren(QPushButton)[-1].click()
    assert dialog.table.isRowHidden(row)
    assert dialog.search.text() == "モンスター"
    assert decision_for(saved[-1], entry.key) == "-"
    dialog.close()


def test_manager_clear_persists_for_default_mod_and_profiles_stay_independent(qapp):
    config = default_map_check_config()
    key = next(iter(config["decisions"]))
    dialog = MapModManagerDialog(config)
    row = next(row for row, entry in enumerate(dialog._entries) if entry.key == key)
    buttons = dialog.table.cellWidget(row, 1).findChildren(QPushButton)
    saved = []
    dialog.config_changed.connect(saved.append)
    buttons[-1].click()
    assert saved[-1]["decisions"][key] == "---"
    reopened = MapModManagerDialog(saved[-1])
    assert reopened.table.cellWidget(row, 1).findChildren(QPushButton)[-1].isChecked()
    reopened.profile_buttons[1].click()
    reopened.table.cellWidget(row, 1).findChildren(QPushButton)[0].click()
    assert reopened.config["decisions"][key] == "-d-"
    reopened.profile_buttons[0].click()
    assert reopened.table.cellWidget(row, 1).findChildren(QPushButton)[-1].isChecked()
    reopened.close()
    dialog.close()


def test_manager_regex_search_matches_names_and_scope_and_reports_invalid_patterns(qapp):
    dialog = MapModManagerDialog(default_map_check_config())

    def visible_rows():
        return {row for row in range(dialog.table.rowCount()) if not dialog.table.isRowHidden(row)}

    mod = dialog._entries[0]
    dialog.search.setText(r"^heist限定$|^" + mod.ref.split()[0].lower())
    assert not visible_rows()
    dialog.regex_search.click()
    expected = {row for row, entry in enumerate(dialog._entries)
                if entry.scope == "heist_exclusive"
                or entry.ref.casefold().startswith(mod.ref.split()[0].casefold())}
    assert visible_rows() == expected

    dialog.search.setText("[")
    assert dialog.search.property("error")
    assert dialog.count_label.text() == "Regexの構文エラー"
    assert visible_rows() == expected

    dialog.search.setText("^レアモンスター")
    assert not dialog.search.property("error")
    expected = {row for row, entry in enumerate(dialog._entries)
                if entry.japanese.startswith("レアモンスター")}
    assert expected and visible_rows() == expected
    dialog.selected_only.click()
    assert visible_rows() == {row for row in expected if decision_for(dialog.config, dialog._entries[row].key) != "-"}
    dialog.regex_search.click()
    assert not visible_rows()
    dialog.close()


def test_manager_regex_search_accepts_poe_quoted_and_negated_terms(qapp):
    dialog = MapModManagerDialog(default_map_check_config())
    dialog.regex_search.click()
    dialog.search.setText('"!ter e|son,|from$"')
    visible = {dialog._entries[row].ref for row in range(dialog.table.rowCount())
               if not dialog.table.isRowHidden(row)}
    assert visible == {
        "+#% Monster Elemental Resistances",
        "Monsters cannot be Leeched from",
        "Monsters have a #% chance to avoid Poison, Impale, and Bleeding",
    }
    assert not dialog.search.property("error")

    dialog.search.setText('"cannot be leeched from" "[" ')
    assert dialog.count_label.text() == "Regexの構文エラー"
    dialog.close()


@pytest.mark.parametrize("mode", [POENAVI_MODE, POETORE_MODE])
def test_map_check_uses_mode_theme_and_shared_profile_controls(qapp, mode):
    dialog = MapModManagerDialog(default_map_check_config(), app_mode=mode)
    window = MapCheckWindow(default_map_check_config(), app_mode=mode)
    assert dialog.property("dialogTheme") == mode
    assert f'QDialog[dialogTheme="{mode}"] QTableWidget QPushButton[decisionSegment="true"]' in dialog.styleSheet()
    assert window.property("dialogTheme") == mode
    assert window.property("dialogAccent") == dialog_theme_for_mode(mode).accent
    assert not window.close_button.icon().isNull()
    assert window.close_button.accessibleName() == "閉じる"
    assert [button.minimumSize() for button in window.profile_buttons] == [
        button.minimumSize() for button in dialog.profile_buttons
    ]
    window.close()
    dialog.close()


def test_seen_column_is_hidden_when_new_mod_notifications_are_disabled():
    QApplication.instance() or QApplication([])
    parsed = parse_item_text("""アイテムクラス: マップ
レアリティ: レア
UI Test
Map (Tier 16)
--------
アイテムレベル: 83
--------
{ プレフィックスモッド (ティア: 1) }
レアモンスターの数が25%増加する
""")
    window = MapCheckWindow(default_map_check_config())
    window._render(parsed)
    assert not [
        button for button in window.body.findChildren(QPushButton)
        if button.property("map_seen_key")
    ]
    window.close()


def test_seen_column_uses_clear_labels_and_preserves_colored_decisions():
    QApplication.instance() or QApplication([])
    parsed = parse_item_text("""アイテムクラス: マップ
レアリティ: レア
UI Test
Map (Tier 16)
--------
アイテムレベル: 83
--------
{ プレフィックスモッド (ティア: 1) }
レアモンスターの数が25%増加する
""")
    config = default_map_check_config()
    config["show_new_stats"] = True
    window = MapCheckWindow(config)
    window._render(parsed)
    seen = next(
        button for button in window.body.findChildren(QPushButton)
        if button.property("map_seen_key")
    )
    key = seen.property("map_seen_key")
    assert seen.text() == "未確認"
    assert "確認済み" in seen.toolTip()

    seen.click()
    assert seen.text() == "確認済み"
    decision = next(button for button in window.body.findChildren(QPushButton)
                    if button.property("map_mod_key") == key)
    assert decision.verdict.text() == "未設定"
    decision.click()
    assert decision.verdict.text() == "危険"
    assert seen.text() == "判定済み"
    assert not seen.isEnabled()
    assert decision_for(window.config, key) == "d"
    for label, value in (("警告", "w"), ("有利", "g"), ("未設定", "-")):
        decision.click()
        assert decision.verdict.text() == label
        assert decision_for(window.config, key) == value
    assert seen.text() == "未確認"
    assert seen.isEnabled()
    window.close()


def test_map_check_grows_to_show_all_mod_rows_and_caps_at_screen_height():
    QApplication.instance() or QApplication([])
    parsed = parse_item_text("""アイテムクラス: マップ
レアリティ: レア
Tall UI Test
Map (Tier 16)
--------
アイテムレベル: 83
--------
{ プレフィックスモッド (ティア: 1) }
マジックモンスターの数が23(20-30)%増加する
{ サフィックスモッド (ティア: 1) }
モンスターはヒット時にパワーチャージ、フレンジーチャージおよびエンデュランスチャージのスタックを盗む
{ サフィックスモッド (ティア: 1) }
モンスターはアタックによるヒット時に重傷を付与する
{ サフィックスモッド (ティア: 1) }
全てのプレイヤーの命中力が25%低下する
{ サフィックスモッド (ティア: 1) }
モンスターはヒット時に盲目を付与する
{ サフィックスモッド (ティア: 1) }
モンスターはヒット時にパワーチャージを1個獲得する
{ サフィックスモッド (ティア: 1) }
モンスターはヒット時にフレンジーチャージを1個獲得する
{ サフィックスモッド (ティア: 1) }
モンスターはヒット時にエンデュランスチャージを1個獲得する
{ サフィックスモッド (ティア: 1) }
全てのプレイヤーの獲得フラスコチャージが50%減少する
""")
    window = MapCheckWindow(default_map_check_config())
    window._render(parsed)

    large_screen = PlacementContext(QRect(0, 0, 1920, 1080), QPoint(800, 500))
    window._resize_to_content(large_screen)
    expanded_height = window.height()
    assert expanded_height > window.DEFAULT_HEIGHT
    assert window.scroll.verticalScrollBar().maximum() == 0

    small_screen = PlacementContext(QRect(0, 0, 800, 300), QPoint(400, 150))
    window._resize_to_content(small_screen)
    window.show()
    QApplication.processEvents()
    assert window.height() == 300 - window.SCREEN_EDGE_MARGIN * 2
    assert window.scroll.verticalScrollBar().maximum() > 0
    window.close()


def test_manager_uses_numeric_profiles_without_removed_reflect_defaults():
    QApplication.instance() or QApplication([])
    dialog = MapModManagerDialog(default_map_check_config())
    assert [button.text() for button in dialog.profile_buttons] == ["1", "2", "3"]
    assert dialog.table.rowCount() == 232
    assert "全232件" in dialog.count_label.text()
    dialog.search.setText("更新確認が必要")
    assert all(dialog.table.isRowHidden(row) for row in range(dialog.table.rowCount()))
    dialog.close()


def test_manager_orders_normal_then_uber_map_then_heist_mods():
    QApplication.instance() or QApplication([])
    dialog = MapModManagerDialog(default_map_check_config())
    scopes = [
        next((label.text() for label in dialog.table.cellWidget(row, 0).findChildren(QLabel)
              if label.property("uiRole") == "mapModScope"), "")
        for row in range(dialog.table.rowCount())
    ]
    assert scopes == sorted(
        scopes,
        key={
            "": 0,
            "Uber Map限定": 1,
            "Heist限定": 2,
            "更新確認が必要": 3,
        }.get,
    )
    assert scopes.index("Uber Map限定") > scopes.index("")
    assert scopes.index("Heist限定") > scopes.index("Uber Map限定")
    for tag in ("Uber Map限定", "Heist限定"):
        dialog.search.setText(tag)
        assert [scope for row, scope in enumerate(scopes) if not dialog.table.isRowHidden(row)] == [
            scope for scope in scopes if scope == tag
        ]
    dialog.close()


def test_non_map_clipboard_is_rejected_without_trade_search():
    app = QApplication.instance() or QApplication([])
    app.clipboard().setText("""アイテムクラス: 指輪
レアリティ: ノーマル
鉄の指輪
--------
アイテムレベル: 1
""")
    window = MapCheckWindow(default_map_check_config())
    # The offscreen Qt clipboard is separate from CF_UNICODETEXT. Keep this
    # UI rejection test independent of whatever is on the Windows clipboard.
    with (
        patch("src.poetore.clipboard._read_windows_unicode_text", return_value=""),
        patch("src.ui.map_check.QMessageBox.information") as information,
        patch("src.ui.map_check.QMessageBox.warning", side_effect=AssertionError("Ring fixture must parse")),
    ):
        window._consume_clipboard()
    information.assert_called_once()
    assert "Map系アイテムではありません" in information.call_args.args[2]
    assert not window.isVisible()
    window.close()


def test_map_check_uses_shared_result_font_size(qapp):
    from tests.poetore_ui_scenarios import MAP_ITEM_TEXT

    config = default_map_check_config()
    config["_font_size"] = "large"
    window = MapCheckWindow(config)

    window._item = parse_item_text(MAP_ITEM_TEXT)
    window._render(window._item)
    window.show()
    qapp.processEvents()
    description = window.findChild(QLabel, "mapModText")
    assert description.font().pixelSize() == 16

    window.reload_config({**config, "_font_size": "small"})
    qapp.processEvents()
    description = window.findChild(QLabel, "mapModText")
    assert description.font().pixelSize() == 11
    window.close()


def test_map_check_escape_restores_poe_focus_and_deactivation_closes(qapp):
    window = MapCheckWindow(default_map_check_config())
    window._poe_window_hwnd = 81
    window.show()
    qapp.processEvents()
    with patch("src.ui.map_check.focus_window") as focus:
        QTest.keyClick(window, Qt.Key_Escape)
        qapp.processEvents()
        focus.assert_called_once_with(81)
    assert not window.isVisible()

    window.show()
    qapp.sendEvent(window, QEvent(QEvent.WindowDeactivate))
    qapp.processEvents()
    assert not window.isVisible()
