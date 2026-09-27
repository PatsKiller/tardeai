"""Closed-market quotes are not a liquidity verdict (operator 2026-09-27). Hermetic.

On a weekend the chain showed XLB OI 0 / 131% spread and XAR OI 0 / 198% spread, so
every covered call was dropped as NO_LIQUID_CONTRACT and the desk showed none.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import options_income_quality as q  # noqa: E402

WEEKEND_QUOTE = {"strike": 51.5, "bid": 0.05, "ask": 0.80, "mid": 0.43, "oi": 0, "dte": 33}
CFG = {"min_open_interest": 50, "max_bid_ask_spread_pct": 12.0}


def test_weekend_quote_is_deferred_not_dropped():
    assert q.income_drop_reason("covered_call", WEEKEND_QUOTE, "schwab_chain", 49.8, CFG, session="REGULAR") \
        == "NO_LIQUID_CONTRACT"
    for s in ("WEEKEND", "CLOSED", "PRE_MARKET", "AFTER_HOURS"):
        assert q.income_drop_reason("covered_call", WEEKEND_QUOTE, "schwab_chain", 49.8, CFG, session=s) != \
            "NO_LIQUID_CONTRACT"


def test_other_floors_still_apply_when_closed():
    tiny = {**WEEKEND_QUOTE, "mid": 0.02}
    assert q.income_drop_reason("covered_call", tiny, "schwab_chain", 49.8, CFG, session="WEEKEND") == \
        "PREMIUM_BELOW_FLOOR"
    assert q.income_drop_reason("covered_call", None, "schwab_chain", 49.8, CFG, session="WEEKEND") == "NO_CHAIN"


def test_drop_setting_restores_old_behaviour():
    cfg = {**CFG, "closed_market_liquidity": "drop"}
    assert not q.defer_liquidity("WEEKEND", cfg)
    assert q.income_drop_reason("covered_call", WEEKEND_QUOTE, "schwab_chain", 49.8, cfg, session="WEEKEND") == \
        "NO_LIQUID_CONTRACT"
    assert not q.defer_liquidity(None, CFG)  # unknown session: no deferral


def test_enterprise_gate_labels_awaiting_live_quotes(monkeypatch):
    import types
    import options_desk_enterprise as ode
    fake = types.ModuleType("lib.canonical_observation")
    fake.market_session = lambda: "WEEKEND"
    monkeypatch.setitem(sys.modules, "lib.canonical_observation", fake)
    monkeypatch.setattr(ode, "earnings_blackout_check", lambda *a, **k: {"in_blackout": False})
    p = {"symbol": "XLB", "strategy": "covered_call", "dte": 33, "edge_score": 60, "underlying_price": 49.8}
    ode.enterprise_enrich_proposal(p, contract=WEEKEND_QUOTE, chain=None, cfg=CFG)
    blocks = (p.get("enterprise") or {}).get("blocks") or []
    assert p.get("liquidity_pending") is True
    assert any(str(b).startswith("awaiting live quotes (market weekend)") for b in blocks), blocks
    assert not (p.get("enterprise") or {}).get("live_eligible")
