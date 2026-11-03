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


# ── 2026-11-03 codex review: structure, producer hash, missing evidence, overflow ─────────

def _producer_hash(doc):
    """The orchestrator's own expression (portfolio_orchestrator.py:1192-1196), copied verbatim."""
    import hashlib
    tuples = sorted(
        (h.get("symbol", ""), h.get("account", ""), round(h.get("shares", 0) or 0, 4))
        for h in (doc.get("holdings") or [])
        if (h.get("market_value") or 0) > 100
    )
    return hashlib.md5(str(tuples).encode()).hexdigest()[:12]


def test_a_row_with_no_identity_or_numbers_is_unavailable(tmp_path):
    (tmp_path / "holdings.json").write_text('{"holdings":[{}]}')
    _raw_manifest(tmp_path, "94f18d5b8ced")
    r = g.guard(tmp_path, now=NOW)
    assert r["status"] == "UNAVAILABLE" and "holdings_row_missing_symbol" in r["reasons"]

    (tmp_path / "holdings.json").write_text('{"holdings":[{"symbol":"AAA"}]}')
    r = g.guard(tmp_path, now=NOW)
    assert r["status"] == "UNAVAILABLE" and "holdings_row_missing_market_value" in r["reasons"]

    (tmp_path / "holdings.json").write_text('{"holdings":[{"symbol":"AAA","market_value":1200}]}')
    r = g.guard(tmp_path, now=NOW)
    assert r["status"] == "UNAVAILABLE" and "holdings_row_missing_quantity" in r["reasons"]


def _raw_manifest(tmp_path, hash_value, *, completed_at=None):
    payload = {"status": "fresh", "completed_at": (completed_at or NOW - timedelta(minutes=5)).isoformat()}
    if hash_value is not None:
        payload["holdings_hash"] = hash_value
    (tmp_path / "_freshness.json").write_text(json.dumps(payload))


def test_integer_share_hash_matches_the_producer(tmp_path):
    # 10 (int) vs 10.0 (float) hash differently; the producer keeps the integer.
    doc = {"holdings": [{"symbol": "AAA", "account": "schwab_taxable", "shares": 10,
                         "market_value": 1200.0}], "as_of": "2026-11-03"}
    (tmp_path / "holdings.json").write_text(json.dumps(doc))
    _raw_manifest(tmp_path, _producer_hash(doc))
    r = g.guard(tmp_path, now=NOW)
    assert r["ok"] is True and r["status"] == "OK", r["reasons"]
    assert g.holdings_hash(doc) == _producer_hash(doc)


def test_missing_holdings_hash_is_stale(tmp_path):
    _store(tmp_path)
    _raw_manifest(tmp_path, None)
    r = g.guard(tmp_path, now=NOW)
    assert r["status"] == "STALE" and "freshness_manifest_missing_holdings_hash" in r["reasons"]


def test_huge_integer_shares_is_unavailable_not_a_crash(tmp_path):
    (tmp_path / "holdings.json").write_text(
        json.dumps({"holdings": [{"symbol": "AAA", "account": "x",
                                  "shares": 10 ** 400, "market_value": 1200.0}]})
    )
    _raw_manifest(tmp_path, "94f18d5b8ced")
    r = g.guard(tmp_path, now=NOW)          # must not raise OverflowError
    assert r["status"] == "UNAVAILABLE" and any("overflow" in x for x in r["reasons"])
