"""Phase 10 tests — options lifecycle policy engine (pure functions only;
no DB, no orders, no ledger rows — outcome tables receive zero fixtures)."""
import json
import sys
from datetime import datetime, timedelta, timezone, date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from options_lifecycle_model import classify_strategy, occ_symbol, parse_occ
from options_lifecycle_engine import decide, strategy_economics, policy

POL = policy()


def _strategy(stype, legs, opened_days_ago=10, objective=None, share_qty=None):
    return {"strategy_position_id": 1, "strategy_type": stype, "underlying": "TEST",
            "opened_at": datetime.now(timezone.utc) - timedelta(days=opened_days_ago),
            "operator_objective": objective, "linked_share_qty": share_qty, "legs": legs}


def _leg(leg_id, otype, side, strike, dte=30, opening=None, contracts=1):
    return {"leg_id": leg_id, "occ_symbol": occ_symbol("TEST", str(date.today() + timedelta(days=dte)), otype, strike),
            "option_type": otype, "side": side, "strike": strike,
            "expiration": date.today() + timedelta(days=dte),
            "opening_price": opening, "contracts": contracts, "multiplier": 100, "status": "open"}


def _quote(mid, delta=0.25, und=100.0, theta=-0.05, spread_pct=5.0):
    return {"ok": True, "bid": mid * 0.97, "ask": mid * 1.03, "mid": mid, "spread_pct": spread_pct,
            "delta": delta, "gamma": 0.01, "theta": theta, "vega": 0.1, "iv": 30.0,
            "underlying_price": und, "source": "fixture", "ts": "t"}


def eco_for(s, quotes):
    return strategy_economics(s, quotes)


def test_low_capture_is_not_harvest():
    # profitable short option with only ~5% captured must NOT become HARVEST
    s = _strategy("covered_call", [_leg(1, "call", "short", 110, dte=40, opening=2.00)], opened_days_ago=2)
    eco = eco_for(s, {1: _quote(1.90, delta=0.25, und=100)})  # 5% captured
    assert eco["pct_max_profit_captured"] == 5.0
    d = decide(s, {**eco, "mfe": None, "mae": None, "giveback": None}, POL)
    assert d["recommendation"] == "HOLD", d


def test_fast_capture_becomes_harvest():
    # 60%+ captured in 7 days with substantial DTE -> harvest candidate
    s = _strategy("covered_call", [_leg(1, "call", "short", 110, dte=31, opening=2.00)], opened_days_ago=7)
    eco = eco_for(s, {1: _quote(0.72, delta=0.15, und=100)})  # 64% captured
    d = decide(s, {**eco, "mfe": None, "mae": None, "giveback": None}, POL)
    assert d["recommendation"] == "HARVEST_FULL", d
    assert "64%" in d["rationale"] or "64" in d["rationale"]


def test_profitable_protective_put_held_when_hedge_needed():
    s = _strategy("protective_put", [_leg(1, "put", "long", 95, dte=60, opening=2.00, contracts=2)],
                  opened_days_ago=15, share_qty=200)
    eco = eco_for(s, {1: _quote(3.64, delta=-0.35, und=140)})  # up 82%
    d = decide(s, {**eco, "mfe": eco["unrealized_pnl"], "mae": None, "giveback": 0.0}, POL,
               defense_posture={"protected_sector_states": ["LAGGING"]})
    assert d["recommendation"] == "HOLD", d
    assert "do not sell protection solely" in d["rationale"]


def test_hedge_no_longer_needed_closes():
    s = _strategy("protective_put", [_leg(1, "put", "long", 95, dte=60, opening=2.00)], share_qty=100)
    eco = eco_for(s, {1: _quote(2.40, delta=-0.30, und=110)})
    d = decide(s, {**eco, "mfe": None, "mae": None, "giveback": None}, POL,
               defense_posture={"protected_sector_states": ["LEADING"]})
    assert d["recommendation"] == "CLOSE", d


def test_credit_spread_short_strike_threat_closes_as_spread():
    s = _strategy("credit_spread",
                  [_leg(1, "put", "short", 98.6, dte=20, opening=1.50),
                   _leg(2, "put", "long", 93, dte=20, opening=0.70)], opened_days_ago=9)
    eco = eco_for(s, {1: _quote(0.90, delta=-0.37, und=100), 2: _quote(0.52, delta=-0.15, und=100)})
    assert eco["short_delta"] == 0.37
    d = decide(s, {**eco, "mfe": None, "mae": None, "giveback": None}, POL)
    assert d["recommendation"] == "CLOSE", d
    assert "never legs" in d["rationale"] or "one order" in d["rationale"]


