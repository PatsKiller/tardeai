#!/usr/bin/env python3
"""Options desk card semantics — debit/credit labels, route copy, PRIME display, liquidity."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.options_pipeline import card_semantics as cs  # noqa: E402
from lib.options_pipeline import options_education as oe  # noqa: E402
from lib.options_pipeline import options_metric_tooltips as omt  # noqa: E402


@pytest.mark.parametrize("strategy,expected", [
    ("deep_itm_call", "Total debit"),
    ("protective_put", "Total debit"),
    ("atm_call", "Total debit"),
    ("atm_put", "Total debit"),
    ("long_call", "Total debit"),
    ("covered_call", "Total credit"),
    ("cash_secured_put", "Total credit"),
    ("credit_spread", "Net credit"),
    ("put_credit_spread", "Net credit"),
    ("debit_spread", "Net debit"),
    ("earnings_put_debit_spread", "Net debit"),
])
def test_option_cashflow_label(strategy, expected):
    assert cs.option_cashflow_label(strategy) == expected


@pytest.mark.parametrize("strategy,is_credit", [
    ("deep_itm_call", False),
    ("protective_put", False),
    ("covered_call", True),
    ("cash_secured_put", True),
    ("debit_spread", False),
    ("credit_spread", True),
])
def test_cashflow_is_credit(strategy, is_credit):
    assert cs.cashflow_is_credit(strategy) is is_credit


def test_fidelity_route_note_never_mentions_schwab_live():
    p = {"broker": "fidelity", "execution_mode": "manual", "data_source": "schwab_chain"}
    out = cs.apply_card_semantics(p, schwab_armed=True)
    assert "Schwab live" not in out["execution_note"]
    assert "Fidelity" in out["execution_note"]
    assert out["execution_route_kind"] == "fidelity_manual"
    assert out["data_source_badge"] == "Schwab chain"


def test_schwab_live_eligible_route_when_armed():
    p = {"broker": "schwab", "enterprise": {"live_eligible": True}}
    out = cs.apply_card_semantics(p, schwab_armed=True)
    assert "2FA" in out["execution_note"]
    assert out["execution_route_kind"] == "schwab_live"


def test_paper_model_route_not_live_schwab():
    p = {"strategy": "deep_itm_call", "educational_paper_model": True, "broker": "schwab"}
    out = cs.apply_card_semantics(p, schwab_armed=True)
    assert "Schwab live" not in out["execution_note"]
    assert out["execution_route_kind"] in ("paper_model", "alpaca_paper")
    assert out["enterprise"]["live_eligible"] is False


@pytest.mark.parametrize("score,label_fragment", [
    (50, "PAPER WATCH"),
    (61, "PAPER WATCH"),
    (63, "PAPER WATCH"),
    (70, "PRIME FOR PAPER"),
    (82, "LIVE REVIEW"),
    (30, "NOT PRIME"),
])
def test_prime_display_label_bands(score, label_fragment):
    d = cs.prime_display_label(score)
    assert label_fragment in d["label"] or label_fragment in d["short_label"]
    if score < 65:
        assert "PRIME FOR PAPER" not in d["short_label"]
        assert d["short_label"] != f"PRIME {int(score)}"


def test_oi_zero_illiquid_warning_and_score_cap():
    p = {"strategy": "covered_call", "oi": 0, "edge_score": 78}
    out = cs.apply_card_semantics(p)
    assert out["liquidity_status"] == "illiquid"
    assert out["display_edge_score"] <= cs.OI_ZERO_SCORE_CAP
    msgs = [w["message"] for w in out["liquidity_warnings"]]
    assert any("open interest is 0" in m for m in msgs)


def test_plain_english_debit_strategies():
    assert "pay a debit" in cs.plain_english_strategy_hint("deep_itm_call").lower()
    assert "pay a debit" in cs.plain_english_strategy_hint("protective_put").lower()
    assert "collect a credit" in cs.plain_english_strategy_hint("covered_call").lower()
    assert "collect a credit" in cs.plain_english_strategy_hint("cash_secured_put").lower()


def test_paper_model_row_shows_no_live_path_not_blocked():
    p = {
        "strategy": "deep_itm_call",
        "symbol": "RTX",
        "educational_paper_model": True,
        "alpaca_paper_enabled": True,
        "enterprise": {"blocks": ["validation gate not met"], "live_eligible": False},
    }
    out = cs.apply_card_semantics(p)
    badge = out["safety_status_badge"]
    assert badge is not None
    assert badge["label"] == "NO LIVE PATH"
    assert badge["label"] != "BLOCKED"
    assert out["is_paper_model_row"] is True
    assert out["desk_trade_blocked"] is False
    assert out["enterprise"]["live_eligible"] is False


def test_true_blocked_covered_call_still_blocked_badge():
    p = {"strategy": "covered_call", "status": "blocked", "enterprise": {"blocks": ["OI zero"]}}
    badge = cs.safety_status_badge(p)
    assert badge is not None
    assert badge["label"] == "BLOCKED"
    assert cs.is_desk_trade_blocked(p)


def test_deep_itm_beginner_summary_buy_call_debit_stock_replacement():
    card = {
        "strategy": "deep_itm_call",
        "symbol": "RTX",
        "contracts": 1,
        "premium_total": 2225.0,
        "educational_paper_model": True,
        "alpaca_paper_enabled": True,
    }
    summary = oe.build_beginner_summary(card).lower()
    assert "buy" in summary and "call" in summary
    assert "pay" in summary and "stock-like" in summary
    assert "paper only" in summary


def test_protective_put_beginner_summary_hedge():
    summary = oe.build_beginner_summary({
        "strategy": "protective_put", "symbol": "AAPL", "premium_total": 450.0,
    }).lower()
    assert "buy" in summary and "put" in summary
    assert "insurance" in summary or "offset" in summary
    assert "cost" in summary or "pay" in summary


def test_covered_call_beginner_summary_sell_credit():
    summary = oe.build_beginner_summary({
        "strategy": "covered_call", "symbol": "SCHD", "premium_total": 120.0,
    }).lower()
    assert "sell" in summary and "call" in summary
    assert "collect" in summary and "upside" in summary


def test_cash_secured_put_beginner_summary_assignment_risk():
    summary = oe.build_beginner_summary({
        "strategy": "cash_secured_put", "symbol": "DGRO", "premium_total": 95.0,
    }).lower()
    assert "sell" in summary and "put" in summary and "collect" in summary
    assert "buy shares" in summary or "buy" in summary


def test_credit_spread_beginner_summary_net_credit():
    summary = oe.build_beginner_summary({
        "strategy": "credit_spread", "symbol": "XOM", "premium_total": 80.0,
    }).lower()
    assert "collect" in summary
    assert "short strike" in summary or "capped risk" in summary


def test_novice_glossary_includes_core_terms():
    terms = {t.lower() for t in oe.NOVICE_GLOSSARY_TERMS}
    for need in ("call", "put", "delta", "theta", "iv", "dte", "oi"):
        assert need in terms


def test_monitor_checklist_includes_greeks_iv_spread_pl_dte():
    items = " ".join(oe.monitor_checklist("deep_itm_call")).lower()
    for frag in ("delta", "theta", "iv", "spread", "p/l", "dte"):
        assert frag in items


def test_alpaca_paper_education_no_live_broker():
    snippet = oe.alpaca_paper_education_snippet().lower()
    assert "paper" in snippet
    assert "simulated" in snippet or "does not place" in snippet
    assert "live broker" in snippet


def test_rtx_deep_itm_metric_tooltips():
    """RTX $170 deep ITM call summary line — novice chip copy."""
    ctx = {
        "symbol": "RTX",
        "strategy": "deep_itm_call",
        "option_type": "call",
        "strike": 170,
        "spot": 199.0,
        "delta": 0.81,
        "breakeven": 205.0,
        "breakeven_move_pct": 2.9,
        "capital_ratio_pct": 18,
        "dte_bucket": 180,
    }
    bucket = omt.get_options_metric_tooltip("dte_bucket", ctx)
    assert "180" in bucket["short"]
    assert "60d" in bucket["more"] and "180d" in bucket["more"]
    assert "theta" in bucket["watch"].lower()

    strike = omt.get_options_metric_tooltip("strike", ctx)
    assert "anchored" in strike["short"].lower()
    assert "call" in strike["more"].lower()
    assert "170" in strike["more"]

    delta = omt.get_options_metric_tooltip("delta", ctx)
    assert "stock-like" in delta["short"].lower()
    assert "0.81" in delta["more"]

    be = omt.get_options_metric_tooltip("breakeven", ctx)
    assert "expiration" in be["short"].lower()
    assert "205" in be["more"]
    assert "2.9" in be["more"]

    cap = omt.get_options_metric_tooltip("share_capital_pct", ctx)
    assert "100 shares" in cap["short"].lower()
    assert "18%" in cap["more"]
    assert "100%" in cap["watch"]


def test_strike_tooltip_put_vs_call():
    call = omt.get_options_metric_tooltip("strike", {"strategy": "atm_call", "option_type": "call"})
    put = omt.get_options_metric_tooltip("strike", {"strategy": "atm_put", "option_type": "put"})
    assert "buy" in call["more"].lower()
    assert "sell" in put["more"].lower()


def test_metric_chip_info_affordance_keys():
    """Every compact summary metric key resolves tooltip copy."""
    for key in (
        "dte_bucket", "strike", "delta", "breakeven", "share_capital_pct",
        "max_loss", "spread_pct", "oi", "volume", "pop", "ev", "edge", "rr", "dte",
        "no_live_path", "alpaca_paper_only", "live_eligible_false", "paper_validation",
    ):
        tip = omt.get_options_metric_tooltip(key, {})
        assert tip["short"]
        assert tip["more"]


def test_mobile_tap_phase_cycle():
    assert omt.metric_chip_tap("closed") == "short"
    assert omt.metric_chip_tap("short") == "more"
    assert omt.metric_chip_tap("more") == "closed"


def test_desktop_hover_phases():
    assert omt.metric_chip_hover_enter("closed") == "short"
    assert omt.metric_chip_hover_leave("short") == "closed"
    assert omt.metric_chip_hover_enter("more") == "more"
    assert omt.metric_chip_hover_leave("more") == "more"


def test_paper_model_review_button_renamed():
    p = {
        "strategy": "deep_itm_call",
        "educational_paper_model": True,
        "enterprise": {"blocks": ["paper only"]},
        "alpaca_paper_enabled": True,
    }
    labels = [b["label"] for b in cs.sanitize_action_buttons(p)]
    assert "Review Paper Guards" in labels
    assert "Review Block Reason" not in labels