"""ANCHOR: HERMES_PAGE_MEMORY_20261025 — batch 36: Hermes page memory + leftovers.

* GET /api/v2/hermes/pipeline-quality?limit=N reads N rows (twice: newest + newest open) and two counts in
  Postgres instead of all ~31.6k findings (15.7 MB of JSON, ~255 MB of RSS growth per request). Regression test on
  peak allocation with a synthetic 30k-row store.
* hermes_source_registry._norm is memoised (bounded): /api/v2/hermes/sources went from ~20 s to ~0.6 s.
* /api/v2/watch-directives honours offset/limit (directives window + pagination; other fields unchanged).
* portfolio_server.py: every sys.path insert on a request path is guarded.
Hermetic: synthetic rows and fakes only — no DB, no network, no live state.
"""

from __future__ import annotations

import re
import sys
import tracemalloc
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import hermes_source_registry as hsr  # noqa: E402


@pytest.fixture(scope="module")
def api_v2():
    import scripts.api_v2 as mod

    return mod


def _store(n):
    statuses = ("open", "resolved", "OPEN", "closed", None, "archived", "new")
    return [
        {"id": i, "hermes_agent_name": "agent", "finding_type": f"type_{i % 7}", "severity": ("critical", "warning", "info")[i % 3],
         "description": "x" * 300, "evidence_json": {"k": "v" * 200, "i": i}, "recommended_action": "review",
         "status": statuses[i % len(statuses)], "created_at": f"2026-10-{1 + (i % 25):02d}T00:00:00Z"}
        for i in range(n)
    ]


class _FakeFindingsDb:
    """Answers the three pipeline-quality queries like Postgres would (rows newest-first)."""

    closed = {"resolved", "closed", "archived"}

    def __init__(self, rows):
        self.rows = sorted(rows, key=lambda r: r["created_at"], reverse=True)
        self.sql: list[str] = []

    def __call__(self, sql, params=None, fetch="all"):
        self.sql.append(" ".join(sql.split()))
        is_open = lambda r: str(r["status"] or "").lower() not in self.closed  # noqa: E731
        if "count(*)" in sql:
            return {"total": len(self.rows), "open_count": sum(1 for r in self.rows if is_open(r))}
        if "LIMIT" not in sql:
            return [dict(r) for r in self.rows]
        limit = params[-1]
        src = [r for r in self.rows if is_open(r)] if "<> ALL" in sql else self.rows
        return [dict(r) for r in src[:limit]]


def test_pipeline_quality_limit_matches_full_list(api_v2, monkeypatch):
    db = _FakeFindingsDb(_store(500))
    monkeypatch.setattr(api_v2, "_db_query", db)
    full = api_v2._hermes_pipeline_quality(None)
    page = api_v2._hermes_pipeline_quality({"limit": ["10"]})
    is_open = lambda f: str(f.get("status") or "").lower() not in ("resolved", "closed", "archived")  # noqa: E731
    assert page["findings"] == full["findings"][:10]
    assert page["open_findings"] == [f for f in full["findings"] if is_open(f)][:10]
    assert page["total"] == full["total"] == 500
    assert page["open_count"] == sum(1 for f in full["findings"] if is_open(f))
    assert page["advisory_notice"] == full["advisory_notice"]
    assert all("LIMIT" in s or "count(*)" in s for s in db.sql[-3:])  # the limited path never reads every row


def test_pipeline_quality_limited_peak_allocation(api_v2, monkeypatch):
    """Peak-allocation regression: 30k synthetic findings. The full list costs tens of MB; ?limit=10 stays small."""
    db = _FakeFindingsDb(_store(30_000))
    monkeypatch.setattr(api_v2, "_db_query", db)
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        api_v2._hermes_pipeline_quality({"limit": "10"})
        limited_peak = tracemalloc.get_traced_memory()[1] - base
        tracemalloc.reset_peak()
        base = tracemalloc.get_traced_memory()[0]
        api_v2._hermes_pipeline_quality(None)
        full_peak = tracemalloc.get_traced_memory()[1] - base
    finally:
        tracemalloc.stop()
    assert limited_peak < 2_000_000, limited_peak  # the fake's own sort/filter dominates; well under 2 MB
    assert full_peak > 10 * limited_peak


