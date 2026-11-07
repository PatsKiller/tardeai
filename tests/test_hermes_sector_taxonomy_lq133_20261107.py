"""ANCHOR: HERMES_SECTOR_TAXONOMY_LQ133_20261107. LQ-20261107-133 — the discovery
worker pool flagged sectors we already cover as coverage gaps, and a re-sighted
candidate's summary disagreed with its own metadata.

Live observations from the 2026-11-07 audit (read-only):

* ``consumer_discretionary`` (190 mentions / 28 sources in the last 168 h) and
  ``consumer_staples`` (91 / 16) were written as MISSING_SECTOR gaps although
  ``symbol_profiles`` holds Consumer Cyclical 298 / Consumer Defensive 131 — GICS
  and Yahoo name the same two sectors differently and nothing mapped between them.
* ``hermes_discovery_candidates`` id 3713: ``summary`` says "recurred 333x across
  12 distinct sources", ``meta_json`` says recurrence_count 24 / source_count 6.
  ``upsert_candidate`` rewrites the summary on every bump but merges meta with
  ``setdefault``, so the counters freeze at the first sighting.

Hermetic: fake rows / fakes for the DB seams; no database, no network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.hermes_discovery import industry_novelty as N  # noqa: E402
from lib.hermes_discovery import inbox, white_space  # noqa: E402

ANCHOR = "HERMES_SECTOR_TAXONOMY_LQ133_20261107"

YAHOO_SECTORS = {"consumer cyclical", "consumer defensive", "financial services", "technology"}


def _obs(value, n=10, n_sources=4, sources=("a", "b", "c", "d")):
    return {"entity_value": value, "n": n, "n_sources": n_sources,
            "sources": list(sources), "sample": "sample"}


# ── the taxonomy: one sector, two names ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("news_name,profile_name", [
    ("consumer_discretionary", "consumer cyclical"),
    ("consumer_staples", "consumer defensive"),
    ("financials", "financial services"),
    ("information technology", "technology"),
])
def test_a_sector_we_cover_under_its_other_name_is_not_a_gap(news_name, profile_name):
    skips: dict = {}
    novel = N.compute_novel([_obs(news_name)], {profile_name}, min_mentions=3, min_sources=2,
                            skipped=skips)
    assert novel == [] and skips == {"already_covered": 1}


def test_a_genuine_sub_industry_gap_is_still_flagged():
    novel = N.compute_novel([_obs("retail", n=47, n_sources=11)], {"consumer cyclical"},
                            min_mentions=3, min_sources=2)
    assert [g["sector"] for g in novel] == ["retail"]


def test_an_unmapped_sector_keeps_its_own_identity():
    novel = N.compute_novel([_obs("biotechnology", n=128, n_sources=16)], YAHOO_SECTORS,
                            min_mentions=3, min_sources=2)
    assert [g["sector"] for g in novel] == ["biotechnology"]


def test_the_synonym_map_is_a_config_document(tmp_path):
    path = tmp_path / "syn.json"
    path.write_text(json.dumps({"schema": "SectorSynonyms@v1",
                                "groups": [["consumer discretionary", "consumer cyclical"]]}))
    syn = N.load_sector_synonyms(path)
    assert syn["consumer discretionary"] == {"consumer discretionary", "consumer cyclical"}
    assert syn["consumer cyclical"] == syn["consumer discretionary"]


def test_a_missing_or_broken_map_hides_nothing(tmp_path):
    assert N.load_sector_synonyms(tmp_path / "absent.json") == {}
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    assert N.load_sector_synonyms(broken) == {}


def test_the_shipped_map_is_what_the_lane_uses():
    syn = N.load_sector_synonyms()
    assert "consumer discretionary" in syn and "consumer cyclical" in syn["consumer discretionary"]
    assert "consumer staples" in syn and "consumer defensive" in syn["consumer staples"]


def test_the_covered_set_expands_through_the_synonyms(monkeypatch):
    monkeypatch.setattr(N, "_table_exists", lambda table: True)
    monkeypatch.setattr(N, "_rows", lambda sql, params=None: [{"sector": "Consumer Cyclical"}])
    monkeypatch.setattr(N.entity_spikes, "covered_keys", lambda notes=None: set())
    covered = N.covered_sector_keys()
    assert "consumer cyclical" in covered and "consumer discretionary" in covered


# ── summary and metadata must describe the same sighting ──────────────────────────────────────────────────────

def test_a_refreshed_key_takes_the_latest_value_and_the_rest_stay_sticky():
    merged = inbox._bump_meta(
        {"recurrence_count": 24, "source_count": 6, "research_domain": "equities"},
        {"recurrence_count": 333, "source_count": 12, "why_missing": "fresh"},
        ["recurrence_count", "source_count", "why_missing"])
    assert merged["recurrence_count"] == 333 and merged["source_count"] == 12
    assert merged["why_missing"] == "fresh"
    assert merged["research_domain"] == "equities"     # enrichment stays sticky


def test_without_a_refresh_the_old_freeze_is_preserved():
    merged = inbox._bump_meta({"recurrence_count": 24}, {"recurrence_count": 333}, None)
    assert merged["recurrence_count"] == 24


def test_an_absent_key_is_never_invented_by_the_refresh():
    merged = inbox._bump_meta({}, {}, ["recurrence_count"])
    assert "recurrence_count" not in merged


def test_the_novelty_payload_names_the_counters_that_go_stale():
    novel = N.compute_novel([_obs("retail", n=43, n_sources=11)], YAHOO_SECTORS,
                            min_mentions=3, min_sources=2)
    p = N.build_payloads(novel, limit=5)[0]
    assert set(p["meta_refresh_keys"]) == {"recurrence_count", "source_count",
                                           "demand_sources", "why_missing"}
    assert "43x across 11" in p["summary"]


def test_the_white_space_payload_names_them_too():
    gaps = [{"subject": "retail", "recurrence": 43, "sources": ["a", "b"],
             "streams": ["discovery_recurrence"], "samples": [], "entity_types": ["sector"]}]
    p = white_space.build_gap_payloads(gaps, "coverage", limit=5)[0]
    assert "recurrence_count" in p["meta_refresh_keys"]
    assert "source_count" in p["meta_refresh_keys"]


def test_run_discovery_hands_the_refresh_to_the_inbox(monkeypatch):
    monkeypatch.setattr(N, "load_novelty_config", lambda path=None: {
        "industry_novelty_enabled": True, "industry_novelty_window_hours": 168,
        "industry_novelty_min_sources": 2, "industry_novelty_min_mentions": 3,
        "industry_novelty_max_per_day": 5})
    monkeypatch.setattr(N, "collect_observed_sectors", lambda h, notes=None: [_obs("retail", n=43, n_sources=11)])
    monkeypatch.setattr(N, "covered_sector_keys", lambda *a, **k: set())
    monkeypatch.setattr(N, "_payload_domain", lambda payload: "equities")
    seen: list[dict] = []

    def fake_upsert(**kw):
        seen.append(kw)
        return {"id": 1, "status": "DISCOVERED", "seen_count": 1}

    monkeypatch.setattr(inbox, "upsert_candidate", fake_upsert)
    report = N.run_discovery()
    assert report["upserted"] == 1 and len(seen) == 1
    assert seen[0]["meta_refresh_keys"] == ("recurrence_count", "source_count",
                                            "demand_sources", "why_missing")


def test_the_lane_never_imports_broker_or_execution_code():
    src = (ROOT / "scripts" / "lib" / "hermes_discovery" / "industry_novelty.py").read_text()
    for banned in ("place_order", "import broker", "from broker", "alpaca", "ib_insync"):
        assert banned not in src
