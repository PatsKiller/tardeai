from pathlib import Path

from scripts.lib.ticker_knowledge_graph import (
    append_record,
    build_profile,
    classify_artifact,
    entity_guid,
    retrieve_context,
    seed_profiles,
)


def test_profile_and_relationship_buckets_are_ticker_first(tmp_path: Path):
    profile = build_profile("AXTI", metadata={"company": "AXT Inc.", "sector": "Semiconductors", "industry": "Semiconductor Materials", "themes": ["AI Infrastructure"]})
    linear = classify_artifact("AXTI", {"source_id": "r1", "summary": "earnings", "relationship": "linear", "catalyst": "earnings"}, profile=profile)
    vertical = classify_artifact("AXTI", {"source_id": "r2", "summary": "wafer supply", "relationship": "vertical", "related_tickers": ["TSM"], "industry": "Semiconductor Materials"}, profile=profile)
    append_record(tmp_path, linear)
    append_record(tmp_path, vertical)
    context = retrieve_context(tmp_path, "AXTI")
    assert context["linear"][0]["subject_key"] == "ticker:AXTI"
    assert context["vertical"][0]["related_tickers"] == ["TSM"]
    assert "Semiconductors" in context["linear"][0]["tags"]
    assert profile["ticker_guid"] == profile["ticker_id"]
    assert profile["sector_guid"] == entity_guid("sector", "Semiconductors")
    assert profile["relationship_guids"]
    assert linear["research_artifact_guid"] == linear["artifact_id"]
    assert linear["ticker_guid"] == profile["ticker_guid"]
    assert linear["catalyst_guids"] == [entity_guid("catalyst", "earnings")]
    assert vertical["related_ticker_guids"] == [entity_guid("ticker", "TSM")]
    assert vertical["relationship_guids"]


def test_guid_reingestion_is_stable_and_relationships_are_distinct():
    profile = build_profile("SCHG", metadata={"sector": "Large Cap Growth", "themes": ["Technology"]})
    a = classify_artifact("SCHG", {"source_id": "same", "summary": "same", "relationship": "linear"}, profile=profile)
    b = classify_artifact("SCHG", {"source_id": "same", "summary": "same", "relationship": "linear"}, profile=profile)
    lateral = classify_artifact("SCHG", {"source_id": "same", "summary": "same", "relationship": "lateral"}, profile=profile)
    assert a["research_artifact_guid"] == b["research_artifact_guid"]
    assert a["relationship_guid"] != lateral["relationship_guid"]


def test_seed_profiles_is_idempotent(tmp_path: Path):
    rows = [{"symbol": "SCHG", "memberships": ["WATCH"]}, {"symbol": "SCHD", "memberships": ["HELD"]}]
    assert seed_profiles(tmp_path, rows)["profiles_created"] == 2
    assert seed_profiles(tmp_path, rows)["profiles_created"] == 0
