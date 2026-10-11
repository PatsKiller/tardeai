"""Tests for watchlist ticker_prices backfill helpers."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))



@pytest.fixture(autouse=True)
def price_store(monkeypatch):
    """Replace DB/writer boundaries; do not claim to validate PostgreSQL here."""
    import price_db_sync as prices
    store = SimpleNamespace(rows={("SPY", "prior-day"): 500.0}, writes=[], connections=[])

    class Cursor:
        def __init__(self):
            self.closed = False
            self.result = []
            self.calls = []
        def execute(self, sql, params=None):
            self.calls.append((sql, params))
            if "SELECT symbol, COUNT(*) FROM ticker_prices" in sql:
                self.result = [(sym, sum(symbol == sym for symbol, _ in store.rows)) for sym in params[0]]
            elif "SELECT DISTINCT UPPER(symbol) FROM paper_trade_proposals" in sql:
                self.result = [("KO",), ("SPY",)]
            elif "FROM bounded" in sql:
                self.result = []  # Seeded fixture quotes have no outlier candidates.
            else:
                raise AssertionError("unplanned fixture SQL: " + sql)
        def fetchall(self):
            return self.result
        def close(self):
            self.closed = True

    class Connection:
        def __init__(self):
            self.cur = Cursor()
            self.commits = 0
            self.closed = False
        def cursor(self):
            return self.cur
        def commit(self):
            self.commits += 1
        def close(self):
            self.closed = True

    def connect():
        conn = Connection()
        store.connections.append(conn)
        return conn

    def quote_writer(cursor, symbols, *, min_ratio, max_ratio):
        store.writes.append((list(symbols), min_ratio, max_ratio))
        # Shared writer's upsert contract is a fixture boundary. The tests below
        # verify orchestration, arguments and cleanup, not SQL backend behavior.
        for symbol in symbols:
            store.rows[(symbol, "fixture-day")] = 510.0
        return SimpleNamespace(rows_written=len(symbols))

    def no_provider(*args, **kwargs):
        raise AssertionError("a zero-cap test reached the provider")

    monkeypatch.setattr(prices, "_get_conn", connect)
    monkeypatch.setattr(prices, "sync_ticker_prices_from_market_quotes", quote_writer)
    monkeypatch.setattr(prices, "backfill_yfinance_history", no_provider)
    return store


def test_count_price_rows_returns_int(price_store):
    from price_db_sync import count_price_rows

    assert count_price_rows("spy") == 1
    conn = price_store.connections[-1]
    assert conn.closed and conn.cur.closed
    assert conn.cur.calls[0][1] == (["SPY"],)


def test_sync_quotes_to_ticker_prices_idempotent(price_store):
    from price_db_sync import count_price_rows, sync_quotes_to_ticker_prices

    before = count_price_rows("SPY")
    assert sync_quotes_to_ticker_prices(["spy"]) == 1
    assert count_price_rows("SPY") == before + 1
    assert sync_quotes_to_ticker_prices(["SPY"]) == 1
    assert count_price_rows("SPY") == before + 1
    assert len(price_store.writes) == 2
    assert all(conn.closed and conn.cur.closed for conn in price_store.connections)
    assert sum(conn.commits for conn in price_store.connections) == 2


def test_active_proposal_symbols_returns_list(price_store):
    from price_db_sync import active_proposal_symbols

    syms = active_proposal_symbols()
    assert syms == ["KO", "SPY"]
    conn = price_store.connections[-1]
    assert conn.closed and conn.cur.closed
    from price_db_sync import PROPOSAL_ACTIVE_STATUSES
    assert conn.cur.calls[0][1] == (list(PROPOSAL_ACTIVE_STATUSES),)


def test_ensure_price_history_for_symbol(price_store):
    from price_db_sync import count_price_rows, ensure_price_history

    sym = "SPY"
    before = count_price_rows(sym)
    result = ensure_price_history([sym], min_rows=3, yfinance_cap=0)
    after = count_price_rows(sym)
    assert result == {"symbols": 1, "quotes_synced": 1, "short_candidates": 1, "yfinance": {"filled": 0}}
    assert after == before + 1
    assert price_store.writes[0][0] == ["SPY"]


# ── outlier guard (audit finding C3, 2026-08-27) ───────────────────────────
#
# The 2026-07-24-era corrupt-bar incident (NVDA at $0.05) was never actually
# fixed: the only prior check anywhere in this file was `price > 0`. These
# reproduce the exact shape of that incident against the pure decision
# function — no DB required.

def test_no_prior_price_is_never_an_outlier():
    """First price on record for a symbol — nothing to bound it against."""
    from price_db_sync import is_price_outlier

    outlier, _ = is_price_outlier(120.0, None)
    assert outlier is False
    outlier, _ = is_price_outlier(120.0, 0)
    assert outlier is False


def test_normal_daily_move_is_not_an_outlier():
    from price_db_sync import is_price_outlier

    # NVDA-scale price, a real ~3% down day
    outlier, _ = is_price_outlier(174.30, 179.80)
    assert outlier is False


def test_reproduces_the_nvda_corrupt_bar_incident():
    """The actual incident: NVDA (a real ~$180 stock) priced at $0.05."""
    from price_db_sync import is_price_outlier

    outlier, reason = is_price_outlier(0.05, 179.80)
    assert outlier is True
    assert "0.05" in reason and "179.8" in reason


@pytest.mark.parametrize("new_price,prior_price", [
    (13.45, 0.42),   # BYND-shape 32x single-day jump found in the 30-day sweep
    (6.00, 0.04),    # RCON-shape jump
    (0.0007, 0.29),  # SRNE-shape collapse
])
def test_reproduces_the_30_day_sweep_outliers(new_price, prior_price):
    from price_db_sync import is_price_outlier

    outlier, _ = is_price_outlier(new_price, prior_price)
    assert outlier is True


def test_non_numeric_price_is_rejected():
    from price_db_sync import is_price_outlier

    outlier, reason = is_price_outlier("not-a-number", 100.0)
    assert outlier is True
    assert "non-numeric" in reason


def test_non_positive_price_is_rejected_even_with_no_prior():
    from price_db_sync import is_price_outlier

    outlier, reason = is_price_outlier(0, None)
    assert outlier is True
    assert "non-positive" in reason


def test_bounds_are_env_configurable_without_a_code_change():
    from price_db_sync import is_price_outlier

    # A real 15x move a wider-tolerance operator has explicitly allowed.
    outlier, _ = is_price_outlier(15.0, 1.0, min_ratio=0.05, max_ratio=20.0)
    assert outlier is False


def test_sync_quotes_to_ticker_prices_still_writes_normal_symbols(price_store):
    """The orchestrator passes a normal symbol and the configured bounds to its writer."""
    from price_db_sync import count_price_rows, sync_quotes_to_ticker_prices

    sym = "SPY"
    before = count_price_rows(sym)
    sync_quotes_to_ticker_prices([sym])
    after = count_price_rows(sym)
    assert after == before + 1
    from price_db_sync import PRICE_OUTLIER_MIN_RATIO, PRICE_OUTLIER_MAX_RATIO
    assert price_store.writes == [(["SPY"], PRICE_OUTLIER_MIN_RATIO, PRICE_OUTLIER_MAX_RATIO)]
    assert all(conn.closed for conn in price_store.connections)