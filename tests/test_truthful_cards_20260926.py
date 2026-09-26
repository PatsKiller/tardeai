"""Truthful option cards (operator 2026-09-26).

Cards said "live eligible" while the thesis bar refused them, showed "Reward/risk
0.046" and "EV -$1,100" with no statement of purpose, and spun "validating" on a
weekend. Numbers below are the live SPCX / DELL cards. No DB, broker or network.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib import options_plain_english as pe  # noqa: E402

SPCX = {"symbol": "SPCX", "strategy": "protective_put", "underlying_price": 148.5, "strike": 140,
        "premium": 7.33, "contracts": 3, "expiration": "2026-11-20", "pop_pct": 41.6}
DELL = {"symbol": "DELL", "strategy": "cash_secured_put", "underlying_price": 524.14, "strike": 490,
        "premium": 21.57, "contracts": 1, "expiration": "2026-11-20", "pop_pct": 56.7}


def test_spcx_is_insurance_with_the_right_numbers():
    e = pe.explain(SPCX)
    assert e["objective"].startswith("Insurance")
    assert "$2,199" in e["premium_line"] and "300 SPCX at $140" in e["premium_line"]
    assert e["breakeven"] == 132.67
    low = min(e["scenarios"], key=lambda r: r["price"])
    assert low["option_pl"] > 0                      # the puts pay in a crash
    top = max(e["scenarios"], key=lambda r: r["price"])
    assert top["option_pl"] == -2199.0               # the insurance expires worthless
    assert "shares_plus_option_vs_today" in top


def test_dell_cash_secured_put_says_what_you_collect_and_risk():
    e = pe.explain(DELL)
    assert e["objective"].startswith("Income")
    assert "$2,157" in e["premium_line"]
    assert e["breakeven"] == 468.43
    assert "468.43" in e["cases"]["worst"]


def test_memo_classifies_first_and_never_invents_research():
    m = pe.committee_memo(SPCX, {"thesis_state": "INSUFFICIENT_DATA"}, {"missing_required": ["catalysts"]})
    assert m["classification"] == "HEDGE" and m["intent_answer"] == "Act as insurance"
    assert m["research_status"] == "SCREENING_ONLY" and m["confidence"] == "Low"
    assert m["cio_status"] == "RESEARCH_PENDING"
    assert "screening only" in m["why_now"] and "screening only" in m["contrarian_view"]
    assert "not yet reported per symbol" in m["continuous_research"]["per_symbol_monitors"]
    assert m["plain_summary"].startswith("This is insurance on your SPCX shares.")


def test_memo_cio_status_follows_the_queue_not_the_model():
    t = {"symbol_thesis_version": "symbol_spcx@v13", "thesis_state": "CURRENT", "thesis_confidence": 0.8,
         "evidence_for": ["x"], "thesis_summary": "s"}
    assert pe.committee_memo(SPCX, t, {"missing_required": []}, queue_status="approved")["cio_status"] == "CIO_APPROVED"
    assert pe.committee_memo(SPCX, t, {"missing_required": []}, queue_status="rejected")["cio_status"] == "NOT_APPROVED"
    assert pe.committee_memo(SPCX, t, {"missing_required": []})["cio_status"] == "AWAITING_CIO"


def test_every_metric_guide_says_meaning_why_and_direction():
    for k in ("edge", "pop", "ev", "delta", "gamma", "theta", "iv_rank", "open_interest", "breakeven", "debit", "credit", "dte"):
        g = pe.METRIC_GUIDE[k]
        assert len(g) == 3 and all(g)


def test_thesis_blocked_card_is_not_live_eligible(monkeypatch):
    import options_engine as oe
    monkeypatch.setattr(oe, "_market_session_now", lambda: "WEEKEND")
    p = dict(DELL, enterprise={"live_eligible": True, "blocks": []},
             thesis_blocks=[{"code": "thesis_required", "reason": "x"}],
             options_thesis={"missing_required": ["catalysts", "exit_criteria"]})
    oe._stamp_truth_flags(p)
    keys = {f["key"] for f in p["flags"]}
    assert p["enterprise"]["live_eligible"] is False and p["approvable"] is False
    assert {"INCOME", "NOT_APPROVABLE", "THESIS_INCOMPLETE", "CLOSED_MARKET_CHAIN"} <= keys
    assert p["plain_english"]["breakeven"] == 468.43


def test_clean_card_is_approvable(monkeypatch):
    import options_engine as oe
    monkeypatch.setattr(oe, "_market_session_now", lambda: "REGULAR")
    p = dict(DELL, enterprise={"live_eligible": True, "blocks": []}, thesis_blocks=[],
             options_thesis={"missing_required": []})
    oe._stamp_truth_flags(p)
    assert p["approvable"] is True and {"APPROVABLE", "THESIS_COMPLETE"} <= {f["key"] for f in p["flags"]}


def test_exit_rules_are_config():
    text = (ROOT / "assets" / "portfolio_intent.yaml").read_text(encoding="utf-8")
    assert "  options_exit_rules:" in text and "    protective_put:" in text
