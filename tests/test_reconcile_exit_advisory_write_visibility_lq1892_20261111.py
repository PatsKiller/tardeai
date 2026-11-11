"""LQ-20261107-1892: reconcile-exit-advisory-outcomes reported a green run over zero durable rows.

The lane's only write goes through ``db_adapter._execute``, which **swallows every SQL error and returns
``None``** (linux_port_v2/scripts/db_adapter.py:93-96) — and a *successful* ``fetch="none"`` write also
returns ``None``. The reconciler called the INSERT, ignored the result and did ``done += 1``, so the receipt
said ``produced_count=N`` / ``status ok`` / exit 0 whether the rows landed or the store refused every one of
them. That is AGENTS.md §0 rule 8 in its purest form: exit 0 is not evidence of work.

Measured on 2026-11-11 (read-only projection through the real ``reconcile()`` with every INSERT refused and
the run still returning exit 0 / produced 400) and visible in production as ``exit_advisory_outcomes`` = 0
rows while the standing failure was reported as a selector problem.

The fix reads each row back after the INSERT: only a row that can be seen counts as produced, and a write
that did not land makes the run red (``write_not_visible``) instead of green.

Pins (fail before, pass after):

* every INSERT swallowed -> exit 1, receipt ``write_not_visible``, produced_count 0 (was: exit 0, produced N);
* an INSERT that lands is still counted and the run stays green;
* a partial failure (one row lands, one is swallowed) is not green — a green 1 would hide the lost row.

Hermetic: fake ``db_adapter`` and fake bars, tmp ``TRADEAI_STATE_ROOT``, no DB, no network.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

SCRIPT = SCRIPTS / "reconcile_exit_advisory_outcomes.py"
LANE = "reconcile-exit-advisory-outcomes"
NOW = datetime.now(timezone.utc)


def _norm(sql: str) -> str:
    return " ".join(str(sql).split())


def _row(rid, symbol, age_days, price=100.0, atr=1.0):
    # A symbol 60 days old with a dated series scores both horizons; the write path is what this file tests.
    return {"id": rid, "research_type": "protection_advisory", "symbol": symbol, "topic": "protection_advisory",
            "created_at": NOW - timedelta(days=age_days),
            "evidence_json": {"inputs": {"price": price, "atr": atr},
                              "recommendation": {"stop_pct_below": 9.0}}}


def _seq_from(start: datetime, count: int, base: float = 100.0, step: float = 0.1):
    """``count`` weekday closes from ``start`` forward, oldest first."""
    out: list[tuple[str, float]] = []
    d = start
    while len(out) < count:
        if d.weekday() < 5:
            out.append((d.date().isoformat(), round(base + len(out) * step, 4)))
        d += timedelta(days=1)
    return out


class FakeDB:
    """Models the *real* adapter: a write returns None on success and None when the store swallows the error.

    ``refuse`` holds the advisory ids whose INSERT the store rejects (the row is not stored). Every statement
    returns what ``db_adapter._execute`` returns, never a truthy success flag, so a caller that treats "the
    call returned" as "the row exists" is caught.
    """

    def __init__(self, rows, prices=None, refuse=()):
        self.rows = list(rows)
        self.prices = prices or {}
        self.refuse = set(refuse)
        self.outcomes: list[tuple] = []
        self.inserts: list[dict] = []

    def __call__(self, sql, params=None, fetch=None):
        s = _norm(sql)
        if s.startswith("CREATE TABLE"):
            return True
        if "count(*) AS ever" in s:
            accepted = list(params[0]) if params else []
            rows = [r for r in self.rows if r["research_type"] in accepted and r.get("symbol")]
            due = [r for r in rows if r["created_at"] < NOW - timedelta(days=5)]
            pending = [r for r in due if sum(1 for o in self.outcomes if o[0] == r["id"]) < 2]
            newest = max((r["created_at"] for r in rows), default=None)
            return {"ever": len(rows), "due": len(due), "pending": len(pending), "newest": newest}
        if "FROM hermes_research_intelligence" in s and "LIMIT 200" in s:
            accepted = list(params[0]) if params else []
            due = [r for r in self.rows
                   if r["research_type"] in accepted and r.get("symbol")
                   and r["created_at"] < NOW - timedelta(days=5)
                   and sum(1 for o in self.outcomes if o[0] == r["id"]) < 2]
            due.sort(key=lambda r: r["created_at"])
            return due[:200]
        if "SELECT 1 FROM exit_advisory_outcomes" in s:
            return {"?column?": 1} if (params[0], params[1]) in self.outcomes else None
        if "SELECT 1 FROM alert_events" in s:
            return None
        if "ticker_prices" in s:
            if "SELECT 1" in s:
                return {"?column?": 1} if self.prices.get(str(params[0]).upper()) else None
            sym, since = str(params[0]).upper(), str(params[1])[:10]
            return [{"d": d, "close_price": c} for (d, c) in self.prices.get(sym, []) if d >= since]
        if "INSERT INTO exit_advisory_outcomes" in s:
            (advisory_id, symbol, _advisory, _advisory_at, horizon, _p0, _ph, _ret, _spy, _dd, _gb, _acted,
             verdict) = params
            self.inserts.append({"advisory_id": advisory_id, "symbol": symbol, "horizon_days": horizon,
                                 "verdict": verdict})
            if advisory_id in self.refuse:
                return None                      # db_adapter prints the SQL error and returns None
            self.outcomes.append((advisory_id, horizon))
            return None                          # a successful fetch="none" write also returns None
        raise AssertionError(f"unexpected SQL in the lane under test: {s[:160]}")


def _undated(symbol, days=400):
    """The credential-free live shape: OHLC only, no datetime, so the dated store is the live path."""
    return [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}] * 20


def _load(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    spec = importlib.util.spec_from_file_location("_lq1892_write_visibility", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _wire(monkeypatch, db):
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_execute=db, USE_DB=True))
    monkeypatch.setitem(sys.modules, "holdings_gain_guardian",
                        types.SimpleNamespace(_bars_with_volume=_undated))


def _receipt(tmp_path):
    p = tmp_path / "data" / "runtime" / f"{LANE}_last.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _prices(symbols):
    start = NOW - timedelta(days=60)
    return {s: _seq_from(start, 45) for s in symbols}


def test_a_swallowed_insert_is_never_reported_as_produced(monkeypatch, tmp_path, capsys):
    """The failure this task exists for: the store refuses every write and the run still said ok/produced=N."""
    mod = _load(monkeypatch, tmp_path)
    db = FakeDB([_row(1, "AAA", 60), _row(2, "BBB", 60)], prices=_prices(["AAA", "BBB", "SPY"]),
                refuse={1, 2})
    _wire(monkeypatch, db)

    assert mod.reconcile() == 1
    assert db.inserts, "the lane still attempts the writes"
    assert db.outcomes == [], "nothing was stored"
    receipt = _receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["produced_count"] == 0
    assert receipt["empty_reason"] == "write_not_visible"
    assert receipt["skipped_reasons"] == {"write_not_visible": 4}
    assert "write_not_visible" in capsys.readouterr().err


def test_a_visible_write_is_counted_and_the_run_stays_green(monkeypatch, tmp_path):
    """The honest path is unchanged: rows that can be read back are produced, and the run is green."""
    mod = _load(monkeypatch, tmp_path)
    db = FakeDB([_row(1, "AAA", 60)], prices=_prices(["AAA", "SPY"]))
    _wire(monkeypatch, db)

    assert mod.reconcile() == 0
    assert sorted(db.outcomes) == [(1, 5), (1, 21)]
    receipt = _receipt(tmp_path)
    assert receipt["status"] == "ok" and receipt["produced_count"] == 2
    assert "write_not_visible" not in (receipt.get("skipped_reasons") or {})


def test_a_partial_write_failure_is_not_green(monkeypatch, tmp_path):
    """One lost row out of four is still a refused store: a green 1 would hide it."""
    mod = _load(monkeypatch, tmp_path)
    db = FakeDB([_row(1, "AAA", 60), _row(2, "BBB", 60)], prices=_prices(["AAA", "BBB", "SPY"]),
                refuse={2})
    _wire(monkeypatch, db)

    assert mod.reconcile() == 1
    assert sorted(db.outcomes) == [(1, 5), (1, 21)]
    receipt = _receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["produced_count"] == 2
    assert receipt["skipped_reasons"] == {"write_not_visible": 2}
    # ``empty_reason`` stays null because this run was not empty (it produced two rows); the cause is carried
    # by the failing outcome instead — lane_last_receipt sets empty_reason only when produced_count == 0.
    assert receipt["empty_reason"] is None
    assert receipt["outcome"] == "error"
    assert "not visible after INSERT" in (receipt["error"] or "")
