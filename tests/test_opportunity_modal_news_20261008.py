"""Opportunity modal: what the company does, catalysts, latest news (operator 2026-10-08: "nothing here on what
company does or latest news, catalyst").

Readers (catalyst_record.get_symbol_news / get_symbol_catalysts, title_key), the detail payload carrying the profile
description and news without catalyst repeats, and the news-ingestion opportunity lane that gives the CIO's
top-ranked names news beyond the 60-symbol cap. Fakes only: no database, no network, no real CIO memory.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib.data_broker import catalyst_record as cr  # noqa: E402

NOW = datetime(2026, 10, 8, 15, 0, tzinfo=timezone.utc)


def _q(rows):
    calls = []

    def q(sql, params=None, fetch="all"):
        calls.append((sql, params))
        return rows
    q.calls = calls
    return q


def test_title_key_drops_publisher_suffix_and_case():
    assert cr.title_key("CEVA Following Its Leadership Reset - simplywall.st") == \
        cr.title_key("ceva following its  leadership reset")
    # a dash inside the headline that is not a short publisher tail stays
    long_tail = "Q1 results - " + "x" * 60
    assert cr.title_key(long_tail).endswith("x" * 10)


def test_news_dedupes_titles_and_limits():
    rows = [
        {"title": "Ceva upgraded - MarketBeat", "source": "google_news:MarketBeat", "source_url": "u1",
         "published_at": NOW, "sentiment": 0.4},
        {"title": "Ceva upgraded", "source": "yahoo_rss", "source_url": "u2", "published_at": NOW - timedelta(hours=1)},
        {"title": "Ceva new CEO", "source": "yahoo_rss", "source_url": "u3", "published_at": NOW - timedelta(days=2)},
        {"title": "Ceva third", "source": "yahoo_rss", "source_url": "u4", "published_at": NOW - timedelta(days=3)},
    ]
    q = _q(rows)
    out = cr.get_symbol_news(q, "ceva", days=45, limit=2)
    assert [n["url"] for n in out] == ["u1", "u3"]
    assert out[0]["published_at"].startswith("2026-10-08")
    sql, params = q.calls[0]
    assert "news_articles" in sql and params[0] == "CEVA" and params[1] == 45
    assert cr.get_symbol_news(q, "", days=45) == []


def test_catalysts_typed_dated_verified_flag():
    rows = [
        {"symbol": "AMSC", "catalyst_type": "earnings_beat", "headline": "AMSC sales beat", "confidence": 0.8,
         "source_url": "s1", "at": NOW - timedelta(days=60)},
        {"symbol": "AMSC", "catalyst_type": "earnings_beat", "headline": "AMSC sales beat - Zacks", "confidence": 0.8,
         "source_url": "s2", "at": NOW - timedelta(days=61)},
        {"symbol": "AMSC", "catalyst_type": "news_momentum", "headline": "AMSC chatter", "confidence": 0.1,
         "source_url": "s3", "at": NOW - timedelta(days=62)},
    ]
    q = _q(rows)
    out = cr.get_symbol_catalysts(q, "AMSC", days=90, limit=5)
    assert len(out) == 2
    assert out[0]["at"].startswith("2026-08-09") and out[0]["verified"] is True
    assert out[1]["verified"] is False
    assert "catalyst_type <> 'other'" in q.calls[0][0]


def test_detail_news_skips_headlines_already_shown_as_catalysts(monkeypatch):
    import api_v3_opportunities as api

    monkeypatch.setattr(api, "_catalysts", lambda s: [{"headline": "Ceva upgraded - MarketBeat"}])
    monkeypatch.setattr(api, "_news", lambda s: [{"title": "Ceva upgraded"}, {"title": "Ceva new CEO"}])
    out = api._news_and_catalysts("CEVA")
    assert [n["title"] for n in out["news"]] == ["Ceva new CEO"]
    assert len(out["catalysts"]) == 1


def test_profile_carries_description():
    src = (ROOT / "scripts/lib/data_broker/opportunity.py").read_text(encoding="utf-8")
    assert '"description": p.get("description")' in src
    det = (ROOT / "scripts/api_v3_opportunities.py").read_text(encoding="utf-8")
    assert "**_news_and_catalysts(sym)" in det


def test_news_opportunity_lane_adds_top_ranked_beyond_cap(monkeypatch):
    import news_ingestion as ni
    from lib import cio_opportunity_store as st
    from lib.data_broker import opportunity as op

    class FakeStore:
        def read_projection(self):
            return {"items": {"AOSL": {"rank": 1}, "GDS": {"rank": 2}, "NFLX": {"rank": 3}, "ZZZ": {"rank": 400},
                              "UNR": {"rank": None}}}

    monkeypatch.setattr(st, "CIOOpportunityStore", FakeStore)
    monkeypatch.setattr(op, "load_config", lambda: {"news_lane": {"enabled": True, "top_n": 25}})
    assert ni._opportunity_lane_pairs({"NFLX"}) == [("AOSL", "opportunity"), ("GDS", "opportunity")]
    monkeypatch.setattr(op, "load_config", lambda: {"news_lane": {"enabled": False, "top_n": 25}})
    assert ni._opportunity_lane_pairs(set()) == []


def test_news_opportunity_lane_never_raises(monkeypatch):
    import news_ingestion as ni
    from lib import cio_opportunity_store as st

    class Broken:
        def read_projection(self):
            raise OSError("projection missing")

    monkeypatch.setattr(st, "CIOOpportunityStore", Broken)
    assert ni._opportunity_lane_pairs(set()) == []


def test_config_and_modal_wiring():
    import yaml

    cfg = yaml.safe_load((ROOT / "config/opportunity_conviction.yaml").read_text(encoding="utf-8"))
    assert cfg["news_lane"]["enabled"] is True and cfg["news_lane"]["top_n"] > 0
    assert cfg["modal"]["news_limit"] > 0 and cfg["modal"]["catalyst_days"] >= cfg["modal"]["news_days"]
    tsx = (ROOT / "apps/command-center-v3/src/components/opportunity/OpportunityModal.tsx").read_text(encoding="utf-8")
    for tid in ("opportunity-about", "opportunity-catalysts", "opportunity-news"):
        assert f'data-testid="{tid}"' in tsx
    # the CIO summary is never cut mid-word and has a "more" toggle
    assert "lastIndexOf(' ', SUMMARY_MAX)" in tsx


def test_profile_lane_ranked_names_and_stub_retry(monkeypatch):
    import build_symbol_profiles as b
    from lib import cio_opportunity_store as st

    class FakeStore:
        def read_projection(self):
            return {"items": {"CEVA": {"rank": 6}, "AOSL": {"rank": 1}, "BRK.B": {"rank": 2}, "LOW": {"rank": 900}}}

    monkeypatch.setattr(st, "CIOOpportunityStore", FakeStore)
    assert b._cio_ranked(150) == ["AOSL", "CEVA"]
    assert b._cio_ranked(0) == []
    lane = b._profile_lane()
    assert lane["enabled"] is True and lane["stub_retry_days"] < 30 and lane["stub_retry_max"] > 0
    src = (ROOT / "scripts/build_symbol_profiles.py").read_text(encoding="utf-8")
    assert "COALESCE(source, '') <> 'finviz'" in src  # a Finviz stub is not "fresh" for 30 days
