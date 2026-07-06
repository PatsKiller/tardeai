#!/usr/bin/env python3
"""EARNINGS-SPREADS Stage 2 — earnings vertical generators (spec Parts C + D).

Covers: exact debit-spread package math (debit / max_loss / max_gain /
breakeven / reward:risk from a fixture chain + event_json), the width table
(+ adjacent width), expected-move short-strike selection, every named reject
path (package slippage, per-leg OI/volume, debit % of underlying, max-loss
paper cap), disclosed flags (iv_rich, historical_move_below_breakeven),
paper-flag completeness on every row (desk fail-closed guard accepts them),
deterministic/idempotent proposal ids, generator-side event gates (window /
thesis / confidence / degraded chain), the credit lane blocked by default +
mandatory assignment/gap/short-leg disclosures when force-generated (and the
Alpaca spread lane still refusing its family), and a forbidden-imports AST
sweep (no broker surface).

    .venv/bin/python -m pytest tests/test_options_earnings_vertical_generator.py -q
"""
from __future__ import annotations

import ast
import copy
import re
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.options_pipeline import earnings_event_model as eem      # noqa: E402
from lib.options_pipeline import earnings_vertical_generator as evg  # noqa: E402
from lib.options_pipeline.deep_itm_generator import (             # noqa: E402
    PAPER_MODEL_BLOCK, submit_to_desk_queue)

SPOT = 100.0
TODAY = date(2026, 7, 6)
EARN = "2026-07-15"           # 9 days out — inside the 10/2 window
EXP = "2026-07-17"            # first listed expiration after the event

# IV series: rank of current 40 is high (rich) / mid (not rich)
IV_RICH_SERIES = [30.0 + i * 0.5 for i in range(25)]     # 30 → 42, current 40 rich
IV_MID_SERIES = [38.0 + (i % 10) * 0.5 for i in range(25)]  # 38 → 42.5 band

# Historical bars: |move| = 1.5% (below the 2% the 100/95 breakeven requires)
BARS_SMALL = [{"d": "2026-04-20", "close_price": 100.0},
              {"d": "2026-04-21", "close_price": 100.0},
              {"d": "2026-04-22", "close_price": 101.5},   # event date D
              {"d": "2026-04-23", "close_price": 101.5}]
# |move| = 8% (well above any fixture breakeven requirement)
BARS_BIG = [{"d": "2026-04-20", "close_price": 100.0},
            {"d": "2026-04-21", "close_price": 100.0},
            {"d": "2026-04-22", "close_price": 108.0},
            {"d": "2026-04-23", "close_price": 108.0}]


def _leg(side, strike, bid, ask, *, delta=None, oi=600, volume=60, iv=40.0,
         dte=11, liquidity_score=70):
    mid = round((bid + ask) / 2.0, 4) if bid and ask else None
    spread_pct = (round((ask - bid) / mid * 100.0, 2) if mid else None)
    return {"side": side, "strike": float(strike), "bid": bid, "ask": ask,
            "mid": mid, "spread_pct": spread_pct, "volume": volume, "oi": oi,
            "delta": delta, "iv": iv, "dte": dte,
            "liquidity_score": liquidity_score}


def _puts(overrides=None):
    """Fixture put ladder at the event expiration (tight, liquid quotes)."""
    legs = {
        100.0: _leg("put", 100.0, 3.96, 4.04, delta=-0.50),   # long: mid 4.00
        97.5: _leg("put", 97.5, 2.96, 3.04, delta=-0.40),
        95.0: _leg("put", 95.0, 1.98, 2.02, delta=-0.30),     # short: mid 2.00
        92.5: _leg("put", 92.5, 1.48, 1.52, delta=-0.22),
        90.0: _leg("put", 90.0, 0.98, 1.02, delta=-0.15),     # short: mid 1.00
        85.0: _leg("put", 85.0, 0.58, 0.62, delta=-0.10),
    }
    legs.update(overrides or {})
    return list(legs.values())


