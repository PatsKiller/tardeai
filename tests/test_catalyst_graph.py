"""Catalyst → entity binding, Phase C.

What matters is that an event is anchored to a *durable* entity and to the right
lifecycle bucket. A catalyst keyed on a ticker cannot answer "every earnings
event for this company", because the ticker is an alias.
"""
from __future__ import annotations

import pytest

from scripts.lib.catalyst_graph import (
    bind_catalyst,
    build_graph,
    events_for_entity,
    period_for,
)
from scripts.lib.identity_registry import empty_registry, lookup_symbol, register


@pytest.fixture
def registry():
    doc = empty_registry()
    register(doc, {"symbol": "NOC", "company": "Northrop Grumman"})
    register(doc, {"symbol": "PFLT", "identifiers": {"cusip": "70806A106"}})
    return doc


def _row(**kw):
    base = {"id": 1, "symbol": "NOC", "catalyst_type": "earnings_beat",
            "headline": "Q3 beat", "source": "finviz",
            "published_at": "2026-08-27T13:00:00+00:00"}
    base.update(kw)
    return base


def test_catalyst_binds_to_the_durable_entity(registry):
    bound = bind_catalyst(_row(), registry)

    assert bound is not None
    assert bound["event"]["schema"] == "SecurityEvent@v1"
    assert bound["event"]["event_guid"]
    assert bound["event"]["issuer_guid"] == lookup_symbol(registry, "NOC")["issuer_guid"]
    assert bound["trace"]["target_security"]["subject_guid"]
    assert bound["trace"]["target_security"]["ticker_guid_is_not_security"] is True


def test_earnings_is_quarterly_but_news_is_daily():
    """Earnings is not a timeless catalyst, and two downgrades in a quarter are two events."""
    assert period_for("earnings_beat", "2026-08-27T13:00:00+00:00") == "2026Q3"
    assert period_for("analyst_downgrade", "2026-08-27T13:00:00+00:00") == "20260827"


def test_two_reports_of_one_event_collapse_to_one_node(registry):
    """The node is the event; the traces are the observations of it."""
    graph = build_graph([
        _row(id=1, source="finviz", headline="NOC beats"),
        _row(id=2, source="yahoo", headline="Northrop tops estimates"),
    ], registry)

    assert graph["node_count"] == 1
    assert graph["trace_count"] == 2


def test_separate_quarters_are_separate_nodes(registry):
    graph = build_graph([
        _row(id=1, published_at="2026-05-10T13:00:00+00:00"),
        _row(id=2, published_at="2026-08-27T13:00:00+00:00"),
    ], registry)

    assert graph["node_count"] == 2


def test_unregistered_symbol_is_skipped_not_guessed(registry):
    """An edge to the wrong company is worse than a missing edge."""
    graph = build_graph([_row(symbol="ZZZZ")], registry)

    assert graph["node_count"] == 0
    assert graph["skipped"]["symbol_not_registered"] == 1


def test_entity_without_an_issuer_is_skipped(registry):
    """A ticker-alias-only entity has no issuer to scope the event to.

    Binding anyway would key the event on the alias, which is the failure this
    module exists to prevent.
    """
    register(registry, {"symbol": "TICKONLY"})
    graph = build_graph([_row(symbol="TICKONLY")], registry)

    assert graph["node_count"] == 0
    assert graph["skipped"]["entity_has_no_issuer"] == 1


def test_unusable_timestamp_is_skipped(registry):
    """No period means no guid — never a shared placeholder merging events."""
    graph = build_graph([_row(published_at=None, created_at=None)], registry)

    assert graph["node_count"] == 0
    assert graph["skipped"]["unusable_timestamp"] == 1


def test_chronological_traversal_for_one_entity(registry):
    """The payoff: every catalyst in an entity's life, in order."""
    graph = build_graph([
        _row(id=1, published_at="2026-08-27T13:00:00+00:00", catalyst_type="analyst_upgrade"),
        _row(id=2, published_at="2026-02-10T13:00:00+00:00", catalyst_type="earnings_beat"),
        _row(id=3, symbol="PFLT", published_at="2026-06-01T13:00:00+00:00"),
    ], registry)

    noc = lookup_symbol(registry, "NOC")["subject_guid"]
    timeline = events_for_entity(graph, noc)

    assert len(timeline) == 2
    assert [e["event_type"] for e in timeline] == ["EARNINGS_BEAT", "ANALYST_UPGRADE"]


def test_event_guid_is_stable_across_runs(registry):
    a = bind_catalyst(_row(), registry)["event"]["event_guid"]
    b = bind_catalyst(_row(id=99, source="other"), registry)["event"]["event_guid"]
    assert a == b
