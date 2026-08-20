"""cio_command_center.py — dry tests for the Phase 8 office-home composition.

Pure logic only: decision surfacing, capital-plan projection, posture, funnel,
report + evidence sections. No DB / broker / LLM.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib import cio_command_center as c  # noqa: E402


def _plan() -> dict:
    return {
        "cash_total_usd": 578107.5,
        "cash_reserved_usd": 256485.2,
        "cash_investable_usd": 321622.3,
        "cash_policy_band": {"min_pct": 20.0, "max_pct": 25.0},
        "net_recommended_deploy_usd": 603114.7,
        "net_recommended_raise_usd": 623009.02,
        "post_plan_cash_usd": 598001.82,
        "post_plan_cash_pct": 46.63,
        "cash_posture_status": "ABOVE_BAND",
        "capital_sources": {"trims_usd": 3000.0, "exits_usd": 60000.0,
                            "maturities_usd": 560009.02, "total_raise_usd": 623009.02},
        "capital_uses": {"adds_usd": 5000.0, "new_positions_usd": 0.0,
                         "reentry_usd": 0.0, "sector_rotation_usd": 0.0,
                         "reserve": 256485.2, "total_deploy_request_usd": 603114.7},
        "portfolio_constraints": [{"kind": "concentration_fire_pct", "value": 12.0}],
        "position_decisions": [
            {"symbol": "SCHD", "cio_stance": "HOLD", "current_value_usd": 200000.0,
             "current_weight_pct": 16.53, "recommended_delta_usd": 0.0,
             "why_now": "Advisory TRIM — SCHD", "risk": "concentration > cap",
             "tax_account_constraint": "tax-advantaged: no lot/tax drag on rebalance",
             "counter_thesis": "no Street/desk disagreement on record"},
            {"symbol": "V", "cio_stance": "HOLD", "current_value_usd": 40000.0,
             "current_weight_pct": 3.1, "recommended_delta_usd": -4000.0,
             "why_now": "Advisory TRIM — V", "risk": "within single-name cap",
             "tax_account_constraint": "tax-advantaged"},
            {"symbol": "AAA", "cio_stance": "HOLD", "current_value_usd": 10000.0,
             "current_weight_pct": 1.0, "recommended_delta_usd": 0.0,
             "why_now": "no new desk signal; hold", "risk": "within single-name cap"},
        ],
    }


def _sectors() -> dict:
    return {"opportunities": [
        {"sector": "Energy", "state": "LEADING", "current_exposure_pct": 3.8,
         "target_posture_pct": 5.0, "recommendation": "RESEARCH_FIRST",
         "candidates": [{"symbol": "CVX", "readiness": "NEEDS_RESEARCH"}]},
        {"sector": "Technology", "state": "LEADING", "current_exposure_pct": 7.4,
         "target_posture_pct": 18.0, "recommendation": "STAGED_DEPLOYMENT",
         "candidates": []},
    ]}


def _queue() -> dict:
    return {"items": [
        {"symbol": "XOM", "verdict": None, "source": "advisory",
         "directive_label": "Advisory TRIM — XOM"},
        {"symbol": "ADBE", "verdict": None, "source": "advisory",
         "directive_label": "Advisory RE_ENTER — ADBE"},
        {"symbol": "CVX", "verdict": None, "source": "sector",
         "directive_label": "CIO cash deployment — deploy queue"},
    ]}


def _report() -> dict:
    return {
        "as_of": "2026-08-13T20:00:00+00:00",
        "report_version": "report_v2_1.0.0",
        "authority": "READ_ONLY_ADVISORY",
        "manifest": {"source_sha": "abc123", "manifest_hash": "hash123"},
        "coverage": {"field_count": 64},
        "checkpoint": {
            "fields_present": ["a"] * 32,
            "fields_unavailable": ["perf_QTD", "perf_3Y", "perf_true_TWR", "style_value_blend_growth"],
            "quality_flags": ["x"] * 30,
            "source_traceability_pct": 100.0,
            "pdf_pages": None,
            "render_errors": ["pdf renderer unavailable"],
        },
    }


def _attribution() -> dict:
    return {"port_maxdd": -21.2, "port_sharpe": 0.692, "port_sortino": 0.819,
            "port_cagr": 21.35, "bench_cagr": 19.31, "alpha_annualized": 2.04,
            "benchmark_label": "55% SPY / 20% ITA / 25% AGG"}


def _thesis() -> dict:
    return {"stance": "neutral_hold", "summary": "Concentrated growth.",
            "principles": ["quality bias"]}


# ── CIO NOW ──────────────────────────────────────────────────────────────────

def test_cio_now_surfaces_signal_and_breach_but_not_neutral():
    now = c.build_cio_now(position_decisions=_plan()["position_decisions"])
    symbols = [d["symbol"] for d in now["decisions"]]
    assert "SCHD" in symbols          # concentration breach
    assert "V" in symbols             # non-neutral why_now
    assert "AAA" not in symbols       # neutral hold — omitted


def test_cio_now_breach_not_high_without_action():
    now = c.build_cio_now(position_decisions=_plan()["position_decisions"])
    by_symbol = {d["symbol"]: d for d in now["decisions"]}
    # Concentration breach is a risk fact, never actionability: without an
    # explicit ACT_NOW it must not surface as "high" / "Act now".
    assert by_symbol["SCHD"]["urgency"] != "high"
    assert by_symbol["SCHD"].get("action_label") != "ACT_NOW"


def test_actionability_urgency_act_now_only_when_explicit():
    assert c._actionability_urgency({"act_now": True}) == "high"
    assert c._actionability_urgency({"action_label": "ACT_NOW"}) == "high"
    assert c._actionability_urgency({"risk": "concentration > fire"}) == "low"
    assert c._actionability_urgency({"action_label": "STALE_REFRESH_REQUIRED"}) == "medium"
    assert c._actionability_urgency({"action_label": "REVIEW"}) == "medium"
    assert c._actionability_urgency({}) == "low"


def test_actionability_urgency_stale_overrides_act_now():
    # P0-3 fail-closed: stale/conflict overrides act_now=True and stale ACT_NOW.
    assert c._actionability_urgency({"act_now": True, "action_label": "STALE_REFRESH_REQUIRED"}) == "medium"
    assert c._actionability_urgency({"act_now": True, "freshness": "STALE"}) == "medium"
    assert c._actionability_urgency({"act_now": True, "action_label": "DATA_CONFLICT"}) == "medium"
    assert c._actionability_urgency({"action_label": "ACT_NOW", "freshness": "EXPIRED"}) == "medium"


def test_cio_now_caps_at_five():
    decs = [{"symbol": f"S{i}", "cio_stance": "TRIM", "recommended_delta_usd": 1.0,
             "why_now": f"Advisory TRIM — S{i}", "risk": "within single-name cap",
             "action_label": "REVIEW"} for i in range(12)]
    now = c.build_cio_now(position_decisions=decs)
    assert len(now["decisions"]) == 5
    # Phase 4: decision_count = investment decisions needing attention (all 12)
    assert now["decision_count"] == 12
    assert now["attention"]["investment_decisions"] == 12


def test_cio_now_actions_are_disjoint_kpi_not_decision_cards():
    """Phase 4: workflow actions count separately; not mixed into decision cards."""
    actions = [{"cio_action_id": "A1", "why_now": "cash deployment", "notification_priority": "Critical"}]
    now = c.build_cio_now(actions=actions)
    assert now["open_actions_count"] == 1
    assert now["attention"]["workflow_actions"] == 1
    assert not any(d.get("kind") == "action" for d in now["decisions"])


def test_cio_now_attention_kpis_disjoint():
    decs = [
        {"symbol": "SCHD", "cio_stance": "TRIM", "recommended_delta_usd": -20000,
         "why_now": "Advisory TRIM — SCHD", "risk": "concentration > fire",
         "action_label": "ACT_NOW", "act_now": True, "current_weight_pct": 17.5},
        {"symbol": "AAA", "cio_stance": "HOLD", "recommended_delta_usd": 0,
         "why_now": "no new desk signal; hold", "risk": "within single-name cap",
         "action_label": "WATCH"},
    ]
    actions = [
        {"cio_action_id": "A1", "status": "open", "notification_priority": "High", "symbol": "BBB"},
        {"cio_action_id": "A2", "status": "done"},
    ]
    plans = [
        {"plan_id": "p1", "status": "proposed"},
        {"plan_id": "p2", "status": "cancelled"},
    ]
    now = c.build_cio_now(position_decisions=decs, actions=actions, plans=plans)
    att = now["attention"]
    assert att["investment_decisions"] == 1  # SCHD only
    assert att["workflow_actions"] == 1  # A1 only
    assert att["open_plans"] == 1  # p1 only
    assert att["material_today"] >= 1
    # Material today is not the arithmetic sum of the three buckets
    assert att["material_today"] != (
        att["investment_decisions"] + att["workflow_actions"] + att["open_plans"]
    )

# ── Capital Plan ─────────────────────────────────────────────────────────────

def test_capital_plan_projection():
    cp = c.build_capital_plan(_plan())
    assert cp["cash_total_usd"] == 578107.5
    assert cp["cash_band"]["min_pct"] == 20.0
    assert cp["recommended_deploy_usd"] == 603114.7
    # Phase 8 / Phase 2: recommended raise is prospective; earmark is labeled separately
    assert cp["recommended_raise_usd"] == 623009.02
    assert cp["cash_posture"] == "above policy band"
    assert any("Prospective raise" in s["label"] and s["usd"] == 623009.02 for s in cp["sources"])
    assert any("Earmarked" in s["label"] and s["usd"] == 560009.02 for s in cp["sources"])
    assert any(u["label"] == "Total deploy request" and u["usd"] == 603114.7 for u in cp["uses"])
    assert cp.get("plan_digest")


def test_capital_plan_empty_fail_soft():
    cp = c.build_capital_plan({})
    assert cp["cash_total_usd"] is None
    assert cp["sources"] == []
    assert cp["cash_posture"] == "—"


# ── Posture ──────────────────────────────────────────────────────────────────

def test_posture_concentration_and_heat():
    p = c.build_posture(capital_plan=_plan(), attribution=_attribution(),
                        sector_opportunities=_sectors(), thesis=_thesis())
    assert p["concentration"]["top_position"] == "SCHD"
    assert p["concentration"]["top_weight_pct"] == 16.53
    assert p["concentration"]["fire_pct"] == 12.0
    assert p["risk_heat"]["max_drawdown_pct"] == -21.2
    assert p["performance"]["benchmark_label"].startswith("55% SPY")
    assert p["thesis"]["stance"] == "Neutral · hold"
    assert p["sector_tilts"][0]["sector"] == "Energy"


def test_posture_tax_issue_detected():
    plan = _plan()
    plan["position_decisions"][1]["tax_account_constraint"] = "taxable: short-term gain drag"
    p = c.build_posture(capital_plan=plan, attribution=_attribution(),
                        sector_opportunities=_sectors(), thesis=_thesis())
    assert any("V" in t for t in p["tax_issues"])


# ── Opportunities ────────────────────────────────────────────────────────────

def test_opportunities_buckets():
    o = c.build_opportunities(queue=_queue(), sector_opportunities=_sectors())
    assert [w["symbol"] for w in o["watch"]] == ["XOM", "CVX"]
    assert [r["symbol"] for r in o["reentry"]] == ["ADBE"]
    assert [g["symbol"] for g in o["research_gaps"]] == ["CVX"]
    assert o["rotation"][0]["sector"] == "Energy"
    assert o["watch_total"] == 2
    assert o["reentry_total"] == 1


def test_opportunities_reentry_not_mislabeled_as_watch():
    # Re-entry rows that carry a readiness label (no RE_ENTER token) must bucket
    # under re-entry, not the staged watch queue.
    q = {"items": [
        {"symbol": "FATN", "verdict": None, "source": "advisory",
         "directive_label": "Re-entry NEAR ENTRY — FATN"},
        {"symbol": "GXAI", "verdict": None, "source": "advisory",
         "directive_label": "Re-entry READY TO REVIEW — GXAI"},
        {"symbol": "PLTR", "verdict": None, "source": "advisory",
         "directive_label": "Watchlist NEW — PLTR"},
    ]}
    o = c.build_opportunities(queue=q)
    assert [w["symbol"] for w in o["watch"]] == ["PLTR"]
    assert [r["symbol"] for r in o["reentry"]] == ["FATN", "GXAI"]
    assert o["reentry_total"] == 2


def test_opportunities_source_reentry_wins():
    q = {"items": [
        {"symbol": "IPM", "verdict": None, "source": "reentry", "directive_label": "MISSING PLAN — IPM"},
        {"symbol": "AMC", "verdict": "RE_ENTER", "source": "advisory", "directive_label": "Advisory RE_ENTER — AMC"},
    ]}
    o = c.build_opportunities(queue=q)
    assert [r["symbol"] for r in o["reentry"]] == ["IPM", "AMC"]
    assert o["watch"] == []



# ── Report / Evidence ────────────────────────────────────────────────────────

def test_report_section():
    rs = c.build_report_section(_report())
    assert rs["source_sha"] == "abc123"
    assert rs["source_traceability_pct"] == 100.0
    assert rs["field_count"] == 64
    assert rs["fields_present"] == 32
    assert rs["fields_unavailable"] == ["perf_QTD", "perf_3Y", "perf_true_TWR", "style_value_blend_growth"]


def test_evidence_contains_internal_codes_and_refs():
    ev = c.build_evidence(report=_report(), source_refs=[{"name": "holdings.json", "sha256": "x"}],
                          validator_states=[{"reviewer": "sentinel", "status": "PASS"}])
    assert ev["authority"] == "READ_ONLY_ADVISORY"
    assert ev["source_refs"][0]["name"] == "holdings.json"
    assert "perf_QTD" in ev["internal_codes"]
    assert ev["validator_states"][0]["reviewer"] == "sentinel"


# ── Composition ──────────────────────────────────────────────────────────────

def test_build_office_home_has_six_sections():
    home = c.build_office_home(
        capital_plan=_plan(), sector_opportunities=_sectors(), opportunity_queue=_queue(),
        report=_report(), thesis=_thesis(), attribution=_attribution(),
        income={"grand_total_income": 10543.13},
    )
    for k in ("cio_now", "capital_plan", "posture", "opportunities", "report", "evidence", "operator_trust"):
        assert k in home, k
    assert home["authority"] == "READ_ONLY_ADVISORY"
    assert "aegis_last_run" in home["operator_trust"]
    assert "holdings" in home["operator_trust"]
    assert "notification" in home["operator_trust"]
    assert home["posture"]["income"]["total_usd"] == 10543.13


def test_build_office_home_deterministic():
    from datetime import datetime, timezone
    fixed = datetime(2026, 8, 13, 20, 0, 0, tzinfo=timezone.utc)
    args = dict(capital_plan=_plan(), sector_opportunities=_sectors(), opportunity_queue=_queue(),
                report=_report(), thesis=_thesis(), attribution=_attribution(), now=fixed)
    a = c.build_office_home(**args)
    b = c.build_office_home(**args)
    assert a == b
    assert a["as_of"] == "2026-08-13T20:00:00+00:00"


def test_build_office_home_empty_fail_soft():
    home = c.build_office_home()
    assert home["cio_now"]["decisions"] == []
    assert home["capital_plan"]["cash_total_usd"] is None
    assert home["report"]["source_sha"] is None
    assert home["evidence"]["authority"] == "READ_ONLY_ADVISORY"
    assert home["operator_trust"]["holdings"]["reason_code"]
