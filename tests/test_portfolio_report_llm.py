"""Tests for portfolio_report_llm — grounding and action validation."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from portfolio_report_llm import (  # noqa: E402
    build_grounding,
    fallback_action_text,
    sanitize_action_text,
    validate_action_text,
)


def _sample_holdings():
    return {
        "holdings": [
            {
                "symbol": "V",
                "account": "schwab_rollover_ira",
                "shares": 100,
                "market_value": 30000,
                "current_price": 300.0,
                "is_cash": False,
            },
            {
                "symbol": "SCHD",
                "account": "schwab_rollover_ira",
                "shares": 200,
                "market_value": 6000,
                "current_price": 30.0,
                "is_cash": False,
            },
        ]
    }


def test_build_grounding_includes_held_symbols():
    g = build_grounding(_sample_holdings(), {}, {})
    assert "V" in g.held_symbols
    assert "SCHD" in g.held_symbols
    assert "TSLA" not in g.held_symbols
    assert g.prices.get("V") == 300.0
    assert "V:" in g.positions_table


def test_validate_rejects_unheld_ticker():
    g = build_grounding(_sample_holdings(), {}, {})
    ok, issues = validate_action_text("Buy 50 shares TSLA at $195 before earnings.", g)
    assert not ok
    assert any("TSLA" in i for i in issues)


def test_validate_rejects_price_mismatch():
    g = build_grounding(_sample_holdings(), {}, {})
    ok, issues = validate_action_text("Trim 10 shares of V at $195 to reduce concentration.", g)
    assert not ok
    assert any("price_mismatch" in i for i in issues)


def test_validate_accepts_grounded_action():
    g = build_grounding(_sample_holdings(), {}, {})
    ok, issues = validate_action_text("Add 5 shares of SCHD at $30.00 in Rollover IRA.", g)
    assert ok
    assert issues == []


def test_sanitize_replaces_hallucination_with_fallback():
    g = build_grounding(_sample_holdings(), {}, {})
    out = sanitize_action_text("Buy 50 shares TSLA at $195.", g, monthly=False)
    assert "TSLA" not in out
    assert out == fallback_action_text(g, monthly=False) or len(out) > 10


def test_monthly_fallback_is_numbered():
    g = build_grounding(_sample_holdings(), {}, {})
    fb = fallback_action_text(g, monthly=True)
    assert fb.startswith("1.")