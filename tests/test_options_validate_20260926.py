"""Validate a proposal against the live Schwab chain before approval (operator 2026-09-26).

No network: the chain is stubbed with the shape schwab_transport.normalize_option_chain returns.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib import options_validate as ov  # noqa: E402

P = {"id": "p1", "symbol": "DELL", "strategy": "cash_secured_put", "option_type": "put", "strike": 490.0,
     "expiration": "2026-11-20", "premium": 21.57, "underlying_price": 562.89, "contracts": 1,
     "option_strategy_guid": "g", "data_source": "schwab_chain"}
CFG = {"validation": {"max_premium_change_pct": 15, "max_spot_change_pct": 3, "fresh_minutes": 30},
       "min_open_interest": 50, "max_bid_ask_spread_pct": 12.0}


def _chain(bid=21.3, ask=21.9, oi=277, spot=562.89, strike=490.0, exp="2026-11-20"):
    return lambda sym, strikes=40: {"status": "ok", "underlying_price": spot, "expirations": [
        {"exp": exp, "dte": 55, "strikes": [{"side": "put", "strike": strike, "bid": bid, "ask": ask, "last": 21.6,
                                             "oi": oi, "volume": 40, "delta": -0.2}]}]}


def test_unchanged_contract_validates_and_recomputes():
    r = ov.validate(P, chain_fn=_chain(), cfg=CFG, session="REGULAR")
    assert r["status"] == "VALIDATED"
    assert r["recomputed"] == {**r["recomputed"], "premium_total": 2160.0, "breakeven": 468.4, "cash_flow": "credit"}
    assert r["material_changes"] == [] and r["note"] is None


def test_material_premium_move_is_flagged():
    r = ov.validate(P, chain_fn=_chain(bid=14.0, ask=14.6), cfg=CFG)
    assert r["status"] == "CHANGED" and r["material_changes"][0].startswith("premium 21.57 -> 14.3")


def test_spot_move_is_flagged():
    r = ov.validate(P, chain_fn=_chain(spot=524.14), cfg=CFG)
    assert r["status"] == "CHANGED" and any(c.startswith("spot") for c in r["material_changes"])


def test_missing_contract_requires_regeneration():
    r = ov.validate(P, chain_fn=_chain(strike=495.0), cfg=CFG)
    assert r["status"] == "CONTRACT_NOT_FOUND" and "regenerate" in r["reason"]


def test_illiquid_contract_is_not_validated():
    r = ov.validate(P, chain_fn=_chain(oi=0), cfg=CFG)
    assert r["status"] == "ILLIQUID"


def test_black_scholes_estimate_is_not_a_quote():
    r = ov.validate({**P, "data_source": "bs_estimate"}, chain_fn=_chain(), cfg=CFG)
    assert r["status"] == "NOT_A_LISTED_QUOTE"


def test_closed_market_is_noted():
    assert "closed" in ov.validate(P, chain_fn=_chain(), cfg=CFG, session="WEEKEND")["note"]


def test_protective_put_is_a_debit():
    pp = {**P, "strategy": "protective_put", "contracts": 5}
    r = ov.validate(pp, chain_fn=_chain(), cfg=CFG)
    assert r["recomputed"]["cash_flow"] == "debit" and r["recomputed"]["max_loss"] == 10800.0


def test_fresh_validation_window():
    now = datetime.now(timezone.utc)
    ok = {"event_type": "OPTIONS_VALIDATED", "status": "VALIDATED", "validated_at": (now - timedelta(minutes=5)).isoformat()}
    old = {**ok, "validated_at": (now - timedelta(minutes=45)).isoformat()}
    changed = {**ok, "status": "CHANGED"}
    assert ov.fresh_validation([ok], 30, now) is ok
    assert ov.fresh_validation([old], 30, now) is None
    assert ov.fresh_validation([ok, changed], 30, now) is None


def test_approval_requires_fresh_validation_source():
    src = (ROOT / "scripts" / "options_desk_enterprise.py").read_text(encoding="utf-8")
    assert "stale = _validation_refusal(cur, proposal_id)" in src
    assert "validate against live Schwab data first" in src
    api = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    assert '"/api/v2/options/validate"' in api
