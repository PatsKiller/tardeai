#!/usr/bin/env python3
"""Options desk card semantics — debit/credit labels, route copy, PRIME display, liquidity."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.options_pipeline import card_semantics as cs  # noqa: E402


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