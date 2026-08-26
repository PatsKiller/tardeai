"""Phase 5 — institutional charts + visual unit guards."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib import cio_report_charts as charts  # noqa: E402
from scripts.lib import cio_report_v2 as r  # noqa: E402
from scripts.lib import cio_report_render as render  # noqa: E402

FIXED = datetime(2026, 8, 14, 15, 0, 0, tzinfo=timezone.utc)


def _model(**perf_extra):
    perf = {
        "ytd_return": 5.0,
        "port_cagr": 12.0,
        "bench_cagr": 10.0,
        "period_returns": {
            "1M": {"change_pct": 2.1, "source": "snapshot"},
            "YTD": {"change_pct": 5.0, "source": "snapshot"},
            "1Y": {"change_pct": 18.0, "source": "account-aggregated"},
        },
        "rolling_alpha": [{"alpha": 0.1}, {"alpha": 0.2}, {"alpha": -0.05},
                          {"alpha": 0.15}, {"alpha": 0.12}, {"alpha": 0.08}],
    }
    perf.update(perf_extra)
    return r.build_report_v2(
        part_b_ctx={
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
            "analytics": {
                "top_10_aggregated": [
                    {"symbol": "SCHD", "weight_pct": 17.6},
                    {"symbol": "V", "weight_pct": 9.4},
                    {"symbol": "SCHG", "weight_pct": 8.0},
                    {"symbol": "XLI", "weight_pct": 2.9},
                    {"symbol": "DXCM", "weight_pct": 1.6},
                ],
            },
            "xray": {
                "sectors": [
                    {"sector": "Technology", "pct": 18.0},
                    {"sector": "Financials", "pct": 12.0},
                    {"sector": "Industrials", "pct": 10.0},
                ],
                "themes": {"AI": {"pct": 6.0}, "Defense": {"pct": 4.0}},
            },
            "performance": perf,
        },
        part_a_inputs={
            "capital_plan": {
                "portfolio_value_usd": 1_282_425.99,
                "cash_total_usd": 578_107.50,
                "cash_reserved_usd": 256_485.20,
                "cash_investable_usd": 321_622.30,
                "net_recommended_deploy_usd": 0.0,
                "net_recommended_raise_usd": 0.0,
                "post_plan_cash_usd": 578_107.50,
                "post_plan_cash_pct": 45.08,
                "position_decisions": [
                    {
                        "symbol": "SCHD", "stance": "Trim", "stance_code": "TRIM",
                        "current_value_usd": 225_922.0, "current_weight_pct": 17.6,
                        "recommended_delta_usd": -22_592.0,
                        "why_now": "Advisory TRIM — SCHD", "risk": "concentration > cap",
                    },
                ],
            },
            "sector_opportunities": [
                {"sector": "Technology", "state": "LEADING", "opportunity": True,
                 "current_exposure_pct": 7.4, "target_posture_pct": 18.0,
                 "recommendation": "STAGED_DEPLOYMENT"},
            ],
        },
        source_sha="phase5",
        now=FIXED,
    )


def test_charts_include_allocation_top10_sectors_periods():
    model = _model()
    bundle = charts.build_charts(model)
    inc = set(bundle["included"])
    assert "allocation" in inc
    assert "top10" in inc
    assert "concentration" in inc
    assert "sectors" in inc
    assert "periods" in inc
    assert "benchmark" in inc
    assert "rolling_alpha" in inc
    assert "themes" in inc
    # SVG present
    assert "<svg" in bundle["charts"]["allocation"]["svg"]
    assert bundle["charts"]["allocation"]["data_uri"].startswith("data:image/svg+xml")


def test_risk_return_abstains_without_volatility():
    model = _model()  # no port_vol
    bundle = charts.build_charts(model)
    assert "risk_return" not in bundle["included"]
    assert "risk_return" in bundle["skipped"]
    assert "CAGR-vs-CAGR" in bundle["skipped"]["risk_return"] or "vol" in bundle["skipped"]["risk_return"]


def test_risk_return_only_with_real_vol():
    model = _model(port_vol=14.5, bench_vol=12.0, port_cagr=12.0, bench_cagr=10.0)
    bundle = charts.build_charts(model)
    assert "risk_return" in bundle["included"]
    svg = bundle["charts"]["risk_return"]["svg"]
    assert "volatility" in svg.lower() or "Risk" in svg


def test_value_bridge_requires_reconcile():
    model = _model()
    model["part_b"]["flows"] = {
        "beginning_value": 1_000_000,
        "net_contributions": 50_000,
        "investment_earnings": 30_000,
        "ending_value": 1_080_000,  # reconciles
    }
    bundle = charts.build_charts(model)
    assert "value_bridge" in bundle["included"]

    model["part_b"]["flows"]["ending_value"] = 1_200_000  # broken
    bundle2 = charts.build_charts(model)
    assert "value_bridge" not in bundle2["included"]


def test_export_html_has_cover_toc_charts_no_dollar_pct(tmp_path: Path):
    model = _model()
    result = render.export_report_formats(
        model, tmp_path, basename="p5", write_docx=False, write_pdf=False,
    )
    html = Path(result["paths"]["html"]).read_text()
    assert "Private Investment Office" in html or "cover" in html.lower()
    assert "Contents" in html
    assert "Charts" in html or 'id="charts"' in html
    assert "578107.50%" not in html
    assert "704326.01%" not in html
    # Allocation table shows weight and dollars
    assert "45.08%" in html
    assert "$578,107.50" in html or "578,107.50" in html
    # Professional recommendation, not raw enum
    assert "STAGED_DEPLOYMENT" not in html
    assert result["parity"]["unit_guards"]["allocation_no_dollar_as_percent"] is True
    assert result["parity"]["phase5_exit"]["allocation_unit_errors"] == 0
    assert len(result["parity"]["charts_included"]) >= 4


def test_allocation_regression_exact_shape():
    """Phase 5.8 required shape: Cash $578k / 45.08% — never 578107.50%."""
    model = _model()
    weights = model["part_b"]["allocation_weight_pct"]
    assert weights["Cash & Equivalents"] == 45.08
    assert weights["Equities"] == 54.92
    html = model["html"]
    assert "578107.50%" not in html
    # View allocation table rows
    from scripts.lib.cio_report_view import section_by_id, build_report_view
    v = build_report_view(model)
    alloc_sec = section_by_id(v, "allocation")
    assert alloc_sec is not None
    # rows: Class, USD, Weight
    cash_row = next(r for r in alloc_sec["rows"] if "Cash" in str(r[0]))
    assert "$578,107.50" in cash_row[1]
    assert "45.08%" in cash_row[2]


def test_chart_governance_fields():
    model = _model()
    bundle = charts.build_charts(model)
    for key, c in bundle["charts"].items():
        assert c.get("title")
        assert c.get("source_note") is not None
        assert c.get("units") is not None
        assert c.get("alt_caption")
        assert c.get("spec_version") == charts.CHART_SPEC_VERSION
