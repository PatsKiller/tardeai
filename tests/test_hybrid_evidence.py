from datetime import datetime, timezone

from scripts.lib.hybrid_evidence import build_refresh_request, is_fresh, normalize_hermes_row


NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


def test_promoted_fresh_hermes_row_is_admitted_with_polarity():
    row = {
        "id": 42,
        "symbol": "SCHD",
        "topic": "SCHD dividend case",
        "summary": "Dividend quality remains a supporting factor.",
        "thesis_type": "bullish",
        "status": "promoted",
        "freshness_date": "2026-08-22",
        "source_urls_json": ["https://example.com/source"],
    }
    item = normalize_hermes_row(row, now=NOW)
    assert item is not None
    assert item["polarity"] == "SUPPORTING"
    assert item["provenance"]["independence_group"] == "hermes"


def test_stale_or_unpromoted_hermes_row_is_rejected():
    base = {
        "id": 1,
        "symbol": "SCHG",
        "summary": "growth case",
        "thesis_type": "bullish",
        "freshness_date": "2026-08-01",
        "source_urls_json": ["https://example.com/source"],
    }
    assert normalize_hermes_row({**base, "status": "promoted"}, now=NOW) is None
    assert normalize_hermes_row({**base, "status": "staged", "freshness_date": "2026-08-22"}, now=NOW) is None
    assert is_fresh("2026-08-22", now=NOW)
    assert not is_fresh("2026-08-01", now=NOW)


def test_refresh_request_is_stable_and_non_authoritative():
    first = build_refresh_request("schd", gaps=["insufficient_supporting_rag", "no_approved_primary_or_news"], now=NOW)
    second = build_refresh_request("SCHD", gaps=["no_approved_primary_or_news", "insufficient_supporting_rag"], now=NOW)
    assert first["request_id"] == second["request_id"]
    assert first["trace_id"] == second["trace_id"]
    assert len(first["trace_id"].split("-")) == 5
    assert first["enqueue"] is False
    assert first["financial_action"] is False


def test_refresh_request_contains_independent_source_families():
    request = build_refresh_request("SCHG", gaps=["insufficient_contradictory_rag"])
    assert request["status"] == "PLANNED"
    assert set(("hermes", "primary", "structured", "independent_news")) <= set(request["source_families"])
