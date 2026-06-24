"""Tests for reporting_engine — registry, fingerprints, batch orchestration."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import reporting_engine as re  # noqa: E402


@pytest.fixture
def tmp_registry(tmp_path, monkeypatch):
    reg_path = tmp_path / "registry.json"
    out_dir = tmp_path / "analyst"
    prospectus_dir = out_dir / "prospectus"
    hist = out_dir / "history"
    prospectus_dir.mkdir(parents=True)
    hist.mkdir(parents=True)
    monkeypatch.setattr(re, "REGISTRY_PATH", reg_path)
    monkeypatch.setattr(re, "REPORT_OUT", out_dir)
    monkeypatch.setattr(re, "PROSPECTUS_DIR", prospectus_dir)
    import report_lineage as rl
    monkeypatch.setattr(rl, "REPORT_OUT", out_dir)
    monkeypatch.setattr(rl, "HISTORY_DIR", hist)
    monkeypatch.setattr(rl, "LINEAGE_INDEX_PATH", hist / "index.json")
    return out_dir


def test_load_save_registry_roundtrip(tmp_registry):
    reg = re.load_registry()
    assert reg["version"] == 1
    reg["reports"] = [{"id": "test_1", "symbol": "RKLB"}]
    re.save_registry(reg)
    loaded = re.load_registry()
    assert loaded["reports"][0]["symbol"] == "RKLB"
    assert "updated_at" in loaded


def test_symbol_fingerprint_stable():
    fp1 = re.symbol_fingerprint("RKLB")
    fp2 = re.symbol_fingerprint("RKLB")
    assert len(fp1) == 16
    assert fp1 == fp2


def test_eligible_holding_symbols_all_portfolio():
    rows = re.eligible_holding_symbols()
    assert isinstance(rows, list)
    symbols = [r["symbol"] for r in rows]
    assert len(symbols) == len(set(symbols)), "eligible list must be deduped by symbol"
    for row in rows:
        assert row.get("symbol")
        assert row.get("fingerprint")
    # Should include non-actionable holdings too (e.g. EXIT/HOLD) when they are in the book
    assert len(rows) >= 1


def test_apply_grok_editorial_skips_when_unavailable():
    report = {
        "meta": {"symbol": "RKLB", "kpis": {"recommendation": "BUY"}},
        "sections": [
            {"id": "executive_summary", "content": "Draft summary."},
            {"id": "recommendation", "content": "Draft rec."},
        ],
    }
    with patch("llm_lane.available", return_value=False):
        out = re.apply_grok_editorial(report)
    assert out["meta"]["grok_editorial"]["applied"] is False


def test_apply_grok_editorial_polishes_sections():
    report = {
        "meta": {"symbol": "RKLB", "kpis": {"recommendation": "BUY"}},
        "sections": [
            {"id": "executive_summary", "content": "Draft summary."},
            {"id": "recommendation", "content": "Draft rec."},
        ],
    }
    mock_llm = MagicMock()
    mock_llm.available.return_value = True
    mock_llm.generate.return_value = json.dumps({
        "executive_summary": "Polished executive summary.",
        "recommendation": "Maintain BUY with high conviction.",
        "editor_notes": "Tightened prose.",
    })
    with patch.dict(sys.modules, {"llm_lane": mock_llm}):
        out = re.apply_grok_editorial(report)
    assert out["meta"]["grok_editorial"]["applied"] is True
    exec_sec = next(s for s in out["sections"] if s["id"] == "executive_summary")
    assert exec_sec["content"] == "Polished executive summary."
    assert exec_sec.get("grok_edited") is True


def test_generate_report_registers_entry(tmp_registry):
    fake_report = {
        "meta": {"symbol": "TEST", "title": "Test Report", "generated_at": "2026-01-01T00:00:00Z", "kpis": {"price": 1, "recommendation": "BUY"}},
        "sections": [{"id": "executive_summary", "content": "x"}, {"id": "report_continuity", "content": "first"}],
        "visuals": [],
    }
    docx_p = tmp_registry / "prospectus_TEST_latest.docx"
    docx_p.write_text("d")
    with patch("analyst_report_builder.build_report", return_value=fake_report), \
         patch("report_export.export_report", return_value={"ok": True, "url": "/data/test.docx", "path": str(docx_p)}), \
         patch.object(re, "symbol_fingerprint", return_value="abc123"):
        out = re.generate_report(report_type="symbol_holding", symbol="TEST", formats=["docx"])
    assert out["ok"] is True
    reg = re.load_registry()
    assert len(reg["reports"]) == 1
    assert reg["reports"][0]["symbol"] == "TEST"
    assert reg["reports"][0]["id"] == "prospectus_TEST"
    assert reg["reports"][0]["fingerprint"] == "abc123"
    assert (tmp_registry / "prospectus_TEST_latest.json").exists()


def test_batch_skips_unchanged_fingerprint(tmp_registry):
    sym = "FAKEBUY"
    fp = "deadbeef12345678"
    reg = re.load_registry()
    reg["reports"] = [{
        "id": f"prospectus_{sym}_20260101",
        "report_type": "symbol_holding",
        "symbol": sym,
        "fingerprint": fp,
        "generated_at": re._now_iso(),
    }]
    re.save_registry(reg)

    with patch.object(re, "eligible_holding_symbols", return_value=[{
        "symbol": sym, "recommendation": "BUY", "fingerprint": fp,
        "market_value": 10000, "portfolio_pct": 2.0,
    }]), patch.object(re, "generate_report") as mock_gen:
        out = re.generate_holding_prospectus_batch(force=False, grok_edit=False, limit=5)

    mock_gen.assert_not_called()
    assert len(out["skipped"]) == 1
    assert out["skipped"][0]["symbol"] == sym


def test_prospectus_needs_refresh_stale_days():
    prev = {
        "fingerprint": "abc",
        "generated_at": "2020-01-01T00:00:00+00:00",
    }
    needs, reason = re.prospectus_needs_refresh(prev, "abc", stale_days=6)
    assert needs is True
    assert reason.startswith("stale_")


def test_batch_refreshes_when_stale(tmp_registry):
    sym = "STALE"
    reg = re.load_registry()
    reg["reports"] = [{
        "id": f"prospectus_{sym}_20200101",
        "report_type": "symbol_holding",
        "symbol": sym,
        "fingerprint": "samefp",
        "generated_at": "2020-01-01T00:00:00+00:00",
    }]
    re.save_registry(reg)

    with patch.object(re, "eligible_holding_symbols", return_value=[{
        "symbol": sym, "recommendation": "BUY", "fingerprint": "samefp",
        "market_value": 10000, "portfolio_pct": 2.0,
    }]), patch.object(re, "generate_report", return_value={
        "ok": True,
        "registry_entry": {"id": "new", "grok_edited": False},
        "exports": {},
    }) as mock_gen:
        out = re.generate_holding_prospectus_batch(
            force=False, grok_edit=False, stale_days=6, limit=5,
        )

    mock_gen.assert_called_once()
    assert len(out["generated"]) == 1
    assert out["generated"][0]["refresh_reason"].startswith("stale_")


def test_registry_list_filters():
    reg = {"reports": [
        {"id": "a", "symbol": "RKLB", "report_type": "symbol_holding"},
        {"id": "b", "symbol": "V", "report_type": "symbol_holding"},
        {"id": "c", "report_type": "daily_digest"},
    ]}
    with patch.object(re, "load_registry", return_value=reg):
        out = re.registry_list(symbol="RKLB")
    assert len(out["reports"]) == 1
    assert out["reports"][0]["symbol"] == "RKLB"