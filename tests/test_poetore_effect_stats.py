from dataclasses import replace
from pathlib import Path
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
    clipboard = fixture_path.read_text(encoding="utf-8")
    assert clipboard.count(" \u200b") == len(expected)
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
