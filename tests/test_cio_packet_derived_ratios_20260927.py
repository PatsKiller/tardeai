"""The options CIO packet supplies the ratios a reviewer derives from a defined-risk spread
(2026-09-27). DELL cb162b79 attempt 1 was a valid MONITOR_ONLY review refused for one number:
"max loss / credit = 2.15" (1365 / 635). The traceability rail stays; the packet now carries
the ratio. Hermetic."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import options_cio_review as ocr  # noqa: E402

DELL = {"symbol": "DELL", "strategy": "credit_spread", "underlying_price": 563.0, "strike": 520.0,
        "short_strike": 520.0, "long_strike": 500.0, "expiration": "2026-11-20", "dte": 54, "premium": 6.35,
        "executable_credit": 6.35, "mid_credit": 8.1, "credit_haircut": 1.75, "credit_basis": "executable",
        "contracts": 1, "breakeven": 513.65, "pop_pct": 58.7, "iv_rank": 45.4, "max_loss": 1365.0,
        "max_profit": 635.0, "max_loss_at_mid": 1190.0, "breakeven_at_mid": 511.9,
        "enterprise": {"liquidity": {"pass": True, "oi": 366, "bid_ask_spread_pct": 6.99}},
        "legs_liquidity": [{"role": "short put", "strike": 520.0, "bid": 31.75, "ask": 34.05, "mid": 32.9,
                            "open_interest": 366, "volume": 168, "spread_pct": 7.0},
                           {"role": "long put", "strike": 500.0, "bid": 24.2, "ask": 25.4, "mid": 24.8,
                            "open_interest": 666, "volume": 127, "spread_pct": 4.8}]}


def _facts():
    return ocr.build_facts(DELL, disclosures_loader=lambda sym: [])


def test_spread_ratios_are_supplied_as_facts():
    d = _facts()["derived"]
    assert d["loss_to_credit_ratio"] == 2.15 and d["credit_to_loss_ratio"] == 0.47
    assert d["return_on_risk_pct"] == 46.5 and d["spread_width"] == 20.0
    assert d["credit_pct_of_width"] == 31.8 and d["max_loss_per_share"] == 13.65
    assert d["executable_credit"] == 6.35 and d["mid_credit"] == 8.1 and d["credit_haircut_pct_of_mid"] == 21.6
    assert d["long_strike_vs_spot_pct"] == round(100.0 * (500.0 - 563.0) / 563.0, 1)


def test_the_refused_dell_review_now_validates():
    facts = _facts()
    review = {"outcome": "MONITOR_ONLY", "confidence": "MEDIUM",
              "reasoning": ("Thesis is sound, but max loss is 2.15x the credit received ($1,365 vs $635), "
                            "POP 58.7% barely clears the 52% floor, and the 6.99% bid/ask spread is wide."),
              "concerns": ["risk 2.15x reward", "spread 6.99%"], "assumptions_challenged": ["pricing"],
              "evidence_for": ["8-K"], "evidence_against": ["POP 58.7%"], "unknowns": []}
    ok, errs = ocr.validate(review, facts)
    assert ok, errs
    # A number that is genuinely not in the facts is still refused (the rail is intact).
    bad = dict(review, reasoning=review["reasoning"] + " Implied move 7.77% by expiry.")
    ok2, errs2 = ocr.validate(bad, facts)
    assert not ok2 and any("7.77" in e for e in errs2)


def test_single_leg_ideas_get_no_spread_fields_and_no_division_by_zero():
    csp = {"symbol": "P", "strategy": "cash_secured_put", "underlying_price": 120.0, "strike": 115.0, "premium": 2.78,
           "dte": 40, "max_loss": 11222.0, "max_profit": 278.0, "contracts": 1}
    d = ocr.build_facts(csp, disclosures_loader=lambda sym: [])["derived"]
    assert "spread_width" not in d and d["loss_to_credit_ratio"] == round(11222.0 / 278.0, 2)
    hedge = dict(csp, strategy="protective_put", max_profit="hedge", max_loss=1671.0)
    d2 = ocr.build_facts(hedge, disclosures_loader=lambda sym: [])["derived"]
    assert "loss_to_credit_ratio" not in d2
