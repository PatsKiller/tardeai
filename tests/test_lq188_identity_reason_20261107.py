"""LQ-20261107-188 — identity lookup separates "never in the registry" from "registry has no subject".

Diagnosis (12:20 DB retest): VIG (an ETF, quote_type ETF in instrument_facts) had no by_symbol entry in
the identity registry, because the minter's feeds (holdings, watchlist, decision surface, intel, e-confirm
identifiers, broker reference) never produced it. The old reason string "registry_answered_no_entity"
reported that gap as if the registry had examined the symbol and decided. These tests pin the split.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.lib.cio_subject_guid import RESOLVED, UNRESOLVED, lookup_subject


def _registry(tmp_path: Path, monkeypatch, *, entities: dict, by_symbol: dict) -> None:
    path = tmp_path / "identity_registry.json"
    doc = {
        "schema": "IdentityRegistry@v1",
        "authority": "READ_ONLY_ADVISORY",
        "memory_behavior_influence": 0,
        "entities": entities,
        "by_symbol": by_symbol,
        "events": {},
        "updated_at": None,
    }
    path.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(path))


def test_symbol_absent_from_registry_is_reported_as_not_in_registry(tmp_path, monkeypatch):
    # VIG-shaped case: the registry never minted it.
    _registry(tmp_path, monkeypatch, entities={}, by_symbol={})
    hit = lookup_subject("VIG")
    assert hit["identity_lookup"] == UNRESOLVED
    assert hit["identity_status"] == UNRESOLVED
    assert hit["subject_guid"] is None
    assert hit["identity_lookup_reason"] == "symbol_not_in_registry"


def test_minted_entity_without_subject_keeps_registry_answered_reason(tmp_path, monkeypatch):
    # The registry has an opinion: a by_symbol entry whose entity carries no subject.
    _registry(
        tmp_path, monkeypatch,
        entities={"ent-1": {"subject_guid": None, "identity_status": "UNRESOLVED_WITH_REASON"}},
        by_symbol={"ABCD": "ent-1"},
    )
    hit = lookup_subject("ABCD")
    assert hit["identity_lookup"] == UNRESOLVED
    assert hit["identity_lookup_reason"] == "registry_answered_no_entity"


def test_resolved_symbol_is_unchanged(tmp_path, monkeypatch):
    # Control: a resolvable symbol still resolves and carries no reason.
    _registry(
        tmp_path, monkeypatch,
        entities={"ent-2": {"subject_guid": "subj-2", "identity_status": "CONFIRMED",
                            "entity_type": "SECURITY"}},
        by_symbol={"SPY": "ent-2"},
    )
    hit = lookup_subject("spy")
    assert hit["identity_lookup"] == RESOLVED
    assert hit["subject_guid"] == "subj-2"
    assert hit["identity_lookup_reason"] is None
