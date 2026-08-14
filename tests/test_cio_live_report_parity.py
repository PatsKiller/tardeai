"""Phases 8–9 — live report renderer + plan/report decision parity (dry).

No live network. No broker. No Telegram.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib import cio_live_report as lr  # noqa: E402
from scripts.lib.cio_decision_semantics import make_decision_id  # noqa: E402

FIXED = datetime(2026, 8, 14, 22, 0, 0, tzinfo=timezone.utc)


def _holdings_fixture() -> dict:
    """Holdings-shaped fixture (not a $100k toy book)."""
    return {
        "as_of": "2026-08-14T00:00:00+00:00",
        "portfolio_totals": {"total_value": 1_250_000.0},
        "config": {
            "accounts": {
                "schwab_taxable": {"taxable": True, "display_name": "Schwab Taxable"},
            }
        },
        "holdings": [
            {
                "symbol": "CASH",
                "is_cash": True,
                "market_value": 400_000.0,
                "quantity": 400_000.0,
                "shares": 400_000.0,
                "current_price": 1.0,
                "price": 1.0,
                "account": "schwab_taxable",
            },
            {
                "symbol": "SCHD",
                "name": "Schwab U.S. Dividend Equity ETF",
                "is_cash": False,
                "market_value": 220_000.0,
                "quantity": 2_500.0,
                "shares": 2_500.0,
                "current_price": 88.0,
                "price": 88.0,
                "account": "schwab_taxable",
            },
            {
                "symbol": "V",
                "name": "Visa Inc",
                "is_cash": False,
                "market_value": 120_000.0,
                "quantity": 400.0,
                "shares": 400.0,
                "current_price": 300.0,
                "price": 300.0,
                "account": "schwab_taxable",
            },
        ],
    }


def _decision(symbol="SCHD", stance="TRIM", delta=-14800.0, why="concentration fire"):
    return {
        "decision_id": make_decision_id(symbol, stance, delta, why),
        "symbol": symbol,
        "stance": stance.title() if stance.isupper() else stance,
        "stance_code": stance,
        "cio_stance": stance,
        "recommended_delta_usd": delta,
        "why_now": why,
        "current_value_usd": 220_000.0,
        "current_weight_pct": 17.6,
    }


def test_holdings_shaped_fixture_is_not_synthetic():
    doc = _holdings_fixture()
    assert lr.is_holdings_shaped(doc) is True
    assert lr.is_synthetic_book(doc) is False


def test_toy_100k_book_is_synthetic():
    toy = {"portfolio_value": 100_000.0, "cash": 20_000.0, "positions": []}
    assert lr.is_holdings_shaped(toy) is False
    assert lr.is_synthetic_book(toy) is True


def test_render_live_report_synthetic_false_for_holdings_fixture(tmp_path, monkeypatch):
    det = lr.detect_renderers()
    det = {
        **det,
        "pdf": {
            **(det.get("pdf") or {}),
            "available": False,
            "status": "missing",
            "ok": False,
            "reason": "No PDF renderer (weasyprint/wkhtmltopdf/chromium)",
            "engines": [],
        },
    }
    monkeypatch.setattr(lr, "detect_renderers", lambda: det)

    result = lr.render_live_report(
        _holdings_fixture(),
        out_dir=tmp_path,
        basename="dry",
        now=FIXED,
        attach_live_queue=False,
        allow_ms_assemble=False,
        source_sha="testsha",
    )
    assert result["synthetic"] is False
    assert result["live"] is True
    assert result["html"]
    assert Path(result["html"]).is_file()
    assert result["source_sha"] == "testsha"
    # Live book dollars — not a $100k toy
    assert result["portfolio_value_usd"] != 100_000.0
    assert float(result["portfolio_value_usd"] or 0) > 100_000.0


def test_missing_pdf_renderer_status_is_missing_not_ok(tmp_path, monkeypatch):
    det = lr.detect_renderers()
    det = {
        **det,
        "pdf": {
            "available": False,
            "status": "missing",
            "ok": False,
            "commands": {},
            "weasyprint_python": False,
            "engines": [],
            "reason": "No PDF renderer (weasyprint/wkhtmltopdf/chromium)",
        },
    }
    monkeypatch.setattr(lr, "detect_renderers", lambda: det)

    result = lr.render_live_report(
        _holdings_fixture(),
        out_dir=tmp_path,
        basename="nopdf",
        now=FIXED,
        attach_live_queue=False,
        allow_ms_assemble=False,
        source_sha="testsha",
    )
    pdf = result["formats"]["pdf"]
    assert pdf["status"] == "missing"
    assert pdf["ok"] is not True
    assert result["pdf"] is None
    assert result.get("production_formats_ok") is not True


def test_docx_created_when_python_docx_present(tmp_path, monkeypatch):
    pytest.importorskip("docx")
    det = lr.detect_renderers()
    assert det["docx"]["available"] is True
    det = {
        **det,
        "pdf": {
            **(det.get("pdf") or {}),
            "available": False,
            "status": "missing",
            "ok": False,
            "engines": [],
            "reason": "No PDF renderer (weasyprint/wkhtmltopdf/chromium)",
        },
    }
    monkeypatch.setattr(lr, "detect_renderers", lambda: det)
    result = lr.render_live_report(
        _holdings_fixture(),
        out_dir=tmp_path,
        basename="withdocx",
        now=FIXED,
        attach_live_queue=False,
        allow_ms_assemble=False,
        source_sha="testsha",
    )
    assert result["formats"]["docx"]["status"] == "ok"
    assert result["formats"]["docx"]["ok"] is True
    assert result["docx"]
    assert Path(result["docx"]).is_file()
    assert Path(result["docx"]).stat().st_size > 0


def test_parity_matching_surfaces_ok():
    row = _decision()
    plan = {"position_decisions": [row]}
    report = {"part_a": {"decisions_now": [dict(row)]}}
    r = lr.compare_plan_report_decisions(plan, report)
    assert r["ok"] is True
    assert r["compared"] == 1
    assert r["mismatches"] == []


def test_parity_delta_mismatch_fails():
    row = _decision(delta=-14800.0)
    plan = {"position_decisions": [row]}
    report_row = dict(row)
    report_row["recommended_delta_usd"] = -500.0
    report = {"part_a": {"decisions_now": [report_row]}}
    r = lr.compare_plan_report_decisions(plan, report)
    assert r["ok"] is False
    assert any(m["field"] == "recommended_delta_usd" for m in r["mismatches"])


def test_parity_against_built_report():
    """Same fixture plan → report model: published decisions match the plan."""
    plan = lr.build_capital_plan_from_live_sources(
        _holdings_fixture(), now=FIXED, attach_live_queue=False,
    )
    model = lr.build_report_from_live_sources(
        _holdings_fixture(),
        capital_plan=plan,
        now=FIXED,
        source_sha="parity",
        attach_live_queue=False,
        allow_ms_assemble=False,
    )
    r = lr.compare_plan_report_decisions(plan, model)
    assert r["ok"] is True
    assert r["report_count"] >= 0


def test_refuses_synthetic_100k_book(tmp_path):
    result = lr.render_live_report(
        {"portfolio_value": 100_000.0, "cash": 25_000.0},
        out_dir=tmp_path,
        write_files=False,
    )
    assert result["synthetic"] is True
    assert result["live"] is False
    assert result["ok"] is False
    assert result["html"] is None


def test_detect_renderers_honest_pdf_shape():
    det = lr.detect_renderers()
    assert "pdf" in det and "docx" in det and "html" in det
    pdf = det["pdf"]
    assert pdf["status"] in {"ok", "missing"}
    if not pdf["available"]:
        assert pdf["ok"] is False
        assert pdf["status"] == "missing"
        assert pdf["ok"] is not True
