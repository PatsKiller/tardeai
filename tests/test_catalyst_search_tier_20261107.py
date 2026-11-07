"""Item 25 (2026-11-07): the catalyst search tier must answer, and a dead tier must not read as a quiet market.

The lane `catalyst-momentum-engine-overnight` staged no `momentum_catalyst` row after 2026-10-29 while its runs
kept reporting `candidates: 4, catalyst_confirmed: 0, search_errors: 0`. Measured against the live SearXNG on
2026-11-07: the old query (`categories=news` + `time_range=day` + `engines=google news,bing news,duckduckgo`)
returns 0 results for every candidate, `time_range=day` returns 0 for every category, and the engine allowlist
named engines that were suspended plus `duckduckgo`, which is not a news engine.

Hermetic: no network, no DB, no credential, no real symbol (TEST is synthetic). Every assertion below fails on
the old single-shot query.
"""
from __future__ import annotations

import json
import sys
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import hermes_momentum_catalyst_researcher as hr  # noqa: E402

SEARCH = hr.SEARXNG_URL
CONFIG = SEARCH.rsplit("/", 1)[0] + "/config"


class _Resp:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body


def _result(symbol="TEST", name="first"):
    return {"title": f"{symbol} announces a new contract", "url": f"https://example.invalid/{name}",
            "content": "Synthetic fixture", "engine": "fixture", "publishedDate": "2026-11-07"}


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    """No routing engine, no .env read, no cached engine count carried between tests."""
    monkeypatch.setattr(hr, "_hot_research_on", lambda: False)
    monkeypatch.setattr(hr, "_routed_search", lambda *a, **k: None)
    monkeypatch.setattr(hr, "_load_env", lambda: None)
    monkeypatch.setattr(hr, "_ENGINE_COUNT", None, raising=False)
    monkeypatch.setitem(sys.modules, "hermes_source_policy",
                        type(sys)("hermes_source_policy"))


def _fake_searxng(monkeypatch, tiers, *, engines=85, news_raises=False):
    """Answer each category from ``tiers`` (``news`` / ``general``); record every request's params."""
    seen = []

    def urlopen(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if url == CONFIG:
            return _Resp({"engines": [{"name": f"e{i}", "enabled": True} for i in range(engines)]})
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        seen.append(params)
        cats = params.get("categories") or "general"
        if cats == "news" and news_raises:
            raise TimeoutError("news tier timed out")
        payload = tiers.get(cats, {})
        return _Resp({"results": payload.get("results", []),
                      "unresponsive_engines": payload.get("unresponsive", [])})

    monkeypatch.setattr(hr.urllib.request, "urlopen", urlopen)
    return seen


def test_the_query_no_longer_asks_for_a_day_window_or_an_engine_allowlist(monkeypatch):
    """The three old parameters are what made every candidate answer nothing."""
    seen = _fake_searxng(monkeypatch, {"news": {"results": [_result()], "unresponsive": []}})
    hr.search_catalyst("TEST", "catalyst news swing")
    assert seen, "no SearXNG request was made"
    first = seen[0]
    assert "time_range" not in first, "the day filter returns 0 results for every category on this instance"
    assert "engines" not in first, "the allowlist named suspended engines and a non-news engine"
    assert first.get("categories") == "news", "the news tier is still asked first"


def test_an_empty_news_tier_falls_back_to_the_general_tier(monkeypatch):
    seen = _fake_searxng(monkeypatch, {
        "news": {"results": [], "unresponsive": ["google news", "brave.news", "bing news"]},
        "general": {"results": [_result(name="a"), _result(name="b")], "unresponsive": ["yep"]},
    })
    out = hr.search_catalyst("TEST", "catalyst news swing")
    assert [r["url"] for r in out] == ["https://example.invalid/a", "https://example.invalid/b"]
    assert len(seen) == 2, "the fallback must be one extra request, not a retry loop"
    assert "categories" not in seen[1], "the general tier is the instance's whole engine set"


def test_a_news_tier_answer_never_costs_a_second_request(monkeypatch):
    seen = _fake_searxng(monkeypatch, {"news": {"results": [_result()], "unresponsive": []}})
    out = hr.search_catalyst("TEST", "catalyst news swing")
    assert len(out) == 1 and len(seen) == 1
    assert out[0]["title"].startswith("TEST announces")
    assert out[0]["published"] == "2026-11-07"


def test_a_news_tier_that_answers_nothing_with_no_failed_engine_is_honest_and_costs_one_request(monkeypatch):
    """`{"results": []}` with no unresponsive engines is "nothing today", not a tier failure (the 2026-10-10
    legacy-path contract: one request, empty answer)."""
    seen = _fake_searxng(monkeypatch, {"news": {"results": [], "unresponsive": []}})
    assert hr.search_catalyst("TEST", "catalyst news swing") == []
    assert len(seen) == 1 and seen[0].get("categories") == "news"


def test_nothing_from_either_tier_with_the_whole_instance_down_is_an_error(monkeypatch):
    """Old behaviour: an empty list, indistinguishable from "no catalyst today" -> 0 staged, no error."""
    _fake_searxng(monkeypatch, {
        "news": {"results": [], "unresponsive": ["google news", "bing news", "brave.news"]},
        "general": {"results": [], "unresponsive": ["a", "b", "c"]},
    }, engines=3)
    out = hr.search_catalyst("TEST", "catalyst news swing")
    assert len(out) == 1 and "no_results_across_tiers" in out[0]["error"]


def test_nothing_from_either_tier_while_engines_answered_is_an_honest_empty(monkeypatch):
    """One chronic engine error must not turn a genuinely quiet ticker into a lane failure."""
    _fake_searxng(monkeypatch, {
        "news": {"results": [], "unresponsive": ["google news"]},
        "general": {"results": [], "unresponsive": ["yep"]},
    }, engines=85)
    assert hr.search_catalyst("TEST", "catalyst news swing") == []


def test_a_failed_news_request_still_asks_the_general_tier(monkeypatch):
    seen = _fake_searxng(monkeypatch, {"general": {"results": [_result(name="g")], "unresponsive": []}},
                         news_raises=True)
    out = hr.search_catalyst("TEST", "catalyst news swing")
    assert [r["url"] for r in out] == ["https://example.invalid/g"]
    assert [s.get("categories") for s in seen] == ["news", None], "news failed, then the general tier answered"


def test_a_failed_news_request_with_nothing_else_is_an_error(monkeypatch):
    _fake_searxng(monkeypatch, {"general": {"results": [], "unresponsive": []}}, news_raises=True)
    out = hr.search_catalyst("TEST", "catalyst news swing")
    assert len(out) == 1 and "timed out" in out[0]["error"]


def test_an_unreadable_config_never_invents_a_dead_tier(monkeypatch):
    """No /config -> the dead-tier verdict is unavailable; the answer stays an honest empty."""
    def urlopen(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if url == CONFIG:
            raise OSError("config unavailable")
        cats = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query)).get("categories") or "general"
        return _Resp({"results": [], "unresponsive": ["a", "b", "c", "d"] if cats == "general" else []})

    monkeypatch.setattr(hr.urllib.request, "urlopen", urlopen)
    assert hr.search_catalyst("TEST", "catalyst news swing") == []
