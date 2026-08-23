from pathlib import Path

from scripts.lib.ticker_knowledge_graph import (
    append_record,
    build_profile,
    classify_artifact,
    retrieve_context,
    seed_profiles,
)


def test_profile_and_relationship_buckets_are_ticker_first(tmp_path: Path):
    profile = build_profile("AXTI", metadata={"sector": "Semiconductors", "themes": ["AI Infrastructure"]})
    linear = classify_artifact("AXTI", {"source_id": "r1", "summary": "earnings", "relationship": "linear"}, profile=profile)
    vertical = classify_artifact("AXTI", {"source_id": "r2", "summary": "wafer supply", "relationship": "vertical", "related_tickers": ["TSM"]}, profile=profile)
    append_record(tmp_path, linear)
    append_record(tmp_path, vertical)
    context = retrieve_context(tmp_path, "AXTI")
    assert context["linear"][0]["subject_key"] == "ticker:AXTI"
    assert context["vertical"][0]["related_tickers"] == ["TSM"]
    assert "Semiconductors" in context["linear"][0]["tags"]


def test_seed_profiles_is_idempotent(tmp_path: Path):
    rows = [{"symbol": "SCHG", "memberships": ["WATCH"]}, {"symbol": "SCHD", "memberships": ["HELD"]}]
    assert seed_profiles(tmp_path, rows)["profiles_created"] == 2
    assert seed_profiles(tmp_path, rows)["profiles_created"] == 0
