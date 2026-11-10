"""LQ-20261107-1706: a bar source with no dated bars produced N outcomes and reported a green run.

Emulated in an isolated PROJECT_ROOT (the emulation the assignment asks for is credential-free, so
``holdings_gain_guardian._bars_with_volume`` falls through to ``holding_protection_advisor._bars``, whose
yfinance fallback returns ``{"open","high","low","close"}`` — **no datetime**). Measured on the live fold
(08fc34433) with the 2026-11-08 slot's state:

    dated bars    exit 0  produced 400  verdicts {SIGNAL_CORRECT: 338, SIGNAL_WRONG: 62}
    undated bars  exit 0  produced 400  verdicts {NOT_EVALUABLE: 400}

The second line is the defect. Those 400 rows are permanent: the table is UNIQUE(advisory_id,
horizon_days) and the INSERT is ON CONFLICT DO NOTHING, so no later run ever re-scores them. A run that
measured nothing must not report ``produced 400`` and exit 0.

Pins (fail before, pass after):

* a fetch that returns no bar carrying a date is a ``bars_unavailable`` skip — no outcome row is written;
* a run whose only obstacle was that bar source exits 1 with ``dependency_unavailable`` (the contract's
  fatal reason), naming the source — never a green zero and never ``produced``;
* a **dated** series that merely begins after one advisory's window is unchanged: that advisory's pair is
  written NOT_EVALUABLE, because that is a fact about the advisory, not the source;
* a partial failure stays green, writes the measurable pairs, and names the skipped ones.

Hermetic: fake ``db_adapter`` and fake bars, tmp ``TRADEAI_STATE_ROOT``, no DB, no network.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

SCRIPT = SCRIPTS / "reconcile_exit_advisory_outcomes.py"
LANE = "reconcile-exit-advisory-outcomes"
NOW = datetime.now(timezone.utc)


# ----------------------------------------------------------------------------------------------------------
# fake infrastructure
# ----------------------------------------------------------------------------------------------------------

def _norm(sql: str) -> str:
    return " ".join(str(sql).split())


def _row(rid, research_type, symbol, age_days, evidence):
    return {"id": rid, "research_type": research_type, "symbol": symbol, "topic": research_type,
            "created_at": NOW - timedelta(days=age_days), "evidence_json": evidence}


def _protection(symbol, price=10.0, atr=0.5, pct=9.0):
    return {"inputs": {"price": price, "atr": atr},
            "recommendation": {"stop_pct_below": pct, "stop_price": price * (1 - pct / 100)}}


class FakeDB:
    """Answers the lane's statements from in-memory rows; records what it was asked to write."""

    def __init__(self, rows):
        self.rows = list(rows)
        self.inserts: list[dict] = []
        self.outcomes: list[tuple] = []

    def _accepted(self, params):
        return list(params[0]) if params else []

    def __call__(self, sql, params=None, fetch=None):
        s = _norm(sql)
        if s.startswith("CREATE TABLE"):
            return True
        if "count(*) AS ever" in s:
            types_ = self._accepted(params)
            rows = [r for r in self.rows if r["research_type"] in types_ and r.get("symbol")]
            due = [r for r in rows if r["created_at"] < NOW - timedelta(days=5)]
            pending = [r for r in due if sum(1 for o in self.outcomes if o[0] == r["id"]) < 2]
            newest = max((r["created_at"] for r in rows), default=None)
            return {"ever": len(rows), "due": len(due), "pending": len(pending), "newest": newest}
        if "FROM hermes_research_intelligence" in s and "LIMIT 200" in s:
            types_ = self._accepted(params)
            due = [r for r in self.rows
                   if r["research_type"] in types_ and r.get("symbol")
                   and r["created_at"] < NOW - timedelta(days=5)
                   and sum(1 for o in self.outcomes if o[0] == r["id"]) < 2]
            due.sort(key=lambda r: r["created_at"])
            return due[:200]
        if "SELECT 1 FROM exit_advisory_outcomes" in s:
            return {"?column?": 1} if (params[0], params[1]) in self.outcomes else None
        if "SELECT 1 FROM alert_events" in s:
            return None
        if "ticker_prices" in s:
            # LQ-20261107-1777: the reconciler now falls back to ticker_prices before declaring the source
            # unavailable. This fixture holds no prices, so a symbol has no dated row -> stays bars_unavailable.
            return None if "SELECT 1" in s else []
        if "INSERT INTO exit_advisory_outcomes" in s:
            (advisory_id, symbol, advisory, advisory_at, horizon, price_at_advisory, price_at_horizon,
             symbol_return_pct, spy_return_pct, max_drawdown_atr, giveback_frac_then, operator_acted,
             verdict) = params
            self.inserts.append({"advisory_id": advisory_id, "symbol": symbol, "horizon_days": horizon,
                                 "price_at_advisory": price_at_advisory, "verdict": verdict,
                                 "symbol_return_pct": symbol_return_pct})
            self.outcomes.append((advisory_id, horizon))
            return True
        raise AssertionError(f"unexpected SQL in the lane under test: {s[:160]}")


