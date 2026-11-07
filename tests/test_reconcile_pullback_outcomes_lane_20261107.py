"""reconcile-pullback-outcomes writes a LaneRunReceipt@v2 on a real run (n8n onboarding, 2026-11-07).

LQ-20261107-26, lane 8 of the cc-deepseek-8 wave (family F50, disposition MIGRATE_N8N, class learn). Its registry
``output_signal`` was the cron ``>> logs/pullback_outcomes.log`` redirect's mtime — cron opening a file, not the run
(AGENTS.md §9.3, rail 8) — so ``r1_class_admission`` could not admit it (it needs ``json_key ok_at`` on
``data/runtime/<lane>_last.json``). These tests pin the receipt's shape and the two failure modes that used to be
invisible: a run that dies, and one unreadable symbol costing the whole batch.

Synthetic fixtures only (the repo is public): a fake ``db_adapter`` / ``holdings_gain_guardian`` and a tmp state root.
No DB, no network, no .env read (a fake ``dotenv`` is injected before the module imports).
"""
from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

LANE = "reconcile-pullback-outcomes"


class _DB:
    """Records the lane's writes; answers the due-trigger SELECT with ``rows``."""

    def __init__(self, rows, *, use_db=True, select_raises=None):
        self.rows, self.use_db, self.select_raises = rows, use_db, select_raises
        self.updates: list[tuple] = []

    def _execute(self, sql, params=None, fetch=None):
        if "SELECT id, symbol, trigger_date" in sql:
            if self.select_raises is not None:
                raise self.select_raises
            return list(self.rows)
        if "UPDATE pullback_trigger_history" in sql:
            self.updates.append(params)
            return None
        raise AssertionError(f"unexpected SQL: {sql[:60]}")


def _load(monkeypatch, tmp_path, db, bars):
    """Import the lane against fake dotenv/db/bars modules and a throwaway state root."""
    dotenv = types.ModuleType("dotenv")
    dotenv.load_dotenv = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "dotenv", dotenv)

    db_mod = types.ModuleType("db_adapter")
    db_mod._execute = db._execute
    db_mod.USE_DB = db.use_db
    monkeypatch.setitem(sys.modules, "db_adapter", db_mod)

    hgg = types.ModuleType("holdings_gain_guardian")
    hgg._bars_with_volume = bars
    monkeypatch.setitem(sys.modules, "holdings_gain_guardian", hgg)

    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.delenv("TRADEAI_RUN_ID", raising=False)
    sys.modules.pop("reconcile_pullback_outcomes", None)
    return importlib.import_module("reconcile_pullback_outcomes")


def _receipt(tmp_path) -> dict:
    path = tmp_path / "state" / "data" / "runtime" / f"{LANE}_last.json"
    assert path.is_file(), f"no receipt at {path}"
    return json.loads(path.read_text(encoding="utf-8"))


def _row(rid, symbol, stop=1.0, tgt=10.0, day="2026-10-01"):
    import datetime as dt

    return {"id": rid, "symbol": symbol, "trigger_date": dt.date.fromisoformat(day),
            "entry": 5.0, "stop": stop, "target1": tgt}


def _bars(*, n, high=0.0, low=0.0, start="2026-10-02"):
    """n daily bars after the trigger, each with the given high/low."""
    import datetime as dt

    d0 = dt.date.fromisoformat(start)
    return [{"date": (d0 + dt.timedelta(days=i)).isoformat(), "high": high, "low": low} for i in range(n)]


def test_a_real_run_writes_a_v2_receipt_and_only_names_what_it_did(monkeypatch, tmp_path):
    db = _DB([_row(1, "AAA"), _row(2, "BBB")])

    def bars(symbol, days=60):
        return _bars(n=3, high=11.0) if symbol == "AAA" else _bars(n=2, high=6.0)

    m = _load(monkeypatch, tmp_path, db, bars)
    assert m.main() == 0
    assert sum(1 for _ in db.updates) == 1, "BBB has too few bars — it must not be written this week"

    r = _receipt(tmp_path)
    assert r["schema"] == "LaneRunReceipt@v2"
    assert r["lane_id"] == LANE and r["script"] == "reconcile_pullback_outcomes.py"
    assert r["status"] == "ok" and r["exit"] == 0 and r["ok_at"]
    assert r["produced_count"] == 1 and r["attempted_count"] == 2
    assert r["skipped_reasons"] == {"not_enough_bars_yet": 1}
    assert r["summary"]["by_outcome"] == {"TARGET1_FIRST": 1}
    assert r["summary"]["due"] == 2
    # run QUALITY (scripts/lib/run_quality.py): the summary is evidence about the product, and the run's own
    # verdict is the top-level `status`, so a verdict word must not live in the summary.
    assert not {"status", "overall_status", "verdict"} & set(r["summary"])


def test_a_clean_no_due_run_still_advances_ok_at(monkeypatch, tmp_path):
    m = _load(monkeypatch, tmp_path, _DB([]), lambda *a, **k: [])
    assert m.main() == 0
    r = _receipt(tmp_path)
    assert r["status"] == "ok" and r["ok_at"]
    assert r["produced_count"] == 0 and r["attempted_count"] == 0
    assert r["empty_reason"] == "no_due_rows"


def test_one_unreadable_symbol_does_not_cost_the_batch(monkeypatch, tmp_path):
    db = _DB([_row(1, "AAA"), _row(2, "BBB")])

    def bars(symbol, days=60):
        if symbol == "AAA":
            raise RuntimeError("bars source unavailable")
        return _bars(n=3, high=11.0)

    m = _load(monkeypatch, tmp_path, db, bars)
    assert m.main() == 0
    r = _receipt(tmp_path)
    assert r["status"] == "ok"
    assert r["produced_count"] == 1 and r["attempted_count"] == 2
    assert r["skipped_reasons"] == {"bars_unavailable": 1}


def test_a_db_unavailable_run_writes_failed_without_an_ok_at(monkeypatch, tmp_path):
    m = _load(monkeypatch, tmp_path, _DB([], use_db=False), lambda *a, **k: [])
    assert m.main() == 2
    r = _receipt(tmp_path)
    assert r["status"] == "failed" and r["exit"] == 2
    assert not r.get("ok_at"), "a failed run must not mint an ok_at"
    assert r["error"].startswith("DBUnavailable")
