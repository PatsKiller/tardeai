"""Target selection for the Schwab identifier sweep.

Which symbols the sweep asks about is the part that costs broker rate limit and
the part that can quietly go wrong; the HTTP call itself is thin. No network is
touched here.
"""
from __future__ import annotations

from scripts.lib.identity_registry import empty_registry, register
from scripts.sweep_schwab_instruments import symbols_needing_identifiers


def _registry_with(rows):
    doc = empty_registry()
    for row in rows:
        register(doc, row)
    return doc


def test_confirmed_entities_are_not_re_asked():
    """Spending rate limit to re-learn an identifier we already hold."""
    doc = _registry_with([
        {"symbol": "ABCL", "identifiers": {"cusip": "00288U106"}},
        {"symbol": "ACAD", "company": "Acadia Pharmaceuticals"},
        {"symbol": "ADTN"},
    ])
    targets = symbols_needing_identifiers(doc)

    assert "ABCL" not in targets, "already CONFIRMED"
    assert targets == ["ACAD", "ADTN"]


def test_superseded_entities_are_skipped():
    """An upgraded entity leaves its old GUID behind, still resolvable.

    Sweeping the superseded record would ask about a symbol whose live entity is
    already confirmed, and could write evidence against a retired identity.
    """
    doc = _registry_with([
        {"symbol": "PFLT", "company": "PennantPark Floating Rate"},
        {"symbol": "PFLT", "identifiers": {"cusip": "70806A106"}},
    ])
    assert len(doc["entities"]) == 2, "the superseded GUID is retained by design"
    assert symbols_needing_identifiers(doc) == []


def test_non_equity_shaped_aliases_are_not_sent_to_the_broker():
    """A CUSIP-shaped or malformed 'ticker' is not a symbol lookup.

    These exist in the watch tail; sending them burns rate limit on a guaranteed
    miss and pollutes the miss log with rows that were never symbols.
    """
    doc = _registry_with([
        {"symbol": "70806A106"},
        {"symbol": "BRK.B"},
        {"symbol": "TOOLONGSYM"},
        {"symbol": "AAPL"},
    ])
    assert symbols_needing_identifiers(doc) == ["AAPL"]


def test_targets_are_deduplicated_and_ordered():
    """Stable ordering keeps a resumed or compared sweep meaningful."""
    doc = _registry_with([{"symbol": "ZTS"}, {"symbol": "AAPL"}, {"symbol": "MSFT"}])
    targets = symbols_needing_identifiers(doc)

    assert targets == sorted(set(targets)) == ["AAPL", "MSFT", "ZTS"]
