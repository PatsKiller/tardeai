"""Phase 3 — Freshness & Materiality gate (pure)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_freshness_materiality_gate import (  # noqa: E402
    FRESHNESS_MATERIALITY_VERSION,
    GROUP_FINANCIAL_STATE,
    GROUP_MARKET_PRICE,
    LABEL_ACT_NOW,
    LABEL_DATA_CONFLICT,
    LABEL_REVIEW,
    LABEL_REVALIDATE,
    LABEL_STALE_REFRESH,
    LABEL_WATCH,
    apply_to_decisions,
    attach_to_capital_plan,
    evaluate_decision_actionability,
)
from scripts.lib import cio_capital_plan as cp  # noqa: E402


NOW = datetime(2026, 8, 14, 15, 0, tzinfo=timezone.utc)  # weekday ~RTH


def _fresh_holdings():
    return {
        "updated_at": (NOW - timedelta(minutes=5)).isoformat(),
        "as_of": "2026-08-14",
        "portfolio_totals": {"total_value": 100_000.0},
        "holdings": [
            # The cash row carries its own confirmation stamp. It used to carry
            # none and be dated by the document above it, which is how the live
            # book came to report 27-day-old balances as 11.7 hours old.
            {"symbol": "CASH", "is_cash": True, "market_value": 20_000.0, "account": "ira",
             "canonical_mark_as_of": (NOW - timedelta(minutes=5)).isoformat()},
            {
                "symbol": "SCHD",
                "account": "ira",
                "shares": 100,
                "current_price": 100.0,
                "price": 100.0,
                "market_value": 10_000.0,
                "updated_at": (NOW - timedelta(minutes=3)).isoformat(),
                "source_as_of": (NOW - timedelta(minutes=3)).isoformat(),
                "canonical_mark_as_of": (NOW - timedelta(minutes=3)).isoformat(),
                "price_source": "test",
            },
        ],
    }


def test_version():
    assert FRESHNESS_MATERIALITY_VERSION.startswith("freshness_materiality_")


def test_an_undated_cash_row_does_not_borrow_the_documents_clock():
    """The document was written 5 minutes ago. That dates the equity marks."""
    doc = _fresh_holdings()
    doc["holdings"][0].pop("canonical_mark_as_of")
    out = evaluate_decision_actionability(
        _trim_fire_decision(generated_at=NOW.isoformat()),
        holdings_doc=doc, financial_truth=_ft_ok(), now=NOW)
    cash = next(b for b in out["freshness_board"] if b["name"] == "cash")
    assert cash["source_as_of"] is None
    assert cash["detail"] == "undated"
    assert cash["pass"] is False
    assert out["act_now"] is False


def test_a_stale_cash_row_is_stale_however_fresh_the_document_is():
    doc = _fresh_holdings()
    doc["holdings"][0]["canonical_mark_as_of"] = (NOW - timedelta(days=27)).isoformat()
    out = evaluate_decision_actionability(
        _trim_fire_decision(generated_at=NOW.isoformat()),
        holdings_doc=doc, financial_truth=_ft_ok(), now=NOW)
    cash = next(b for b in out["freshness_board"] if b["name"] == "cash")
    assert cash["quality"] == "STALE"
    assert cash["age_seconds"] > 26 * 24 * 3600
    # And the holdings class, which really is 5 minutes old, is unaffected.
    holdings = next(b for b in out["freshness_board"] if b["name"] == "holdings")
    assert holdings["quality"] != "STALE"


def _ft_ok():
    return {"overall_quality": "VERIFIED_AS_OF", "suppress_act_now_symbols": []}


def _trim_fire_decision(**overrides):
    """TRIM + concentration fire. Callers add/omit clocks to target a label."""
    d = {
        "symbol": "SCHD",
        "stance_code": "TRIM",
        "recommended_delta_usd": -1000.0,
        "why_now": "Advisory TRIM — SCHD",
        "risk": "concentration fire — single-name > cap",
    }
    d.update(overrides)
    return d


def test_nonzero_delta_alone_not_act_now_without_freshness():
    """Core invariant: delta != 0 is insufficient for ACT NOW."""
    decision = _trim_fire_decision()
    # No timestamps, no holdings → cannot ACT NOW
    ev = evaluate_decision_actionability(decision, now=NOW)
    assert ev["act_now"] is False
    assert ev["action_label"] != LABEL_ACT_NOW
    assert ev["action_label"] == LABEL_REVALIDATE
    assert abs(ev["recommended_delta_usd"]) == 1000.0


def test_stale_holdings_forces_stale_refresh():
    doc = _fresh_holdings()
    doc["as_of"] = (NOW - timedelta(days=10)).isoformat()
    doc["updated_at"] = NOW.isoformat()  # process clock must not refresh
    decision = {
        "symbol": "SCHD",
        "stance_code": "TRIM",
        "recommended_delta_usd": -1000.0,
        "why_now": "Advisory TRIM — SCHD",
        "risk": "concentration > cap",
        "revalidated_at": NOW.isoformat(),
    }
    pos = doc["holdings"][1]
    # even with fresh quote on row, holdings book stale fails required holdings check
    pos["updated_at"] = (NOW - timedelta(minutes=2)).isoformat()
    ft = {"overall_quality": "VERIFIED_AS_OF", "suppress_act_now_symbols": []}
    ev = evaluate_decision_actionability(
        decision, holdings_doc=doc, position_row=pos, financial_truth=ft, now=NOW,
    )
    assert ev["act_now"] is False
    assert ev["action_label"] in (LABEL_STALE_REFRESH, LABEL_REVIEW, LABEL_DATA_CONFLICT)


def test_financial_conflict_blocks_act_now():
    doc = _fresh_holdings()
    decision = {
        "symbol": "DXCM",
        "stance_code": "TRIM",
        "recommended_delta_usd": -500.0,
        "why_now": "Advisory TRIM — DXCM",
        "risk": "within single-name cap",
        "revalidated_at": NOW.isoformat(),
    }
    ft = {
        "overall_quality": "CONFLICTED",
        "suppress_act_now_symbols": ["DXCM"],
        "conflicted_symbols": ["DXCM"],
    }
    ev = evaluate_decision_actionability(
        decision,
        holdings_doc=doc,
        position_row={
            "symbol": "DXCM",
            "updated_at": (NOW - timedelta(minutes=2)).isoformat(),
            "market_value": 5000,
        },
        financial_truth=ft,
        now=NOW,
    )
    assert ev["action_label"] == LABEL_DATA_CONFLICT
    assert ev["act_now"] is False


def test_act_now_trim_fire_dated_decision_quote_risk_thesis_hermes():
    """ACT NOW fixture: TRIM + fire + dated clocks + thesis/hermes."""
    doc = _fresh_holdings()
    decision = _trim_fire_decision(
        generated_at=NOW.isoformat(),
        revalidated_at=NOW.isoformat(),
        risk_as_of=(NOW - timedelta(minutes=10)).isoformat(),
        thesis_as_of=(NOW - timedelta(hours=2)).isoformat(),
        hermes_as_of=(NOW - timedelta(hours=3)).isoformat(),
    )
    pos = doc["holdings"][1]
    ev = evaluate_decision_actionability(
        decision, holdings_doc=doc, position_row=pos, financial_truth=_ft_ok(), now=NOW,
    )
    assert ev["action_label"] == LABEL_ACT_NOW
    assert ev["act_now"] is True
    assert ev["actionable"] is True
    assert ev["evidence_source_count"] >= 2
    assert ev["independent_evidence_count"] >= 1
    assert "hermes" in ev["independent_evidence_groups"] or "fundamental" in ev["independent_evidence_groups"]
    details = [r.get("detail") for r in ev["freshness_board"]]
    assert "evaluated_now" not in details


def test_hold_is_watch_not_act_now():
    doc = _fresh_holdings()
    decision = {
        "symbol": "SCHD",
        "stance_code": "HOLD",
        "recommended_delta_usd": 0.0,
        "why_now": "no new desk signal; hold",
        "risk": "within single-name cap",
        "revalidated_at": NOW.isoformat(),
    }
    ev = evaluate_decision_actionability(
        decision,
        holdings_doc=doc,
        position_row=doc["holdings"][1],
        financial_truth={"overall_quality": "VERIFIED_AS_OF", "suppress_act_now_symbols": []},
        now=NOW,
    )
    assert ev["action_label"] == LABEL_WATCH
    assert ev["act_now"] is False


def test_apply_to_decisions_summary_counts():
    doc = _fresh_holdings()
    decisions = [
        {
            "symbol": "SCHD",
            "decision_id": "dec_schd",
            "stance_code": "TRIM",
            "recommended_delta_usd": -1000.0,
            "why_now": "Advisory TRIM — SCHD",
            "risk": "concentration > cap",
            "revalidated_at": NOW.isoformat(),
        },
        {
            "symbol": "ZZZ",
            "decision_id": "dec_zzz",
            "stance_code": "HOLD",
            "recommended_delta_usd": 0.0,
            "why_now": "no new desk signal; hold",
            "risk": "within single-name cap",
            "revalidated_at": NOW.isoformat(),
        },
    ]
    out, summary = apply_to_decisions(
        decisions,
        holdings_doc=doc,
        financial_truth={"overall_quality": "VERIFIED_AS_OF", "suppress_act_now_symbols": []},
        now=NOW,
    )
    assert len(out) == 2
    assert out[0]["action_label_display"] in (
        "ACT NOW", "REVIEW", "WATCH", "STALE — REFRESH REQUIRED", "DATA CONFLICT", "REVALIDATE",
    )
    assert "counts" in summary
    assert summary["act_now_count"] == summary["counts"].get(LABEL_ACT_NOW, 0)


def test_capital_plan_attaches_freshness_gate():
    doc = {
        "updated_at": (NOW - timedelta(minutes=5)).isoformat(),
        "portfolio_totals": {"total_value": 100_000.0},
        "config": {"accounts": {"ira": {"taxable": False}}},
        "holdings": [
            {"symbol": "CASH", "is_cash": True, "market_value": 20_000.0, "account": "ira"},
            {
                "symbol": "SCHD",
                "account": "ira",
                "shares": 100,
                "current_price": 800,
                "price": 800,
                "market_value": 80_000,
                "updated_at": (NOW - timedelta(minutes=2)).isoformat(),
            },
        ],
    }
    plan = cp.build_capital_plan_from_sources(
        holdings_doc=doc,
        queue={"items": [
            {"symbol": "SCHD", "verdict": "TRIM", "directive_label": "Advisory TRIM — SCHD", "source": "advisory"},
        ]},
        redeploy_open_events=[],
        now=NOW,
    )
    assert "freshness_materiality_gate" in plan
    assert plan["freshness_materiality_gate"].get("version", "").startswith("freshness_materiality_")
    # At least one decision annotated
    decs = plan.get("position_decisions") or []
    assert decs
    assert "action_label" in decs[0]
    assert "action_label_display" in decs[0]


def test_attach_to_capital_plan_idempotent_structure():
    plan = {
        "computed_at": NOW.isoformat(),
        "position_decisions": [
            {
                "symbol": "AAA",
                "stance_code": "HOLD",
                "recommended_delta_usd": 0,
                "why_now": "no new desk signal; hold",
                "risk": "within single-name cap",
            }
        ],
        "financial_truth_gate": {"overall_quality": "VERIFIED_AS_OF", "suppress_act_now_symbols": []},
    }
    out = attach_to_capital_plan(plan, holdings_doc=_fresh_holdings(), now=NOW)
    assert out["freshness_materiality_gate"]["act_now_count"] == 0


def test_undated_decision_cannot_be_act_now():
    """Missing generated_at / revalidated_at => REVALIDATE, never ACT NOW."""
    doc = _fresh_holdings()
    decision = _trim_fire_decision(
        risk_as_of=(NOW - timedelta(minutes=10)).isoformat(),
        thesis_as_of=(NOW - timedelta(hours=2)).isoformat(),
        hermes_as_of=(NOW - timedelta(hours=3)).isoformat(),
    )
    ev = evaluate_decision_actionability(
        decision,
        holdings_doc=doc,
        position_row=doc["holdings"][1],
        financial_truth=_ft_ok(),
        now=NOW,
    )
    assert ev["act_now"] is False
    assert ev["action_label"] == LABEL_REVALIDATE
    dec = next(r for r in ev["freshness_board"] if r["name"] == "decision")
    assert dec["pass"] is False
    assert dec["detail"] in ("undated", "missing")


def test_evaluated_now_must_not_appear_as_passing_detail():
    """The undated-decision-as-fresh loophole is gone."""
    doc = _fresh_holdings()
    decision = _trim_fire_decision()  # no decision clock
    ev = evaluate_decision_actionability(
        decision,
        holdings_doc=doc,
        position_row=doc["holdings"][1],
        financial_truth=_ft_ok(),
        now=NOW,
    )
    details = [r.get("detail") for r in ev["freshness_board"]]
    assert "evaluated_now" not in details
    for rec in ev["freshness_board"]:
        assert rec.get("detail") != "evaluated_now"
        if rec.get("name") == "decision":
            assert rec["pass"] is False
    src = (ROOT / "scripts/lib/cio_freshness_materiality_gate.py").read_text(encoding="utf-8")
    assert "evaluated_now" not in src
    assert ev["action_label"] != LABEL_ACT_NOW


def test_holdings_quote_same_snapshot_not_independent_act_now():
    """Holdings + quote from holdings.json are one group, not ACT NOW alone."""
    doc = _fresh_holdings()
    decision = _trim_fire_decision(
        generated_at=NOW.isoformat(),
        revalidated_at=NOW.isoformat(),
        risk_as_of=doc["updated_at"],  # book clock — not independent of holdings
    )
    ev = evaluate_decision_actionability(
        decision,
        holdings_doc=doc,
        position_row=doc["holdings"][1],
        financial_truth=_ft_ok(),
        now=NOW,
    )
    assert ev["act_now"] is False
    assert ev["action_label"] != LABEL_ACT_NOW
    assert ev["same_snapshot_quote"] is True
    assert ev["independent_evidence_count"] == 0
    ok_names = {g["name"] for g in ev["evidence_groups"] if g.get("ok")}
    assert GROUP_FINANCIAL_STATE in ok_names
    market = next((g for g in ev["evidence_groups"] if g["name"] == GROUP_MARKET_PRICE), None)
    assert market is None or not market.get("ok") or not market.get("independent")
    book = next(g for g in ev["evidence_groups"] if g["name"] == GROUP_FINANCIAL_STATE)
    assert "holdings" in book["members"]
    assert "quote" in book["members"] or "market_value" in book["members"]
    assert "insufficient_independent_evidence_beyond_book" in ev["reasons"]


def test_computed_at_is_not_a_decision_clock():
    """plan computed_at / decision computed_at cannot substitute generated_at."""
    doc = _fresh_holdings()
    decision = _trim_fire_decision(
        computed_at=NOW.isoformat(),
        thesis_as_of=(NOW - timedelta(hours=2)).isoformat(),
        hermes_as_of=(NOW - timedelta(hours=3)).isoformat(),
    )
    ev = evaluate_decision_actionability(
        decision,
        holdings_doc=doc,
        position_row=doc["holdings"][1],
        financial_truth=_ft_ok(),
        extra={"plan_computed_at": NOW.isoformat()},
        now=NOW,
    )
    assert ev["action_label"] == LABEL_REVALIDATE
    assert ev["act_now"] is False


def test_every_contributing_account_row_is_checked():
    """A stale second account row blocks ACT NOW even if the first row is fresh."""
    doc = _fresh_holdings()
    doc["holdings"].append({
        "symbol": "SCHD",
        "account": "taxable",
        "shares": 10,
        "current_price": 100.0,
        "price": 100.0,
        "market_value": 1_000.0,
        "updated_at": (NOW - timedelta(days=3)).isoformat(),
        "price_source": "test",
    })
    decision = _trim_fire_decision(
        generated_at=NOW.isoformat(),
        revalidated_at=NOW.isoformat(),
        risk_as_of=(NOW - timedelta(minutes=10)).isoformat(),
        thesis_as_of=(NOW - timedelta(hours=2)).isoformat(),
        hermes_as_of=(NOW - timedelta(hours=3)).isoformat(),
    )
    ev = evaluate_decision_actionability(
        decision,
        holdings_doc=doc,
        position_row=doc["holdings"][1],  # fresh IRA row only — must still see taxable
        financial_truth=_ft_ok(),
        now=NOW,
    )
    assert ev["act_now"] is False
    assert ev["action_label"] != LABEL_ACT_NOW
    accounts = {r.get("account") for r in ev["account_rows_checked"]}
    assert "ira" in accounts
    assert "taxable" in accounts
    quote = next(r for r in ev["freshness_board"] if r["name"] == "quote")
    assert quote["pass"] is False


def test_old_source_as_of_new_updated_at_quote_not_current():
    """P0-7: old source_as_of + new updated_at remains STALE / not VERIFIED_CURRENT."""
    doc = _fresh_holdings()
    pos = doc["holdings"][1]
    pos["source_as_of"] = (NOW - timedelta(days=5)).isoformat()
    pos["canonical_mark_as_of"] = pos["source_as_of"]
    pos["updated_at"] = NOW.isoformat()
    pos["ingested_at"] = NOW.isoformat()
    pos["fetched_at"] = NOW.isoformat()
    pos["reconciled_at"] = NOW.isoformat()
    decision = _trim_fire_decision(
        generated_at=NOW.isoformat(),
        revalidated_at=NOW.isoformat(),
        risk_as_of=(NOW - timedelta(minutes=10)).isoformat(),
        thesis_as_of=(NOW - timedelta(hours=2)).isoformat(),
        hermes_as_of=(NOW - timedelta(hours=3)).isoformat(),
    )
    ev = evaluate_decision_actionability(
        decision, holdings_doc=doc, position_row=pos, financial_truth=_ft_ok(), now=NOW,
    )
    assert ev["act_now"] is False
    assert ev["action_label"] != LABEL_ACT_NOW
    quote = next(r for r in ev["freshness_board"] if r["name"] == "quote")
    assert quote["quality"] != "VERIFIED_CURRENT"
    assert quote["quality"] in ("STALE", "DATA_UNAVAILABLE")
    assert quote["pass"] is False
    assert ev["session"]["market_session"]["exchange"] == "XNYS"
    assert ev["session"]["market_session"]["state"] in ("PRE", "RTH", "POST", "CLOSED")


def test_session_context_uses_nyse_calendar_not_utc_weekday_window():
    """Labor Day 2026 is a weekday but the NYSE is closed — not RTH."""
    labor = datetime(2026, 9, 7, 15, 0, tzinfo=timezone.utc)  # 11:00 ET
    ev = evaluate_decision_actionability(_trim_fire_decision(), now=labor)
    sess = ev["session"]["market_session"]
    assert sess["state"] == "CLOSED"
    assert ev["session"]["likely_rth"] is False
