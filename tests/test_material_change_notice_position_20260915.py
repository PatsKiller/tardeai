"""Operator 2026-09-15 (WMT notice): say that I own it, my P/L, whether to buy more / wait, sector, strategy and thesis."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import notify_material_change as n  # noqa: E402

HOLDINGS = {"holdings": [
    {"symbol": "WMT", "account": "schwab_rollover_ira", "shares": 100.0, "cost_basis": 10581.0,
     "market_value": 10809.0, "gain_loss": 13.0, "gain_loss_pct": 0.1229},
    {"symbol": "CASH", "is_cash": True, "shares": 1.0, "market_value": 5.0},
]}


def test_position_pl_is_value_minus_cost_not_the_stale_gain_field():
    h = n.holding_for("WMT", HOLDINGS)
    assert h["shares"] == 100.0 and h["accounts"] == ["Rollover IRA"]
    assert round(h["pl_usd"]) == 228 and round(h["pl_pct"], 1) == 2.2
    assert n.holding_for("AAPL", HOLDINGS) is None


# Re-anchored 2026-09-24 (maturity review): sector, strategy and thesis moved to the
# Command Center. What the 09-15 ask needs on the phone survives: that you own it,
# your P/L, and one CIO verdict on whether to add / wait.

WMT_ROW = {"change_guid": "g-1", "symbol": "WMT", "kind": "price_excursion", "magnitude": 3.3,
           "observed_value": 4.1, "universe_reason": "held", "evidence_json": {"move_pct_signed": 4.1}}


def _wmt_info(**over):
    info = {
        "holding": n.holding_for("WMT", HOLDINGS), "price": 108.42, "quote_age_h": 0.1,
        "plan": {"entry": 103.65, "stop": 100.45, "target": 116.69},
        "entry_state": {"state": "NOT_YET", "entry_low": 103.65, "entry_high": 103.65, "rr": 4.07,
                        "distance_pct": 4.6},
    }
    info.update(over)
    return info


def test_the_wmt_page_says_you_own_it_and_your_pl():
    text = n.render([WMT_ROW], {"g-1": _wmt_info()})
    first = text.splitlines()[0]
    assert first == "⚡ BIG MOVE — WMT (held, 100 sh)", first
    assert "position +$228 (+2.2%)" in text and "quote 6m" in text


def test_one_cio_verdict_by_entry_state():
    v = lambda **es: n.cio_verdict({"entry_state": es})["text"]  # noqa: E731
    assert v(state="BUY_READY", entry_low=103.0, entry_high=104.0) == "BUY READY (zone $103.00–$104.00)"
    assert v(state="ENTRY_NEAR", distance_pct=-1.2) == "NEAR ENTRY (1.2% away)"
    assert v(state="BLOCKED", reasons=["quote is 6.0h old"]) == "HOLD-OFF (quote is 6.0h old)"
    assert n.cio_verdict({})["text"] == "no stance on file"


def test_the_more_conservative_view_wins_and_the_other_is_named_superseded():
    """RCL / EXPE 2026-09-24: 'don't buy — blocked' beside 'CIO decision: Buy Ready'."""
    blocked_vs_ready = n.cio_verdict({"entry_state": {"state": "BLOCKED", "reasons": ["price is at or below the plan stop"]},
                                      "cio": {"action": "BUY_READY", "date": "2026-09-22"}})
    assert blocked_vs_ready["text"].startswith("HOLD-OFF (price is at or below the plan stop)")
    assert "BUY READY (2026-09-22) superseded" in blocked_vs_ready["text"]
    avoid_vs_ready = n.cio_verdict({"entry_state": {"state": "BUY_READY", "entry_low": 10.0, "entry_high": 10.0},
                                    "cio": {"action": "AVOID", "date": "2026-09-23"}})
    assert avoid_vs_ready["text"].startswith("AVOID (2026-09-23)") and "overridden" in avoid_vs_ready["text"]
    assert avoid_vs_ready["state"] == "AVOID"


def test_an_unheld_buy_ready_page_says_watchlist_not_held():
    info = _wmt_info(holding=None, entry_state={"state": "BUY_READY", "entry_low": 108.0, "entry_high": 109.0})
    first = n.render([dict(WMT_ROW, universe_reason="watchlist")], {"g-1": info}).splitlines()[0]
    assert first == "🟢 BUY READY — WMT (watchlist, not held)", first
