"""catalyst_news_sources: ONE governed search pull only when every live slot is empty.

Offline: the two live slots and the governed search are monkeypatched; nothing
here opens a socket or touches a ledger. The negative controls are the ones
that matter — a live slot that answered must mean NO search call.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import catalyst_news_sources as cns  # noqa: E402

NOW = cns._now_ts()
FRESH_TS = NOW - 3600
STALE_TS = NOW - 30 * 86400


def _row(headline: str, ts: int, source: str) -> dict:
    return cns._standardize(headline, f"https://x/{headline}", ts, source, "NVDA", 72)


@dataclass
class FakeResp:
    ok: bool = True
    reason: str = "SPILLED:searxng"
    provider: str = "searxng"
    results: list = field(default_factory=list)
    receipt: dict | None = None


class SearchSpy:
    def __init__(self, resp: FakeResp):
        self.resp = resp
        self.calls: list[str] = []

    def __call__(self, query: str, count: int = 10):
        self.calls.append(query)
        return self.resp


def _wire(monkeypatch, finviz, yahoo, resp: FakeResp) -> SearchSpy:
    spy = SearchSpy(resp)
    monkeypatch.setattr(cns, "_SOURCES", [("finviz_news", lambda t, h: finviz), ("yahoo", lambda t, h: yahoo)])
    monkeypatch.setattr(cns, "_governed_search", spy)
    return spy


def _search_results():
    return [
        {"title": "NVDA fresh headline", "url": "https://example.com/a", "age": "2 hours ago", "provider": "searxng"},
        {"title": "NVDA old headline", "url": "https://example.com/b", "age": "30 days ago", "provider": "searxng"},
        {"title": "NVDA undated", "url": "https://example.com/c", "age": "", "provider": "searxng"},
    ]


# ── negative controls: a live slot answered → no search ──────────────────────


def test_no_search_when_finviz_answers(monkeypatch):
    spy = _wire(monkeypatch, [_row("f1", FRESH_TS, "finviz")], [], FakeResp())
    receipt: dict = {}
    out = cns.fetch_catalyst_news("NVDA", receipt=receipt)
    assert [a["source"] for a in out] == ["finviz"]
    assert spy.calls == []
    assert receipt["answered_by"] == "finviz_news" and receipt["search"] is None


def test_no_search_when_yahoo_answers_after_finviz_is_empty(monkeypatch):
    spy = _wire(monkeypatch, [], [_row("y1", FRESH_TS, "yahoo_finance")], FakeResp())
    receipt: dict = {}
    out = cns.fetch_catalyst_news("NVDA", receipt=receipt)
    assert [a["source"] for a in out] == ["yahoo_finance"]
    assert spy.calls == []
    assert receipt["answered_by"] == "yahoo" and receipt["live"] == {"finviz_news": 0, "yahoo": 1}


def test_no_search_when_stale_articles_are_acceptable(monkeypatch):
    spy = _wire(monkeypatch, [_row("f-old", STALE_TS, "finviz")], [], FakeResp())
    out = cns.fetch_catalyst_news("NVDA", require_fresh=False)
    assert len(out) == 1 and spy.calls == []


# ── the backup ───────────────────────────────────────────────────────────────


def test_one_search_pull_when_every_live_slot_is_empty(monkeypatch):
    spy = _wire(monkeypatch, [], [], FakeResp(results=_search_results()))
    receipt: dict = {}
    out = cns.fetch_catalyst_news("NVDA", receipt=receipt)
    assert spy.calls == ["NVDA stock news"], "exactly one governed pull"
    assert [a["headline"] for a in out] == ["NVDA fresh headline"], "require_fresh keeps only the fresh row"
    assert out[0]["source"] == "search:searxng"
    assert out[0]["is_fresh"] is True and out[0]["ticker"] == "NVDA"
    assert receipt["answered_by"] == "search:searxng"
    assert receipt["live"] == {"finviz_news": 0, "yahoo": 0}
    assert receipt["search"]["reason"] == "SPILLED:searxng"


def test_stale_only_live_slots_also_fall_to_search(monkeypatch):
    spy = _wire(monkeypatch, [_row("f-old", STALE_TS, "finviz")], [_row("y-old", STALE_TS, "yahoo_finance")],
                FakeResp(results=_search_results()))
    out = cns.fetch_catalyst_news("NVDA")
    assert len(spy.calls) == 1 and out[0]["source"] == "search:searxng"


def test_is_fresh_is_computed_from_the_result_age_as_usual(monkeypatch):
    _wire(monkeypatch, [], [], FakeResp(provider="brave", results=_search_results()))
    out = cns.fetch_catalyst_news("NVDA", require_fresh=False)
    by = {a["headline"]: a for a in out}
    assert by["NVDA fresh headline"]["is_fresh"] is True
    assert by["NVDA old headline"]["is_fresh"] is False
    assert by["NVDA undated"]["is_fresh"] is False and by["NVDA undated"]["datetime"] == 0


def test_rows_are_labelled_by_the_provider_that_answered(monkeypatch):
    rows = [{"title": "h", "url": "https://example.com/h", "age": "1h"}]   # no per-row provider → response's
    _wire(monkeypatch, [], [], FakeResp(provider="brave", reason="OK", results=rows))
    receipt: dict = {}
    out = cns.fetch_catalyst_news("NVDA", receipt=receipt)
    assert out[0]["source"] == "search:brave" and receipt["answered_by"] == "search:brave"


def test_a_denied_search_says_so_and_returns_empty(monkeypatch):
    spy = _wire(monkeypatch, [], [], FakeResp(ok=False, reason="BUDGET_REFUSED:DAILY_EXHAUSTED", results=[],
                                              receipt={"spilled_to": None}))
    receipt: dict = {}
    assert cns.fetch_catalyst_news("NVDA", receipt=receipt) == []
    assert len(spy.calls) == 1
    assert receipt["answered_by"] is None
    assert receipt["search"]["reason"] == "BUDGET_REFUSED:DAILY_EXHAUSTED"
    assert receipt["search"]["receipt"] == {"spilled_to": None}


def test_a_search_exception_never_escapes(monkeypatch):
    def boom(query, count=10):
        raise RuntimeError("router import failed")
    monkeypatch.setattr(cns, "_SOURCES", [("finviz_news", lambda t, h: []), ("yahoo", lambda t, h: [])])
    monkeypatch.setattr(cns, "_governed_search", boom)
    receipt: dict = {}
    assert cns.fetch_catalyst_news("NVDA", receipt=receipt) == []
    assert receipt["search"]["reason"].startswith("SEARCH_ERROR:RuntimeError")


def test_governed_search_goes_through_the_router_with_spill_enabled(monkeypatch):
    """The only network path is brave_router.search — news kind, budget caller, no_spill=False."""
    from scripts.lib import brave_router as br
    seen: dict = {}

    def fake_search(query, **kw):
        seen.update(kw, query=query)
        return FakeResp(results=[])

    monkeypatch.setattr(br, "search", fake_search)
    cns._governed_search("NVDA stock news")
    assert seen["query"] == "NVDA stock news"
    assert seen["kind"] == "news"
    assert seen["caller"] == "catalyst_intelligence"
    assert seen["no_spill"] is False


# ── age parsing ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("age,expected_delta", [
    ("2 hours ago", 7200), ("1d", 86400), ("3 days ago", 3 * 86400), ("45 minutes ago", 2700),
    ("1 week ago", 604800), ("2 months ago", 2 * 2_592_000), ("just now", 0), ("yesterday", 86400),
])
def test_age_to_ts_relative(age, expected_delta):
    assert cns._age_to_ts(age, now_ts=1_000_000_000) == 1_000_000_000 - expected_delta


def test_age_to_ts_iso_and_unknown():
    assert cns._age_to_ts("2026-09-13T12:00:00Z") == 1789300800
    assert cns._age_to_ts("") == 0
    assert cns._age_to_ts("sometime") == 0
    assert cns._age_to_ts(None) == 0
