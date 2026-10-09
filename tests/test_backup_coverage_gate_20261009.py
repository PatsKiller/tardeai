"""Backup/recovery coverage gate (operator question 2026-10-09).

scripts/check_backup_coverage.py --fail-on-new must fail when a change adds an asset the
manifest does not cover, name the gap, and pass once the manifest lists it. Known gaps
are a ratchet: a new gap fails, a baselined one is reported. Fixture repos live in
tmp_path; nothing here reads the host or runs a backup.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_backup_coverage.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_backup_coverage_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


cbc = _load()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _manifest(classes):
    return {
        "schema": "BackupCoverageManifest@v1",
        "mechanisms": {
            "pg_dump_local": {"what": "dump", "pg_exclude_table_data": ["intelligence.*"]},
            "data_offsite": {"what": "tar"},
            "git_remote": {"what": "git"},
        },
        "asset_classes": classes,
    }


def _fixed_class():
    return {"id": "fixed", "mechanism": ["git_remote"], "coverage": "FULL", "restore": "clone",
            "covers": list(cbc.FIXED_ASSETS)}


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    _write(tmp_path / "config/data_source_authority.json", json.dumps({
        "served_from": {"linked_dirs": ["cio"]},
        "domains": [
            {"domain": "quote_price", "store": {"table": "market_quotes"}},
            {"domain": "holdings_accounts", "store": {"file": "portfolios/state/holdings.json"}},
        ],
    }))
    _write(tmp_path / "config/systemd/user/tradeai-x.service", "[Service]\n")
    _write(tmp_path / "config/secret_registry.yaml", "secrets:\n  DB_PASSWORD:\n    class: self_minted\n")
    _write(tmp_path / "migrations/2026-10-01_quotes.sql",
           "CREATE TABLE IF NOT EXISTS market_quotes (id int);\n-- CREATE TABLE ghost (id int);\n")
    _write(tmp_path / "linux_launchers/run_pg_backup.sh",
           "pg_dump --exclude-table-data='intelligence.*' \"$DB\"\n")
    classes = [
        {"id": "stores_pg", "mechanism": ["pg_dump_local"], "coverage": "FULL", "restore": "psql",
         "covers": ["store:quote_price"]},
        {"id": "stores_files", "mechanism": ["data_offsite"], "coverage": "FULL", "restore": "untar",
         "covers": ["store:holdings_accounts", "persistent_tree:data/cio"]},
        {"id": "units", "mechanism": ["git_remote"], "coverage": "FULL", "restore": "install",
         "covers": ["unit:tradeai-x.service"]},
        {"id": "secrets", "mechanism": ["git_remote"], "coverage": "FULL", "restore": "render",
         "covers": ["secret:DB_PASSWORD"]},
        {"id": "pg_excluded", "mechanism": ["pg_dump_local"], "coverage": "PARTIAL", "restore": "ddl only",
         "gap": "data excluded", "covers": ["pg_table:intelligence.*"]},
        {"id": "pg_dumped", "mechanism": ["pg_dump_local"], "coverage": "FULL", "restore": "psql",
         "covers": ["pg_table:public.*"]},
        {"id": "unbacked", "mechanism": "NONE", "coverage": "NONE", "gap": "nothing copies it",
         "covers": ["ps:logs"]},
        _fixed_class(),
    ]
    _write(tmp_path / cbc.MANIFEST_REL, json.dumps(_manifest(classes)))
    _write(tmp_path / cbc.BASELINE_REL, json.dumps({"schema": "BackupCoverageBaseline@v1", "gaps": {}}))
    return tmp_path


def _run(repo: Path, capsys, *extra: str) -> tuple[int, str]:
    rc = cbc.main(["--fail-on-new", "--repo", str(repo), *extra])
    return rc, capsys.readouterr().out


def _add_store(repo: Path, domain: str, store: dict) -> None:
    p = repo / "config/data_source_authority.json"
    data = json.loads(p.read_text())
    data["domains"].append({"domain": domain, "store": store})
    p.write_text(json.dumps(data))


def _edit_manifest(repo: Path, fn) -> None:
    p = repo / cbc.MANIFEST_REL
    data = json.loads(p.read_text())
    fn(data)
    p.write_text(json.dumps(data))


def _cls(data, cid):
    return next(c for c in data["asset_classes"] if c["id"] == cid)


def test_fixture_repo_passes(repo, capsys):
    rc, out = _run(repo, capsys)
    assert rc == 0, out
    assert "PASS" in out


def test_new_store_without_manifest_entry_fails_and_names_it(repo, capsys):
    _add_store(repo, "new_ledger", {"file": "governance/new_ledger.jsonl"})
    rc, out = _run(repo, capsys)
    assert rc == 1
    assert "[NOT IN MANIFEST] store:new_ledger" in out
    assert "stores_pg" in out and "stores_files" in out  # the fix names the candidate classes
    assert "FAIL" in out


def test_report_mode_never_fails(repo, capsys):
    _add_store(repo, "new_ledger", {"file": "governance/new_ledger.jsonl"})
    assert cbc.main(["--repo", str(repo)]) == 0
    assert "store:new_ledger" in capsys.readouterr().out


def test_listed_store_passes(repo, capsys):
    _add_store(repo, "new_ledger", {"file": "portfolios/state/new_ledger.json"})
    _edit_manifest(repo, lambda d: _cls(d, "stores_files")["covers"].append("store:new_ledger"))
    rc, out = _run(repo, capsys)
    assert rc == 0, out


def test_store_cannot_ride_a_wildcard(repo, capsys):
    _add_store(repo, "new_ledger", {"table": "new_ledger"})
    _edit_manifest(repo, lambda d: _cls(d, "stores_pg")["covers"].append("store:*"))
    rc, out = _run(repo, capsys)
    assert rc == 1
    assert "wildcard 'store:*' not allowed" in out


def test_store_in_none_class_is_a_new_gap_until_baselined(repo, capsys):
    _add_store(repo, "new_ledger", {"file": "governance/new_ledger.jsonl"})
    _edit_manifest(repo, lambda d: _cls(d, "unbacked")["covers"].append("store:new_ledger"))
    rc, out = _run(repo, capsys)
    assert rc == 1
    assert "[NEW GAP] store:new_ledger" in out
    assert cbc.BASELINE_REL in out
    (repo / cbc.BASELINE_REL).write_text(json.dumps(
        {"schema": "BackupCoverageBaseline@v1", "gaps": {"store:new_ledger": "NONE: unbacked (test)"}}))
    rc, out = _run(repo, capsys)
    assert rc == 0, out
    assert "[known gap] unbacked: 1 asset(s)" in out


def test_stale_baseline_entry_fails_in_ci_but_not_in_report_mode(repo, capsys):
    # store:quote_price is FULL; a baseline entry for it is stale and would later let a
    # regression of the same asset pass as a "known gap".
    (repo / cbc.BASELINE_REL).write_text(json.dumps(
        {"schema": "BackupCoverageBaseline@v1", "gaps": {"store:quote_price": "NONE: was unbacked"}}))
    rc, out = _run(repo, capsys)
    assert rc == 1, out
    assert "[STALE BASELINE] store:quote_price" in out
    assert cbc.main(["--repo", str(repo)]) == 0


def test_stale_baseline_would_have_hidden_a_regression(repo, capsys):
    (repo / cbc.BASELINE_REL).write_text(json.dumps(
        {"schema": "BackupCoverageBaseline@v1", "gaps": {"store:quote_price": "NONE: fixed long ago"}}))
    # regression: the store loses its backup
    def regress(d):
        _cls(d, "stores_pg")["covers"].remove("store:quote_price")
        _cls(d, "unbacked")["covers"].append("store:quote_price")
    _edit_manifest(repo, regress)
    rc, out = _run(repo, capsys)
    assert rc == 0  # the stale entry absorbs it -- which is why the stale state itself must fail first
    assert "[known gap] unbacked" in out


def test_exact_id_cannot_claim_full_for_excluded_table(repo, capsys):
    _write(repo / "migrations/2026-10-09_vec.sql", "CREATE TABLE intelligence.new_vectors (id int);\n")
    _edit_manifest(repo, lambda d: _cls(d, "pg_dumped")["covers"].append("pg_table:intelligence.new_vectors"))
    rc, out = _run(repo, capsys)
    assert rc == 1, out
    assert "claims FULL coverage for pg_table:intelligence.new_vectors" in out
    assert "pg_table:intelligence.new_vectors resolves to FULL class pg_dumped" in out


def test_broad_full_pattern_ahead_of_excluded_schema_fails(repo, capsys):
    _write(repo / "migrations/2026-10-09_vec.sql", "CREATE TABLE intelligence.new_vectors (id int);\n")
    def broaden(d):
        full = _cls(d, "pg_dumped")
        full["covers"] = ["pg_table:*"]
        d["asset_classes"].remove(full)
        d["asset_classes"].insert(0, full)
    _edit_manifest(repo, broaden)
    rc, out = _run(repo, capsys)
    assert rc == 1, out
    assert "resolves to FULL class pg_dumped" in out


def test_new_unit_and_secret_fail(repo, capsys):
    _write(repo / "config/systemd/user/tradeai-new.timer", "[Timer]\n")
    _write(repo / "config/secret_registry.yaml",
           "secrets:\n  DB_PASSWORD:\n    class: self_minted\n  NEW_KEY:\n    class: vendor_manual\n")
    rc, out = _run(repo, capsys)
    assert rc == 1
    assert "[NOT IN MANIFEST] unit:tradeai-new.timer" in out
    assert "[NOT IN MANIFEST] secret:NEW_KEY" in out


def test_migration_tables_by_schema(repo, capsys):
    _write(repo / "migrations/2026-10-09_more.sql",
           "create table public_extra (id int);\nCREATE TABLE intelligence.new_vectors (id int);\n")
    rc, out = _run(repo, capsys)
    assert rc == 1
    assert "[NEW GAP] pg_table:intelligence.new_vectors" in out
    assert "pg_table:public.public_extra" not in out  # pg_dump covers the public schema
    assert "ghost" not in out  # commented-out DDL is not an asset
    _write(repo / "migrations/2026-10-09_schema.sql", "CREATE TABLE brand_new.t1 (id int);\n")
    rc, out = _run(repo, capsys)
    assert "[NOT IN MANIFEST] pg_table:brand_new.t1" in out


def test_pg_exclusion_drift_fails(repo, capsys):
    _write(repo / "linux_launchers/run_pg_backup.sh",
           "pg_dump --exclude-table-data='intelligence.*' --exclude-table-data='public.*' \"$DB\"\n")
    rc, out = _run(repo, capsys)
    assert rc == 1
    assert "pg_exclude_table_data" in out
    assert "pg_table:public.* has its data excluded" in out


@pytest.mark.parametrize("mutate, message", [
    (lambda c: c.pop("gap"), "requires a gap note"),
    (lambda c: c.update(mechanism=["pg_dump_local"]), "coverage NONE requires mechanism NONE"),
    (lambda c: c.update(mechanism=["tape_robot"], coverage="FULL", restore="x"), "not defined in mechanisms"),
])
def test_manifest_validation(repo, capsys, mutate, message):
    _edit_manifest(repo, lambda d: mutate(_cls(d, "unbacked")))
    rc, out = _run(repo, capsys)
    assert rc == 1
    assert message in out


def test_missing_fixed_asset_fails(repo, capsys):
    _edit_manifest(repo, lambda d: _cls(d, "fixed")["covers"].remove("coordination_ledger:n8n_coordination_ledger.sqlite"))
    rc, out = _run(repo, capsys)
    assert rc == 1
    assert "[NOT IN MANIFEST] coordination_ledger:n8n_coordination_ledger.sqlite" in out


def test_state_root_listing(repo, tmp_path, capsys):
    state = tmp_path / "state_root"
    (state / "logs").mkdir(parents=True)
    rc, out = _run(repo, capsys, "--state-root", str(state))
    assert rc == 1 and "[NEW GAP] ps:logs" in out
    (state / "surprise").mkdir()
    rc, out = _run(repo, capsys, "--state-root", str(state))
    assert "[NOT IN MANIFEST] ps:surprise" in out


def test_unreadable_manifest_exits_2(repo, capsys):
    (repo / cbc.MANIFEST_REL).unlink()
    assert cbc.main(["--fail-on-new", "--repo", str(repo)]) == 2


def test_real_repo_manifest_is_green():
    report = cbc.audit(REPO)
    assert report["manifest_errors"] == []
    assert report["unmapped"] == [], report["unmapped"][:5]
    assert report["new_gaps"] == [], report["new_gaps"][:5]
    # every gap class carries its note, every covered class a restore procedure
    manifest = json.loads((REPO / cbc.MANIFEST_REL).read_text(encoding="utf-8"))
    names = {c["id"] for c in manifest["asset_classes"]}
    for required in ("coordination_ledger", "crontab", "n8n_lab_db", "registry_secrets", "repo_systemd_units"):
        assert required in names
