"""Cognitive memory anchored on the durable entity spine.

441 live memory records carried `symbols` — ticker strings — and none carried a
`subject_guid`, while a registry of 5,000+ GUID'd entities sat beside them. A
ticker is an alias: it is reassigned after a delisting, so two companies can
collide on one memory key years apart, and a memory written before a symbol
change becomes unfindable after it.
"""
from __future__ import annotations

import pytest

from scripts.lib.agent_durable_memory import _resolve_subject_guids
from scripts.lib.identity_registry import empty_registry, register, save


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path, monkeypatch):
    """Never read the production registry from a test.

    Otherwise these pass or fail depending on which symbols happen to be minted
    on the machine — the trap that surfaced in test_cio_lineage.
    """
    path = tmp_path / "registry.json"
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(path))
    doc = register(empty_registry(), {"symbol": "NVDA", "identifiers": {"cusip": "67066G104"}})
    register(doc, {"symbol": "SCHD", "company": "Schwab US Dividend Equity ETF"})
    save(doc)
    return doc


def test_a_registered_symbol_resolves_to_its_durable_guid(_isolated_registry):
    guids, unresolved = _resolve_subject_guids(["NVDA"])

    assert guids == [_isolated_registry["by_symbol"]["NVDA"]]
    assert unresolved == []


def test_an_unregistered_symbol_is_named_not_dropped():
    """A dropped symbol looks like an entity with no memories.

    Recording it as unresolved keeps the gap measurable instead of invisible.
    """
    guids, unresolved = _resolve_subject_guids(["NOTATICKER"])

    assert guids == []
    assert unresolved == ["NOTATICKER"]


def test_symbols_are_normalized_and_deduplicated():
    guids, _ = _resolve_subject_guids([" nvda ", "NVDA", "nvda"])
    assert len(guids) == 1, "one entity, one guid"


def test_a_missing_registry_claims_nothing():
    """Memory is not an identity authority.

    With no registry the write must proceed unanchored rather than mint an
    identity or block — the same fail-soft rule the lineage stamp follows.
    """
    import os

    os.environ["TRADEAI_IDENTITY_REGISTRY"] = "/nonexistent/registry.json"
    try:
        guids, unresolved = _resolve_subject_guids(["NVDA"])
    finally:
        os.environ.pop("TRADEAI_IDENTITY_REGISTRY", None)

    assert guids == []


def test_persist_sets_a_single_subject_guid_only_for_one_entity(tmp_path, monkeypatch):
    """A portfolio-wide memory has no single subject.

    Collapsing many symbols onto one `subject_guid` would manufacture a join
    between a broad observation and one arbitrary security.
    """
    from scripts.lib.agent_durable_memory import DurableJsonlMemoryProvider

    registry = tmp_path / "registry.json"
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(registry))
    doc = register(empty_registry(), {"symbol": "NVDA", "identifiers": {"cusip": "67066G104"}})
    register(doc, {"symbol": "SCHD", "company": "Schwab US Dividend Equity ETF"})
    save(doc)

    provider = DurableJsonlMemoryProvider(path=tmp_path / "mem.jsonl")

    single = {"symbols": ["NVDA"], "subject": "s", "content": "c"}
    provider._persist_record(single)
    assert single["subject_guid"] == doc["by_symbol"]["NVDA"]
    assert single["subject_guids"] == [doc["by_symbol"]["NVDA"]]

    broad = {"symbols": ["NVDA", "SCHD"], "subject": "s", "content": "c"}
    provider._persist_record(broad)
    assert "subject_guid" not in broad, "a multi-entity memory has no single subject"
    assert len(broad["subject_guids"]) == 2


def test_persist_does_not_overwrite_a_producer_supplied_guid(tmp_path, monkeypatch):
    """A producer that already knows the subject is not second-guessed."""
    from scripts.lib.agent_durable_memory import DurableJsonlMemoryProvider

    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "registry.json"))
    save(register(empty_registry(), {"symbol": "NVDA", "identifiers": {"cusip": "67066G104"}}))

    provider = DurableJsonlMemoryProvider(path=tmp_path / "mem.jsonl")
    rec = {"symbols": ["NVDA"], "subject_guid": "pre-set", "subject": "s", "content": "c"}
    provider._persist_record(rec)

    assert rec["subject_guid"] == "pre-set"
