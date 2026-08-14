"""Phase 6 — analytic completeness + methodology truth."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib import cio_report_analytics as an  # noqa: E402
from scripts.lib import cio_report_v2 as r  # noqa: E402

FIXED = datetime(2026, 8, 14, 18, 0, 0, tzinfo=timezone.utc)


def _part_b(**extra):
    base = {
        "as_of": FIXED.isoformat(),
        "portfolio": {"total_value": 1_282_425.99, "cash_value": 578_107.5, "cash_pct": 45.08},
        "allocation": {"Cash & Equivalents": 578_107.5, "Equities": 704_326.01, "Other": 0.0},
        "performance": {
            "ytd_return": 5.0,
            "port_cagr": 12.0,
            "bench_cagr": 10.0,
            "alpha_annualized": 2.0,
            "inception_return": 45.0,
            "benchmark_label": "55% SPY / 20% ITA / 25% AGG",
            "current_value": 1_282_425.99,
            "period_returns": {
                "1M": {"change_pct": 2.1, "source": "snapshot"},
                "3M": {"change_pct": 4.0, "source": "account-aggregated"},
                "YTD": {"change_pct": 5.0, "source": "snapshot"},
                "1Y": {"change_pct": 18.0, "source": "account-aggregated"},
            },
            "change_value": {
                "beginning_value": 1_200_000.0,
                "net_contributions": 20_000.0,
                "investment_earnings": 62_425.99,
                "ending_value": 1_282_425.99,
            },
        },
        "benchmark": {"label": "55% SPY / 20% ITA / 25% AGG", "cagr": 10.0},
        "analytics": {
            "weighted_pe": 24.1,
            "weighted_pb": 3.2,
            "weighted_ps": 2.5,
            "valuation_coverage_pct": 31.0,
            "valuation_coverage_note": "direct-equity only",
            "fund_etf_pct": 55.0,
        },
        "xray": {
            "coverage_pct": 78.0,
            "sectors": [
                {"sector": "Technology", "pct": 18.0},
                {"sector": "Financials", "pct": 12.0},
            ],
            "top_underlying": [{"symbol": "AAPL", "pct": 3.1}],
            "not_decomposed": ["FCNTX"],
        },
        "unrealized": {
            "lt_unrealized": 70_000.0,
            "st_unrealized": 5_000.0,
            "count": 2,
            "rows": [
                {
                    "symbol": "SCHD", "account": "ira", "quantity": 1000,
                    "cost_basis": 50_000, "market_value": 60_000,
                    "unrealized_gl": 10_000, "holding_period": "long_term",
                    "quality_flag": "ok",
                },
                {
                    "symbol": "V", "account": "taxable", "quantity": 100,
                    "cost_basis": 20_000, "market_value": 25_000,
                    "unrealized_gl": 5_000, "holding_period": "long_term",
                    "quality_flag": "basis_partial",
                },
            ],
        },
    }
    base.update(extra)
    return base


def test_performance_definitions_complete_and_label_methodologies():
    defs = an.build_performance_definitions(_part_b()["performance"], as_of="2026-08-14")
    assert defs["definitions_complete"] is True
    by = {m["metric"]: m for m in defs["metrics"]}
    assert by["return_3M"]["quality"] == "flagged"
    assert "account" in by["return_3M"]["methodology"] or by["return_3M"]["methodology"] == an.METH_ACCOUNT_AGG
    assert by["return_QTD"]["is_unavailable"] is True
    assert by["return_QTD"]["value_display"] == an.DATA_UNAVAILABLE
    assert by["true_twr"]["is_unavailable"] is True
    assert by["true_twr"]["value"] is None
    assert by["portfolio_cagr"]["methodology"] == an.METH_CAGR
    assert "not true TWR" in by["portfolio_cagr"]["note"].lower() or "Not true TWR" in by["portfolio_cagr"]["note"]


def test_change_in_value_reconciles():
    civ = an.build_change_in_value(_part_b()["performance"])
    assert civ["reconciles"] is True
    assert civ["displayed"] is True
    assert civ["invariant_ok"] is True
    assert abs(civ["residual_usd"]) <= 1.01


def test_change_in_value_hides_broken_bridge():
    perf = _part_b()["performance"]
    perf["change_value"]["ending_value"] = 9_999_999.0
    civ = an.build_change_in_value(perf)
    assert civ["reconciles"] is False
    assert civ["displayed"] is False
    assert civ["invariant_ok"] is True  # not displayed ⇒ invariant holds


def test_benchmark_alignment():
    ba = an.build_benchmark_alignment(_part_b()["performance"], _part_b()["benchmark"])
    assert ba["comparable"] is True
    assert ba["comparability_label"] == "comparable_cagr"


def test_lookthrough_coverage_disclosed():
    lt = an.build_lookthrough_coverage(_part_b()["xray"])
    assert lt["coverage_disclosed"] is True
    assert lt["lookthrough_coverage_pct"] == 78.0
    assert lt["unclassified_pct"] == 22.0
    assert "78%" in lt["coverage_label"]
    assert "22%" in lt["coverage_label"]


def test_valuation_coverage_impossible_to_miss():
    val = an.build_valuation_coverage(_part_b()["analytics"])
    assert val["coverage_disclosed"] is True
    assert val["coverage_pct"] == 31.0
    assert "31%" in val["coverage_label"]
    assert any(m["metric"] == "weighted_pe" for m in val["multiples"])
    # without multiples still discloses coverage
    val2 = an.build_valuation_coverage({})
    assert val2["coverage_disclosed"] is True
    assert "DATA_UNAVAILABLE" in val2["coverage_label"]


def test_attribution_does_not_fabricate_brinson():
    attr = an.build_attribution_section(_part_b()["performance"], {})
    by = {c["component"]: c for c in attr["components"]}
    assert by["allocation_effect"]["value"] is None
    assert by["selection_effect"]["value"] is None
    assert by["allocation_effect"]["value_display"] == an.DATA_UNAVAILABLE
    assert by["rolling_alpha_annualized"]["value"] == 2.0


def test_tax_lots_disclaimer():
    tax = an.build_tax_lot_section(_part_b()["unrealized"])
    assert tax["coverage_disclosed"] is True
    assert "not tax-filing" in tax["disclaimer"].lower() or "not tax-filing" in tax["disclaimer"]
    assert tax["row_count"] == 2
    assert any(r["quality_flag"] == "basis_partial" for r in tax["rows"])


def test_income_unavailable_not_invented():
    inc = an.build_income_section({})
    assert inc["status"] == "unavailable"
    assert inc["value_display"] == an.DATA_UNAVAILABLE


def test_analytics_packet_exit_gate():
    packet = an.build_analytics_packet(_part_b())
    gate = packet["exit_gate"]
    assert gate["PERFORMANCE_METRIC_DEFINITIONS"] == "PASS"
    assert gate["CHANGE_IN_VALUE_RECONCILIATION"] == "PASS"
    assert gate["BENCHMARK_PERIOD_ALIGNMENT"] == "PASS"
    assert gate["LOOKTHROUGH_COVERAGE_DISCLOSED"] == "PASS"
    assert gate["VALUATION_COVERAGE_DISCLOSED"] == "PASS"
    assert gate["TAX_LOT_SOURCE_QUALITY_DISCLOSED"] == "PASS"
    assert gate["FABRICATED_METRIC_COUNT"] == 0
    assert gate["ALL_PASS"] is True


def test_build_report_v2_embeds_analytics_packet():
    model = r.build_report_v2(
        part_b_ctx=_part_b(),
        part_a_inputs={
            "capital_plan": {
                "portfolio_value_usd": 1_282_425.99,
                "cash_total_usd": 578_107.5,
                "cash_reserved_usd": 256_485.2,
                "cash_investable_usd": 321_622.3,
                "net_recommended_deploy_usd": 0,
                "net_recommended_raise_usd": 0,
                "post_plan_cash_usd": 578_107.5,
                "position_decisions": [],
            },
        },
        source_sha="phase6",
        now=FIXED,
    )
    assert model["report_version"].startswith("report_v2_1.")
    pb = model["part_b"]
    assert pb.get("analytics_packet")
    assert pb["analytics_packet"]["exit_gate"]["ALL_PASS"] is True
    html = model["html"]
    assert "Performance Definitions" in html or "methodology truth" in html
    assert "DATA_UNAVAILABLE" in html  # TWR/QTD honest
    assert "look-through coverage" in html.lower() or "Look-Through" in html
    assert "31%" in html  # valuation coverage
    assert "not tax-filing" in html.lower() or "filing truth" in html.lower()


def test_no_fabricated_twr_in_html():
    model = r.build_report_v2(
        part_b_ctx=_part_b(),
        part_a_inputs={},
        source_sha="x",
        now=FIXED,
    )
    # Must not invent a TWR percentage
    defs = model["part_b"]["performance_definitions"]["metrics"]
    twr = next(m for m in defs if m["metric"] == "true_twr")
    assert twr["value"] is None
    assert twr["is_unavailable"] is True
