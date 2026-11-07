"""One price rule, one reader — PRICE_RULE_SHARED_20261107.

The operator price rule (2026-11-07): a live price is the Finviz cache when it is younger than
``portfolio_positions.price_stale_after_s`` (30 min), else a fresh broker quote — and never a
stored print older than 30 minutes. Finviz, never yfinance.

LQ-20261107-280 removed the three places a lane re-derived its own answer to that question:

  1. ``market_quote._best_quote`` accepted whatever the quote-only waterfall returned, including a
     delayed yfinance quote — so a symbol whose brokers were silent came back "priced" from the
     provider the operator rule forbids.
  2. ``watchlist_entry_planner._bars`` had no age guard: a 717-hour-old bar close reached a plan as
     "the price".
  3. ``shadow_decision_service.gather_facts`` read the newest ``market_quotes`` row whatever its age
     and called it ``live_price`` (measured 2026-11-07 21:10Z: SPY 735.53 from a row fetched the
     previous session).

The rule now lives in ``market_quote.fresh_price`` / ``quote_age_seconds``, and this file holds it
there. Every test is hermetic: no DB, no network, no broker, no live-store fixture.
"""
from __future__ import annotations

import datetime as dt
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib.data_broker import market_quote as mq   # noqa: E402
import market_quote_provider as mqp              # noqa: E402
import shadow_decision_service as sds            # noqa: E402
import watchlist_entry_planner as wep            # noqa: E402

NOW = dt.datetime.now(dt.timezone.utc)


def _iso(delta_s: float) -> str:
    return (NOW - dt.timedelta(seconds=delta_s)).isoformat()


# ── 1. a delayed display quote is not a price ────────────────────────────────

def _patch_provider(monkeypatch, quote: dict) -> None:
    monkeypatch.setattr(mqp, "quote_only_enabled", lambda: True)
    monkeypatch.setattr(mqp, "get_best_quote", lambda symbol, **kw: dict(quote))


def test_a_yfinance_quote_is_refused_by_the_value_fallback(monkeypatch):
    """The waterfall asks yfinance third. Before this guard a silent broker produced a "priced"
    symbol from the provider the operator rule forbids."""
    _patch_provider(monkeypatch, {"price": 735.29, "provider": "yfinance",
                                  "quote_timestamp": _iso(60)})
    assert mq._best_quote("SPY") is None


def test_a_yahoo_quote_is_refused_too(monkeypatch):
    _patch_provider(monkeypatch, {"price": 735.29, "provider": "Yahoo ",
                                  "quote_timestamp": _iso(60)})
    assert mq._best_quote("SPY") is None


def test_a_broker_quote_still_comes_through(monkeypatch):
    """The guard must not silence the providers the rule allows."""
    _patch_provider(monkeypatch, {"price": 735.29, "provider": "schwab",
                                  "quote_timestamp": _iso(60)})
    q = mq._best_quote("SPY")
    assert q is not None and q["price"] == 735.29 and q["provider"] == "schwab"


# ── 2. quote ages: an unreadable stamp cannot be aged ────────────────────────

@pytest.mark.parametrize("stamp,ok", [
    (_iso(120), True),                       # ISO instant
    (_iso(120).replace("+00:00", "Z"), True),  # the Z spelling
    (NOW.replace(tzinfo=None), True),        # naive is UTC
    (NOW.timestamp(), True),                 # epoch seconds
    ("2026-11-07 01:30:01 ET", False),       # the cache's own spelling, not an instant
    (None, False),
    ("", False),
    ("not a date", False),
])
def test_quote_age_reads_or_refuses_a_stamp(stamp, ok):
    age = mq.quote_age_seconds(stamp)
    if ok:
        assert age is not None and math.isfinite(age) and age < 3600
    else:
        assert age is None


# ── 3. fresh_price: the one reader of the operator rule ──────────────────────

def _patch_batch(monkeypatch, quote: dict | None) -> None:
    monkeypatch.setattr(mq, "get_price_batch",
                        lambda db_query, symbols, **kw: ({symbols[0].upper(): dict(quote)}
                                                          if quote else {}))


def test_a_fresh_finviz_cache_price_is_the_price(monkeypatch):
    """The cache overlay in ``get_price_batch`` only fires when it is younger than
    price_stale_after_s; ``fresh_price`` takes that answer outright."""
    _patch_batch(monkeypatch, {"price": 29.39, "chg_pct": 0.4, "as_of": _iso(20),
                               "source": "finviz_quote_cache"})
    q = mq.fresh_price(lambda *a, **k: [], "pfe")
    assert q is not None and q["price"] == 29.39 and q["source"] == "finviz_quote_cache"


def test_a_fresh_broker_quote_is_accepted(monkeypatch):
    _patch_batch(monkeypatch, {"price": 735.29, "chg_pct": 0.1, "as_of": _iso(90),
                               "source": "data_broker.market_quote:get_best_quote:schwab"})
    q = mq.fresh_price(lambda *a, **k: [], "SPY")
    assert q is not None and q["price"] == 735.29


def test_a_stored_print_older_than_thirty_minutes_is_not_a_price(monkeypatch):
    """The shadow-lane defect: a yesterday-session row served as today's live price."""
    _patch_batch(monkeypatch, {"price": 735.53, "chg_pct": None, "as_of": _iso(19 * 3600),
                               "source": "data_broker.market_quotes:alpaca"})
    assert mq.fresh_price(lambda *a, **k: [], "SPY") is None