def _snapshot(puts=None, *, spot=SPOT):
    contracts = list(puts if puts is not None else _puts())
    # ATM call (mid 1.00) → straddle implied move (4.00 + 1.00) / 100 = 5.0%
    contracts.append(_leg("call", 100.0, 0.96, 1.04, delta=0.50))
    return {"available": True, "symbol": "TST", "underlying_price": spot,
            "expirations": [
                {"exp": "2026-07-10", "dte": 4, "liquidity_score": 60,
                 "contracts": [_leg("call", 100.0, 0.5, 0.6, dte=4),
                               _leg("put", 100.0, 0.5, 0.6, dte=4)]},
                {"exp": EXP, "dte": 11, "liquidity_score": 70,
                 "contracts": contracts},
            ],
            "liquidity_score": 70}


NO_CHAIN = {"available": False, "reason": "weekend — no chain (test fixture)"}
BEARISH_CTX = {"verdict": "sell", "held_shares": None}
BULLISH_CTX = {"verdict": "buy", "held_shares": None}
THESIS_BEARISH = {"conviction": 0.70, "conviction_source": "watchlist_sell",
                  "verdict": "sell", "held_shares": None, "hedge_of_held": False}
THESIS_BULLISH = {"conviction": 0.70, "conviction_source": "watchlist_buy",
                  "verdict": "buy", "held_shares": None, "hedge_of_held": False}


def _event(snapshot=None, *, context=BEARISH_CTX, earnings_date=EARN,
           closes=BARS_BIG, iv_series=IV_MID_SERIES):
    return eem.build_event_json(
        "TST", chain_snapshot=snapshot if snapshot is not None else _snapshot(),
        earnings_date=earnings_date, today=TODAY, context=context,
        past_earnings_dates=["2026-04-22"], closes_fn=lambda s, d: closes,
        iv_history_series=iv_series)


def _gen(snapshot=None, event_json=None, config=None, thesis_ctx=None, **kw):
    snap = snapshot if snapshot is not None else _snapshot()
    ev = event_json if event_json is not None else _event(snap)
    return evg.generate_put_debit_spreads(
        "TST", ev, config, thesis_ctx or THESIS_BEARISH, snapshot=snap, **kw)


def _by_short(gen, short):
    return next((p for p in gen["proposals"] if p["short_strike"] == short), None)


# ── (1) debit spread math — exact from the fixture ───────────────────────────

def test_debit_math_exact_100x95():
    gen = _gen()
    assert gen["available"] is True and gen["count"] >= 1
    p = _by_short(gen, 95.0)
    assert p is not None
    assert p["long_strike"] == 100.0 and p["short_strike"] == 95.0
    assert p["width"] == 5.0
    assert p["premium"] == 2.0                 # 4.00 − 2.00 package mid
    assert p["net_debit"] == 2.0
    assert p["premium_total"] == 200.0
    assert p["max_loss"] == 200.0              # debit × 100
    assert p["max_profit"] == 300.0            # (width − debit) × 100
    assert p["breakeven"] == 98.0              # long strike − debit
    assert p["breakeven_move_pct"] == -2.0
    assert p["reward_to_risk"] == 1.5          # 300 / 200
    assert p["risk_reward"] == 1.5
    assert p["expiration"] == EXP and p["dte"] == 11
    a = p["meta"]["analysis"]
    assert a["debit"] == 2.0 and a["max_loss"] == 200.0 and a["max_gain"] == 300.0
    assert a["required_move_to_breakeven_pct"] == 2.0
    assert a["implied_move_pct"] == 5.0
    assert a["debit_pct_of_underlying"] == 2.0
    assert a["package_slippage_pct"] == pytest.approx(6.0)   # (0.08+0.04)/2.0


def test_debit_math_exact_100x90_adjacent_width():
    p = _by_short(_gen(), 90.0)
    assert p is not None
    assert p["width"] == 10.0 and p["net_debit"] == 3.0
    assert p["max_loss"] == 300.0 and p["max_profit"] == 700.0
    assert p["breakeven"] == 97.0 and p["reward_to_risk"] == 2.33
    assert p["meta"]["short_strike_method"] == "width_table_10"