def test_missing_quote_is_data_blocked():
    s = _strategy("credit_spread",
                  [_leg(1, "put", "short", 95, dte=20, opening=1.50),
                   _leg(2, "put", "long", 90, dte=20, opening=0.70)])
    eco = eco_for(s, {1: _quote(0.90, delta=-0.20), 2: {"ok": False, "error": "no quote"}})
    d = decide(s, {**eco, "mfe": None, "mae": None, "giveback": None}, POL)
    assert d["recommendation"] == "DATA_BLOCKED", d


def test_unknown_basis_is_data_blocked_not_zero():
    s = _strategy("covered_call", [_leg(1, "call", "short", 110, dte=40, opening=None)])
    eco = eco_for(s, {1: _quote(1.00)})
    assert eco["unrealized_pnl"] is None          # UNKNOWN, never 0
    assert eco["pct_max_profit_captured"] is None
    d = decide(s, {**eco, "mfe": None, "mae": None, "giveback": None}, POL)
    assert d["recommendation"] == "DATA_BLOCKED", d


def test_long_option_giveback_escalates():
    s = _strategy("long_call", [_leg(1, "call", "long", 100, dte=45, opening=3.00)], opened_days_ago=8)
    eco = eco_for(s, {1: _quote(4.50, delta=0.55, und=106)})  # +150/contract now
    # peak was +600, now +150 -> giveback 450 = 75% of peak
    d = decide(s, {**eco, "mfe": 600.0, "mae": None, "giveback": 450.0}, POL)
    assert d["recommendation"] == "HARVEST_FULL", d
    assert "given back" in d["rationale"]


def test_spread_pin_window_closes():
    s = _strategy("credit_spread",
                  [_leg(1, "call", "short", 101, dte=2, opening=1.00),
                   _leg(2, "call", "long", 105, dte=2, opening=0.40)], opened_days_ago=20)
    eco = eco_for(s, {1: _quote(0.55, delta=0.30, und=100), 2: _quote(0.15, delta=0.10, und=100)})
    d = decide(s, {**eco, "mfe": None, "mae": None, "giveback": None}, POL)
    assert d["recommendation"] == "CLOSE", d


def test_naked_short_call_never_classified_manageable():
    assert classify_strategy([{"option_type": "call", "side": "short", "contracts": 1}],
                             held_shares=0) == "unknown_multi_leg"


def test_collar_and_spread_grouping():
    assert classify_strategy([
        {"option_type": "call", "side": "short", "strike": 190, "contracts": 1},
        {"option_type": "put", "side": "long", "strike": 150, "contracts": 1}]) == "collar"
    assert classify_strategy([
        {"option_type": "put", "side": "short", "strike": 95, "contracts": 1, "opening_price": 1.5},
        {"option_type": "put", "side": "long", "strike": 90, "contracts": 1, "opening_price": 0.7}]) == "credit_spread"


def test_occ_roundtrip():
    occ = occ_symbol("XLI", "2026-09-18", "put", 170)
    assert parse_occ(occ) == {"underlying": "XLI", "expiration": "2026-09-18",
                              "option_type": "put", "strike": 170.0}


def test_csp_assignment_ok_objective_changes_read():
    s = _strategy("cash_secured_put", [_leg(1, "put", "short", 98, dte=25, opening=2.00)],
                  opened_days_ago=6, objective="assignment_ok")
    eco = eco_for(s, {1: _quote(3.10, delta=-0.50, und=97)})
    d = decide(s, {**eco, "mfe": None, "mae": None, "giveback": None}, POL)
    assert d["recommendation"] == "ACCEPT_ASSIGNMENT", d
    s2 = _strategy("cash_secured_put", [_leg(1, "put", "short", 98, dte=25, opening=2.00)], opened_days_ago=6)
    d2 = decide(s2, {**eco, "mfe": None, "mae": None, "giveback": None}, POL)
    assert d2["recommendation"] == "DEFEND", d2


# ── Phase 4+5: assignment review + alert dedupe (pure, patched I/O) ──────────

import options_lifecycle_alerts as ola