def test_a_fresh_yfinance_stored_row_is_not_a_price_either(monkeypatch):
    """market_quotes holds yfinance rows too (measured 2026-11-07: V 422.65, source yfinance).
    Recent is not the same as allowed: the rule says Finviz, never yfinance."""
    _patch_batch(monkeypatch, {"price": 422.65, "chg_pct": None, "as_of": _iso(120),
                               "source": "data_broker.market_quotes:yfinance"})
    assert mq.fresh_price(lambda *a, **k: [], "V") is None


def test_an_undated_price_is_not_a_price(monkeypatch):
    _patch_batch(monkeypatch, {"price": 735.53, "chg_pct": None, "as_of": None,
                               "source": "data_broker.market_quotes:alpaca"})
    assert mq.fresh_price(lambda *a, **k: [], "SPY") is None


def test_no_quote_at_all_is_none_never_a_number(monkeypatch):
    _patch_batch(monkeypatch, None)
    assert mq.fresh_price(lambda *a, **k: [], "SPY") is None


def test_a_failed_read_is_no_price_not_an_exception(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(mq, "get_price_batch", _boom)
    assert mq.fresh_price(lambda *a, **k: [], "SPY") is None


def test_the_planner_and_the_shadow_lane_share_the_max_age():
    assert wep.QUOTE_MAX_AGE_S == mq.PRICE_MAX_AGE_S == 30 * 60


# ── 4. a bar's last close is history, not a price ────────────────────────────

class _Frame:
    """``h["High"]``-style columns plus the row ``index`` a real yfinance frame carries."""

    def __init__(self, rows: int, index):
        self._cols = {"High": [1.02] * rows, "Low": [0.98] * rows, "Close": [1.00] * rows}
        self.index = index

    def __getitem__(self, key):
        return self._cols[key]

    def __len__(self):
        return len(self._cols["Close"])


class _Ticker:
    def __init__(self, frame):
        self._frame = frame

    def history(self, period="1y"):
        return self._frame


def _fake_yfinance(monkeypatch, index) -> None:
    import types
    mod = types.ModuleType("yfinance")
    mod.Ticker = lambda symbol: _Ticker(_Frame(60, index))
    monkeypatch.setitem(sys.modules, "yfinance", mod)


def test_recent_bars_are_used_without_touching_the_broker(monkeypatch):
    _fake_yfinance(monkeypatch, [NOW - dt.timedelta(days=59 - i) for i in range(60)])

    def _no_broker(*a, **k):
        raise AssertionError("the broker path must not run when yfinance bars are current")
    monkeypatch.setattr(wep, "_bars_data_broker", _no_broker)
    bars = wep._bars("TEST", days=60)
    assert bars is not None and len(bars) == 60


def test_a_717_hour_old_bar_is_refused(monkeypatch):
    """The measured defect: the newest candle was 717 hours old and its close became a plan price."""
    # newest candle ~30 days old = 720 h, the measured shape (JEPQ's was 717.05 h)
    _fake_yfinance(monkeypatch, [NOW - dt.timedelta(days=30 + (59 - i)) for i in range(60)])
    monkeypatch.setattr(wep, "_bars_data_broker", lambda *a, **k: None)
    assert wep._bars("JEPQ", days=60) is None


def test_an_undated_frame_is_refused(monkeypatch):
    """A frame that cannot be dated is not evidence of freshness."""
    _fake_yfinance(monkeypatch, [])
    monkeypatch.setattr(wep, "_bars_data_broker", lambda *a, **k: None)
    assert wep._bars("TEST", days=60) is None


def test_the_threshold_is_the_brokers_own():
    assert wep.BROKER_BARS_MAX_AGE_HOURS == 120.0


# ── 5. gather_facts reads live_price through the rule ────────────────────────

class _Cursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _Conn:
    def __init__(self):
        self.cur = _Cursor()

    def cursor(self):
        return self.cur


def _facts(monkeypatch, quote: dict | None, conn=None) -> dict:
    monkeypatch.setattr(mq, "fresh_price",
                        lambda db_query, symbol, **kw: (dict(quote) if quote else None))
    monkeypatch.setattr(sds, "_fundamentals_for", lambda symbol: {})
    monkeypatch.setattr(wep, "_bars", lambda symbol, days=70: None)
    return sds.gather_facts("SPY", conn or _Conn())


def test_gather_facts_records_the_quote_it_used(monkeypatch):
    facts = _facts(monkeypatch, {"price": 735.29, "as_of": _iso(30),
                                 "source": "finviz_quote_cache"})
    assert facts["live_price"] == 735.29
    assert facts["live_price_source"] == "finviz_quote_cache"
    assert facts["live_price_as_of"] is not None
    assert "live_price_reason" not in facts


def test_gather_facts_states_the_absence_instead_of_a_stored_print(monkeypatch):
    conn = _Conn()
    facts = _facts(monkeypatch, None, conn)
    assert facts["live_price"] is None
    assert facts["live_price_source"] is None
    assert "no quote within 30 minutes" in facts["live_price_reason"]
    # It must not go looking for a market_quotes row of its own: the price read is the shared
    # helper above, the only pricing input this lane has.
    assert not any("market_quotes" in sql for sql, _ in conn.cur.calls)
