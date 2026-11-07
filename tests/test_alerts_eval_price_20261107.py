#!/usr/bin/env python3
"""A price-cross watch alert must read the one shared price helper, never market_quotes itself.

Data-truth audit 2026-11-07 (LQ-20261107-04): the evaluator read
``market_quotes`` directly, which served PFE 27.56 from 16:45 ET while Finviz at 23:30 ET said
29.39. Under the operator price rule (2026-11-07) a live price comes from the Finviz cache when it
is younger than the configured limit, else a fresh Schwab / Alpaca / moomoo quote — never a stored
DB print older than that.

The three behaviours pinned here:

  1. A symbol whose market_quotes row is stale but whose Finviz quote is fresh DOES fire. The old
     code skipped it: a stale print silenced a real cross.
  2. With the helper returning nothing, the evaluator does NOT fall back to its own market_quotes
     read. The old code fired off that row. One price source, or none.
  3. A quote the helper returns but which is stale for its session still never fires.

No database, no network: ``ex`` is a stub and the helper is monkeypatched.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import watch_alerts_eval as W  # noqa: E402
import lib.data_broker.market_quote as MQ  # noqa: E402


ALERT = {
    "id": 41,
    "symbol": "TESTX",
    "condition_type": "price_cross_above",
    "threshold": 100,
    "recurring": False,
    "last_fired_at": None,
    "cooldown_days": 5,
}


class StubDb:
    """Only the statements the evaluator is allowed to issue.

    ``market_quote`` is what a direct read WOULD have found — the fix must never ask for it.
    """

    def __init__(self, market_quote: dict | None):
        self.market_quote = market_quote
        self.sql: list[str] = []
        self.inserted: list[tuple] = []

    def __call__(self, sql, params=(), fetch="all"):
        flat = " ".join(str(sql).split())
        self.sql.append(flat)
        if flat.startswith("SELECT 1 FROM alert_events"):
            return None
        if "FROM market_quotes" in flat:
            return self.market_quote
        if flat.startswith("INSERT INTO alert_events"):
            self.inserted.append(tuple(params or ()))
            return None
        if flat.startswith("UPDATE watch_alerts"):
            return None
        raise AssertionError(f"unexpected SQL from the alert evaluator: {flat[:120]}")


@pytest.fixture
def helper(monkeypatch):
    """Install a fake get_price_batch and hand back a setter."""
    state = {"result": {}}

    def fake_get_price_batch(db_query, symbols, max_age_hours=12, *, skip_live=False, finviz_first=True):
        state["called_with"] = list(symbols)
        return state["result"]

    monkeypatch.setattr(MQ, "get_price_batch", fake_get_price_batch, raising=True)
    return state


@pytest.fixture
def quotes_are_current(monkeypatch):
    """The session gate is not what these cases are about (this file may be run on a Saturday).

    It IS exercised, unpatched, by test_a_stale_quote_from_the_helper_never_fires.
    """
    monkeypatch.setattr(W, "_quote_is_current", lambda fetched_at: True)


def _now_iso(minutes_ago: float = 0.5) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes_ago)).isoformat()


THREE_DAYS_AGO = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)).isoformat()


def test_a_fresh_finviz_quote_fires_even_when_the_db_row_is_stale(helper, quotes_are_current):
    helper["result"] = {"TESTX": {"price": 105.0, "as_of": _now_iso(), "source": "finviz_quote_cache"}}
    db = StubDb(market_quote={"price": 105.0, "fetched_at": THREE_DAYS_AGO})

    lines, fired = W._evaluate_single_condition_alerts(db, [dict(ALERT)], "2026-11-07")

    assert fired == [41], "a fresh Finviz price above the threshold must fire the cross"
    assert len(db.inserted) == 1
    assert helper["called_with"] == ["TESTX"], "the pass must batch the price symbols, not read per alert"
    assert not [s for s in db.sql if "FROM market_quotes" in s], (
        "the evaluator must not read market_quotes itself; the shared helper owns the price source"
    )


def test_no_helper_quote_never_falls_back_to_the_market_quotes_row(helper, quotes_are_current):
    helper["result"] = {}
    db = StubDb(market_quote={"price": 105.0, "fetched_at": _now_iso()})

    lines, fired = W._evaluate_single_condition_alerts(db, [dict(ALERT)], "2026-11-07")

    assert fired == [], "with no quote from the helper there is no price to fire on"
    assert db.inserted == []


def test_a_stale_quote_from_the_helper_never_fires(helper):
    helper["result"] = {"TESTX": {"price": 105.0, "as_of": THREE_DAYS_AGO, "source": "data_broker.market_quotes:x"}}
    db = StubDb(market_quote=None)

    lines, fired = W._evaluate_single_condition_alerts(db, [dict(ALERT)], "2026-11-07")

    assert fired == [], "a quote stale for its session keeps its stale-print protection"
    assert db.inserted == []


def test_a_quote_below_the_threshold_does_not_fire(helper, quotes_are_current):
    helper["result"] = {"TESTX": {"price": 99.0, "as_of": _now_iso(), "source": "finviz_quote_cache"}}
    db = StubDb(market_quote=None)

    _, fired = W._evaluate_single_condition_alerts(db, [dict(ALERT)], "2026-11-07")

    assert fired == []
