from datetime import datetime, timezone

from scripts.maya_intelligence_contract import (
    CONTRACT_VERSION,
    bounded_news_quality,
    domain_authority_matrix,
    normalize_evidence,
)

NOW = datetime(2026, 7, 25, 14, 0, tzinfo=timezone.utc)


def test_deterministic_value_requires_current_provenance():
    current = normalize_evidence(
        "support",
        {
            "value": 101.5,
            "provider": "portfolio.reentry.resistance.v1",
            "as_of": "2026-07-25T13:00:00+00:00",
            "provenance_ref": "cache:ABC:20260725",
            "methodology_version": "portfolio.reentry.resistance.v1",
        },
        now=NOW,
        max_age_hours=8,
    )
    assert current["state"] == "CURRENT"
    assert current["deterministic_usable"] is True
    assert current["may_override_gate"] is False

    stale = normalize_evidence(
        "support",
        {
            "value": 101.5,
            "provider": "portfolio.reentry.resistance.v1",
            "as_of": "2026-07-23T13:00:00+00:00",
            "provenance_ref": "cache:ABC:20260723",
        },
        now=NOW,
        max_age_hours=8,
    )
    assert stale["state"] == "STALE"
    assert stale["deterministic_usable"] is False


def test_missing_value_or_provenance_is_never_fabricated():
    result = normalize_evidence(
        "pe", {"provider": "finviz", "as_of": "2026-07-25T13:00:00Z"}, now=NOW
    )
    assert result["state"] == "MISSING"
    assert result["value"] is None
    assert "value" in result["missing"]
    assert "provenance_ref" in result["missing"]
    assert result["deterministic_usable"] is False


def test_analyst_consensus_is_display_only_even_when_current():
    result = normalize_evidence(
        "analyst_rating",
        {
            "value": "BUY",
            "provider": "maya_analyst_feed",
            "as_of": "2026-07-25T13:00:00Z",
            "provenance_ref": "analyst:ABC:20260725",
        },
        now=NOW,
        max_age_hours=24 * 7,
    )
    assert result["state"] == "CURRENT"
    assert result["authority"] == "display_only"
    assert result["deterministic_usable"] is False
    assert result["may_override_gate"] is False


def test_news_rating_is_bounded_explainable_and_not_trade_sentiment():
    rated = bounded_news_quality(
        source_reliability=5,
        freshness=4,
        primary_source_proximity=5,
        corroboration=4,
        materiality=3,
    )
    assert rated["contract"] == CONTRACT_VERSION
    assert rated["state"] == "RATED"
    assert rated["rating"] == 4
    assert len(rated["explanation"]) == 5
    assert "not sentiment" in rated["meaning"]
    assert rated["may_override_gate"] is False

    incomplete = bounded_news_quality(
        source_reliability=5,
        freshness=None,
        primary_source_proximity=5,
        corroboration=4,
        materiality=3,
    )
    assert incomplete["state"] == "INSUFFICIENT_EVIDENCE"
    assert incomplete["rating"] is None
    assert "freshness" in incomplete["missing_or_invalid"]


def test_matrix_covers_every_domain_and_blocks_opinion_override():
    rows = domain_authority_matrix()
    assert {row["domain"] for row in rows} == {
        "WATCH", "PROPOSAL", "DEFENSE", "SECTOR", "INDUSTRY"
    }
    fields = {row["field"] for row in rows}
    assert {
        "pe", "forward_pe", "pb", "ps", "support", "resistance",
        "catalysts", "news_quality", "analyst_rating",
        "analyst_upgrade", "analyst_downgrade",
    } <= fields
    assert all(row["may_override_deterministic_gate"] is False for row in rows)