def test_pipeline_quality_limit_is_bounded(api_v2, monkeypatch):
    db = _FakeFindingsDb(_store(50))
    monkeypatch.setattr(api_v2, "_db_query", db)
    assert api_v2._hermes_pipeline_quality({"limit": "999999"})["limit"] == 200
    assert api_v2._hermes_pipeline_quality({"limit": "abc"})["limit"] == 10
    assert api_v2._hermes_pipeline_quality({"limit": ""})["total"] == 50 and "open_findings" not in api_v2._hermes_pipeline_quality({})


def _reference_norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _reference_linked(news_name, web_by_name):
    if news_name in hsr.KNOWN_NEWS_WEB:
        dom = hsr.KNOWN_NEWS_WEB[news_name]
        if dom == "hermes":
            return None
        if dom in web_by_name:
            return dom
    label = hsr.news_label(news_name)
    if label in hsr.KNOWN_NEWS_WEB:
        dom = hsr.KNOWN_NEWS_WEB[label]
        if dom in web_by_name:
            return dom
    nlabel = _reference_norm(label)
    for dom in web_by_name:
        if _reference_norm(dom) == nlabel or _reference_norm(dom).startswith(nlabel) or nlabel in _reference_norm(dom):
            return dom
    slug = re.sub(r"[^a-z0-9]", "", label.lower())
    for suffix in (".com", ".co.uk", ".io"):
        guess = f"{slug}{suffix}" if not slug.endswith(suffix.replace(".", "")) else slug
        if guess in web_by_name:
            return guess
    return None


def test_linked_web_domain_memoised_and_unchanged():
    assert hsr._norm.cache_info().maxsize == 8192  # bounded
    web = {f"pub{i}.example.com": {} for i in range(400)} | {"Alpha-News.io": {}, "fool.com": {}}
    names = [f"google_news:Pub {i}" for i in range(0, 800, 3)] + ["motley_fool", "hermes", "alpha_news", "nothing here"]
    hsr._norm.cache_clear()
    for n in names:
        assert hsr.linked_web_domain(n, web) == _reference_linked(n, web), n
    info = hsr._norm.cache_info()
    assert info.hits > 10 * info.misses


def test_watch_directives_honours_offset_and_limit(api_v2, monkeypatch):
    body = {"directive_count": 120, "directives": [{"id": i} for i in range(120)], "desk_suggestions": [{"hit_id": 1}],
            "recent_hits": [{"x": 1}]}
    monkeypatch.setattr(api_v2, "_watch_directives_all", lambda q=None: dict(body))
    assert api_v2._watch_directives({}) == body  # no limit: unchanged
    page = api_v2._watch_directives({"offset": "100", "limit": "50"})
    assert [d["id"] for d in page["directives"]] == list(range(100, 120))
    assert page["pagination"] == {"offset": 100, "limit": 50, "total": 120, "returned": 20, "next_offset": None, "has_more": False}
    first = api_v2._watch_directives({"offset": ["0"], "limit": ["50"]})
    assert first["pagination"]["next_offset"] == 50 and first["pagination"]["has_more"] is True
    assert {k: v for k, v in first.items() if k not in ("directives", "pagination")} == {
        k: v for k, v in body.items() if k != "directives"}


def test_portfolio_server_sys_path_inserts_are_guarded():
    lines = (ROOT / "scripts" / "portfolio_server.py").read_text(encoding="utf-8").splitlines()
    unguarded = []
    for i, line in enumerate(lines):
        if re.search(r"\bsys\.path\.insert\(0, ", line) and line.startswith(" "):
            prev = lines[i - 1] if i else ""
            if "not in" not in prev and "not in" not in line:
                unguarded.append((i + 1, line.strip()))
    assert not unguarded, unguarded
