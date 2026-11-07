"""ANCHOR: CATALYST_GRAPH_TYPED_NODES_20261107 — only an EVENT becomes a lifecycle node.

LQ-20261107-111. The served projection (`data/cio/catalyst_graph_latest.json`, built 2026-11-06) held
21,165 nodes; 11,300 of them had `event_type` OTHER, and the audit's headline "20,184 of 21,165 (95%)"
divided untyped **traces** by total **nodes**. Measured 2026-11-07 over the same 40,000-row window the
lane reads:

    rows scanned            40,000
    bound traces            33,585   of which 'other' 20,481 (61.0%)
    nodes (deduped)         21,446   of which 'other' 11,420 (53.3%)
    untyped rows            26,308
    re-classifying them     recovers a real type for 1.9% (382 rows)

So the typer is not broken for stored rows: an untyped row says "this article names no catalyst". Two
writers let such rows into `catalyst_events` anyway — `catalyst_classifier`'s deterministic fallback
(confidence 0.2, 100% 'other'), and `news_ingestion`'s legacy keyword pass, which wrote a row for every
article above a 0.3 relevance floor (77.6% of its rows untyped). The graph then bound each one.

The fix is at both ends: a row with no catalyst type is not bound, and the ingest path stops minting one.
Hermetic: synthetic rows and a recording fake cursor. No DB, no network.
"""
from __future__ import annotations

import pytest

from scripts.lib.catalyst_graph import (
    UNTYPED_CATALYST_TYPES,
    bind_catalyst,
    build_graph,
    is_catalyst_type,
)
from scripts.lib.identity_registry import empty_registry, lookup_symbol, register


@pytest.fixture
def registry():
    doc = empty_registry()
    register(doc, {"symbol": "NOC", "company": "Northrop Grumman"})
    return doc


def _row(**kw):
    base = {"id": 1, "symbol": "NOC", "catalyst_type": "earnings_beat",
            "headline": "Q3 beat", "source": "finviz",
            "published_at": "2026-08-27T13:00:00+00:00"}
    base.update(kw)
    return base


# ── what counts as an event ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["", "  ", "other", "OTHER", " Other ", "unknown", "none", "null", None])
def test_a_value_that_names_no_catalyst_is_untyped(value):
    assert is_catalyst_type(value) is False


@pytest.mark.parametrize("value", ["earnings_beat", "news_momentum", "analyst_downgrade", "offering_dilution"])
def test_a_named_catalyst_is_typed(value):
    assert is_catalyst_type(value) is True


def test_the_untyped_tokens_are_stated_not_implied():
    assert {"other", ""} <= set(UNTYPED_CATALYST_TYPES)


# ── the binder ─────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ctype", ["other", "", None, "OTHER"])
def test_an_untyped_row_is_not_bound(registry, ctype):
    """An article that names no catalyst is not an event, so it gets no node and no edge."""
    assert bind_catalyst(_row(catalyst_type=ctype), registry) is None


def test_a_typed_row_still_binds(registry):
    bound = bind_catalyst(_row(catalyst_type="news_momentum"), registry)
    assert bound is not None
    assert bound["event"]["event_type"] == "NEWS_MOMENTUM"


# ── the graph ─────────────────────────────────────────────────────────────────────────────────

def test_the_graph_never_emits_an_other_node(registry):
    rows = [_row(id=1, headline="one"), _row(id=2, headline="two", catalyst_type="other"),
            _row(id=3, headline="three", catalyst_type=""), _row(id=4, headline="four", catalyst_type=None),
            _row(id=5, headline="five", catalyst_type="analyst_upgrade")]
    graph = build_graph(rows, registry)

    assert graph["node_count"] == 2
    assert sorted(n["event_type"] for n in graph["nodes"]) == ["ANALYST_UPGRADE", "EARNINGS_BEAT"]
    assert "OTHER" not in graph["bound_by_type"]


def test_the_untyped_refusal_is_counted_not_silent(registry):
    graph = build_graph([_row(id=1, catalyst_type="other"), _row(id=2, catalyst_type="other")], registry)
    assert graph["skipped"]["untyped_not_an_event"] == 2
    assert graph["node_count"] == 0


def test_untyped_is_reported_before_a_symbol_problem(registry):
    """A non-event is refused before identity is consulted, so that is the reason the counter names."""
    graph = build_graph([_row(symbol="ZZZZ", catalyst_type="other")], registry)
    assert graph["skipped"]["untyped_not_an_event"] == 1
    assert "symbol_not_registered" not in graph["skipped"]


def test_a_typed_row_with_a_bad_symbol_is_still_the_symbol_reason(registry):
    """The symbol reasons are unchanged for rows that really are catalysts."""
    graph = build_graph([_row(symbol="ZZZZ", catalyst_type="earnings_beat")], registry)
    assert graph["skipped"]["symbol_not_registered"] == 1
    assert "untyped_not_an_event" not in graph["skipped"]


# ── the ingest path stops minting non-events ──────────────────────────────────────────────────

class _RecordingCursor:
    def __init__(self):
        self.statements: list[tuple[str, object]] = []

    def execute(self, sql, params=None):
        self.statements.append((" ".join(str(sql).split()), params))

    def catalyst_inserts(self):
        return [(sql, params) for sql, params in self.statements if "INSERT INTO catalyst_events" in sql]


class _Conn:
    def __init__(self):
        self.cur = _RecordingCursor()

    def cursor(self):
        return self.cur


def _feed(article_title: str, relevance: float = 0.9):
    from scripts.news_ingestion import _feed_downstream

    conn = _Conn()
    wrote = _feed_downstream(
        conn, "SYNTH", "momentum",
        {"title": article_title, "summary": "", "source": "synthetic_fixture", "published_at": None},
        {"relevance_score": relevance}, {})
    return wrote, conn.cur


def test_a_news_article_that_names_no_catalyst_writes_no_catalyst_row():
    """The regression: this path wrote 77.6% untyped rows into a store of events."""
    wrote, cur = _feed("Analyst weighs in on the sector outlook for next year")

    assert wrote is False
    assert cur.catalyst_inserts() == []
    # the article is still reported as sentiment: only the catalyst claim is withheld
    assert any("INSERT INTO sentiment_observations" in s for s, _p in cur.statements)


def test_an_article_naming_a_catalyst_still_writes_its_row():
    wrote, cur = _feed("Synthetic Systems wins contract for a program milestone")

    assert wrote is True
    inserts = cur.catalyst_inserts()
    assert len(inserts) == 1
    params = dict(zip(
        ["symbol", "strategy_type", "catalyst_type", "headline", "description",
         "severity", "confidence", "impact_score", "source", "published_at"], inserts[0][1]))
    assert params["catalyst_type"] == "contract_win"
    assert params["symbol"] == "SYNTH"


def test_a_low_relevance_article_writes_neither_kind_of_row():
    wrote, cur = _feed("Synthetic Systems wins contract for a program milestone", relevance=0.1)
    assert wrote is False
    assert cur.catalyst_inserts() == []


def test_the_ingest_stats_report_the_skips():
    import inspect

    from scripts import news_ingestion

    src = inspect.getsource(news_ingestion)
    assert '"skipped_not_a_catalyst"' in src
    assert "skipped_not_a_catalyst += 1" in src


def test_the_registry_fixture_is_the_shape_the_binder_expects(registry):
    """Guards the fixture itself: without an issuer the binder refuses for the wrong reason."""
    assert lookup_symbol(registry, "NOC")["issuer_guid"]
