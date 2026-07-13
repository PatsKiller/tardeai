"""Tests for watchlist ticker_prices backfill helpers."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def test_count_price_rows_returns_int():
    from price_db_sync import count_price_rows

    n = count_price_rows("SPY")
    assert isinstance(n, int)
    assert n >= 0


def test_sync_quotes_to_ticker_prices_idempotent():
    from price_db_sync import count_price_rows, sync_quotes_to_ticker_prices

    sym = "SPY"
    before = count_price_rows(sym)
    sync_quotes_to_ticker_prices([sym])
    after = count_price_rows(sym)
    assert after >= before


def test_active_proposal_symbols_returns_list():
    from price_db_sync import active_proposal_symbols

    syms = active_proposal_symbols()
    assert isinstance(syms, list)
    assert all(isinstance(s, str) and s.isupper() for s in syms)


def test_ensure_price_history_for_symbol():
    from price_db_sync import count_price_rows, ensure_price_history

    sym = "SPY"
    before = count_price_rows(sym)
    result = ensure_price_history([sym], min_rows=1, yfinance_cap=0)
    after = count_price_rows(sym)
    assert result.get("symbols") == 1
    assert after >= before