class FakeBars:
    """Daily closes per symbol, in one of three shapes.

    ``"dated"`` — the real Schwab shape: an ISO ``date`` per bar, long enough to reach the advisory.
    ``"undated"`` — ``holding_protection_advisor._bars``' yfinance fallback: OHLC only, no datetime at all.
    ``"late"`` — dated, but the series starts 20 days ago: honest "does not reach this window".
    """

    def __init__(self, symbols, shape="dated", start_days_ago=None):
        self.symbols = set(symbols)
        self.shape = shape
        self.start_days_ago = start_days_ago
        self.calls: list[str] = []

    def __call__(self, symbol, days=400):
        self.calls.append(symbol)
        if symbol not in self.symbols:
            return []
        start = self.start_days_ago if self.start_days_ago is not None else int(days) + 5
        out = []
        for i in range(start + 1):
            d = (NOW - timedelta(days=start - i)).date()
            if d.weekday() >= 5:
                continue
            if self.shape == "undated":
                out.append({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0 + i * 0.01})
            else:
                out.append({"date": d.isoformat(), "close": 100.0 + i * 0.01})
        return out


def _load(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    spec = importlib.util.spec_from_file_location("_lq1706_exit_advisory_outcomes", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _wire(monkeypatch, mod, db, bars):
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_execute=db, USE_DB=True))
    monkeypatch.setitem(sys.modules, "holdings_gain_guardian",
                        types.SimpleNamespace(_bars_with_volume=bars))
    return db


def _receipt(tmp_path):
    p = tmp_path / "data" / "runtime" / f"{LANE}_last.json"
    return json.loads(p.read_text()) if p.exists() else {}


def _two_due():
    return [_row(1, "protection_advisory", "AAA", 60, _protection("AAA")),
            _row(2, "protection_advisory", "BBB", 60, _protection("BBB", price=20.0))]


# ----------------------------------------------------------------------------------------------------------
# the defect
# ----------------------------------------------------------------------------------------------------------

def test_undated_bars_write_nothing_and_fail_naming_the_source(monkeypatch, tmp_path, capsys):
    """The measured shape: bars with no datetime. Before the fix this wrote 4 NOT_EVALUABLE rows and exited 0."""
    mod = _load(monkeypatch, tmp_path)
    db = FakeDB(_two_due())
    _wire(monkeypatch, mod, db, FakeBars({"AAA", "BBB", "SPY"}, shape="undated"))

    assert mod.reconcile() == 1
    err = capsys.readouterr().err
    assert "bars_unavailable" in err and "all_skipped" in err
    assert db.inserts == []                      # nothing was measured, so nothing is written
    receipt = _receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["empty_reason"] == "dependency_unavailable"
    assert receipt["produced_count"] == 0
    assert receipt["attempted_count"] == 4       # both advisories x (5d, 21d)
    assert receipt["skipped_reasons"] == {"bars_unavailable": 4}


def test_dated_bars_are_the_green_control(monkeypatch, tmp_path):
    """Same rows, same code, dated bars: the four pairs really are measurable, so 4 is an honest produced count."""
    mod = _load(monkeypatch, tmp_path)
    db = FakeDB(_two_due())
    _wire(monkeypatch, mod, db, FakeBars({"AAA", "BBB", "SPY"}, shape="dated"))

    assert mod.reconcile() == 0
    assert len(db.inserts) == 4
    assert {i["verdict"] for i in db.inserts} != {"NOT_EVALUABLE"}
    receipt = _receipt(tmp_path)
    assert receipt["status"] == "ok" and receipt["produced_count"] == 4


