"""Phase 8 — CIO NOW / report / capital-plan consistency."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib import cio_command_center as cc  # noqa: E402
from scripts.lib import cio_capital_plan as cp  # noqa: E402
from scripts.lib import cio_report_v2 as r  # noqa: E402
from scripts.lib import cio_decision_semantics as ds  # noqa: E402

FIXED = datetime(2026, 8, 14, 21, 0, 0, tzinfo=timezone.utc)


def _live_ish_plan() -> dict:
    """Capital plan with Phase 2 semantics + multi-account positions."""
    return cp.build_capital_plan(
        portfolio_value=1_282_425.99,
        cash_total=578_107.50,
        positions=[
            {"symbol": "SCHD", "market_value": 200_000.0, "account": "schwab_rollover_ira"},
            {"symbol": "SCHD", "market_value": 25_922.0, "account": "schwab_taxable"},
            {"symbol": "V", "market_value": 70_000.0, "account": "schwab_rollover_ira"},
            {"symbol": "V", "market_value": 51_133.0, "account": "schwab_taxable"},
            {"symbol": "NVDA", "market_value": 50_000.0, "account": "schwab_taxable"},
        ],
        queue={"items": [
            {"symbol": "SCHD", "verdict": None, "directive_label": "Advisory TRIM — SCHD", "source": "advisory"},
            {"symbol": "V", "verdict": None, "directive_label": "Advisory TRIM — V", "source": "advisory"},
        ]},
        redeploy_open_events=[{"event_id": 1, "symbol": "X", "remaining_usd": 100_000.0}],
        account_cash=[
            {"account": "schwab_rollover_ira", "settled_cash_usd": 533_243.97},
            {"account": "schwab_taxable", "settled_cash_usd": 37_894.31},
        ],
        now=FIXED,
    )


def test_decision_id_stable():
    a = ds.make_decision_id("SCHD", "TRIM", -22592.26, "Advisory TRIM — SCHD")
    b = ds.make_decision_id("SCHD", "TRIM", -22592.26, "Advisory TRIM — SCHD")
    assert a == b
    assert a.startswith("dec_")
    c = ds.make_decision_id("SCHD", "HOLD", 0, "no new desk signal; hold")
    assert c != a


def test_cio_now_and_report_share_decision_ids():
    plan = _live_ish_plan()
    home = cc.build_office_home(capital_plan=plan, now=FIXED)
    report = r.build_report_v2(
        part_b_ctx={
            "portfolio": {
                "total_value": plan["portfolio_value_usd"],
                "cash_value": plan["cash_total_usd"],
                "cash_pct": 45.08,
            },
            "allocation": {
                "Cash & Equivalents": plan["cash_total_usd"],
                "Equities": plan["portfolio_value_usd"] - plan["cash_total_usd"],
            },
        },
        part_a_inputs={"capital_plan": plan, "thesis": {"stance": "neutral_hold", "summary": "x"}},
        source_sha="phase8",
        now=FIXED,
    )
    cc_ids = set(home["consistency"]["decision_ids"])
    report_ids = set(report["part_a"]["consistency"]["decision_ids"])
    assert cc_ids
    assert report_ids
    # Material position decisions must be the same identity set
    assert cc_ids == report_ids

    # Symbols present
    cc_syms = {d["symbol"] for d in home["cio_now"]["decisions"] if d.get("kind") == "position"}
    rep_syms = {d["symbol"] for d in report["part_a"]["decisions_now"]}
    assert "SCHD" in cc_syms and "V" in cc_syms
    assert cc_syms == rep_syms


def test_capital_plan_digest_matches_report():
    plan = _live_ish_plan()
    home = cc.build_office_home(capital_plan=plan, now=FIXED)
    report = r.build_report_v2(
        part_b_ctx={"portfolio": {"total_value": plan["portfolio_value_usd"], "cash_value": plan["cash_total_usd"]}},
        part_a_inputs={"capital_plan": plan},
        source_sha="phase8",
        now=FIXED,
    )
    assert home["consistency"]["capital_plan_digest"]
    assert home["consistency"]["capital_plan_digest"] == report["part_a"]["consistency"]["capital_plan_digest"]
    # Prefer engine digest when present
    assert home["capital_plan"]["plan_digest"] == plan["digest"]


def test_capital_plan_does_not_call_earmark_a_raise():
    plan = _live_ish_plan()
    surface = cc.build_capital_plan(plan)
    labels = [s["label"] for s in surface["sources"]]
    assert any("already in cash" in lbl.lower() or "Earmarked" in lbl for lbl in labels)
    assert surface["recommended_raise_usd"] == plan["net_recommended_raise_usd"]
    # Earmark is labeled, not additive raise
    assert surface["cash_earmarked_redeploy_usd"] is not None
    assert surface["double_count_guard"]


def test_cio_now_cards_have_cio_speak_fields():
    plan = _live_ish_plan()
    now = cc.build_cio_now(
        position_decisions=plan["position_decisions"],
        portfolio_value=plan["portfolio_value_usd"],
    )
    assert len(now["decisions"]) <= 5
    for d in now["decisions"]:
        if d.get("kind") != "position":
            continue
        assert d.get("decision_id")
        assert d.get("action")
        assert d.get("why_now")
        assert d.get("what_changes_call")
        assert d.get("counter_thesis")
        assert d.get("operator_actions")
        codes = {a["code"] for a in d["operator_actions"]}
        assert {"ACK", "DEFER", "DONE", "REJECT", "RATE"} <= codes
        # No HOLD+TRIM contradiction
        assert d["action"] != "Hold" or "TRIM" not in str(d.get("why_now")).upper()


def test_no_raw_enums_in_primary_posture():
    plan = _live_ish_plan()
    home = cc.build_office_home(
        capital_plan=plan,
        sector_opportunities={"opportunities": [
            {"sector": "Technology", "state": "LEADING", "current_exposure_pct": 7.4,
             "target_posture_pct": 18.0, "recommendation": "STAGED_DEPLOYMENT"},
            {"sector": "Iwm−Spy", "state": "IMPROVING", "recommendation": "RESEARCH_FIRST"},
        ]},
        now=FIXED,
    )
    for t in home["posture"]["sector_tilts"]:
        assert t["recommendation"] != "STAGED_DEPLOYMENT"
        assert "Iwm" not in str(t.get("sector"))
    # Internal constraint kinds may live in evidence only
    for d in home["cio_now"]["decisions"]:
        assert "STAGED_DEPLOYMENT" not in str(d.get("why_now"))
        assert "desk@v" not in str(d.get("why_now")).lower()


def test_office_home_version():
    home = cc.build_office_home(capital_plan=_live_ish_plan(), now=FIXED)
    assert home["version"] == "office_home_1.1.0"
    assert home["consistency"]["office_home_version"] == "office_home_1.1.0"
