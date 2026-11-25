import json
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

import pytest

from scripts import build_poetore_metadata as builder
from scripts import update_poetore_trade_data as updater
from scripts.build_poetore_map_mods import source_from_lock
from scripts.build_poetore_metadata import _run_regression_tests
from scripts.update_poetore_trade_data import (
    atomic_apply_manifest,
    audit_bilingual_items,
    audit_bilingual_stats,
    build_pseudo_relations_candidate,
    diff_pseudo_relations,
    sha256_file,
    verify_manifest,
    verify_representative_trade_api,
)


def test_bilingual_items_ignore_entry_order_but_detect_structure_difference():
    english = {"result": [{"id": "gem", "entries": [
        {"type": "Fireball"},
        {"type": "Vaal Fireball", "disc": "vaal"},
    ]}]}
    japanese = {"result": [{"id": "gem", "entries": [
        {"type": "ヴァールファイヤーボール", "disc": "vaal"},
        {"type": "ファイヤーボール"},
    ]}]}
    assert audit_bilingual_items(english, japanese)["structure_mismatches"] == []

    japanese["result"][0]["entries"].pop()
    assert audit_bilingual_items(english, japanese)["structure_mismatches"][0]["group"] == "gem"


def test_bilingual_stats_compare_ids_types_and_option_ids_not_translation():
    english = {"result": [{"id": "explicit", "entries": [
        {"id": "explicit.one", "text": "One", "type": "explicit",
         "option": {"options": [{"id": 1, "text": "A"}]}},
        {"id": "explicit.english_only", "text": "Only", "type": "explicit"},
    ]}]}
    japanese = {"result": [{"id": "explicit", "entries": [
        {"id": "explicit.one", "text": "一", "type": "implicit",
         "option": {"options": [{"id": 2, "text": "乙"}]}},
    ]}]}
    result = audit_bilingual_stats(english, japanese)
    assert result["english_only"] == ["explicit.english_only"]
    assert result["option_mismatches"][0]["id"] == "explicit.one"
    assert result["type_mismatches"][0]["id"] == "explicit.one"


def _manifest(root: Path, targets: dict[str, tuple[Path, Path]]) -> Path:
    rows = {}
    for name, (target, candidate) in targets.items():
        rows[name] = {
            "target": str(target.relative_to(root)),
            "candidate": str(candidate.relative_to(root)),
            "base_sha256": sha256_file(target),
            "candidate_sha256": sha256_file(candidate),
        }
    path = root / "manifest.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "mode": "refresh",
        "root": str(root),
        "files": rows,
    }), encoding="utf-8")
    return path


def test_manifest_rejects_candidate_tampering_and_authoritative_changes(tmp_path):
    target = tmp_path / "target.json"
    candidate = tmp_path / "candidate.json"
    target.write_text("old", encoding="utf-8")
    candidate.write_text("new", encoding="utf-8")
    manifest = _manifest(tmp_path, {"data": (target, candidate)})
    verify_manifest(manifest, tmp_path)

    candidate.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="candidate file hash mismatch"):
        verify_manifest(manifest, tmp_path)
    candidate.write_text("new", encoding="utf-8")
    target.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="authoritative file changed"):
        verify_manifest(manifest, tmp_path)


