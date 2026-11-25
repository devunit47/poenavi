from dataclasses import replace
from pathlib import Path
import re
from unittest.mock import patch

import pytest

from src.poetore.metadata import MetadataIndex, ModMetadata, normalize_stat_text
from src.poetore.parser import parse_item_text
from src.poetore.trade import build_search_query, resolve_trade_stat_filters, unresolved_modifier_warnings


@pytest.mark.parametrize(("fixture", "expected"), (
    ("shaper-support-gloves.txt", (("explicit.effect_1276857842", 20), ("explicit.effect_3972941836", 20))),
    ("shaper-support-helmet.txt", (("explicit.effect_1994599451", 18), ("explicit.effect_4174205387", 20))),
))
def test_shaper_support_effects_match_and_keep_their_trade_ids(fixture, expected):
    fixture_path = Path(__file__).parent / "fixtures" / "poetore" / fixture
    clipboard, inserted = re.subn(
        r"(?m)^ソケットされたジェムはレベル\d+ ",
        lambda match: match[0] + "\u200b",
        fixture_path.read_text(encoding="utf-8"),
    )
    assert inserted == len(expected)
    item = parse_item_text(clipboard)
    supports = tuple(mod for mod in item.modifiers if mod.text.startswith("ソケットされたジェム"))
    assert tuple((mod.stat_id, mod.values) for mod in supports) == tuple(
        (stat_id, (level,)) for stat_id, level in expected
    )
    assert unresolved_modifier_warnings(item) == ()

    official_entries = tuple(
        {"id": stat_id, "type": "explicit", "text": normalize_stat_text(mod.text)}
        for (stat_id, _), mod in zip(expected, supports, strict=True)
    )
    with patch("src.poetore.trade._trade_stat_entries", return_value=official_entries):
        filters_by_id = {row.stat_id: row for row in resolve_trade_stat_filters(item)}
    filters = tuple(replace(filters_by_id[stat_id], enabled=True) for stat_id, _ in expected)
    query = build_search_query(item, stat_filters=filters)["query"]
    assert [row["id"] for row in query["stats"][0]["filters"]] == [
        stat_id for stat_id, _ in expected
    ]


def test_effect_index_ignores_zero_width_characters_in_official_template():
    record = ModMetadata(
        "Socketed Gems are Supported by Level # Slower Projectiles Support",
        "explicit.effect_1276857842",
        "explicit",
        ("ソケットされたジェムはレベル# \u200b\u200c\u200d\ufeff投射物低速化サポートによってサポートされる",),
    )
    index = MetadataIndex((record,))
    assert index.match(
        "ソケットされたジェムはレベル20 投射物低速化サポートによってサポートされる", "explicit",
    ) == (record, 1.0)


@pytest.mark.parametrize(("text", "stat_id", "level"), (
    ("Grants Level 25 Wintertide Brand Skill", "explicit.effect_582742716", 25),
    ("Grants Level 25 Wintertide Brand", "explicit.effect_582742716", 25),
    ("Socketed Gems are Supported by Level 20 Faster Projectiles", "explicit.effect_1770376530", 20),
    ("Socketed Gems are Supported by Level 20 Faster Projectiles Support", "explicit.effect_1770376530", 20),
))
def test_english_fixed_skill_effects_use_new_trade_ids(text, stat_id, level):
    item = parse_item_text(
        "Item Class: Gloves\nRarity: Rare\nDoom Grip\nFingerless Silk Gloves\n"
        f"--------\nItem Level: 85\n--------\n{text}"
    )
    assert [(mod.stat_id, mod.values) for mod in item.modifiers] == [(stat_id, (level,))]


@pytest.mark.parametrize("name", ("Forbidden Shako", "Replica Forbidden Shako"))
def test_english_shako_support_keeps_the_random_support_id(name):
    item = parse_item_text(
        f"Item Class: Helmets\nRarity: Unique\n{name}\nGreat Crown\n"
        "--------\nItem Level: 85\n--------\n"
        "Socketed Gems are Supported by Level 20 Faster Projectiles"
    )
    assert [(mod.stat_id, mod.values) for mod in item.modifiers] == [
        ("explicit.indexable_support_84", (20,)),
    ]


def test_english_affliction_keeps_the_existing_matcher_when_text_is_shared():
    item = parse_item_text(
        "Item Class: Gloves\nRarity: Rare\nDoom Grip\nFingerless Silk Gloves\n"
        "--------\nItem Level: 85\n--------\nGrants Level 20 Affliction"
    )
    assert [(mod.stat_id, mod.values) for mod in item.modifiers] == [
        ("explicit.stat_3486646279", (20,)),
    ]


@pytest.mark.parametrize(("stat_id", "ja", "en", "value"), (
    ("explicit.effect_2031996092",
     "ソケットされたジェムはレベル20 \u200b神のセンチネルサポートによってサポートされる",
     "Socketed Gems are Supported by Level 20 Divine Sentinel Support", 20),
    ("explicit.effect_3251718963",
     "ソケットされたジェムはレベル18 \u200b殲滅サポートによってサポートされる",
     "Socketed Gems are Supported by Level 18 Annihilation Support", 18),
    ("fractured.stat_1351682252",
     "設置したトラップまたはマイン1個ごとにダメージが5%増加する",
     "5% increased Damage for each Trap and Mine you have", 5),
    ("fractured.stat_181387736", "1個のプレフィックスモッドが変化しない",
     "1 Prefix Modifier cannot be changed", 1),
    ("fractured.stat_181387736", "2個のプレフィックスモッドが変化しない",
     "2 Prefix Modifiers cannot be changed", 2),
))
def test_new_official_stats_resolve_from_bilingual_clipboard(stat_id, ja, en, value):
    fractured = stat_id.startswith("fractured.")
    for prefix, header, text in (
        ("アイテムクラス: 手袋\nレアリティ: レア\nテスト\n指無しシルクグローブ\n--------\nアイテムレベル: 85",
         "{ フラクチャー プレフィックスモッド「テスト」 (ティア: 1) }", ja),
        ("Item Class: Gloves\nRarity: Rare\nTest\nFingerless Silk Gloves\n--------\nItem Level: 85",
         '{ Fractured Prefix Modifier "Test" (Tier: 1) }', en),
    ):
        item = parse_item_text(f"{prefix}\n--------\n" + (header + "\n" if fractured else "") + text)
        assert [(mod.stat_id, mod.values) for mod in item.modifiers] == [(stat_id, (value,))]
