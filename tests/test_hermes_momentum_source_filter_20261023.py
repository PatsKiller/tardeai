"""WP-28 item2: synthetic ranked sources only; no search/model/secret/DB calls."""

from __future__ import annotations

import copy
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import hermes_momentum_catalyst_researcher as hr  # noqa: E402
from lib import hermes_scalp_catalyst_record as validator  # noqa: E402
import lib  # noqa: E402


def article(name="first", title="TEST announces a new contract"):
    return {
        "title": title,
        "url": f"https://example.invalid/articles/{name}",
        "content": "Synthetic fixture",
        "engine": "fixture",
        "published": "2026-10-23",
    }


@pytest.fixture(autouse=True)
def barriers(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("production/search/secret access forbidden")

    monkeypatch.setattr(hr.urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(hr, "_load_env", forbidden)
    monkeypatch.setattr(hr.time, "sleep", lambda value: None)
    monkeypatch.setattr(hr, "datetime", SimpleNamespace(now=lambda: datetime(2026, 10, 23, 12)))
    monkeypatch.setitem(sys.modules, "hermes_source_policy", SimpleNamespace(filter_search_results=lambda rows: rows))


@pytest.mark.parametrize(
    "source",
    [
        {"title": "ALL NEWS", "url": "https://example.invalid/articles/a"},
        {"title": "Latest Headlines", "url": None},
        {"title": "TEST stock news", "url": "https://example.invalid/"},
        {"title": "TEST research", "url": "https://example.invalid/markets/"},
        {"title": "TEST research", "url": "https://example.invalid/section/biotech"},
        {"title": "TEST research", "url": "https://example.invalid/tag/biotech"},
        {"title": "TEST research", "url": "https://example.invalid/news/series/all-news"},
    ],
)
def test_prefilter_reuses_exact_existing_index_verdict(source):
    assert validator.generic_index_page(source["title"], source["url"])
    assert hr.filter_article_sources([source, article()]) == [article()]


def test_valid_article_order_fields_and_error_rows_are_preserved():
    first, second = article("first"), article("second")
    rows = [{"title": "ALL NEWS"}, first, {"error": "routing refused"}, second]
    original = copy.deepcopy(rows)
    result = hr.filter_article_sources(rows)
    assert result == [first, {"error": "routing refused"}, second]
    assert result[0] is first and result[-1] is second
    assert rows == original


def ranked_with_first_article_beyond_cap():
    return [
        {"title": "ALL NEWS", "url": "https://example.invalid/markets/"},
        {"title": "Latest Headlines", "url": "https://example.invalid/news/"},
        {"title": "TEST", "url": "https://example.invalid/section/biotech"},
        article("first-valid"),
        article("second-valid"),
    ]


def test_hot_route_filters_before_cap_and_preserves_route_arguments(monkeypatch):
    calls = []

    def route(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "ok": True,
            "results": ranked_with_first_article_beyond_cap(),
            "provider": "fixture",
            "cache_hit": True,
            "decision": "CACHE",
        }

    monkeypatch.setattr(lib, "scalp_research_route", SimpleNamespace(route=route), raising=False)
    rows = hr._routed("TEST", "latest news", caller="fixture-caller", dry_run=True, priority=True)
    assert [row["url"] for row in rows] == [article("first-valid")["url"], article("second-valid")["url"]]
    assert calls == [
        (
            ("TEST", "latest news"),
            {"caller": "fixture-caller", "priority": True, "dry_run": True, "limit": hr.MAX_SOURCES_PER_TICKER},
        )
    ]
    assert rows[0]["routed"] == {"provider": "fixture", "cache_hit": True, "decision": "CACHE"}


def test_standard_route_filters_before_cap_without_changing_budget_or_rank(monkeypatch):
    calls = []

    def route_search(query, **kwargs):
        calls.append((query, kwargs))
        return {"results": ranked_with_first_article_beyond_cap()}

    monkeypatch.setattr(
        lib, "search_router", SimpleNamespace(engine_enabled=lambda: True, route_search=route_search), raising=False
    )
    candidate = {"symbol": "TEST"}
    rows = hr._routed_search("TEST", "synthetic query", candidate, "fixture-caller", "fixture-intent")
    assert [row["url"] for row in rows] == [article("first-valid")["url"], article("second-valid")["url"]]
    assert calls == [
        (
            "synthetic query",
            {
                "request_class": "scalp_research",
                "caller": "fixture-caller",
                "subject": "TEST",
                "intent": "fixture-intent",
                "categories": "news",
                "limit": hr.MAX_SOURCES_PER_TICKER,
                "cache_ttl_s": 1200,
                "candidates": [candidate],
            },
        )
    ]


def test_direct_search_filters_before_cap_with_one_existing_request(monkeypatch):
    calls = []
    monkeypatch.setattr(hr, "_hot_research_on", lambda: False)
    monkeypatch.setattr(hr, "_routed_search", lambda *a, **k: None)

    def fixture_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        return SimpleNamespace(read=lambda: json.dumps({"results": ranked_with_first_article_beyond_cap()}).encode())

    monkeypatch.setattr(hr.urllib.request, "urlopen", fixture_urlopen)
    rows = hr.search_catalyst("TEST", "latest news", dry_run=True)
    assert [row["url"] for row in rows] == [article("first-valid")["url"], article("second-valid")["url"]]
    assert len(calls) == 1 and calls[0][1] == 10


def test_provider_policy_still_filters_before_article_selection(monkeypatch):
    rejected, allowed = article("rejected"), article("allowed")
    monkeypatch.setitem(
        sys.modules,
        "hermes_source_policy",
        SimpleNamespace(filter_search_results=lambda rows: [row for row in rows if row["url"] != rejected["url"]]),
    )
    monkeypatch.setattr(
        lib,
        "search_router",
        SimpleNamespace(engine_enabled=lambda: True, route_search=lambda *a, **k: {"results": [rejected, allowed]}),
        raising=False,
    )
    assert hr._routed_search("TEST", "synthetic") == [allowed]


def test_research_ticker_skips_index_before_first_source_and_dedupes(monkeypatch):
    calls = []
    first, second = article("first"), article("second")

    def search(*args, **kwargs):
        calls.append(args)
        return [{"title": "ALL NEWS", "url": "https://example.invalid/markets/"}, first, second]

    monkeypatch.setattr(hr, "search_catalyst", search)
    record = hr.research_ticker("TEST", dry_run=True)
    assert record["catalyst_summary"] == first["title"]
    assert record["sources"] == [first, second] and record["source_count"] == 2
    assert record["research_timestamp"] == "2026-10-23T12:00:00"
    assert record["confidence"] == 0.5
    assert record["advisory_only"] and record["not_trade_signal"] and record["no_execution"]
    assert len(calls) == 3  # existing three-query ceiling; no extra retry/query added


def test_all_generic_results_produce_no_clear_catalyst(monkeypatch):
    monkeypatch.setattr(
        hr, "search_catalyst", lambda *a, **k: [{"title": "ALL NEWS", "url": "https://example.invalid/"}]
    )
    record = hr.research_ticker("TEST", dry_run=True)
    assert record["catalyst_type"] == "no_clear_catalyst"
    assert record["source_count"] == 0 and record["sources"] == [] and record["confidence"] == 0.2


def test_filter_does_not_promote_wrong_company_article_or_replace_identity_gate(monkeypatch):
    other = article("other-company", "Different Company wins a contract")
    monkeypatch.setattr(hr, "search_catalyst", lambda *a, **k: [other])
    record = hr.research_ticker("TEST", dry_run=True)
    assert record["sources"] == [other]
    assert (
        validator.verify_identity("TEST", record, ["Testlab Therapeutics Inc"])["status"]
        == validator.UNVERIFIED_IDENTITY
    )


@pytest.mark.parametrize(
    "reason,expected", [("NO_COVERAGE fixture", []), ("BUDGET_REFUSED", [{"error": "BUDGET_REFUSED"}])]
)
def test_router_empty_and_refusal_semantics_are_preserved(monkeypatch, reason, expected):
    monkeypatch.setattr(
        lib,
        "search_router",
        SimpleNamespace(
            engine_enabled=lambda: True, route_search=lambda *a, **k: {"results": [], "denied_reason": reason}
        ),
        raising=False,
    )
    assert hr._routed_search("TEST", "synthetic") == expected


def test_new_test_is_in_canonical_gate():
    gate = json.loads((ROOT / "config/ci_gates/hermes_momentum_source_filter_20261023.json").read_text())
    assert "tests/test_hermes_momentum_source_filter_20261023.py" in gate["files"]
