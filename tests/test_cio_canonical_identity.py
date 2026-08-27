"""Canonical event identity — the join the two lineage arcs never had.

The property that matters is cross-arc determinism: two processes that see the
same real event, at different moments, holding different field spellings, must
independently derive the same id with no shared state between them.
"""
from __future__ import annotations

import pytest

from scripts.lib.cio_canonical_identity import (
    ENTITY_SECURITY,
    ENTITY_UNRESOLVED,
    event_id_for,
    identity_fields,
    resolve_entity,
    time_bucket,
    workflow_id_for_event,
)


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path, monkeypatch):
    """No test in this module may read the production identity registry.

    Since Phase A, resolve_entity consults it — so without isolation these tests
    pass or fail depending on which symbols happen to be minted in production.
    Individual tests opt back in by setting the env var themselves.
    """
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "_isolated.json"))



def test_both_arcs_derive_the_same_id():
    """The whole point: no shared state, no lookup, no ordering requirement.

    Arc A holds `symbol` and its own timestamp; arc B holds `subject_id` in a
    different case and a timestamp 47 minutes later. Same hour bucket, same event.
    """
    arc_a = {"symbol": "SCHD", "occurred_at": "2026-08-27T15:05:00+00:00"}
    arc_b = {"subject_id": "schd", "created_at": "2026-08-27T15:52:41+00:00"}

    a = event_id_for(arc_a, event_kind="RESEARCH_REQUEST")
    b = event_id_for(arc_b, event_kind="RESEARCH_REQUEST")

    assert a is not None and a == b
    assert a.startswith("evt_")
    assert workflow_id_for_event(a) == workflow_id_for_event(b)


def test_different_subjects_do_not_collide():
    kw = {"event_kind": "RESEARCH_REQUEST", "occurred_at": "2026-08-27T15:00:00+00:00"}
    assert event_id_for({"symbol": "SCHD"}, **kw) != event_id_for({"symbol": "NOC"}, **kw)


def test_different_event_kinds_do_not_collide():
    """A research request and a CIO run about one ticker are different events."""
    p = {"symbol": "SCHD", "occurred_at": "2026-08-27T15:00:00+00:00"}
    assert event_id_for(p, event_kind="RESEARCH_REQUEST") != event_id_for(p, event_kind="CIO_RUN")


def test_separate_hours_are_separate_events():
    kw = {"event_kind": "RESEARCH_REQUEST"}
    a = event_id_for({"symbol": "SCHD", "occurred_at": "2026-08-27T15:59:00+00:00"}, **kw)
    b = event_id_for({"symbol": "SCHD", "occurred_at": "2026-08-27T16:00:00+00:00"}, **kw)
    assert a != b


def test_unresolvable_payload_refuses_to_join():
    """None, never a shared placeholder.

    A common "unknown" id would join every unresolved event to every other one
    and manufacture completions that never happened -- worse than no join.
    """
    assert event_id_for({"foo": "bar"}, event_kind="CIO_RUN") is None
    assert event_id_for(None, event_kind="CIO_RUN") is None
    assert event_id_for({"symbol": "  "}, event_kind="CIO_RUN") is None


def test_missing_timestamp_is_still_deterministic():
    """No timestamp must not mean 'key on now' — that breaks the join silently."""
    p = {"symbol": "SCHD"}
    assert event_id_for(p, event_kind="CIO_RUN") == event_id_for(p, event_kind="CIO_RUN")
    assert time_bucket(None) == "unbucketed"
    assert time_bucket("not-a-date") == "unbucketed"


def test_ticker_never_becomes_a_security_guid(tmp_path, monkeypatch):
    """A symbol is a subject_id, not a security identity.

    Pinned to an empty registry. `resolve_entity` consults the identity registry
    since Phase A, so without this the test reads whatever production happens to
    hold — it began failing the moment SCHD was minted for real.
    """
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "empty.json"))
    ent = resolve_entity({"symbol": "SCHD"})

    assert ent["subject_guid"] is None
    assert ent["entity_type"] == ENTITY_UNRESOLVED
    assert ent["never_minted_security_guid"] is True

    with_guid = resolve_entity({"symbol": "SCHD", "security_guid": "sec-123"})
    assert with_guid["entity_type"] == ENTITY_SECURITY
    assert with_guid["subject_guid"] == "sec-123"


def test_registered_entity_supplies_its_guid(tmp_path, monkeypatch):
    """The Phase A payoff, and its boundary.

    The GUID comes from the registry and is derived from the issuer, never from
    ticker text — so registering an entity resolves it without violating the rule
    above.
    """
    monkeypatch.setenv("TRADEAI_IDENTITY_REGISTRY", str(tmp_path / "r.json"))
    from scripts.lib.identity_registry import register_all

    assert resolve_entity({"symbol": "NOC"})["entity_type"] == ENTITY_UNRESOLVED

    register_all([{"symbol": "NOC", "company": "Northrop Grumman"}], apply=True)
    ent = resolve_entity({"symbol": "NOC"})

    assert ent["entity_type"] == ENTITY_SECURITY
    assert ent["subject_guid"]
    assert ent["never_minted_security_guid"] is True


def test_goal_wake_is_a_goal_not_a_security():
    """Production CIO runs are goal wakes; typing them SECURITY would be a lie."""
    fields = identity_fields(
        {"subject_id": "wake_goal_goal_695a5dbe2401_2026082714", "entity_type": "GOAL",
         "occurred_at": "2026-08-27T14:00:00+00:00"},
        event_kind="CIO_RUN",
    )
    assert fields["entity_type"] == "GOAL"
    assert fields["event_id"].startswith("evt_")


def test_identity_fields_never_sets_workflow_id():
    """Rewriting workflow_id changes how every consumer keys lineage.

    That has to stay an explicit caller decision, so these fields are purely
    additive and safe to merge into a live envelope.
    """
    fields = identity_fields({"symbol": "SCHD"}, event_kind="CIO_RUN")
    assert "workflow_id" not in fields
def test_hermes_envelope_now_carries_an_event_id():
    """Arc A's envelope had `event_id` read but never populated."""
    from scripts.lib.cio_workflow_envelope import hermes_request_fields

    fields = hermes_request_fields(
        {"research_id": "res_1", "symbol": "SCHD", "occurred_at": "2026-08-27T15:00:00+00:00"}
    )
    assert fields["event_id"] is not None
    assert fields["event_id"].startswith("evt_")


def test_request_and_completion_land_on_one_event():
    """A completion must not open a second event for the same request."""
    from scripts.lib.cio_workflow_envelope import hermes_completion_fields, hermes_request_fields

    request = {"research_id": "res_1", "symbol": "SCHD", "occurred_at": "2026-08-27T15:00:00+00:00"}
    opened = hermes_request_fields(request)
    closed = hermes_completion_fields(request, {"result_id": "rr_1"})

    assert closed["event_id"] == opened["event_id"]
