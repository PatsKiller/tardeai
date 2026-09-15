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
    assert n._position_line({"holding": h}) == "You own 100 sh (Rollover IRA) · cost $105.81 · now $108.09 · +$228 (+2.2%)"
    assert n.holding_for("AAPL", HOLDINGS) is None


def _wmt_info(**over):
    info = {
        "watch": {"source": "portfolio", "since": "2026-09-08"},
        "holding": n.holding_for("WMT", HOLDINGS),
        "strategy": "core_growth_compounder", "strategy_inactive": True,
        "plan": {"entry": 103.65, "stop": 100.45, "target": 116.69}, "price": 108.42,
        "sector": {"sector": "Consumer Defensive", "industry": "Discount Stores"},
        "entry_state": {"state": "NOT_YET", "entry_low": 103.65, "entry_high": 103.65, "rr": 4.07, "distance_pct": 4.6},
        "thesis": {"state": "CURRENT", "summary": n.clean_thesis("WMT", "WMT 1. Walmart remains a high-quality defensive retailer guid=f5794")},
        "last_research": "2026-09-15",
    }
    info.update(over)
    return info


def test_wmt_notice_carries_position_stance_strategy_sector_and_thesis():
    lines = n._detail_lines({"universe_reason": "watchlist"}, _wmt_info())
    text = "\n".join(lines)
    assert lines[0].startswith("you hold this")
    assert "You own 100 sh (Rollover IRA)" in text and "+$228 (+2.2%)" in text
    assert "CIO stance: hold, don't add yet — price is 4.6% above the entry $103.65 · R:R 4.1" in text
    assert "Strategy: core growth compounder (classification inactive)" in text and "none assigned" not in text
    assert "Sector: Consumer Defensive · Discount Stores" in text
    assert "Thesis (current): Walmart remains a high-quality defensive retailer" in text and "guid=" not in text


def test_stance_wording_by_entry_state():
    held = _wmt_info()
    assert "add more: price is inside the entry zone" in n._stance_line({**held, "entry_state": {"state": "BUY_READY", "entry_low": 103.0, "entry_high": 104.0, "rr": 3.0}})
    assert "getting close" in n._stance_line({**held, "entry_state": {"state": "ENTRY_NEAR", "entry_low": 103.65, "entry_high": 103.65, "distance_pct": 1.2}})
    assert "don't add — blocked: quote is 6.0h old" in n._stance_line({**held, "entry_state": {"state": "BLOCKED", "reasons": ["quote is 6.0h old"]}})
    watcher = _wmt_info(holding=None, watch={"source": "ai_discovered", "since": "2026-05-19"})
    assert n._stance_line(watcher).startswith("CIO stance: wait — price is 4.6% above the entry")


def test_ai_discovered_name_is_not_you_asked():
    info = _wmt_info(holding=None, watch={"source": "ai_discovered", "since": "2026-05-19"})
    line = n._provenance_line({"universe_reason": "operator"}, info)
    assert not line.startswith("you asked") and "found by" in line
