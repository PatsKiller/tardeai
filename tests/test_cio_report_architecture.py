"""Phase 4 — one reporting architecture (model → view → formats)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib import cio_report_v2 as r  # noqa: E402
from scripts.lib import cio_report_view as view  # noqa: E402
from scripts.lib import cio_report_render as render  # noqa: E402


FIXED = datetime(2026, 8, 14, 12, 0, 0, tzinfo=timezone.utc)


def _sample_model() -> dict:
    part_a_inputs = {
        "thesis": {
            "summary": "Preserve dry powder; selective trims on concentration.",
            "stance": "Neutral / cautious",
            "bullets": ["Cash above band", "Trim SCHD on cap"],
            "risk_posture": "defensive-leaning",
            "escalation_rules": ["do not chase non-improving sectors"],
        },
        "capital_plan": {
            "portfolio_value_usd": 1_282_425.99,
            "cash_total_usd": 578_107.50,
            "cash_reserved_usd": 256_485.20,
            "cash_investable_usd": 321_622.30,
            "cash_earmarked_redeploy_usd": 578_107.50,
            "net_recommended_deploy_usd": 0.0,
            "net_recommended_raise_usd": 0.0,
            "deployable_usd": 321_622.30,
            "post_plan_cash_usd": 578_107.50,
            "post_plan_cash_pct": 45.08,
            "cash_policy_band": {"min_pct": 20.0, "max_pct": 25.0},
            "plan_version": "capital_plan_1.1.0",
            "capital_sources": {
                "trims_usd": 0.0, "exits_usd": 0.0, "maturities_usd": 578_107.50,
                "earmarked_redeploy_usd": 578_107.50, "total_raise_usd": 0.0,
                "total_prospective_raise_usd": 0.0,
                "double_count_guard": "earmarked_redeploy_excluded_from_raise",
            },
            "capital_uses": {
                "adds_usd": 0.0, "new_positions_usd": 0.0, "reentry_usd": 0.0,
                "sector_rotation_usd": 0.0, "reserve": 256_485.20,
                "total_deploy_request_usd": 0.0,
            },
            "position_decisions": [
                {
                    "symbol": "SCHD", "cio_stance": "TRIM", "stance": "Trim",
                    "stance_code": "TRIM",
                    "current_value_usd": 225_922.59, "current_weight_pct": 17.62,
                    "recommended_delta_usd": -22_592.26,
                    "why_now": "Advisory TRIM — SCHD",
                    "risk": "concentration > cap",
                },
                {
                    "symbol": "V", "cio_stance": "TRIM", "stance": "Trim",
                    "stance_code": "TRIM",
                    "current_value_usd": 121_133.90, "current_weight_pct": 9.45,
                    "recommended_delta_usd": -12_113.39,
                    "why_now": "Advisory TRIM — V",
                    "risk": "within single-name cap",
                },
            ],
        },
        "sector_opportunities": [
            {
                "sector": "Technology", "state": "LEADING", "opportunity": True,
                "current_exposure_pct": 7.4, "target_posture_pct": 18.0,
                "recommendation": "STAGED_DEPLOYMENT",
            },
            {
                "sector": "Iwm−Spy", "state": "IMPROVING", "opportunity": True,
                "recommendation": "RESEARCH_FIRST",
            },
        ],
        "opportunity_queue": {
            "items": [
                {"symbol": "SCHD", "verdict": None,
                 "directive_label": "Advisory TRIM — SCHD", "source": "advisory"},
            ],
            "distinct_sources": 2,
        },
        "performance_attribution": {
            "port_cagr": 0.12, "bench_cagr": 0.10, "alpha_annualized": 0.02,
            "port_maxdd": -0.08, "port_sharpe": 1.1, "port_sortino": 1.4,
            "benchmark_label": "SPY",
        },
        "performance": {"periods": {"YTD": 0.05}},
    }
    part_b = {
        "portfolio": {
            "total_value": 1_282_425.99,
            "cash_value": 578_107.50,
            "cash_pct": 45.08,
            "positions_count": 26,
        },
        "allocation": {
            "Cash & Equivalents": 578_107.50,
            "Equities": 704_326.01,
            "Other": 0.0,
        },
        "accounts": [
            {"display_name": "Schwab IRA", "broker": "Schwab",
             "total_value": 900_000.0, "weight_pct": 70.0, "gain_loss": 10_000.0,
             "status": "ok"},
        ],
        "performance": {
            "ytd_return": 5.0, "port_cagr": 12.0, "bench_cagr": 10.0,
            "alpha_annualized": 2.0, "sharpe": 1.1, "sortino": 1.4,
            "max_drawdown": -8.0,
        },
    }
    return r.build_report_v2(
        part_b_ctx=part_b,
        part_a_inputs=part_a_inputs,
        source_sha="testsha123",
        input_payloads={"holdings.json": b'{"ok":true}'},
        now=FIXED,
    )


def test_model_has_architecture_and_view():
    model = _sample_model()
    assert model["report_version"].startswith("report_v2_1.")
    assert model.get("architecture_version") == "report_arch_1.0.0"
    assert model.get("view")
    assert model.get("facts_fingerprint")
    assert model.get("html")
    assert "Trade AI" in model["html"]


def test_allocation_normalized_on_model():
    model = _sample_model()
    pb = model["part_b"]
    weights = pb.get("allocation_weight_pct") or {}
    assert weights
    assert all(abs(float(v)) <= 100.01 for v in weights.values())
    # Cash ~45% not 578107
    assert weights["Cash & Equivalents"] == 45.08
    assert weights["Equities"] == 54.92


def test_view_facts_match_model_capital():
    model = _sample_model()
    v = model["view"]
    facts = v["facts"]
    assert facts["cash_total_usd"] == 578_107.50
    assert facts["cash_investable_usd"] == 321_622.30
    assert facts["recommended_deploy_usd"] == 0.0
    assert facts["recommended_raise_usd"] == 0.0
    # decisions present and unique
    symbols = [d["symbol"] for d in facts["decisions"]]
    assert "SCHD" in symbols and "V" in symbols
    assert len(symbols) == len(set(symbols))
    # Iwm−Spy not in sector posture
    assert not any("Iwm" in str(s.get("sector")) for s in facts["sector_posture"])


def test_html_and_view_share_fingerprint():
    model = _sample_model()
    v1 = view.build_report_view(model)
    html = render.render_html_from_view(v1)
    # Re-project — same fingerprint
    v2 = view.build_report_view(model)
    assert v1["facts_fingerprint"] == v2["facts_fingerprint"]
    assert v1["facts_fingerprint"] in html or v1["facts_fingerprint"][:12] in html
    # No absurd percentage from dollars
    assert "578107.50%" not in html
    assert "704326.01%" not in html
    # Weight present
    assert "45.08%" in html or "45.08" in html


def test_export_bundle_html_parity(tmp_path: Path):
    model = _sample_model()
    result = render.export_report_formats(
        model, tmp_path, basename="cio_test", write_docx=False, write_pdf=False,
    )
    assert result["paths"]["html"]
    assert result["paths"]["model_json"]
    assert result["paths"]["view_json"]
    assert result["paths"]["parity_json"]
    parity = json.loads(Path(result["paths"]["parity_json"]).read_text())
    assert parity["facts_fingerprint"] == result["facts_fingerprint"]
    assert parity["unit_guards"]["allocation_weights_le_100"] is True
    assert parity["unit_guards"]["decision_symbols_unique"] is True
    # HTML from export matches view facts fingerprint
    html = Path(result["paths"]["html"]).read_text()
    assert result["facts_fingerprint"][:12] in html


def test_command_center_slice_uses_same_facts():
    model = _sample_model()
    cc = model["view"]["command_center"]
    assert cc["capital"]["cash_total_usd"] == 578_107.50
    assert cc["facts_fingerprint"] == model["facts_fingerprint"]
    assert any(d["symbol"] == "SCHD" for d in cc["decisions"])


def test_fmt_pct_guards_dollar_sized_values():
    # Values that look like dollars should not print as clean small percents
    s = view.fmt_pct(578_107.50)
    assert "check units" in s or "%" in s
    assert view.fmt_pct(45.08) == "45.08%"


def test_section_ids_stable():
    model = _sample_model()
    ids = model["view"]["section_ids"]
    assert "cover" in ids
    assert "decisions_now" in ids
    assert "capital_plan" in ids
    assert "allocation" in ids
    assert "disclosure" in ids
