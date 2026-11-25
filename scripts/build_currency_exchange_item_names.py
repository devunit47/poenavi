"""Build the minimal runtime ID/name dictionaries from verified RePoE caches."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.poetore.official_exchange import CHAOS, DIVINE, EXALTED, normalize_name


def _extract_names(payload: object, source: Path | str) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise TypeError(f"Expected object in {source}")
    names = {}
    for item_id, row in payload.items():
        name = row.get("name") if isinstance(row, dict) else row
        if isinstance(name, str) and name.strip():
            names[item_id] = name.strip()
    return names


def load_source(path: Path) -> dict[str, str]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as source:
            payload = json.load(source)
    else:
        with path.open(encoding="utf-8") as source:
            payload = json.load(source)
    return _extract_names(payload, path)


def validate(names: dict[str, str]) -> None:
    expected = {
        CHAOS: "chaos orb",
        DIVINE: "divine orb",
        EXALTED: "exalted orb",
    }
    for item_id, name in expected.items():
        if normalize_name(names.get(item_id, "")) != name:
            raise ValueError(f"Golden ID mismatch for {item_id}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("output", type=Path)
    parser.add_argument("--repoe-url", help="Download an uncompressed RePoE JSON export")
    args = parser.parse_args()
    if (args.source is None) == (args.repoe_url is None):
        parser.error("provide either a source file or --repoe-url")
    if args.repoe_url is not None:
        request = urllib.request.Request(
            args.repoe_url, headers={"User-Agent": "PoENavi/catalog-builder"}
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            names = _extract_names(json.load(response), args.repoe_url)
    else:
        names = load_source(args.source)
    validate(names)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(dict(sorted(names.items())), ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(names)} names to {args.output}")


if __name__ == "__main__":
    main()
