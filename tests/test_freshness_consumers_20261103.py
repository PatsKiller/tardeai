"""Freshness fail-closed across the active consumers (#2530 second block, 2026-11-03).

The guard was wired into the ops summary only; a 0-byte or corrupt holdings.json still rendered FRESH
on the portfolio monitor, the global-alerts banner and GET /api/freshness. These tests make every one
of those surfaces answer from the guard, not from the cached manifest.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import api_v2  # noqa: E402
import portfolio_server  # noqa: E402

NOW = datetime.now(timezone.utc)


def _store(tmp_path, *, holdings_rows=None, status="fresh", hash_ok=True):
    doc = {"holdings": holdings_rows if holdings_rows is not None else [
        {"symbol": "AAA", "account": "schwab_taxable", "shares": 10, "market_value": 1200.0, "price": 120.0},
    ], "as_of": NOW.date().isoformat()}
    (tmp_path / "holdings.json").write_text(json.dumps(doc))
    from lib.authoritative_store_guard import holdings_hash

    (tmp_path / "_freshness.json").write_text(json.dumps({
        "status": status,
        "completed_at": (NOW - timedelta(minutes=5)).isoformat(),
        "holdings_hash": holdings_hash(doc) if hash_ok else "deadbeefcafe",
    }))
    return tmp_path


@pytest.fixture
def broken(tmp_path, monkeypatch):
    """A FRESH manifest over a 0-byte store — the incident shape."""
    (tmp_path / "holdings.json").write_bytes(b"")
    (tmp_path / "_freshness.json").write_text(json.dumps({
        "status": "fresh", "completed_at": (NOW - timedelta(minutes=5)).isoformat(),
        "holdings_hash": "94f18d5b8ced"}))
    monkeypatch.setattr(api_v2, "STATE_DIR", tmp_path)
    return tmp_path


def test_guarded_freshness_is_unavailable_over_a_zero_byte_store(broken):
    doc = api_v2._guarded_freshness()
    assert doc["status"] == "UNAVAILABLE"
    assert "holdings_store_empty" in (doc["guard"]["reasons"] or [])


def test_global_alerts_banner_cannot_say_fresh(broken):
    out = api_v2._global_alerts()
    assert out["freshness"]["status"] == "UNAVAILABLE"


def test_portfolio_monitor_cannot_say_fresh(broken):
    out = api_v2._portfolio_monitor()
    assert "UNAVAILABLE" in json.dumps(out)


def test_api_freshness_route_cannot_say_fresh(broken):
    status, payload = portfolio_server.freshness_payload(broken / "_freshness.json")
    assert status == 200 and payload["status"] == "UNAVAILABLE"
    assert payload["guard"]["ok"] is False
    assert "could not be read" in payload["message"]


def test_a_hash_mismatch_is_stale_not_fresh(tmp_path, monkeypatch):
    _store(tmp_path, hash_ok=False)
    monkeypatch.setattr(api_v2, "STATE_DIR", tmp_path)
    assert api_v2._guarded_freshness()["status"] == "STALE"
    _status, payload = portfolio_server.freshness_payload(tmp_path / "_freshness.json")
    assert payload["status"] == "STALE"


def test_a_healthy_store_still_reports_fresh(tmp_path, monkeypatch):
    _store(tmp_path)
    monkeypatch.setattr(api_v2, "STATE_DIR", tmp_path)
    doc = api_v2._guarded_freshness()
    assert doc["status"] == "fresh" and doc["guard"]["ok"] is True
    _status, payload = portfolio_server.freshness_payload(tmp_path / "_freshness.json")
    assert payload["status"] == "fresh"
    assert api_v2._global_alerts()["freshness"]["status"] == "fresh"
