#!/usr/bin/env python3
"""An entry plan is priced from a live quote, never from the bars' last close (LQ-20261107-04).

``_tech(bars)["price"]`` is ``closes[-1]`` — the last daily bar's close, which the lane used as
today's price: it flowed into atr_pct, sma50_dist, the plan record, the readiness-zone test (which
decides "ready"), the LLM prompt and the Telegram alerter. On a throttled Yahoo feed that close can
be weeks old.

The operator price rule (2026-11-07): the Finviz cache when it is younger than the configured limit,
else a fresh Schwab / Alpaca / moomoo quote — and never a stored print older than 30 minutes. When no
quote satisfies it the symbol is not planned at all; a plan off history is the defect.

No database, no LLM, no network: the price helper is monkeypatched.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import watchlist_entry_planner as P  # noqa: E402
import lib.data_broker.market_quote as MQ  # noqa: E402

SRC = (ROOT / "scripts" / "watchlist_entry_planner.py").read_text()


def _quote(monkeypatch, quote: dict | None):
    monkeypatch.setattr(MQ, "get_price_batch",
                        lambda db_query, symbols, max_age_hours=1, **kw: ({"TESTX": quote} if quote else {}),
                        raising=True)


def _minutes_ago(minutes: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes)).isoformat()


def test_a_finviz_quote_is_accepted_and_carries_its_source(monkeypatch):
    _quote(monkeypatch, {"price": 41.5, "as_of": _minutes_ago(2), "source": "finviz_quote_cache"})
    q = P._fresh_price("TESTX")
    assert q and q["price"] == 41.5 and q["source"] == "finviz_quote_cache"


def test_a_recent_broker_quote_is_accepted(monkeypatch):
    _quote(monkeypatch, {"price": 41.5, "as_of": _minutes_ago(5), "source": "data_broker.market_quote:get_best_quote:schwab"})
    assert P._fresh_price("TESTX")["price"] == 41.5


def test_a_stored_quote_older_than_thirty_minutes_is_refused(monkeypatch):
    _quote(monkeypatch, {"price": 41.5, "as_of": _minutes_ago(180), "source": "data_broker.market_quotes:yahoo"})
    assert P._fresh_price("TESTX") is None, "a three-hour-old DB print is not a live price under the operator rule"


def test_no_quote_at_all_is_refused(monkeypatch):
    _quote(monkeypatch, None)
    assert P._fresh_price("TESTX") is None


def test_an_unreadable_stamp_is_not_a_price(monkeypatch):
    _quote(monkeypatch, {"price": 41.5, "as_of": "yesterday-ish", "source": "data_broker.market_quotes:x"})
    assert P._fresh_price("TESTX") is None


def test_quote_age_reads_iso_and_datetime_and_refuses_junk():
    assert P._quote_age_seconds(_minutes_ago(10)) == pytest.approx(600, abs=30)
    assert P._quote_age_seconds(dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=30)) == pytest.approx(30, abs=30)
    assert P._quote_age_seconds("not a stamp") is None
    assert P._quote_age_seconds(None) is None


def test_the_loop_prices_from_the_quote_after_the_technicals_and_never_falls_back():
    """The seam, in source: the quote replaces the close BEFORE anything reads t["price"].

    On the old file there is no `_fresh_price`, no `no_fresh_price` skip and no such assignment, so
    this is the assertion that fails there.
    """
    tech_at = SRC.index("t = _tech(bars)")
    override_at = SRC.index('t["price"] = float(quote["price"])')
    prompt_at = SRC.index('sma50_dist=(t["price"] - t["sma50"])')
    assert tech_at < override_at < prompt_at, "the price override must sit between the technicals and the prompt"
    assert 'quote = _fresh_price(sym)' in SRC
    assert '_skip("no_fresh_price")' in SRC and "continue" in SRC
    assert 'p["price_source"] = t.get("price_source")' in SRC
    # The close is still what _tech computes; it is simply no longer what a plan is priced from.
    assert 'return {"price": closes[-1]' in SRC
