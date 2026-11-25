import gzip
import json

from scripts.build_currency_exchange_item_names import load_source


def test_load_source_accepts_plain_json_and_gzip(tmp_path):
    payload = {"Metadata/Items/Example": "Example Item"}
    plain = tmp_path / "items.json"
    compressed = tmp_path / "items.json.gz"
    plain.write_text(json.dumps(payload), encoding="utf-8")
    with gzip.open(compressed, "wt", encoding="utf-8") as target:
        json.dump(payload, target)

    assert load_source(plain) == payload
    assert load_source(compressed) == payload


def test_load_source_extracts_base_item_names_from_repoe(tmp_path):
    source = tmp_path / "base_items.min.json"
    source.write_text(json.dumps({
        "Metadata/Items/Orb": {"name": " Example Orb ", "drop_level": 1},
        "Metadata/Items/Other": {"drop_level": 1},
        "Metadata/Items/Blank": {"name": " "},
    }), encoding="utf-8")

    assert load_source(source) == {"Metadata/Items/Orb": "Example Orb"}
