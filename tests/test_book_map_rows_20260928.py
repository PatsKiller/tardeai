"""Book map uses today's broker day P/L when day_change is 0."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.book_map_rows import cash_total, shape_book_row  # noqa: E402


def test_zero_day_change_uses_todays_broker_pl():
    row = shape_book_row(
        {
            "symbol": "SCHD",
            "account": "schwab_rollover_ira",
            "market_value": 63142.52,
            "day_change": 0.0,
            "current_price": 35.14,
            "broker_day_pl": -363.33,
            "broker_day_pl_at": "2026-09-28T15:52:03+00:00",
        },
        sector="Financials",
        stop=None,
        today="2026-09-28",
    )
    assert row["day_change"] == -363.33
    assert row["day_change_basis"] == "broker_day_pl"
    assert row["unpriced"] is False


def test_stale_broker_pl_is_not_used():
    row = shape_book_row(
        {
            "symbol": "V",
            "market_value": 100,
            "day_change": 0,
            "current_price": 10,
            "broker_day_pl": -50,
            "broker_day_pl_at": "2026-09-27T15:00:00+00:00",
        },
        sector="Financials",
        stop=None,
        today="2026-09-28",
    )
    assert row["day_change"] == 0
    assert "day_change_basis" not in row


def test_nonzero_day_change_is_kept():
    row = shape_book_row(
        {
            "symbol": "BAH",
            "market_value": 639,
            "day_change": -18.97,
            "current_price": 74.87,
            "broker_day_pl": -1,
            "broker_day_pl_at": "2026-09-28T15:00:00+00:00",
        },
        sector="Industrials",
        stop=None,
        today="2026-09-28",
    )
    assert row["day_change"] == -18.97
    assert "day_change_basis" not in row


def test_unpriced_cusip_and_cash_total():
    row = shape_book_row(
        {"symbol": "12507E201", "market_value": 0, "day_change": None, "current_price": None, "price": None},
        sector="Unclassified",
        stop=None,
        today="2026-09-28",
    )
    assert row["unpriced"] is True
    assert cash_total([
        {"is_cash": True, "market_value": 978131.38},
        {"is_cash": False, "market_value": 100},
    ]) == 978131.38
