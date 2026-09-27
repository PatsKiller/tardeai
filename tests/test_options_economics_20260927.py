"""Honest option economics, instrument classes, block reasons, and the desk-side
never-approvable guarantees (operator 2026-09-27, Wave A). Hermetic, no psycopg2."""
from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts.lib import options_economics as oe  # noqa: E402
from scripts.lib.instrument_class import classify  # noqa: E402


def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _bs_put_zero_rate(s, k, iv, dte):
    t = dte / 365.0
    d1 = (math.log(s / k) + 0.5 * iv * iv * t) / (iv * math.sqrt(t))
    d2 = d1 - iv * math.sqrt(t)
    return k * _ncdf(-d2) - s * _ncdf(-d1)


def test_ev_is_about_zero_for_a_fairly_priced_put_not_credit_times_pop():
    fair = _bs_put_zero_rate(563.0, 490.0, 0.45, 54)
    e = oe.economics({"strategy": "cash_secured_put", "strike": 490, "premium": fair, "underlying_price": 563.0,
                      "dte": 54, "contracts": 1, "iv_used": 0.45})
    assert abs(e["expected_pl_at_expiry"]) < 5.0            # ~0 per contract
    assert e["expected_pl_at_expiry"] < fair * 100 * 0.5     # nowhere near credit x POP


def test_cash_secured_put_net_cost_and_cash_committed():
    e = oe.economics({"strategy": "cash_secured_put", "strike": 490, "premium": 21.57, "underlying_price": 563.0,
                      "dte": 54, "contracts": 1, "iv_used": 0.45})
    assert e["net_cost_if_assigned_per_share"] == 468.43 and e["net_cost_if_assigned_total"] == 46843.0
    assert e["cash_committed"] == 49000.0 and e["credit_total"] == 2157.0 and e["discount_to_spot_pct"] == 16.8


def test_credit_spread_collateral_max_loss_breakeven():
    e = oe.economics({"strategy": "credit_spread", "short_strike": 522.5, "long_strike": 497.5, "strike": 522.5,
                      "premium": 8.10, "underlying_price": 563.0, "dte": 54, "iv_used": 0.45})
    assert (e["credit_total"], e["collateral"], e["max_loss_total"], e["breakeven"]) == (810.0, 2500.0, 1690.0, 514.4)


def test_protective_put_is_described_as_a_hedge_not_premium_max_loss():
    """The brief's hand-checked XAR / XLB numbers."""
    xar = oe.economics({"strategy": "protective_put", "strike": 230, "premium": 7.25, "underlying_price": 239.46,
                        "dte": 54, "contracts": 1, "iv_used": 0.25}, shares_held=100)
    assert xar["floor_value_after_premium"] == 22275.0 and xar["downside_to_floor_from_mark"] == 1671.0
    assert xar["stock_plus_put_breakeven_from_mark"] == 246.71 and xar["uninsured_shares"] == 0.0
    xlb = oe.economics({"strategy": "protective_put", "strike": 47.5, "premium": 0.69, "underlying_price": 49.8,
                        "dte": 40, "contracts": 5, "iv_used": 0.2}, shares_held=504)
    assert xlb["insured_shares"] == 500 and xlb["uninsured_shares"] == 4.0
    assert xlb["floor_value_after_premium"] == 23405.0 and xlb["downside_to_floor_from_mark"] == 1495.0


def test_missing_iv_gives_no_ev_rather_than_a_guess():
    e = oe.economics({"strategy": "cash_secured_put", "strike": 100, "premium": 2, "underlying_price": 110, "dte": 30})
    assert e["expected_pl_at_expiry"] is None


def test_instrument_classes():
    assert classify("stock", None, "The fund is an actively managed exchange traded fund that seeks to achieve two times (200%") == "LEVERAGED_FUND"
    assert classify("etf", "ETF", "Direxion Daily Semiconductor Bull 3X ETF") == "LEVERAGED_FUND"
    assert classify("etf", "ETF", "State Street SPDR S&P Aerospace & Defense ETF") == "ETF"
    assert classify("stock", "EQUITY", "Dell Technologies Inc - Computer Hardware.") == "OPERATING_COMPANY"


def _flags(p):
    import options_engine as oeng
    oeng._stamp_truth_flags(p)
    return p


