"""LQ-20261107-1777: reconcile-exit-advisory-outcomes exits 1 in n8n because its bar source is credential-gated.

Emulated in the credential-free shape every n8n lane child runs in (env-scrubbed, no Schwab creds): the live bar
transport (``schwab_transport.get_price_history``) needs a broker client and returns nothing datable, and
``holding_protection_advisor._bars``' yfinance fallback returns OHLC with **no datetime**. Before this fix every
due pair was a ``bars_unavailable`` skip and a run whose only obstacle was the bar source exited 1 with
``dependency_unavailable`` — the lane could never go green in n8n. The DB already holds dated daily closes
(``ticker_prices``), so the reconciler now falls back to them before declaring the source unavailable.

Pins (fail before, pass after):

* undated live bars + dated ``ticker_prices`` -> the pairs are scored from the DB, exit 0, produced > 0;
* undated live bars + NO dated row in ``ticker_prices`` -> still ``bars_unavailable``, exit 1 (LQ-1706 kept);
* undated live bars + a DB series that starts after the advisory window -> NOT_EVALUABLE rows, exit 0 (the fact
  is about the series, not the source);
* an unreadable ``ticker_prices`` is ``bars_unavailable``, not a silent zero.

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
    """Answers the lane's statements plus the ``ticker_prices`` fallback; records outcome writes."""

    def __init__(self, rows, prices=None, ticker_error=False):
        self.rows = list(rows)
        self.prices = prices or {}          # {"AAA": [(date, close), ...]}
        self.ticker_error = ticker_error
        self.outcomes: list[tuple] = []
        self.inserts: list[dict] = []

    def _accepted(self, params):
        return list(params[0]) if params else []

    def __call__(self, sql, params=None, fetch=None):
        s = _norm(sql)
        if s.startswith("CREATE TABLE"):
            return True
        if "count(*) AS ever" in s:
            rows = [r for r in self.rows if r["research_type"] in self._accepted(params) and r.get("symbol")]
            due = [r for r in rows if r["created_at"] < NOW - timedelta(days=5)]
            pending = [r for r in due if sum(1 for o in self.outcomes if o[0] == r["id"]) < 2]
            newest = max((r["created_at"] for r in rows), default=None)
            return {"ever": len(rows), "due": len(due), "pending": len(pending), "newest": newest}
        if "FROM hermes_research_intelligence" in s and "LIMIT 200" in s:
            due = [r for r in self.rows
                   if r["research_type"] in self._accepted(params) and r.get("symbol")
                   and r["created_at"] < NOW - timedelta(days=5)
                   and sum(1 for o in self.outcomes if o[0] == r["id"]) < 2]
            due.sort(key=lambda r: r["created_at"])
            return due[:200]
        if "SELECT 1 FROM exit_advisory_outcomes" in s:
            return {"?column?": 1} if (params[0], params[1]) in self.outcomes else None
        if "SELECT 1 FROM alert_events" in s:
            return None
        if "ticker_prices" in s:
            if self.ticker_error:
                raise RuntimeError("ticker_prices unavailable")
            if "SELECT 1" in s:
                return {"?column?": 1} if self.prices.get(str(params[0]).upper()) else None
            sym, since = str(params[0]).upper(), str(params[1])[:10]
            rows = [(d, c) for (d, c) in self.prices.get(sym, []) if d >= since]
            return [{"d": d, "close_price": c} for (d, c) in rows]
        if "INSERT INTO exit_advisory_outcomes" in s:
            (advisory_id, symbol, advisory, advisory_at, horizon, price_at_advisory, price_at_horizon,
             symbol_return_pct, spy_return_pct, max_drawdown_atr, giveback_frac_then, operator_acted,
             verdict) = params
            self.inserts.append({"advisory_id": advisory_id, "symbol": symbol, "horizon_days": horizon,
                                 "verdict": verdict, "symbol_return_pct": symbol_return_pct})
            self.outcomes.append((advisory_id, horizon))
            return True
        raise AssertionError(f"unexpected SQL in the lane under test: {s[:160]}")


def _undated(symbol, days=400):
    """The credential-free shape: OHLC only, no datetime (holding_protection_advisor._bars)."""
    return [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}] * 20