# ── (2) width table ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("spot,width", [
    (40.0, 2.5), (49.99, 2.5), (50.0, 5.0), (100.0, 5.0), (150.0, 5.0),
    (150.01, 10.0), (400.0, 10.0), (400.01, 20.0), (900.0, 20.0)])
def test_width_table(spot, width):
    assert evg.width_for_price(spot) == width


def test_candidate_widths_include_adjacent():
    assert evg.candidate_widths(100.0) == [5.0, 10.0]
    assert evg.candidate_widths(40.0) == [2.5, 5.0]
    assert evg.candidate_widths(900.0) == [20.0, 10.0]   # largest rung: next smaller


# ── (3) expected-move short-strike selection ─────────────────────────────────

def test_expected_move_boundary_picks_highest_strike_below():
    gen = _gen()
    p = _by_short(gen, 95.0)
    # implied move 5% → boundary 100 × (1 − 0.05) = 95 → highest strike ≤ 95
    assert p["meta"]["short_strike_method"] == "expected_move_boundary"
    # the width-table 5-wide candidate snapped to the same strike — deduped
    shorts = [q["short_strike"] for q in gen["proposals"]]
    assert shorts.count(95.0) == 1


def test_width_table_fallback_when_no_implied_move():
    # kill both event-expiration ATM quotes AND the OTM strangle pair the
    # fallback would use → implied move honestly unavailable
    puts = _puts({100.0: _leg("put", 100.0, 3.96, 4.04, delta=-0.50)})
    snap = _snapshot(puts)
    for c in snap["expirations"][1]["contracts"]:
        if c["side"] == "call":
            c.update(bid=0, ask=0, mid=None)
    ev = _event(snap)
    assert ev["implied_move_pct"]["available"] is False
    gen = _gen(snapshot=snap, event_json=ev)
    assert gen["available"] is True and gen["count"] >= 1
    methods = {p["meta"]["short_strike_method"] for p in gen["proposals"]}
    assert methods <= {"width_table_5", "width_table_10"}
    assert "expected_move_boundary" not in methods


# ── (4) reject paths — named, machine-readable ───────────────────────────────

def test_reject_package_slippage():
    puts = _puts({95.0: _leg("put", 95.0, 1.80, 2.20, delta=-0.30)})  # 0.48 total
    gen = _gen(snapshot=_snapshot(puts))
    assert _by_short(gen, 95.0) is None
    assert any("package_slippage_" in n and "gt_8" in n
               for n in gen["reject_notes"])


def test_reject_leg_open_interest():
    puts = _puts({95.0: _leg("put", 95.0, 1.98, 2.02, delta=-0.30, oi=100)})
    gen = _gen(snapshot=_snapshot(puts))
    assert _by_short(gen, 95.0) is None
    assert any("short_leg_oi_100_lt_250" in n for n in gen["reject_notes"])


def test_reject_leg_volume():
    puts = _puts({100.0: _leg("put", 100.0, 3.96, 4.04, delta=-0.50, volume=3)})
    gen = _gen(snapshot=_snapshot(puts))
    assert gen["count"] == 0
    assert any("long_leg_volume_3_lt_10" in n for n in gen["reject_notes"])


def test_reject_debit_pct_of_underlying():
    # long mid 8.50 → 100/95 debit 6.50 = 6.5% of spot > 6% cap
    puts = _puts({100.0: _leg("put", 100.0, 8.46, 8.54, delta=-0.50)})
    gen = _gen(snapshot=_snapshot(puts))
    assert _by_short(gen, 95.0) is None
    assert any("debit_6.5pct_of_underlying_gt_6" in n for n in gen["reject_notes"])


