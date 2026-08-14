"""Phase 7 — output pipeline, instance manifest, cross-format parity."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from scripts.lib import cio_report_v2 as r  # noqa: E402
from scripts.lib import cio_report_render as render  # noqa: E402
from scripts.lib import cio_report_pipeline as pipe  # noqa: E402
from scripts import render_cio_report_files as cli  # noqa: E402

FIXED = datetime(2026, 8, 14, 20, 0, 0, tzinfo=timezone.utc)


def _model():
    return r.build_report_v2(
        part_b_ctx={
            "as_of": FIXED.isoformat(),
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
            "performance": {
                "ytd_return": 5.0,
                "port_cagr": 12.0,
                "bench_cagr": 10.0,
                "max_drawdown": -8.0,
                "benchmark_label": "SPY blend",
                "period_returns": {
                    "YTD": {"change_pct": 5.0, "source": "snapshot"},
                },
                "change_value": {
                    "beginning_value": 1_200_000.0,
                    "net_contributions": 20_000.0,
                    "investment_earnings": 62_425.99,
                    "ending_value": 1_282_425.99,
                },
            },
            "analytics": {
                "weighted_pe": 24.1,
                "valuation_coverage_pct": 31.0,
            },
            "xray": {"coverage_pct": 78.0, "sectors": [{"sector": "Technology", "pct": 18.0}]},
            "unrealized": {
                "lt_unrealized": 70_000.0,
                "st_unrealized": 0.0,
                "count": 1,
                "rows": [{
                    "symbol": "SCHD", "account": "ira", "quantity": 100,
                    "cost_basis": 5000, "market_value": 6000, "unrealized_gl": 1000,
                    "holding_period": "long_term", "quality_flag": "ok",
                }],
            },
            "analytics_top": {},
            "analytics_x": {},
        },
        part_a_inputs={
            "capital_plan": {
                "portfolio_value_usd": 1_282_425.99,
                "cash_total_usd": 578_107.50,
                "cash_reserved_usd": 256_485.20,
                "cash_investable_usd": 321_622.30,
                "net_recommended_deploy_usd": 10_000.0,
                "net_recommended_raise_usd": 0.0,
                "post_plan_cash_usd": 568_107.50,
                "post_plan_cash_pct": 44.3,
                "plan_version": "capital_plan_1.1.0",
                "position_decisions": [
                    {
                        "symbol": "SCHD", "stance": "Trim", "stance_code": "TRIM",
                        "current_value_usd": 225_922.0, "current_weight_pct": 17.6,
                        "recommended_delta_usd": -22_592.0,
                        "why_now": "Advisory TRIM — SCHD", "risk": "concentration > cap",
                    },
                    {
                        "symbol": "V", "stance": "Trim", "stance_code": "TRIM",
                        "current_value_usd": 121_000.0, "current_weight_pct": 9.4,
                        "recommended_delta_usd": -12_100.0,
                        "why_now": "Advisory TRIM — V", "risk": "within single-name cap",
                    },
                ],
            },
            "thesis": {"stance": "Neutral", "summary": "Preserve dry powder."},
        },
        source_sha="phase7sha",
        input_payloads={"holdings.json": b'{"ok":true}'},
        now=FIXED,
    )


def test_extract_key_values_from_view():
    model = _model()
    kv = pipe.extract_key_values_from_view(model["view"], model)
    assert kv["portfolio_total_usd"] == 1_282_425.99
    assert kv["cash_usd"] == 578_107.50
    assert kv["cash_pct"] == 45.08
    assert kv["recommended_deploy_usd"] == 10_000.0
    assert kv["post_plan_cash_usd"] == 568_107.50
    assert "SCHD" in (kv["top_decision_symbols"] or [])
    assert kv["facts_fingerprint"]


def test_export_writes_instance_manifest_and_claims(tmp_path: Path):
    model = _model()
    result = render.export_report_formats(
        model, tmp_path, basename="p7", formats=["html"], report_id="cio-rpt-testfixed",
    )
    assert result["paths"]["html"]
    assert result["paths"]["instance_manifest"]
    assert result["paths"]["claims_json"]
    assert result["paths"]["parity_json"]
    assert result["report_id"] == "cio-rpt-testfixed"

    inst = json.loads(Path(result["paths"]["instance_manifest"]).read_text())
    assert inst["immutable"] is True
    assert inst["instance_hash"]
    assert inst["report_id"] == "cio-rpt-testfixed"
    assert inst["source_sha"] == "phase7sha"
    assert "key_values" in inst
    assert inst["key_values"]["portfolio_total_usd"] == 1_282_425.99
    assert "output_sha256" in inst
    assert "html" in inst["output_files"] or "html" in (result["claims"]["files_created"] or {})

    claims = json.loads(Path(result["paths"]["claims_json"]).read_text())
    for p in claims["files_created"].values():
        assert Path(p).exists()

    gate = result["phase7_exit_gate"]
    assert gate["CLI_CLAIMS_EQ_FILES_CREATED"] == "PASS"
    assert gate["HTML_PDF_DOCX_KEY_VALUE_PARITY"] == "PASS"
    assert gate["MANIFEST_HASHES"] == "PASS"


def test_html_parity_with_canonical_keys(tmp_path: Path):
    model = _model()
    result = render.export_report_formats(
        model, tmp_path, basename="p7b", formats=["html"],
    )
    html = Path(result["paths"]["html"]).read_text()
    can = result["parity"]["key_values"]
    extracted = pipe.extract_key_values_from_html(html)
    cmp = pipe.compare_key_values(can, extracted)
    # portfolio total and cash should be recoverable from HTML
    assert extracted["portfolio_total_usd"] == can["portfolio_total_usd"]
    assert result["parity"]["html_parity"]["ok"] is True
    assert cmp["ok"] is True or len(cmp["hard_mismatches"]) == 0


def test_cli_file_source_html(tmp_path: Path):
    model = _model()
    model_path = tmp_path / "in_model.json"
    model_path.write_text(json.dumps(model, default=str))
    out = tmp_path / "out"
    rc = cli.main([
        "--source", "file",
        "--model", str(model_path),
        "--formats", "html",
        "--out", str(out),
        "--basename", "cli_test",
        "--report-id", "cio-rpt-cli1",
    ])
    assert rc == 0
    assert (out / "cli_test.html").exists()
    assert (out / "cli_test.instance_manifest.json").exists()
    assert (out / "cli_test.claims.json").exists()
    claims = json.loads((out / "cli_test.claims.json").read_text())
    assert claims["report_id"] == "cio-rpt-cli1"
    assert "html" in claims["files_created"]


def test_cli_legacy_positional(tmp_path: Path):
    model = _model()
    model_path = tmp_path / "legacy.json"
    model_path.write_text(json.dumps(model, default=str))
    out = tmp_path / "legacy_out"
    rc = cli.main([str(model_path), str(out)])
    assert rc == 0
    assert (out / "cio_institutional_report_v2.html").exists()


def test_manifest_hash_stable_for_same_body():
    model = _model()
    view = model["view"]
    m1 = pipe.build_instance_manifest(
        model=model, view=view, paths={}, report_id="fixed",
        generated_at="2026-08-14T20:00:00+00:00",
    )
    m2 = pipe.build_instance_manifest(
        model=model, view=view, paths={}, report_id="fixed",
        generated_at="2026-08-14T20:00:00+00:00",
    )
    assert m1["instance_hash"] == m2["instance_hash"]


def test_report_version_phase7():
    assert _model()["report_version"] == "report_v2_1.4.0"