def test_block_reasons_name_the_real_blocker():
    import options_engine as oeng
    rej = {"code": "awaiting_cio_decision", "reason": "CIO decision: REJECT (dec_c53f)"}
    assert oeng._not_approvable_reason({}, [rej], {}) == "CIO rejected"
    mr = {"code": "awaiting_cio_decision", "reason": "CIO decision: MORE_RESEARCH"}
    assert oeng._not_approvable_reason({}, [mr], {}) == "CIO asked for more research"
    assert oeng._not_approvable_reason({}, [{"code": "thesis_missing_catalysts"}], {}) == "thesis incomplete"
    assert oeng._not_approvable_reason({}, [], {"blocks": ["awaiting live quotes (market weekend): OI 0 < 50"]}) \
        == "awaiting live quotes"


def test_desk_never_marks_a_blocked_card_approvable(monkeypatch):
    import options_engine as oeng
    monkeypatch.setattr(oeng, "_market_session_now", lambda: "WEEKEND")
    cases = [
        {"enterprise": {"blocks": ["awaiting live quotes (market weekend): spread 131%"]}},
        {"enterprise": {"blocks": ["daily leveraged fund: not an income/wheel underlying"]}, "enterprise_blocked": True},
        {"enterprise": {}, "thesis_blocks": [{"code": "awaiting_cio_decision", "reason": "CIO decision: REJECT"}]},
        {"enterprise": {}, "thesis_blocks": [{"code": "thesis_missing_catalysts", "reason": "x"}]},
    ]
    for c in cases:
        p = _flags({"strategy": "cash_secured_put", "symbol": "X", **c})
        assert p["approvable"] is False, c
        assert any(f["key"] == "NOT_APPROVABLE" for f in p["flags"])
    ok = _flags({"strategy": "cash_secured_put", "symbol": "X", "enterprise": {}})
    assert ok["approvable"] is True  # the gate is not simply always-false


def test_approval_needs_a_fresh_validated_quote():
    from scripts.lib.options_validate import fresh_validation
    now = datetime(2026, 9, 28, 14, 0, tzinfo=timezone.utc)
    ok = {"event_type": "OPTIONS_VALIDATED", "status": "VALIDATED", "validated_at": (now - timedelta(minutes=5)).isoformat()}
    assert fresh_validation([ok], 30, now=now) is not None
    stale = dict(ok, validated_at=(now - timedelta(minutes=45)).isoformat())
    changed = dict(ok, status="CHANGED")
    illiquid = dict(ok, status="ILLIQUID")
    for ev in (stale, changed, illiquid):
        assert fresh_validation([ev], 30, now=now) is None
    assert fresh_validation([], 30, now=now) is None


def test_unanswerable_gap_is_retired_then_the_question_forms_a_stance(tmp_path):
    import json
    import run_symbol_thesis_acquisition as rsa
    fields = {"research_gaps": ["What is DELL's exact AI server backlog dollar figure?", "Bear case?"],
              "thesis_stance": ""}
    kw = dict(root=tmp_path, memberships=["WATCHLIST"], role="UNKNOWN", thesis_state="THIN")
    q1, why1 = rsa.choose_question("DELL", fields, **kw)
    assert why1 == "first_open_gap"
    led = tmp_path / rsa.LEDGER_REL
    led.parent.mkdir(parents=True)
    rows = [{"symbol": "DELL", "status": "PUBLISHED", "question_digest": rsa._digest("DELL", q1)}] * rsa.GAP_RETRY_LIMIT
    led.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    q2, why2 = rsa.choose_question("DELL", fields, **kw)
    assert why2 == "first_open_gap" and q2 != q1
    rows += [{"symbol": "DELL", "status": "PUBLISHED", "question_digest": rsa._digest("DELL", q2)}] * rsa.GAP_RETRY_LIMIT
    led.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    q3, why3 = rsa.choose_question("DELL", fields, **kw)
    assert why3 == "gaps_exhausted_form_stance" and "Form a thesis stance for DELL" in q3
    q4, why4 = rsa.choose_question("DELL", {**fields, "thesis_stance": "watch"}, **kw)
    assert why4 == "first_gap"   # with a stance, the normal first-gap behaviour is unchanged