def _load(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    spec = importlib.util.spec_from_file_location("_lq1777_exit_advisory_outcomes", SCRIPT)
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


def _prices(symbols, start_days_ago=60, count=45):
    start = NOW - timedelta(days=start_days_ago)
    return {s: _seq_from(start, count) for s in symbols}


# ----------------------------------------------------------------------------------------------------------
# the fix: a dated store rescues a credential-free child
# ----------------------------------------------------------------------------------------------------------

def test_undated_live_bars_are_scored_from_the_dated_store(monkeypatch, tmp_path):
    """Before the fix: undated bars -> every pair bars_unavailable -> exit 1 (the n8n failure)."""
    mod = _load(monkeypatch, tmp_path)
    db = FakeDB([_row(1, "AAA", 60), _row(2, "BBB", 60)], prices=_prices(["AAA", "BBB", "SPY"]))
    _wire(monkeypatch, db)

    assert mod.reconcile() == 0
    assert len(db.inserts) == 4
    assert {i["verdict"] for i in db.inserts} != {"NOT_EVALUABLE"}
    receipt = _receipt(tmp_path)
    assert receipt["status"] == "ok" and receipt["produced_count"] == 4
    assert "bars_unavailable" not in (receipt.get("skipped_reasons") or {})


def test_no_dated_row_anywhere_still_fails_naming_the_source(monkeypatch, tmp_path, capsys):
    """LQ-1706 preserved: if the DB also has no dated close for the symbol, the source is unavailable."""
    mod = _load(monkeypatch, tmp_path)
    db = FakeDB([_row(1, "AAA", 60)], prices={})       # no ticker_prices rows at all
    _wire(monkeypatch, db)

    assert mod.reconcile() == 1
    err = capsys.readouterr().err
    assert "bars_unavailable" in err
    assert db.inserts == []
    receipt = _receipt(tmp_path)
    assert receipt["status"] == "failed"
    assert receipt["empty_reason"] == "dependency_unavailable"
    assert receipt["skipped_reasons"] == {"bars_unavailable": 2}


def test_a_db_series_that_starts_after_the_window_is_not_evaluable(monkeypatch, tmp_path):
    """A datable series that exists but starts after the advisory is a fact about the series, not the source."""
    mod = _load(monkeypatch, tmp_path)
    db = FakeDB([_row(1, "AAA", 60)], prices=_prices(["AAA", "SPY"], start_days_ago=20, count=30))
    _wire(monkeypatch, db)

    assert mod.reconcile() == 0
    assert len(db.inserts) == 2
    assert {i["verdict"] for i in db.inserts} == {"NOT_EVALUABLE"}
    receipt = _receipt(tmp_path)
    assert receipt["status"] == "ok" and receipt["produced_count"] == 2


def test_an_unreadable_store_is_bars_unavailable_not_a_silent_zero(monkeypatch, tmp_path):
    mod = _load(monkeypatch, tmp_path)
    db = FakeDB([_row(1, "AAA", 60)], prices=_prices(["AAA", "SPY"]), ticker_error=True)
    _wire(monkeypatch, db)

    assert mod.reconcile() == 1
    assert db.inserts == []
    assert _receipt(tmp_path)["empty_reason"] == "dependency_unavailable"


# ----------------------------------------------------------------------------------------------------------
# the helper's three answers must not collapse
# ----------------------------------------------------------------------------------------------------------

def test_db_closes_since_three_answers(monkeypatch, tmp_path):
    mod = _load(monkeypatch, tmp_path)
    since = (NOW - timedelta(days=60)).date()
    cover_by = since + timedelta(days=mod.BAR_COVER_SLACK_DAYS)
    have = _seq_from(NOW - timedelta(days=60), 30)

    db = FakeDB([], prices={"AAA": have})
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_execute=db, USE_DB=True))
    closes = mod._db_closes_since("AAA", since.isoformat(), cover_by)
    assert closes == [c for (_, c) in have]                                # reachable window: the closes

    db2 = FakeDB([], prices={})
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_execute=db2, USE_DB=True))
    assert mod._db_closes_since("AAA", since.isoformat(), cover_by) is None   # no dated source at all

    db3 = FakeDB([], prices={"AAA": _seq_from(NOW - timedelta(days=20), 30)})
    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(_execute=db3, USE_DB=True))
    assert mod._db_closes_since("AAA", since.isoformat(), cover_by) == []      # starts after the window
