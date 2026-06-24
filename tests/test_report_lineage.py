"""Tests for report_lineage — continuity, archive, canonical exports."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import report_lineage as rl  # noqa: E402


@pytest.fixture
def lineage_env(tmp_path, monkeypatch):
    out = tmp_path / "analyst"
    hist = out / "history"
    hist.mkdir(parents=True)
    monkeypatch.setattr(rl, "REPORT_OUT", out)
    monkeypatch.setattr(rl, "HISTORY_DIR", hist)
    monkeypatch.setattr(rl, "LINEAGE_INDEX_PATH", hist / "index.json")
    return out


def test_compute_continuity_first_report():
    c = rl.compute_continuity(None, price=100, recommendation="HOLD", unrealized_pnl_pct=5, thesis_status="Still valid", fingerprint="abc")
    assert c["first_report"] is True
    assert c["generation"] == 1


def test_compute_continuity_price_delta():
    prior = {
        "meta": {
            "generated_at": "2026-06-01T00:00:00+00:00",
            "kpis": {"price": 100, "recommendation": "ADD", "unrealized_pnl_pct": -10, "thesis_status": "Still valid"},
            "generation": 1,
        }
    }
    c = rl.compute_continuity(
        prior, price=90, recommendation="HOLD", unrealized_pnl_pct=-15,
        thesis_status="At risk", fingerprint="newfp",
    )
    assert c["first_report"] is False
    assert c["generation"] == 2
    assert c["metrics"]["price_delta_pct"] == pytest.approx(-10.0)
    assert c["metrics"]["recommendation_changed"] is True
    assert "Adverse" in c["metrics"]["prior_call_assessment"]


def test_archive_and_load_prior(lineage_env):
    report = {"meta": {"symbol": "LDOS", "generated_at": "2026-06-01T00:00:00Z", "kpis": {"recommendation": "ADD"}, "generation": 1}}
    src = lineage_env / "LDOS_v1.json"
    src.write_text(json.dumps(report))
    rl.archive_report(report, report_id="LDOS_v1", report_type="symbol_holding", symbol="LDOS", json_path=src, fingerprint="fp1")
    loaded = rl.load_prior_report("LDOS", "symbol_holding")
    assert loaded is not None
    assert loaded["meta"]["symbol"] == "LDOS"


def test_publish_canonical_exports(lineage_env):
    sym = "RKLB"
    src_json = lineage_env / "RKLB_run.json"
    src_docx = lineage_env / "RKLB_run.docx"
    src_pdf = lineage_env / "RKLB_run.pdf"
    src_json.write_text("{}")
    src_docx.write_text("docx")
    src_pdf.write_text("pdf")
    urls = rl.publish_canonical_exports(sym, report_type="symbol_holding", json_path=src_json, docx_path=src_docx, pdf_path=src_pdf)
    assert urls["json"].endswith("prospectus_RKLB_latest.json")
    assert (lineage_env / "prospectus_RKLB_latest.pdf").exists()


def test_upsert_registry_reports():
    rows = [
        {"id": "old", "report_type": "symbol_holding", "symbol": "LDOS"},
        {"id": "other", "report_type": "symbol_holding", "symbol": "V"},
    ]
    entry = {"id": "new", "report_type": "symbol_holding", "symbol": "LDOS"}
    out = rl.upsert_registry_reports(rows, entry)
    assert out[0]["id"] == "new"
    assert len([r for r in out if r.get("symbol") == "LDOS"]) == 1


def test_generate_report_archives_and_canonical(tmp_path, monkeypatch):
    import reporting_engine as re

    out_dir = tmp_path / "analyst"
    hist = out_dir / "history"
    hist.mkdir(parents=True)
    reg_path = out_dir / "registry.json"
    monkeypatch.setattr(re, "REPORT_OUT", out_dir)
    monkeypatch.setattr(re, "REGISTRY_PATH", reg_path)
    monkeypatch.setattr(re, "PROSPECTUS_DIR", out_dir / "prospectus")
    monkeypatch.setattr(rl, "REPORT_OUT", out_dir)
    monkeypatch.setattr(rl, "HISTORY_DIR", hist)
    monkeypatch.setattr(rl, "LINEAGE_INDEX_PATH", hist / "index.json")

    fake_report = {
        "meta": {"symbol": "TEST", "title": "T", "generated_at": "2026-06-23T00:00:00Z", "kpis": {"price": 10, "recommendation": "BUY"}, "generation": 1},
        "sections": [{"id": "report_continuity", "content": "first"}],
        "visuals": [],
    }
    with patch("analyst_report_builder.build_report", return_value=fake_report), \
         patch("report_export.export_report") as mock_exp, \
         patch.object(re, "symbol_fingerprint", return_value="abc123"):
        def _exp(report, fmt, **kw):
            stem = kw.get("output_stem") or "prospectus_TEST_latest"
            p = out_dir / f"{stem}.{fmt}"
            p.write_text(fmt)
            return {"ok": True, "path": str(p), "url": f"/data/test.{fmt}"}
        mock_exp.side_effect = _exp
        out = re.generate_report(report_type="symbol_holding", symbol="TEST", formats=["docx", "pdf"])

    assert out["ok"]
    assert (out_dir / "prospectus_TEST_latest.pdf").exists()
    assert (out_dir / "prospectus_TEST_latest.json").exists()
    reg = re.load_registry()
    assert len(reg["reports"]) == 1
    assert reg["reports"][0]["exports"]["json"].endswith("prospectus_TEST_latest.json")
    assert reg["reports"][0]["id"] == "prospectus_TEST"