def test_reject_max_loss_paper_cap():
    gen = _gen(config={"selection_policy": {"max_loss_usd_paper": 150}})
    assert gen["count"] == 0
    assert any("max_loss_200_gt_max_loss_usd_paper_150" in n
               for n in gen["reject_notes"])
    assert any("max_loss_300_gt_max_loss_usd_paper_150" in n
               for n in gen["reject_notes"])


# ── (5) generator-side event gates (window / thesis / confidence / chain) ────

def test_gate_event_window():
    ev = _event(earnings_date="2026-08-30")      # 55 days out
    gen = _gen(event_json=ev)
    assert gen["available"] is False and gen["gate"] == "event_window"
    assert "no earnings in window" in gen["reason"]
    assert gen["proposals"] == []


def test_gate_thesis_bearish_or_hedge():
    gen = _gen(thesis_ctx=THESIS_BULLISH)
    assert gen["available"] is False and gen["gate"] == "thesis"
    assert "bearish/hedge thesis missing" in gen["reason"]


def test_hedge_of_held_satisfies_thesis_gate():
    hedge = {"conviction": 0.60, "conviction_source": "hedge_of_held",
             "verdict": None, "held_shares": 100.0, "hedge_of_held": True}
    gen = _gen(thesis_ctx=hedge)
    assert gen["available"] is True and gen["count"] >= 1


def test_gate_event_confidence():
    ev = dict(_event(), event_confidence=0.30)
    gen = _gen(event_json=ev)
    assert gen["available"] is False and gen["gate"] == "event_confidence"
    assert "0.30" in gen["reason"] and "0.65" in gen["reason"]


def test_degraded_chain_is_disclosed():
    ev = _event()                                # good event context
    gen = _gen(snapshot=NO_CHAIN, event_json=ev)
    assert gen["available"] is False and gen.get("degraded") is True
    assert "weekend" in gen["reason"]


def test_no_expiration_after_event_gate():
    ev = _event(earnings_date="2026-07-08")      # in window (2 days out) but…
    ev = copy.deepcopy(ev)
    ev["nearest_expiration_after_earnings"] = {
        "available": False, "reason": "no listed expiration on/after the earnings date"}
    gen = _gen(event_json=ev)
    assert gen["available"] is False and gen["gate"] == "event_expiration"


# ── (6) disclosed flags ──────────────────────────────────────────────────────

def test_iv_rich_flag_from_event_json():
    ev = _event(iv_series=IV_RICH_SERIES)
    assert "iv_rich" in ev["risk_flags"]
    gen = _gen(event_json=ev)
    assert gen["count"] >= 1
    for p in gen["proposals"]:
        assert "iv_rich" in p["meta"]["gate_flags"]


def test_historical_move_below_breakeven_flag():
    ev = _event(closes=BARS_SMALL)               # hist avg |move| 1.5%
    assert ev["historical_earnings_moves"]["avg_abs_move_pct"] == 1.5
    gen = _gen(event_json=ev)
    p95 = _by_short(gen, 95.0)                   # requires 2% down-move
    assert "historical_move_below_breakeven" in p95["meta"]["gate_flags"]


def test_no_hist_flag_when_history_covers_breakeven():
    gen = _gen(event_json=_event(closes=BARS_BIG))   # hist avg 8%
    for p in gen["proposals"]:
        assert "historical_move_below_breakeven" not in p["meta"]["gate_flags"]
        assert "iv_rich" not in p["meta"]["gate_flags"]


# ── (7) paper-flag completeness + desk-queue guard acceptance ────────────────