def test_a_dated_series_that_starts_late_still_writes_not_evaluable(monkeypatch, tmp_path):
    """``[]`` stays distinct from ``None``: this series exists and is datable, it just does not reach the
    advisory. That fact belongs to the advisory's row (NOT_EVALUABLE), not to the run."""
    mod = _load(monkeypatch, tmp_path)
    db = FakeDB(_two_due())
    _wire(monkeypatch, mod, db, FakeBars({"AAA", "BBB", "SPY"}, shape="dated", start_days_ago=20))

    assert mod.reconcile() == 0
    assert len(db.inserts) == 4
    assert {i["verdict"] for i in db.inserts} == {"NOT_EVALUABLE"}
    receipt = _receipt(tmp_path)
    assert receipt["status"] == "ok" and receipt["produced_count"] == 4
    assert "bars_unavailable" not in (receipt.get("skipped_reasons") or {})


def test_a_partial_bar_failure_stays_green_and_names_what_it_skipped(monkeypatch, tmp_path, capsys):
    """One symbol's source is undatable, the other's is not: score what can be scored, name the rest."""
    mod = _load(monkeypatch, tmp_path)
    db = FakeDB(_two_due())

    class OneSymbolUndated(FakeBars):
        def __call__(self, symbol, days=400):
            if symbol == "AAA":
                self.calls.append(symbol)
                return [{"open": 1.0, "high": 1.0, "low": 1.0, "close": 100.0}] * 10
            return super().__call__(symbol, days)

    _wire(monkeypatch, mod, db, OneSymbolUndated({"AAA", "BBB", "SPY"}, shape="dated"))

    assert mod.reconcile() == 0
    capsys.readouterr()
    assert {i["symbol"] for i in db.inserts} == {"BBB"}
    assert len(db.inserts) == 2
    receipt = _receipt(tmp_path)
    assert receipt["status"] == "ok"
    assert receipt["produced_count"] == 2
    assert receipt["skipped_reasons"] == {"bars_unavailable": 2}


# ----------------------------------------------------------------------------------------------------------
# the helper's two answers must not collapse
# ----------------------------------------------------------------------------------------------------------

def test_closes_since_returns_none_only_when_nothing_carries_a_date(monkeypatch, tmp_path):
    mod = _load(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "_db_closes_since", lambda *a, **k: None)  # LQ-1777: no DB fallback in this unit
    since = (NOW - timedelta(days=60)).isoformat()

    monkeypatch.setitem(sys.modules, "holdings_gain_guardian", types.SimpleNamespace(
        _bars_with_volume=lambda symbol, days=0: [{"open": 1, "high": 1, "low": 1, "close": 9.5}] * 5))
    assert mod._closes_since("AAA", since, 100) is None

    monkeypatch.setitem(sys.modules, "holdings_gain_guardian", types.SimpleNamespace(
        _bars_with_volume=lambda symbol, days=0: []))
    assert mod._closes_since("AAA", since, 100) is None     # no bars at all is the same answer

    monkeypatch.setitem(sys.modules, "holdings_gain_guardian", types.SimpleNamespace(
        _bars_with_volume=lambda symbol, days=0: [{"date": (NOW - timedelta(days=20)).date().isoformat(),
                                                   "close": 9.5}] * 5))
    assert mod._closes_since("AAA", since, 100) == []       # datable but does not reach the window

    monkeypatch.setitem(sys.modules, "holdings_gain_guardian", types.SimpleNamespace(
        _bars_with_volume=lambda symbol, days=0: [
            {"date": (NOW - timedelta(days=d)).date().isoformat(), "close": 10.0} for d in range(90, 0, -1)]))
    assert len(mod._closes_since("AAA", since, 100)) == 60  # only the bars on/after the advisory date


def test_bar_failure_is_not_cached_as_a_timed_outcome(monkeypatch, tmp_path):
    """The cache keeps the raw bars, so one fetch per symbol per run still holds and the answer stays stable."""
    mod = _load(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "_db_closes_since", lambda *a, **k: None)  # LQ-1777: no DB fallback in this unit
    calls: list[str] = []

    def bars(symbol, days=0):
        calls.append(symbol)
        return [{"open": 1, "high": 1, "low": 1, "close": 9.5}]

    monkeypatch.setitem(sys.modules, "holdings_gain_guardian", types.SimpleNamespace(_bars_with_volume=bars))
    cache: dict = {}
    since = (NOW - timedelta(days=60)).isoformat()
    assert mod._closes_since("AAA", since, 100, cache) is None
    assert mod._closes_since("AAA", since, 100, cache) is None
    assert calls == ["AAA"]
