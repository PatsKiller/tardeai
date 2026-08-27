"""IdentityRegistry@v1 — durable entity spine, Phase A.

The behaviour under test is not "can we compute a GUID" (security_identity
already does that) but "does a GUID stay usable for the entity's whole life",
which is what the lifecycle requirement actually asks for.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.lib.identity_registry import (
    empty_registry,
    load,
    lookup_symbol,
    register,
    register_all,
    registry_path,
    resolve_guid,
    save,
)


@pytest.fixture(autouse=True)
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    p = tmp_path / "identity_registry.json"
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(p))
    return p


def test_symbol_only_registers_honestly():
    """No company, no CIK, no CUSIP: a ticker alias and an honest status."""
    doc = register(empty_registry(), {"symbol": "SCHD"})
    ent = lookup_symbol(doc, "SCHD")

    assert ent is not None
    assert ent["subject_guid"]
    assert ent["identity_status"] == "UNRESOLVED_WITH_REASON"
    assert ent["ticker_guid_is_not_security"] is True


def test_company_name_yields_a_candidate_issuer():
    doc = register(empty_registry(), {"symbol": "NOC", "company": "Northrop Grumman"})
    ent = lookup_symbol(doc, "NOC")

    assert ent["identity_status"] == "CANDIDATE"
    assert ent["issuer_guid"]


def test_cusip_yields_a_confirmed_identity():
    doc = register(empty_registry(), {"symbol": "NOC", "company": "Northrop Grumman",
                                      "identifiers": {"cusip": "666807102"}})
    assert lookup_symbol(doc, "NOC")["identity_status"] == "CONFIRMED"


def test_upgrade_keeps_the_old_guid_resolvable():
    """The lifecycle guarantee: an id written before an upgrade still resolves.

    Silently switching GUIDs on upgrade would strand every record written under
    the old one — history would stop being traversable exactly where it matters.
    """
    doc = register(empty_registry(), {"symbol": "NOC", "company": "Northrop Grumman"})
    old = lookup_symbol(doc, "NOC")["subject_guid"]

    register(doc, {"symbol": "NOC", "company": "Northrop Grumman",
                   "identifiers": {"cusip": "666807102"}})
    new = lookup_symbol(doc, "NOC")["subject_guid"]

    assert new != old
    assert resolve_guid(doc, old) == new          # forward from a historical id
    assert doc["entities"][old]["active"] is False
    assert doc["entities"][old]["superseded_by"] == new
    assert old in doc["entities"][new]["supersedes"]   # and backward


def test_weaker_observation_never_downgrades():
    """A feed that stops sending CUSIPs must not silently weaken an entity."""
    doc = register(empty_registry(), {"symbol": "NOC", "company": "Northrop Grumman",
                                      "identifiers": {"cusip": "666807102"}})
    strong = lookup_symbol(doc, "NOC")["subject_guid"]

    register(doc, {"symbol": "NOC"})  # bare symbol arrives later

    assert lookup_symbol(doc, "NOC")["subject_guid"] == strong
    assert lookup_symbol(doc, "NOC")["identity_status"] == "CONFIRMED"


def test_registration_is_idempotent():
    doc = empty_registry()
    for _ in range(4):
        register(doc, {"symbol": "SCHD", "company": "Schwab US Dividend Equity ETF"})
    assert len(doc["entities"]) == 1


def test_resolve_guid_survives_a_corrupt_cycle():
    """Append-only makes a cycle impossible; a corrupt file must not hang a reader."""
    doc = empty_registry()
    doc["entities"] = {"a": {"superseded_by": "b"}, "b": {"superseded_by": "a"}}
    assert resolve_guid(doc, "a") in {"a", "b"}


def test_missing_registry_reads_as_empty():
    doc = load()
    assert doc["entities"] == {} and doc["schema"] == "IdentityRegistry@v1"


def test_round_trip_and_atomic_write(registry: Path):
    doc = register(empty_registry(), {"symbol": "SCHD", "company": "Schwab US Dividend"})
    save(doc)

    assert registry.exists()
    assert not registry.with_suffix(registry.suffix + ".tmp").exists()  # temp cleaned
    assert lookup_symbol(load(), "SCHD")["subject_guid"]
    assert json.loads(registry.read_text())["schema"] == "IdentityRegistry@v1"


def test_register_all_summarises_without_writing(registry: Path):
    summary = register_all([{"symbol": "SCHD"}, {"symbol": "NOC", "company": "Northrop"}])

    assert summary["entities_added"] == 2
    assert summary["applied"] is False
    assert not registry.exists()          # dry run really writes nothing


def test_register_all_applies_when_asked(registry: Path):
    register_all([{"symbol": "SCHD"}], apply=True)
    assert registry.exists()


def test_rows_without_a_symbol_are_skipped():
    summary = register_all([{"company": "No Ticker Inc"}, {"symbol": ""}, {"symbol": "SCHD"}])
    assert summary["rows_seen"] == 1


def test_canonical_identity_uses_the_registry(registry: Path):
    """The payoff: envelopes stop reading UNRESOLVED once an entity is registered."""
    from scripts.lib.cio_canonical_identity import resolve_entity

    assert resolve_entity({"symbol": "NOC"})["entity_type"] == "UNRESOLVED"

    register_all([{"symbol": "NOC", "company": "Northrop Grumman"}], apply=True)
    resolved = resolve_entity({"symbol": "NOC"})

    assert resolved["entity_type"] == "SECURITY"
    assert resolved["subject_guid"]


def test_event_id_keys_on_the_guid_not_the_ticker(registry: Path):
    """A ticker is reassigned after delisting; an event id must not depend on it."""
    from scripts.lib.cio_canonical_identity import event_id_for

    before = event_id_for({"symbol": "NOC", "occurred_at": "2026-08-27T15:00:00+00:00"},
                          event_kind="RESEARCH_REQUEST")
    register_all([{"symbol": "NOC", "company": "Northrop Grumman"}], apply=True)
    after = event_id_for({"symbol": "NOC", "occurred_at": "2026-08-27T15:00:00+00:00"},
                         event_kind="RESEARCH_REQUEST")

    assert before != after   # now derived from the durable spine
    assert after.startswith("evt_")


def test_broker_cusip_upgrades_a_named_entity():
    """The Schwab path end to end: name → CANDIDATE, then CUSIP → CONFIRMED.

    Reproduces the live PFLT upgrade. The broker hands us the CUSIP in the same
    `instrument` dict as the symbol; capturing it is what makes an entity
    CONFIRMED rather than name-derived.
    """
    doc = register(empty_registry(), {"symbol": "PFLT", "company": "PennantPark Floating Rate"})
    assert lookup_symbol(doc, "PFLT")["identity_status"] == "CANDIDATE"
    candidate = lookup_symbol(doc, "PFLT")["subject_guid"]

    register(doc, {"symbol": "PFLT", "identifiers": {"cusip": "70806A106"}})
    confirmed = lookup_symbol(doc, "PFLT")

    assert confirmed["identity_status"] == "CONFIRMED"
    assert confirmed["subject_guid"] != candidate
    assert resolve_guid(doc, candidate) == confirmed["subject_guid"]


def test_schwab_adapter_keeps_the_cusip():
    """Guard the discard. `instrument.cusip` was dropped on every sync."""
    src = (Path(__file__).resolve().parent.parent / "scripts" / "schwab_adapter.py").read_text()
    block = src.split("fields=positions", 1)[1][:1200]

    assert '"cusip"' in block, "Schwab positions must carry the broker-supplied CUSIP"