def test_paper_flags_complete_on_every_row():
    gen = _gen()
    assert gen["count"] >= 2
    for p in gen["proposals"]:
        assert p["educational_paper_model"] is True
        assert p["requires_manual_review"] is True
        assert p["paper_only"] is True
        assert p["execution_mode"] == "manual_review_only"
        assert p["auto_eligible"] is False
        assert p["enterprise"]["live_eligible"] is False
        assert PAPER_MODEL_BLOCK in p["enterprise"]["blocks"]
        assert p["contracts"] == 1 and p["spreads"] == 1
        assert p["recommended_action"] == \
            "Review Earnings Put Debit Spread (paper model)"
        assert "auto_execute" not in p
        assert not any("auto" in str(b.get("action")) for b in p["action_buttons"])
        sj = p["meta"]["strategy_json"]
        assert sj["family"] == "earnings_vertical_debit"
        assert sj["strategy_id"] == "earnings_put_debit_spread"
        # meta.strategy_json.legs disclosure shape (spec Part C)
        assert [l["side"] for l in sj["legs"]] == ["buy", "sell"]
        for leg in sj["legs"]:
            assert set(leg) == {"side", "type", "strike", "exp", "mid", "oi",
                                "volume", "spread_pct"}
            assert leg["type"] == "put" and leg["exp"] == EXP
        # top-level legs in the guarded Alpaca spread-lane shape
        assert [l["side"] for l in p["legs"]] == ["buy", "sell"]
        for leg in p["legs"]:
            assert set(leg) == {"underlying", "expiration", "strike",
                                "option_type", "side", "ratio_qty"}
            assert leg["ratio_qty"] == 1 and leg["option_type"] == "put"
        # event context embedded for the desk card
        assert p["meta"]["event_json"]["symbol"] == "TST"
        assert p["meta"]["event_json"]["event_window"]["in_window"] is True


def test_rows_pass_the_fail_closed_desk_writer_guard(monkeypatch):
    monkeypatch.setattr("options_desk_enterprise.sync_approval_queue",
                        lambda rows: {"ok": True, "upserted": len(rows)},
                        raising=False)
    rows = _gen()["proposals"]
    assert submit_to_desk_queue(rows).get("ok") is True
    bad = [copy.deepcopy(rows[0])]
    bad[0]["enterprise"]["live_eligible"] = True
    refused = submit_to_desk_queue(bad)
    assert refused["ok"] is False and "fail-closed" in refused["error"]


# ── (8) deterministic, idempotent ids ────────────────────────────────────────

def test_proposal_id_format_and_idempotency():
    first = {p["id"] for p in _gen()["proposals"]}
    second = {p["id"] for p in _gen()["proposals"]}
    assert first == second and len(first) >= 2
    assert "opt_earnings_put_debit_spread_TST_paper_model_100x95_20260717" in first
    for pid in first:
        assert re.fullmatch(
            r"opt_earnings_put_debit_spread_TST_paper_model_"
            r"[0-9p]+x[0-9p]+_20260717", pid)


# ── (9) credit lane — blocked by default, disclosures when forced ────────────

def test_credit_blocked_by_default():
    out = evg.generate_put_credit_spreads("TST", _event(), None, THESIS_BULLISH,
                                          snapshot=_snapshot())
    assert out["available"] is False and out["blocked"] is True
    assert out["gate"] == "blocked_initial"
    assert "BLOCKED_INITIAL" in out["reason"]
    assert "allow_blocked" in out["reason"]
    assert out["proposals"] == []


def test_credit_force_generated_structure_and_disclosures():
    ev = _event(context=BULLISH_CTX)
    out = evg.generate_put_credit_spreads("TST", ev, None, THESIS_BULLISH,
                                          snapshot=_snapshot(),
                                          allow_blocked=True)
    assert out["available"] is True and out["blocked_initial"] is True
    assert out["count"] >= 1
    p = out["proposals"][0]
    # short 95 (below the 5% expected-move boundary), long 90 → width 5
    assert p["short_strike"] == 95.0 and p["long_strike"] == 90.0
    assert p["net_credit"] == 1.0                # 2.00 − 1.00
    assert p["max_profit"] == 100.0              # credit × 100
    assert p["max_loss"] == 400.0                # (width − credit) × 100
    assert p["breakeven"] == 94.0                # short strike − credit
    assert p["meta"]["analysis"]["credit_pct_of_width"] == 20.0   # ≥ 20 gate
    assert p["strategy"] == "earnings_put_credit_spread"
    assert p["meta"]["strategy_json"]["family"] == "earnings_vertical_credit"
    assert p["blocked_initial"] is True
    # MANDATORY short-premium disclosures (spec Part D)
    d = p["meta"]["disclosures"]
    assert "ASSIGNMENT RISK" in d["assignment_risk"]
    assert "GAP RISK" in d["gap_risk"]
    assert "SHORT-LEG LIFECYCLE" in d["short_leg_lifecycle"]
    # paper walls identical to the debit lane
    assert p["paper_only"] is True and p["enterprise"]["live_eligible"] is False
    # the 10-wide long (85, mid 0.60) gives credit 1.40 = 14% of width → reject
    assert any("credit_14.0pct_of_width_lt_20" in n for n in out["reject_notes"])