def test_expiry_day_and_itm_short_escalate(monkeypatch):
    monkeypatch.setattr(ola, "_fundamentals", lambda u: {})
    monkeypatch.setattr(ola, "_held_shares_live", lambda a, s: 100.0)
    s = _strategy("covered_call", [_leg(1, "call", "short", 95, dte=0, opening=2.0)], share_qty=100)
    s["account_key"] = "schwab_rollover_ira"
    eco = {"dte_nearest": 0, "underlying_price": 100.0, "extrinsic_value": -5.0}
    f = ola.assignment_review(s, eco, POL)
    codes = {x["code"] for x in f}
    assert "expiry_day" in codes
    assert any(c.startswith("itm_short") for c in codes)
    assert any(x["code"] == "early_assignment_extrinsic" for x in f)
    assert all(x["urgency"] == "red" for x in f if x["code"] == "expiry_day")


def test_under_covered_is_red(monkeypatch):
    monkeypatch.setattr(ola, "_fundamentals", lambda u: {})
    monkeypatch.setattr(ola, "_held_shares_live", lambda a, s: 125.0)
    s = _strategy("covered_call", [_leg(1, "call", "short", 120, dte=30, opening=2.0, contracts=2)])
    s["account_key"] = "schwab_rollover_ira"
    f = ola.assignment_review(s, {"dte_nearest": 30, "underlying_price": 100.0}, POL)
    uc = [x for x in f if x["code"] == "under_covered"]
    assert uc and uc[0]["urgency"] == "red" and "200" in uc[0]["line"]


def test_exdiv_unknown_is_a_finding_not_silence(monkeypatch):
    monkeypatch.setattr(ola, "_fundamentals", lambda u: {})
    monkeypatch.setattr(ola, "_held_shares_live", lambda a, s: 100.0)
    s = _strategy("covered_call", [_leg(1, "call", "short", 120, dte=30, opening=2.0)])
    s["account_key"] = "schwab_rollover_ira"
    f = ola.assignment_review(s, {"dte_nearest": 30, "underlying_price": 100.0}, POL)
    assert any(x["code"] == "exdiv_unknown" for x in f)


def test_dedupe_key_changes_with_state():
    d = {"recommendation": "HOLD", "urgency": "green"}
    eco30 = {"dte_nearest": 30, "giveback": None, "mfe": None}
    eco7 = {"dte_nearest": 7, "giveback": None, "mfe": None}
    k1 = ola._dedupe_key(1, d, eco30, POL)
    k2 = ola._dedupe_key(1, d, eco30, POL)
    k3 = ola._dedupe_key(1, d, eco7, POL)   # new DTE window -> new key
    k4 = ola._dedupe_key(1, {**d, "urgency": "amber"}, eco30, POL)
    assert k1 == k2 and k1 != k3 and k1 != k4


def test_giveback_bucket_steps():
    eco_a = {"giveback": 100.0, "mfe": 1000.0}   # 10% -> bucket 0 (step 15)
    eco_b = {"giveback": 320.0, "mfe": 1000.0}   # 32% -> bucket 2
    assert ola._giveback_bucket(eco_a, POL) == 0
    assert ola._giveback_bucket(eco_b, POL) == 2
    assert ola._giveback_bucket({"giveback": None, "mfe": None}, POL) == -1


# ── Phase 6: ticket hash binding + freshness (pure) ──────────────────────────

import options_lifecycle_tickets as olt
from datetime import timedelta as _td


def _ticket(quote_age_s=0, tif="DAY"):
    t = {"legs": [{"leg_id": 1, "occ_symbol": "TEST  260821C00110000", "instruction": "BTC",
                   "contracts": 1.0, "proposed_limit": 0.72}],
         "net_debit_credit": -72.0, "strategy_position_id": 9,
         "quote_ts": (datetime.now(timezone.utc) - _td(seconds=quote_age_s)).isoformat(),
         "quote_max_age_seconds": 90}
    t["approval_hash"] = olt._hash(t, tif)
    return t


def test_hash_changes_when_any_field_changes():
    t = _ticket()
    h0 = olt._hash(t, "DAY")
    assert h0 == t["approval_hash"]
    assert olt._hash(t, "GTC") != h0                      # TIF change invalidates
    t2 = {**t, "legs": [{**t["legs"][0], "proposed_limit": 0.73}]}
    assert olt._hash(t2, "DAY") != h0                     # price change invalidates
    t3 = {**t, "net_debit_credit": -73.0}
    assert olt._hash(t3, "DAY") != h0


def test_stale_quotes_fail_freshness():
    assert olt._fresh_enough(_ticket(quote_age_s=10)) is True
    assert olt._fresh_enough(_ticket(quote_age_s=300)) is False


def test_round_tick():
    assert olt._round_tick(0.7249, 0.01) == 0.72
    assert olt._round_tick(0.7251, 0.01) == 0.73
