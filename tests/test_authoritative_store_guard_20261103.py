"""Fail-closed authoritative-store guard (2026-11-03 incident: 0-byte store rendered FRESH)."""
import json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import authoritative_store_guard as g

NOW = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)


def _store(tmp_path, rows=None, **doc_keys):
    doc = {"holdings": rows if rows is not None else [
        {"symbol": "AAA", "account": "schwab_taxable", "shares": 10, "market_value": 1200.0, "price": 120.0},
        {"symbol": "BBB", "account": "schwab_roth", "shares": 2, "market_value": 80.0, "price": 40.0},
    ], "as_of": "2026-11-03"}
    doc.update(doc_keys)
    (tmp_path / "holdings.json").write_text(json.dumps(doc))
    return doc


def _manifest(tmp_path, doc, *, status="fresh", completed_at=None, hash_value=None):
    (tmp_path / "_freshness.json").write_text(json.dumps({
        "status": status,
        "completed_at": (completed_at or NOW - timedelta(minutes=5)).isoformat(),
        "holdings_hash": hash_value if hash_value is not None else g.holdings_hash(doc),
    }))


def test_zero_byte_store_with_fresh_manifest_is_unavailable(tmp_path):
    (tmp_path / "holdings.json").write_bytes(b"")
    (tmp_path / "_freshness.json").write_text(json.dumps({"status": "fresh", "holdings_hash": "94f18d5b8ced",
                                                           "completed_at": (NOW - timedelta(minutes=5)).isoformat()}))
    r = g.guard(tmp_path, now=NOW)
    assert r["ok"] is False and r["status"] == "UNAVAILABLE" and "holdings_store_empty" in r["reasons"]
    assert g.effective_status("fresh", r) == "UNAVAILABLE"  # the old page said fresh


def test_absent_store_is_unavailable(tmp_path):
    r = g.guard(tmp_path, now=NOW)
    assert r["status"] == "UNAVAILABLE" and "holdings_store_absent" in r["reasons"]


def test_unparseable_store_is_unavailable(tmp_path):
    (tmp_path / "holdings.json").write_text("{not json")
    assert g.guard(tmp_path, now=NOW)["status"] == "UNAVAILABLE"


def test_not_an_object_or_no_positions_is_unavailable(tmp_path):
    (tmp_path / "holdings.json").write_text("[]")
    assert g.guard(tmp_path, now=NOW)["status"] == "UNAVAILABLE"
    (tmp_path / "holdings.json").write_text(json.dumps({"holdings": []}))
    assert g.guard(tmp_path, now=NOW)["status"] == "UNAVAILABLE"


def test_non_finite_market_value_is_unavailable(tmp_path):
    (tmp_path / "holdings.json").write_text('{"holdings":[{"symbol":"A","market_value":NaN}]}')
    assert g.guard(tmp_path, now=NOW)["status"] == "UNAVAILABLE"


def test_hash_mismatch_is_stale(tmp_path):
    doc = _store(tmp_path); _manifest(tmp_path, doc, hash_value="deadbeefcafe")
    r = g.guard(tmp_path, now=NOW)
    assert r["ok"] is False and r["status"] == "STALE" and "holdings_hash_mismatch" in r["reasons"]


def test_healthy_store_is_ok(tmp_path):
    doc = _store(tmp_path); _manifest(tmp_path, doc)
    r = g.guard(tmp_path, now=NOW)
    assert r["ok"] is True and r["status"] == "OK" and g.effective_status("fresh", r) == "fresh"


def test_stale_future_and_manifest_predating_data_clocks(tmp_path):
    doc = _store(tmp_path, as_of="2026-11-03")
    _manifest(tmp_path, doc, completed_at=NOW - timedelta(hours=40))
    assert "freshness_clock_too_old" in g.guard(tmp_path, now=NOW)["reasons"]
    _manifest(tmp_path, doc, completed_at=NOW + timedelta(hours=1))
    assert "freshness_clock_in_the_future" in g.guard(tmp_path, now=NOW)["reasons"]
    _manifest(tmp_path, doc, completed_at=NOW - timedelta(hours=1))
    (tmp_path / "holdings.json").write_text(json.dumps({**doc, "as_of": "2026-11-04"}))
    assert "freshness_predates_store_data" in g.guard(tmp_path, now=NOW)["reasons"]


def test_missing_manifest_is_stale_not_healthy(tmp_path):
    _store(tmp_path)
    r = g.guard(tmp_path, now=NOW)
    assert r["status"] == "STALE" and "freshness_manifest_absent_or_invalid" in r["reasons"]