def test_credit_thesis_gate_bullish_or_neutral():
    out = evg.generate_put_credit_spreads(
        "TST", _event(), None, THESIS_BEARISH, snapshot=_snapshot(),
        allow_blocked=True)
    assert out["available"] is False and out["gate"] == "thesis"
    assert "bullish/neutral thesis missing" in out["reason"]


def test_credit_rows_still_refused_by_alpaca_spread_lane():
    from lib.options_pipeline import alpaca_paper as ap
    ev = _event(context=BULLISH_CTX)
    out = evg.generate_put_credit_spreads("TST", ev, None, THESIS_BULLISH,
                                          snapshot=_snapshot(),
                                          allow_blocked=True)
    row = out["proposals"][0]
    with pytest.raises(ap.SpreadNotEnabledError,
                       match="credit spreads blocked"):
        ap.assert_spread_allowed(row, registry={"strategies": {}})


# ── (10) registry-backed config loader ───────────────────────────────────────

def test_load_pipeline_config_debit():
    cfg = evg.load_pipeline_config("earnings_put_debit_spread")
    assert cfg["status"] == "TESTING_PAPER" and cfg["paper_enabled"] is True
    assert cfg["paper_only"] is True
    assert cfg["execution_mode"] == "manual_review_only"
    pol = cfg["selection_policy"]
    assert pol["min_event_confidence"] == 0.65
    assert pol["max_spread_package_slippage_pct"] == 8
    assert pol["min_open_interest_each_leg"] == 250
    assert pol["min_volume_each_leg"] == 10
    assert pol["max_debit_pct_of_underlying"] == 6
    assert pol["max_loss_usd_paper"] == 1000


def test_load_pipeline_config_credit_blocked():
    cfg = evg.load_pipeline_config("earnings_put_credit_spread")
    assert cfg["status"] == "BLOCKED_INITIAL"
    assert cfg["paper_enabled"] is False
    assert cfg["alpaca_paper_enabled"] is False
    assert cfg["selection_policy"]["min_credit_pct_of_width"] == 20
    with pytest.raises(ValueError):
        evg.load_pipeline_config("iron_condor")


# ── (11) forbidden imports — generator stays broker-free ─────────────────────

FORBIDDEN_MODULES = {
    "options_order_pilot", "options_pilot_arm", "brokers", "approval_service",
    "schwab_transport", "schwab_pilot_orders", "alpaca_trade_api", "alpaca",
    "trade_executor", "order_executor", "telegram_2fa", "two_factor",
    "options_execution_policy",
    # the generator never touches the alpaca lane or the queue writer either
    "options_desk_enterprise",
}


def test_generator_has_no_forbidden_imports_or_queue_calls():
    src = (ROOT / "scripts" / "lib" / "options_pipeline" /
           "earnings_vertical_generator.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.update({a.name, a.name.split(".")[0]})
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.update({node.module, node.module.split(".")[0]})
    # options_desk_enterprise appears only for desk_tier display (read-only);
    # forbid every broker/submit surface outright
    assert not mods & (FORBIDDEN_MODULES - {"options_desk_enterprise"})
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "sync_approval_queue" not in names
    assert "submit_to_desk_queue" not in names
    assert "submit_spread_paper_order" not in names
