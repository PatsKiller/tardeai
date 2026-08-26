"""EOD report must show the real sign of negative unrealized P&L."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from eod_open_trade_alert import format_message  # noqa: E402


def _row(symbol, pnl, entry, current, stop=None, target=None, shares=10, strategy="mean_reversion"):
    return {
        "symbol": symbol,
        "strategy_id": strategy,
        "shares": shares,
        "entry_price": entry,
        "current_price": current,
        "stop_loss": stop,
        "target_1": target,
        "unrealized_pnl": pnl,
        "r_multiple": None,
        "created_at": "2026-08-18",
    }


def test_cvs_kmb_negative_pnl_shows_minus():
    rows = [
        _row("CVS", -5.72, 70.00, 69.428, stop=65.0, target=75.0, shares=10),
        _row("KMB", -163.24, 140.00, 123.676, stop=120.0, target=155.0, shares=10),
    ]
    msg = format_message(rows, {})
    assert "DOWN CVS" in msg
    assert "DOWN KMB" in msg
    assert "P&L: -$5.72" in msg
    assert "P&L: -$163.24" in msg
    assert "(-0.8%)" in msg or "(-0.8%" in msg
    # Must not look like a gain
    assert "P&L: +$5.72" not in msg
    assert "P&L: +$163.24" not in msg
    assert "Total unrealized P&L: -$168.96" in msg


def test_positive_still_shows_plus():
    rows = [_row("AAPL", 12.5, 100, 101.25, stop=95, target=110, shares=10)]
    msg = format_message(rows, {})
    assert "UP AAPL" in msg
    assert "P&L: +$12.50" in msg


def test_missing_stop_and_target_render():
    rows = [_row("MSFT", -1.0, 400, 399, stop=None, target=None, shares=5)]
    msg = format_message(rows, {})
    assert "Stop: not set" in msg
    assert "Target: not set" in msg


def test_option_semantics_labeled():
    rows = [_row("AAPL  240920C00200000", -20.0, 2.0, 1.5, stop=1.0, target=4.0, shares=1)]
    rows[0]["asset_type"] = "option"
    msg = format_message(rows, {})
    assert "option" in msg.lower()
