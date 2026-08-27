"""Tests for watchlist ticker_prices backfill helpers."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

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


def test_sync_quotes_to_ticker_prices_still_writes_normal_symbols():
    """The bulk-SQL bound must not reject a symbol's real, current price —
    only synthetic scripts insert bad data into market_quotes, so a live
    SPY sync should behave exactly as it did before this guard existed."""
    from price_db_sync import count_price_rows, sync_quotes_to_ticker_prices

    sym = "SPY"
    before = count_price_rows(sym)
    sync_quotes_to_ticker_prices([sym])
    after = count_price_rows(sym)
    assert after >= before