def test_atomic_apply_rolls_back_all_files_when_replace_fails(tmp_path):
    targets = {}
    for index in range(2):
        target = tmp_path / f"target-{index}.json"
        candidate = tmp_path / f"candidate-{index}.json"
        target.write_text(f"old-{index}", encoding="utf-8")
        candidate.write_text(f"new-{index}", encoding="utf-8")
        targets[str(index)] = (target, candidate)
    manifest = _manifest(tmp_path, targets)
    calls = 0

    def fail_second(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated replace failure")
        Path(source).replace(target)

    with pytest.raises(OSError, match="simulated"):
        atomic_apply_manifest(manifest, tmp_path, replace=fail_second)
    assert (tmp_path / "target-0.json").read_text() == "old-0"
    assert (tmp_path / "target-1.json").read_text() == "old-1"


def test_atomic_apply_replaces_every_reviewed_file(tmp_path):
    targets = {}
    for index in range(2):
        target = tmp_path / f"target-{index}.json"
        candidate = tmp_path / f"candidate-{index}.json"
        target.write_text(f"old-{index}", encoding="utf-8")
        candidate.write_text(f"new-{index}", encoding="utf-8")
        targets[str(index)] = (target, candidate)
    manifest = _manifest(tmp_path, targets)
    applied = atomic_apply_manifest(manifest, tmp_path)
    assert len(applied) == 2
    assert (tmp_path / "target-0.json").read_text() == "new-0"
    assert (tmp_path / "target-1.json").read_text() == "new-1"


def test_external_candidate_does_not_claim_distribution_data_file(tmp_path):
    candidate = tmp_path / "mod_metadata.json"
    candidate.write_text("{}", encoding="utf-8")
    captured = {}
    commands = []
    command_envs = []

    def run(command, **kwargs):
        commands.append(command)
        command_envs.append(kwargs["env"])
        captured.update(kwargs["env"])

    with patch("scripts.build_poetore_metadata.subprocess.run", side_effect=run):
        _run_regression_tests(candidate)
    assert captured["POETORE_METADATA_PATH"] == str(candidate.resolve())
    assert "POETORE_CANDIDATE_BUILD" not in captured
    assert commands
    assert all(command[1:4] == ["-m", "pytest", "-q"] for command in commands)
    assert any(Path(command[-1]).name == "test_poetore_ui.py" for command in commands)
    single_instance_index = next(
        index for index, command in enumerate(commands)
        if Path(command[-1]).name == "test_single_instance.py"
    )
    assert command_envs[single_instance_index]["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"


def test_candidate_regression_disables_plugins_for_windows_single_instance_path(tmp_path):
    candidate = tmp_path / "mod_metadata.json"
    candidate.write_text("{}", encoding="utf-8")
    captured = {}

    def run(_command, **kwargs):
        captured.update(kwargs["env"])

    with (
        patch.object(
            Path,
            "glob",
            return_value=[PureWindowsPath("tests/test_single_instance.py")],
        ),
        patch("scripts.build_poetore_metadata.subprocess.run", side_effect=run),
    ):
        _run_regression_tests(candidate)

    assert captured["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"


def test_in_place_metadata_candidate_claims_distribution_candidate_file():
    candidate = Path("data/poetore/.mod_metadata.json.candidate")
    captured = {}

    def run(_command, **kwargs):
        captured.update(kwargs["env"])

    with patch("scripts.build_poetore_metadata.subprocess.run", side_effect=run):
        _run_regression_tests(candidate)

    assert captured["POETORE_CANDIDATE_BUILD"] == "1"


def test_representative_api_verifier_reports_success_and_failure():
    cases = [
        {
            "id": "ok", "trade_base": "Fireball",
            "text": "Item Class: Skill Gems\nRarity: Gem\nFireball\n--------\nLevel: 1",
        },
        {
            "id": "bad", "trade_base": "Fireball",
            "text": "Item Class: Skill Gems\nRarity: Gem\nFireball\n--------\nLevel: 1",
        },
    ]
    responses = iter(({"id": "query-1", "result": ["a"]}, {"error": "rejected"}))
    result = verify_representative_trade_api(
        cases=cases, sender=lambda _url, _payload: next(responses), pause=lambda _value: None,
    )
    assert result["passed"] == [{"id": "ok", "query_id": "query-1", "candidates": 1}]
    assert result["failures"] == [{"id": "bad", "error": "rejected"}]


def test_fixed_awakened_archive_reproduces_pseudo_relations():
    root = Path(__file__).parents[1]
    archive, revision = source_from_lock(root / "scripts/poetore-sources.lock.json")
    generated = build_pseudo_relations_candidate(
        root / archive,
        revision,
    )
    current = json.loads(
        (root / "data/poetore/pseudo_relations.json").read_text(encoding="utf-8")
    )
    assert generated["relations"] == current["relations"]


def test_pseudo_diff_reports_added_removed_and_changed_rows():
    old = {"relations": [
        {"pseudo_ref": "same", "stat_id": "1"},
        {"pseudo_ref": "changed", "stat_id": "2"},
        {"pseudo_ref": "removed", "stat_id": "3"},
    ]}
    new = {"relations": [
        {"pseudo_ref": "same", "stat_id": "1"},
        {"pseudo_ref": "changed", "stat_id": "4"},
        {"pseudo_ref": "added", "stat_id": "5"},
    ]}
    result = diff_pseudo_relations(old, new)
    assert [row["pseudo_ref"] for row in result["added"]] == ["added"]
    assert [row["pseudo_ref"] for row in result["removed"]] == ["removed"]
    assert [row["pseudo_ref"] for row in result["changed"]] == ["changed"]


def _write_json(root, relative, payload):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _official_payload(*entries):
    return {"result": [{"id": "Currency", "entries": list(entries)}]}


def test_official_check_reports_changes_without_building_or_applying(tmp_path, monkeypatch):
    stat_id = "fractured.effect_1"
    en = _official_payload({"id": stat_id, "type": "fractured", "text": "Grants A"})
    ja = _official_payload({"id": stat_id, "type": "fractured", "text": "付与 A"})
    effect_path = _write_json(tmp_path, updater.AUTHORITATIVE["effect_english"], {
        "templates": {stat_id: "Grants Old"},
    })
    _write_json(tmp_path, updater.AUTHORITATIVE["official_stats_baseline"], {
        "entries": [{"kind": "fractured", "stat_id": stat_id, "japanese": "付与 A", "english": "Grants Old"}],
    })
    _write_json(tmp_path, "scripts/poetore-stat-rules.json", {"rules": [{"stat_id": stat_id}]})
    catalog = {
        "sources": {
            realm: {lang: {"sha256": "old"} for lang in urls}
            for realm, urls in updater.STATIC_URLS.items()
        },
        "realms": {realm: {"items": [{"en": "Existing"}]} for realm in updater.STATIC_URLS},
    }
    _write_json(tmp_path, updater.EXCHANGE_CATALOG, catalog)
    payloads = {
        updater.OFFICIAL_URLS["stats_en"]: (en, "latest"),
        updater.OFFICIAL_URLS["stats_ja"]: (ja, "latest"),
        **{
            url: (_official_payload(), "same")
            for name, url in updater.OFFICIAL_URLS.items() if name.startswith("items")
        },
        **{
            url: (_official_payload(
                {"id": "new", "text": "New" if lang == "en" else "新規"},
                {"id": "sep", "text": "Category header"},
            ), "latest")
            for urls in updater.STATIC_URLS.values() for lang, url in urls.items()
        },
    }
    monkeypatch.setattr(updater, "run_audit", lambda **_: pytest.fail("heavy audit was called"))
    run_check = updater.run_official_check
    monkeypatch.setattr(updater, "run_official_check", lambda: run_check(tmp_path, payloads.__getitem__))
    assert updater.main(["--check-official", "--fail-on-updates"]) == 3
    assert updater.main(["--check-official"]) == 0
    report = updater.load_json(tmp_path / "build/poetore-official-check-report.json")
    changed = report["metadata"]["official_trade_changes"]["changed"][0]
    assert changed["in_stat_rules"] and changed["is_skill_effect"]
    assert changed["previous_english"] == "Grants Old"
    assert changed["current_english"] == "Grants A"
    effects = report["metadata"]["effect_english_changes"]
    assert effects["current_kind_counts"] == {"fractured.effect_": 1, "crafted.effect_": 0}
    assert report["static"]["poe1"]["sources"]["ja"]["changed"]
    assert report["static"]["poe1"]["candidates"] == [
        {"group": "Currency", "id": "new", "english": "New", "japanese": "新規"},
    ]
    assert "Grants Old → Grants A" in (tmp_path / "build/poetore-official-check-report.md").read_text(encoding="utf-8")
    assert updater.load_json(effect_path)["templates"][stat_id] == "Grants Old"

    _write_json(tmp_path, updater.AUTHORITATIVE["effect_english"], {"templates": {stat_id: "Grants A"}})
    _write_json(tmp_path, updater.AUTHORITATIVE["official_stats_baseline"],
                updater.official_trade_entry_snapshot(ja, en))
    for sources in catalog["sources"].values():
        for source in sources.values():
            source["sha256"] = "latest"
    _write_json(tmp_path, updater.EXCHANGE_CATALOG, catalog)
    assert updater.main(["--check-official", "--fail-on-updates"]) == 0
    assert updater.load_json(tmp_path / "build/poetore-official-check-report.json")["status"] == "UP TO DATE"


def test_official_check_blocks_when_api_is_unavailable(tmp_path, monkeypatch):
    def unavailable(_url, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(updater, "fetch_json", unavailable)
    run_check = updater.run_official_check
    monkeypatch.setattr(updater, "run_official_check", lambda: run_check(tmp_path))
    assert updater.main(["--check-official", "--fail-on-updates"]) == 2
    assert updater.main(["--check-official"]) == 2
    report = updater.load_json(tmp_path / "build/poetore-official-check-report.json")
    assert report["status"] == "BLOCKED"
    assert len(report["failures"]) == 8


def test_refresh_syncs_effect_source_and_manifest_publishes_it(tmp_path, monkeypatch):
    en_url = "https://www.pathofexile.com/api/trade/data/stats"
    stat_id = "explicit.effect_1"
    templates = {stat_id: "Grants A"}
    official_en = json.dumps(_official_payload({
        "id": stat_id, "type": "explicit", "text": templates[stat_id],
    })).encode()
    blobs = {
        "awakened_poe_trade": b"", "awakened_items": b"", "awakened_item_drops": b"[]",
        "jp_trade_api": json.dumps(_official_payload({
            "id": stat_id, "type": "explicit", "text": "付与 A",
        })).encode(),
        "repoe_stats": b"{}", "repoe_mods": b"{}",
    }
    lock = _write_json(tmp_path, "lock.json", {"generated_at": "today", "sources": {
        name: {"url": name, "sha256": updater.sha256_bytes(blob)} for name, blob in blobs.items()
    }})
    baseline = _write_json(tmp_path, "baseline.json", {"entries": []})
    target = _write_json(tmp_path, updater.AUTHORITATIVE["effect_english"], {
        "url": en_url, "sha256": "old", "templates": {},
    })
    candidate_dir = tmp_path / "candidate"
    candidate = _write_json(candidate_dir, target.name, updater.load_json(target))
    monkeypatch.setattr(updater, "CANDIDATE_DIR", candidate_dir)
    command = updater._metadata_command(candidate=True)
    assert command[command.index("--effect-english") + 1] == str(candidate)

    fetched = []

    def get(url):
        fetched.append(url)
        return official_en if url == en_url else blobs[url]

    args = [
        "build_poetore_metadata.py", "--lock", str(lock),
        "--official-baseline", str(baseline), "--effect-english", str(candidate),
        "--stat-rules", str(_write_json(tmp_path, "rules.json", {"rules": []})),
        "--japanese-overrides", str(_write_json(tmp_path, "overrides.json", {})),
        "--output", str(tmp_path / "metadata.json"), "--report", str(tmp_path / "report.json"),
    ]
    monkeypatch.setattr(builder, "_get", get)
    monkeypatch.setattr(builder, "_run_regression_tests", lambda _: None)
    monkeypatch.setattr(builder.sys, "argv", args + ["--apply"])
    assert builder.main() == 0
    assert en_url not in fetched
    previous = updater.load_json(tmp_path / "metadata.json")
    previous["gems"] = {"reviewed": {"trade_type": "Reviewed", "max_level": 20}}
    _write_json(tmp_path, "metadata.json", previous)
    monkeypatch.setattr(builder.sys, "argv", args + ["--refresh-lock"])
    assert builder.main() == 0
    assert en_url in fetched
    assert updater.load_json(candidate)["templates"] == {}
    monkeypatch.setattr(builder.sys, "argv", args + ["--refresh-lock", "--apply"])
    assert builder.main() == 0
    assert list(updater.load_json(candidate)) == ["sha256", "templates", "url"]
    assert updater.load_json(candidate)["sha256"] == updater.sha256_bytes(official_en)
    metadata = updater.load_json(tmp_path / "metadata.json")
    assert metadata["mods"][0]["english"] == ["Grants A"]
    assert metadata["gems"] == previous["gems"]
    report = updater.load_json(tmp_path / "report.json")
    assert report["effect_english_changes"]["added"] == [{"stat_id": stat_id, "english": "Grants A"}]
    manifest = _manifest(tmp_path, {"effect_english": (target, candidate)})
    assert atomic_apply_manifest(manifest, tmp_path) == [target]
    assert updater.load_json(target)["templates"] == templates
