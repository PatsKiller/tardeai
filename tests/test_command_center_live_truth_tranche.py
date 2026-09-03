"""Deterministic regression coverage for the final live-truth tranche."""

import json
from datetime import datetime, timezone
from pathlib import Path


def test_alpaca_rows_share_canonical_observation_metadata():
    from scripts.alpaca_live_read_sync import _account_to_cash_row, _positions_to_holdings_rows

    observed = datetime(2026, 9, 3, 13, 0, tzinfo=timezone.utc)
    position = _positions_to_holdings_rows("alpaca_taxable_live", [{"symbol": "ABC", "qty": "2", "current_price": "10"}], observed_at=observed)[0]
    cash = _account_to_cash_row("alpaca_taxable_live", {"cash": "500"}, observed_at=observed)[0]
    for row in (position, cash):
        assert row["source_identity"] == "alpaca:alpaca_taxable_live"
        assert row["account_scope"] == "alpaca_taxable_live"
        assert row["provider_observed_at"] == "2026-09-03T13:00:00Z"
        assert row["received_at"] == row["normalized_at"]
        assert row["business_date"] == "2026-09-03"
        assert row["quality_state"] == "VALID"
        assert row["entitlement_state"] == "READ_ONLY"
        assert row["observation"]["source_identity"] == row["source_identity"]


def test_finviz_endpoint_uses_governed_cache_and_distinguishes_missing_symbol(tmp_path, monkeypatch):
    import scripts.api_v2 as api

    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    (state / "ticker_enrichment_cache.json").write_text(json.dumps({"ABC": {"company": "Example", "rsi": 55}}))
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    api._FINVIZ_ENRICH_CACHE.update({"mtime": 0, "data": {}})
    present = api._finviz_enrichment({"symbol": ["ABC"]})
    absent = api._finviz_enrichment({"symbol": ["MISSING"]})
    assert present["ok"] is True and present["found"] is True and present["cache_available"] is True
    assert absent == {"ok": True, "symbol": "MISSING", "found": False, "cache_available": True, "groups": [], "note": "No Finviz enrichment cached."}


def test_finviz_endpoint_fails_closed_for_missing_or_malformed_cache(tmp_path, monkeypatch):
    import scripts.api_v2 as api

    state = tmp_path / "data" / "portfolios" / "state"
    state.mkdir(parents=True)
    monkeypatch.setattr(api, "PROJECT_ROOT", tmp_path)
    api._FINVIZ_ENRICH_CACHE.update({"mtime": 0, "data": {}})
    missing = api._finviz_enrichment({"symbol": ["ABC"]})
    assert missing["ok"] is False and "cache unavailable" in missing["error"]
    (state / "ticker_enrichment_cache.json").write_text("[]")
    api._FINVIZ_ENRICH_CACHE.update({"mtime": 0, "data": {}})
    malformed = api._finviz_enrichment({"symbol": ["ABC"]})
    assert malformed["ok"] is False and "cache unavailable" in malformed["error"]


def test_health_probe_has_no_fixed_rklb_symbol():
    from scripts.cc_v3_site_health_probe import ENDPOINTS

    assert not any("RKLB" in path for path in ENDPOINTS)
