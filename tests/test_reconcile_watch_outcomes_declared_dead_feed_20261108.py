"""ANCHOR: LQ-20261107-1182 (re-delivers LQ-20261107-909). reconcile-watch-outcomes must stop grading an
operator-approved no-producer declaration as a fresh failure, without ever letting an *undeclared* dead feed
read as clean.

The lane's input, ``watch_candidate_events``, has had no writer since 2026-07-16. On 2026-09-13 the operator
approved that as a standing state in ``config/data_source_authority.json`` (domain ``watch_discovery``, class
``dead_feed``, ``no_coverage: declared_gap_no_producer``). LQ-104 made the lane attribute its zero and exit 1;
that was right before the declaration existed and is still right for an undeclared death or an unreadable
registry. This suite pins the split:

* declared gap + dead feed  -> ``no_new_input``, ``ok``, exit 0, receipt names age + approval;
* dead feed WITHOUT a valid operator declaration (absent file, unreadable JSON, no row, other class,
  other ``no_coverage``, non-operator approval) -> ``dependency_unavailable``, exit 1, no ``ok_at``;
* a live feed is never masked by the declaration (``nothing_due``), and real rows still reconcile.

Hermetic: fake ``db_adapter``, synthetic registry documents, no DB, no network, no model call.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"lq1182_{name}", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def receipts(monkeypatch):
    import lib.lane_last_receipt as llr

    calls: list[dict] = []
    monkeypatch.setattr(llr, "write_lane_receipt", lambda lane_id, **kw: calls.append({"lane_id": lane_id, **kw}))
    return calls


def _db(monkeypatch, *, rows=(), last_on="2026-07-16", age_days=115):
    def execute(sql, params=None, fetch=None):
        s = " ".join(sql.split()).lower()
        if s.startswith("select id, symbol"):
            return list(rows)
        if s.startswith("update watch_candidate_events"):
            return None
        if s.startswith("select max(emitted_on)"):
            return {"last_on": last_on, "age_days": age_days}
        if s.startswith("select source_type"):
            return []
        raise AssertionError(f"unexpected SQL: {s[:60]}")

    stub = types.ModuleType("db_adapter")
    stub._execute = execute
    stub.USE_DB = True
    monkeypatch.setitem(sys.modules, "db_adapter", stub)


def _registry(tmp_path, row: dict) -> Path:
    p = tmp_path / "data_source_authority.json"
    p.write_text(json.dumps({"domains": [row]}), encoding="utf-8")
    return p


def _row(**over) -> dict:
    row = {
        "domain": "watch_discovery",
        "class": "dead_feed",
        "store": {"table": "watch_candidate_events"},
        "no_coverage": "declared_gap_no_producer",
        "approval": {"approved_by": "operator", "approved_on": "2026-09-13", "reference": "One Source of Truth"},
    }
    row.update(over)
    return row


# ── the shipped registry really carries the declaration ─────────────────────────────────────────────────────

def test_the_shipped_registry_declares_the_watch_gap():
    mod = _load("reconcile_watch_outcomes")
    gap = mod._declared_gap()
    assert gap is not None, "config/data_source_authority.json must keep the watch_discovery declaration"
    assert gap["no_coverage"] == "declared_gap_no_producer"
    assert gap["declared_by"] == "operator"
    assert gap["declared_on"] == "2026-09-13"


# ── declared gap: typed empty, green, and the receipt carries the declaration ───────────────────────────────

def test_declared_dead_feed_is_a_typed_empty_not_a_failure(monkeypatch, receipts, capsys):
    mod = _load("reconcile_watch_outcomes")
    _db(monkeypatch)
    assert mod.main() == 0
    err = capsys.readouterr().err
    assert "no_new_input" in err and "declared_gap_no_producer" in err
    r = receipts[0]
    assert r["ok"] is True and r["empty_reason"] == "no_new_input"
    assert r["skipped_reasons"] == {"no_new_input": 1}
    assert r["produced_count"] == 0
    assert r["summary"]["feed_last_emitted_on"] == "2026-07-16"
    assert r["summary"]["feed_age_days"] == 115
    assert r["summary"]["declared_gap"]["declared_on"] == "2026-09-13"


def test_a_live_feed_is_never_masked_by_the_declaration(monkeypatch, receipts):
    mod = _load("reconcile_watch_outcomes")
    _db(monkeypatch, last_on="2026-11-05", age_days=3)
    assert mod.main() == 0
    assert receipts[0]["ok"] is True and receipts[0]["empty_reason"] == "nothing_due"


def test_rows_still_reconcile_under_the_declaration(monkeypatch, receipts):
    mod = _load("reconcile_watch_outcomes")
    _db(monkeypatch, rows=[{"id": 1, "symbol": "AAPL", "emitted_on": "2026-09-01", "anchor_price": 100.0}])
    monkeypatch.setattr(mod, "_closes", lambda symbol, cache: [])
    assert mod.main() == 0
    assert receipts[0]["produced_count"] == 1


# ── undeclared / unreadable: the LQ-104 failure stays exactly as it was ─────────────────────────────────────

@pytest.mark.parametrize("case", ["absent", "unreadable", "no_row", "native", "say_so", "agent_approved"])
def test_every_non_operator_or_absent_declaration_stays_dependency_unavailable(monkeypatch, receipts, tmp_path, case):
    mod = _load("reconcile_watch_outcomes")
    _db(monkeypatch)
    if case == "absent":
        path = tmp_path / "missing.json"
    elif case == "unreadable":
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
    elif case == "no_row":
        path = tmp_path / "other.json"
        path.write_text(json.dumps({"domains": [_row(store={"table": "something_else"})]}), encoding="utf-8")
    elif case == "native":
        native = _row()
        native["class"] = "native"
        path = _registry(tmp_path, native)
    elif case == "say_so":
        path = _registry(tmp_path, _row(no_coverage="say_so"))
    else:
        path = _registry(tmp_path, _row(approval={"approved_by": "agent", "approved_on": "2026-09-13"}))
    monkeypatch.setattr(mod, "AUTHORITY_PATH", path)
    assert mod.main() == 1
    assert receipts[0]["ok"] is False and receipts[0]["empty_reason"] == "dependency_unavailable"
    assert receipts[0]["skipped_reasons"] == {"dependency_unavailable": 1}


def test_declared_gap_helper_is_fail_closed(monkeypatch, tmp_path):
    mod = _load("reconcile_watch_outcomes")
    monkeypatch.setattr(mod, "AUTHORITY_PATH", tmp_path / "missing.json")
    assert mod._declared_gap() is None
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setattr(mod, "AUTHORITY_PATH", bad)
    assert mod._declared_gap() is None
    monkeypatch.setattr(mod, "AUTHORITY_PATH", _registry(tmp_path, _row()))
    assert mod._declared_gap() is not None
    assert mod._declared_gap("some_other_table") is None
