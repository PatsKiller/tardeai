"""Durable retention controls (2026-10-07): registry gate, loader, archive-before-delete, hygiene → incidents."""
from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.check_retention_policy import TAX, validate  # noqa: E402


def _reg(**over):
    doc = {"schema": "DataRetentionPolicy@v1", "size_budget_gb": 16, "policies": [
        {"table": t, "ts_column": "created_at", "class": "KEEP_FOREVER", "window_days": None, "archive": True, "owner": "portfolio",
         "reason": "brokerage/tax record kept seven years", "since": "2026-10-07"} for t in sorted(TAX)]
        + [{"table": "hermes_external_research", "ts_column": "created_at", "class": "ARCHIVE_THEN_DELETE", "window_days": 90, "archive": True,
            "owner": "hermes", "reason": "raw answers; summaries elsewhere", "since": "2026-10-07"},
           {"table": "scope_governor_audit", "ts_column": "created_at", "class": "DELETE", "window_days": 30, "archive": False,
            "owner": "platform", "reason": "audit rows", "since": "2026-10-07"}]}
    doc.update(over)
    return doc


def test_registry_gate_accepts_the_committed_registry():
    doc = json.loads((ROOT / "config" / "data_retention_policy.json").read_text())
    assert validate(doc) == []
    by = {r["table"]: r for r in doc["policies"]}
    for t in TAX:
        assert by[t]["class"] == "KEEP_FOREVER"          # the 180-day delete policy is gone
    assert by["content_embeddings"]["window_days"] == 90


def test_registry_gate_refuses_tax_delete_and_malformed_rows():
    doc = _reg()
    doc["policies"][0]["class"] = "DELETE"; doc["policies"][0]["window_days"] = 180
    errs = validate(doc)
    assert any("must be KEEP_FOREVER" in e for e in errs)
    doc = _reg(); doc["policies"].append({"table": "x", "ts_column": "ts", "class": "ARCHIVE_THEN_DELETE", "window_days": 3, "archive": False,
                                          "owner": "o", "reason": "r", "since": "2026-10-07"})
    errs = validate(doc)
    assert any("window_days must be an int >= 7" in e for e in errs) and any("requires archive=true" in e for e in errs)
    doc = _reg(); doc["policies"].pop(0)
    assert any("must be declared KEEP_FOREVER" in e for e in validate(doc))


def test_loader_skips_keep_forever_and_external(tmp_path, monkeypatch):
    import db_retention as dr
    doc = _reg(); doc["policies"].append({"table": "ext", "ts_column": "created_at", "class": "EXTERNAL_POLICY", "window_days": None,
                                          "archive": False, "owner": "x", "reason": "enforced by hermes librarian retention", "since": "2026-10-07"})
    p = tmp_path / "reg.json"; p.write_text(json.dumps(doc))
    enforced = dr.enforced_policies(dr.load_registry(str(p)))
    tables = [t for t, _, _, _ in enforced]
    assert set(tables) == {"hermes_external_research", "scope_governor_audit"}
    assert ("hermes_external_research", "created_at", 90, True) in enforced
    bad = tmp_path / "bad.json"; bad.write_text(json.dumps({"schema": "nope"}))
    with pytest.raises(SystemExit):
        dr.load_registry(str(bad))


class _Cur:
    def __init__(self, rows): self.rows = rows; self.executed = []
    def execute(self, sql, params=None): self.executed.append(sql)
    def __iter__(self): return iter([(r,) for r in self.rows])


def test_archive_rows_writes_jsonl_gz_and_counts(tmp_path, monkeypatch):
    import db_retention as dr
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    cur = _Cur([{"id": 1, "symbol": "NVDA"}, {"id": 2, "symbol": "AMD"}])
    n, path = dr.archive_rows(cur, "hermes_external_research", "created_at", 90, "")
    assert n == 2 and Path(path).exists()
    with gzip.open(path, "rt") as fh:
        rows = [json.loads(l) for l in fh]
    assert rows[1]["symbol"] == "AMD"
    assert "interval '90 days'" in cur.executed[0]
    empty = _Cur([])
    n0, p0 = dr.archive_rows(empty, "scope_governor_audit", "created_at", 30, "")
    assert n0 == 0 and not Path(p0).exists()


def test_hygiene_findings_become_incidents(tmp_path, monkeypatch):
    from scripts.n8n_incident_fanin import collect
    root = tmp_path / "state"; (root / "data" / "runtime").mkdir(parents=True); (root / "backups" / "n8n").mkdir(parents=True)
    now = datetime.now(timezone.utc)
    (root / "data" / "runtime" / "db_hygiene_last.json").write_text(json.dumps({
        "schema": "DbHygieneReport@v1", "as_of": now.isoformat(), "findings": [
            {"code": "UNCOVERED_TABLE", "item": "big_table", "severity": "P2", "detail": "300 MB, no retention row"},
            {"code": "DUPLICATE_INDEX", "item": "a~b", "severity": "P3", "detail": "exact duplicate"}]}))
    items = {(f["source"], f["item"], f["severity"]) for f in collect(root, now)}
    assert ("db_hygiene", "UNCOVERED_TABLE:big_table", "P2") in items
    assert ("db_hygiene", "DUPLICATE_INDEX:a~b", "P3") in items
