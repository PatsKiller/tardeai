"""cio_report_v2.py — dry tests for the Institutional Report v2 (Phase 7).

Pure logic: coverage matrix, gap resolution, manifest determinism, HTML render,
Checkpoint 7 shape, Part A composition. No live DB/broker/LLM.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib import cio_report_v2 as r  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Gap resolution
# ─────────────────────────────────────────────────────────────────────────────

def test_all_gaps_have_valid_resolution():
    for g in r.KNOWN_GAPS:
        assert g["resolution"] in r.FIELD_STATUSES, g["gap_id"]
        assert g["gap_id"].startswith("gap_")
        assert g["field_ids"], g["gap_id"]


def test_gap_resolutions_specific():
    assert r.resolve_gap("gap_qtd_absent")["resolution"] == r.UNAVAILABLE
    assert r.resolve_gap("gap_true_twr")["resolution"] == r.UNAVAILABLE
    assert r.resolve_gap("gap_style_box")["resolution"] == r.UNAVAILABLE
    assert r.resolve_gap("gap_per_lot_basis")["resolution"] == r.SUBSTITUTE
    assert r.resolve_gap("gap_fund_lookthrough")["resolution"] == r.SUBSTITUTE
    assert r.resolve_gap("gap_3m_1y_inconsistent")["resolution"] == r.SUBSTITUTE
    assert r.resolve_gap("does_not_exist") is None


def test_gap_resolution_applied_to_fields():
    fields = r.report_fields()
    by = {f["field_id"]: f["status"] for f in fields}
    assert by["perf_QTD"] == r.UNAVAILABLE
    assert by["perf_true_TWR"] == r.UNAVAILABLE
    assert by["style_value_blend_growth"] == r.UNAVAILABLE
    assert by["perf_3M"] == r.SUBSTITUTE
    assert by["perf_1Y"] == r.SUBSTITUTE
    assert by["tax_per_lot_details"] == r.SUBSTITUTE


# ─────────────────────────────────────────────────────────────────────────────
# Coverage matrix
# ─────────────────────────────────────────────────────────────────────────────

def test_coverage_matrix_counts_consistent():
    fields = r.report_fields()
    cov = r.build_coverage_matrix(fields)
    assert cov["field_count"] == len(fields)
    assert sum(cov["by_status"].values()) == len(fields)
    # every numerical field is either reported-with-source or unavailable
    assert cov["numeric_field_count"] == cov["numeric_reported_count"] + len(cov["fields_unavailable"])


def test_source_traceability_100():
    cov = r.build_coverage_matrix()
    assert cov["source_traceability_pct"] == 100.0
    # every reported numerical field carries a source
    fields = r.report_fields()
    for f in fields:
        if f["kind"] == r.NUMERIC and f["status"] != r.UNAVAILABLE:
            assert f.get("source") and f["source"] != "none", f["field_id"]


def test_unavailable_fields_have_no_source():
    cov = r.build_coverage_matrix()
    fields = r.report_fields()
    by = {f["field_id"]: f for f in fields}
    for fid in cov["fields_unavailable"]:
        assert by[fid]["source"] == "none"
        assert by[fid]["coverage"] == "0%"


def test_known_gaps_never_silently_reported():
    # unavailable fields must not appear in fields_present
    cov = r.build_coverage_matrix()
    for fid in cov["fields_unavailable"]:
        assert fid not in cov["fields_present"]


# ─────────────────────────────────────────────────────────────────────────────
# Manifest
# ─────────────────────────────────────────────────────────────────────────────

def test_manifest_hashes_inputs_deterministically():
    from datetime import datetime, timezone
    fixed = datetime(2026, 8, 13, 20, 0, 0, tzinfo=timezone.utc)
    cov = r.build_coverage_matrix()
    m1 = r.build_manifest(inputs={"holdings.json": b"abc"}, coverage=cov, source_sha="sha123", now=fixed)
    m2 = r.build_manifest(inputs={"holdings.json": b"abc"}, coverage=cov, source_sha="sha123", now=fixed)
    assert m1["input_hashes"]["holdings.json"] == m2["input_hashes"]["holdings.json"]
    assert m1["manifest_hash"] == m2["manifest_hash"]
    assert m1["authority"] == "READ_ONLY_ADVISORY"
    assert m1["source_sha"] == "sha123"


def test_manifest_changes_with_input():
    cov = r.build_coverage_matrix()
    a = r.build_manifest(inputs={"x": b"1"}, coverage=cov, source_sha="s")
    b = r.build_manifest(inputs={"x": b"2"}, coverage=cov, source_sha="s")
    assert a["manifest_hash"] != b["manifest_hash"]


def test_manifest_handles_unhashable_payload():
    cov = r.build_coverage_matrix()
    m = r.build_manifest(inputs={"complex": {"a": {"b": [1, 2]}}}, coverage=cov)
    assert len(m["input_hashes"]["complex"]) == 64  # sha256 hex


def test_manifest_dict_list_inputs_hashed():
    cov = r.build_coverage_matrix()
    m = r.build_manifest(inputs={"cfg": {"k": "v"}, "lst": [1, 2, 3]}, coverage=cov)
    assert len(m["input_hashes"]["cfg"]) == 64
    assert len(m["input_hashes"]["lst"]) == 64


# ─────────────────────────────────────────────────────────────────────────────
# Checkpoint 7 shape
# ─────────────────────────────────────────────────────────────────────────────

def test_checkpoint_shape():
    cov = r.build_coverage_matrix()
    cp = r.build_checkpoint(coverage=cov, quality_flags=["a", "b"], pdf_pages=None, render_errors=[])
    for k in ("fields_present", "fields_improved_vs_reference", "fields_unavailable",
              "quality_flags", "pdf_pages", "render_errors", "source_traceability_pct"):
        assert k in cp, k
    assert cp["quality_flags"] == ["a", "b"]
    assert cp["source_traceability_pct"] == 100.0


# ─────────────────────────────────────────────────────────────────────────────
# Part A composition
# ─────────────────────────────────────────────────────────────────────────────

def _sample_part_a_inputs():
    return {
        "thesis": {
            "summary": "Concentrated growth with defensive cash floor.",
            "stance": "moderately constructive, defensive cash band",
            "bullets": ["AI capex leadership", "quality bias"],
            "risk_posture": "cash band 20-25%",
            "escalation_rules": ["do not chase momentum into earnings"],
            "learning_log": [{"kind": "disposition", "note": "trimmed V to policy"}],
            "last_reviewed": "2026-08-12",
        },
        "capital_plan": {
            "cash_total_usd": 578107.5,
            "cash_reserved_usd": 256485.2,
            "cash_investable_usd": 321622.3,
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
            "position_decisions": [
                {"symbol": "V", "cio_stance": "TRIM", "current_value_usd": 40000.0,
                 "current_weight_pct": 3.1, "recommended_delta_usd": -4000.0,
                 "why_now": "overweight", "next_review": "2026-09-12",
                 "counter_thesis": "none"},
            ],
            "portfolio_constraints": [
                {"kind": "concentration_fire_pct", "value": 16.5},
            ],
        },
        "sector_opportunities": [
            {"sector": "Energy", "state": "IMPROVING", "opportunity": True,
             "current_exposure_pct": 4.0, "target_posture_pct": 5.0,
             "recommendation": "STAGED_DEPLOYMENT",
             "candidates": [{"symbol": "CVX", "readiness": "NEEDS_RESEARCH"}]},
        ],
        "opportunity_queue": {
            "top": [{"symbol": "XOM", "verdict": "ADD", "source": "advisory",
                     "directive_label": "energy"}],
            "items": [{"symbol": "XOM", "verdict": "ADD", "source": "advisory",
                       "directive_label": "energy"}],
        },
        "performance_attribution": {
            "benchmark_label": "55% SPY / 20% ITA / 25% AGG",
            "port_cagr": 21.35, "bench_cagr": 19.31, "alpha_annualized": 2.04,
            "port_maxdd": -21.2, "port_sharpe": 0.692, "port_sortino": 0.819,
        },
        "performance": {"periods": {"1M": {"change_pct": 3.45, "source": "snapshot"}}},
        "dispositions": [{"disposition": "ACKNOWLEDGED", "ts": "2026-08-13"}],
    }


def test_part_a_has_all_six_sections():
    a = r.build_part_a(**_sample_part_a_inputs())
    for k in ("letter", "decisions_now", "capital_plan", "portfolio_posture",
              "opportunity_funnel", "counter_thesis_risks"):
        assert k in a, k


def test_part_a_letter_content():
    a = r.build_part_a(**_sample_part_a_inputs())
    letter = a["letter"]
    assert "Concentrated growth" in letter["thesis_summary"]
    assert letter["stance"]
    assert letter["priorities"]
    assert any("no broker/order/stop authority" in s for s in letter["what_not_to_do"])


def test_part_a_decisions_now_delta():
    a = r.build_part_a(**_sample_part_a_inputs())
    assert a["decisions_now"][0]["symbol"] == "V"
    assert a["decisions_now"][0]["recommended_delta_usd"] == -4000.0


def test_part_a_capital_plan_pass_through():
    a = r.build_part_a(**_sample_part_a_inputs())
    cap = a["capital_plan"]
    assert cap["cash_total_usd"] == 578107.5
    assert cap["recommended_deploy_usd"] == 603114.7
    assert cap["sources"]["total_raise_usd"] == 623009.02


def test_part_a_posture_benchmark():
    a = r.build_part_a(**_sample_part_a_inputs())
    posture = a["portfolio_posture"]
    assert posture["benchmark_posture"]["label"].startswith("55% SPY")
    assert posture["risk_heat"]["max_drawdown_pct"] == -21.2


def test_part_a_funnel_and_risks():
    a = r.build_part_a(**_sample_part_a_inputs())
    funnel = a["opportunity_funnel"]
    assert funnel["watch_additions"][0]["symbol"] == "XOM"
    assert funnel["research_gaps"][0]["symbol"] == "CVX"
    risks = a["counter_thesis_risks"]
    assert any("drawdown exceeds" in u for u in risks["highest_impact_unknowns"])


def test_part_a_fail_soft_empty():
    a = r.build_part_a()
    assert a["letter"]["thesis_summary"] is None
    assert a["decisions_now"] == []
    assert a["capital_plan"]["cash_total_usd"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Full model + HTML
# ─────────────────────────────────────────────────────────────────────────────

def _sample_model():
    return r.build_report_v2(
        part_b_ctx={
            "portfolio": {"total_value": 1282425.99, "cash_value": 578107.5, "positions_count": 26},
            "accounts": [{"display_name": "Schwab Rollover IRA", "broker": "schwab",
                          "total_value": 1161081.56, "weight_pct": 90.5, "gain_loss": 70382.79}],
            "performance": {"periods": {
                "1M": {"change": 42764.53, "change_pct": 3.45, "source": "snapshot"},
                "1Y": {"change": 1380701.71, "change_pct": 117.87, "source": "account-aggregated"},
            }},
            "benchmark": {"label": "55% SPY / 20% ITA / 25% AGG", "cagr": 21.35, "3yr": None},
            "unrealized": {"lt_unrealized": 70382.79, "st_unrealized": 0.0, "count": 26},
        },
        part_a_inputs=_sample_part_a_inputs(),
        source_sha="abc123",
        input_payloads={"holdings.json": b"holdings-bytes", "thesis": {"stance": "x"}},
    )


def test_build_report_v2_model_shape():
    m = _sample_model()
    for k in ("report_version", "authority", "as_of", "part_a", "part_b",
              "fields", "coverage", "manifest", "checkpoint", "quality_flags", "html"):
        assert k in m, k
    assert m["authority"] == "READ_ONLY_ADVISORY"
    assert m["checkpoint"]["source_traceability_pct"] == 100.0
    assert m["manifest"]["source_sha"] == "abc123"


def test_html_contains_part_a_and_b():
    m = _sample_model()
    html = m["html"]
    assert "Part A — CIO Investment Committee" in html
    assert "Part B — Institutional Portfolio Book" in html
    assert "Field-Coverage Matrix" in html
    assert "Known-Gap Resolutions" in html


def test_html_has_no_raw_json():
    m = _sample_model()
    html = m["html"]
    assert '"field_id":' not in html
    assert '"status":' not in html
    assert '\\\\n' not in html


def test_html_flags_inconsistent_period():
    m = _sample_model()
    html = m["html"]
    assert "account-aggregated" in html
    assert "flagged" in html


def test_html_is_self_contained():
    m = _sample_model()
    html = m["html"]
    assert html.startswith("<!DOCTYPE html>")
    assert "@page" in html
    assert "@media print" in html
    assert "READ_ONLY_ADVISORY" in html


def test_model_deterministic_given_fixed_now():
    from datetime import datetime, timezone
    fixed = datetime(2026, 8, 13, 20, 0, 0, tzinfo=timezone.utc)
    a = r.build_report_v2(
        part_b_ctx={"portfolio": {"total_value": 100.0}},
        part_a_inputs={}, source_sha="s", input_payloads={"x": b"1"}, now=fixed,
    )
    b = r.build_report_v2(
        part_b_ctx={"portfolio": {"total_value": 100.0}},
        part_a_inputs={}, source_sha="s", input_payloads={"x": b"1"}, now=fixed,
    )
    assert a["manifest"]["manifest_hash"] == b["manifest"]["manifest_hash"]
    assert a["as_of"] == b["as_of"]
    assert a["html"] == b["html"]
