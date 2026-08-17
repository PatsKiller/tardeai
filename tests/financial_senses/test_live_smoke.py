"""Live smoke harness tests — offline (no credentials), no network in tests."""
from __future__ import annotations

from financial_senses.live_smoke import _figi_smoke, _fred_smoke, run_live_smoke


def test_fred_smoke_not_configured_without_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    assert _fred_smoke()["state"] == "NOT_CONFIGURED"


def test_figi_smoke_not_configured_without_key(monkeypatch):
    monkeypatch.delenv("OPENFIGI_API_KEY", raising=False)
    assert _figi_smoke()["state"] == "NOT_CONFIGURED"


def test_live_smoke_report_shape():
    report = run_live_smoke()
    assert report["authority"] == "READ_ONLY_ADVISORY"
    assert report["production_mutations"] == 0
    assert report["telegram_sends"] == 0
    assert report["production_db_writes"] == 0
    assert set(report.keys()) >= {"SEC", "FRED", "OpenFIGI"}
