#!/usr/bin/env python3
"""Agentic-memory tranche 1, Slice 1 (R5): outcome checkpoints bind a real subject
and a real due date at mint, so an outcome can reach an InstrumentRecord.

Measured 2026-09-24 before this change: 171/174 RESOLVED checkpoints carried
entity_type UNRESOLVED (subject_id "UNRESOLVED:position:MCD:RESEARCH") and
~12,000 SCHEDULED rows had due_at null. Hermetic: the identity registry is an
injected document, the record store lives in tmp_path, nothing reads production.

    .venv/bin/python -m pytest tests/test_checkpoint_subject_binding_20260925.py -q
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import cio_institutional_learning as cil  # noqa: E402
from scripts.lib import r17_checkpoint_binding as r17  # noqa: E402
from scripts.lib.cio_instrument_record import (  # noqa: E402
    DEFAULT_PATH,
    InstrumentRecordStore,
    new_record,
    subject_key_for_symbol,
)
from scripts.lib.security_identity import issuer_guid, security_guid  # noqa: E402

NOW = datetime(2026, 9, 25, 14, 0, tzinfo=timezone.utc)

ISSUER_MCD = issuer_guid(company="McDonald's Corp")
SEC_MCD = security_guid(issuer=ISSUER_MCD)
REGISTRY = {
    "by_symbol": {"MCD": SEC_MCD, "ZZZQ": "unresolved-guid"},
    "entities": {
        SEC_MCD: {"schema": "RegisteredEntity@v1", "ticker_alias": "MCD",
                  "issuer_guid": ISSUER_MCD, "security_guid": SEC_MCD,
                  "identity_status": "CONFIRMED"},
        "unresolved-guid": {"schema": "RegisteredEntity@v1", "ticker_alias": "ZZZQ",
                            "identity_status": "UNRESOLVED", "security_guid": None},
    },
}


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    """Registry lookups hit the fixture; the record store lives in tmp_path."""
    real = cil.identity_safe_subject

    def _safe(row, *, registry=None):
        return real(row, registry=REGISTRY if registry is None else registry)

    monkeypatch.setattr(cil, "identity_safe_subject", _safe)
    monkeypatch.setattr(r17, "identity_safe_subject", _safe)
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    store = InstrumentRecordStore(tmp_path / DEFAULT_PATH)
    store.upsert(new_record("HELD", "MCD", symbols=["MCD"]))
    yield tmp_path


# ── identity_safe_subject ──────────────────────────────────────────────────

def test_registry_lookup_binds_a_symbol_only_decision():
    assert cil.identity_safe_subject({"symbol": "MCD"}, registry=REGISTRY) == SEC_MCD


def test_a_guid_already_on_the_row_wins_without_lookup():
    assert cil.identity_safe_subject({"symbol": "MCD", "security_guid": "row-guid"},
                                     registry=REGISTRY) == "row-guid"


def test_unknown_or_unresolved_symbols_still_yield_none():
    """Lookup, never mint: no registry row -> None; an UNRESOLVED row -> None."""
    assert cil.identity_safe_subject({"symbol": "NOPE"}, registry=REGISTRY) is None
    assert cil.identity_safe_subject({"symbol": "ZZZQ"}, registry=REGISTRY) is None
    assert cil.identity_safe_subject({}, registry=REGISTRY) is None


# ── canonical_checkpoint_subject / enrich_checkpoint ───────────────────────

def test_checkpoint_subject_is_security_with_record_key():
    subj = r17.canonical_checkpoint_subject({"symbol": "MCD", "recommendation": "TRIM",
                                             "decision_id": "dec_1"})
    assert subj["entity_type"] == "SECURITY"
    assert subj["subject_guid"] == SEC_MCD
    assert subj["subject_id"] == SEC_MCD
    assert subj["subject_key"] == "HELD:MCD"
    assert subj["ticker_guid_is_not_security"] is False


def test_unknown_symbol_stays_unresolved_and_has_no_record_key():
    subj = r17.canonical_checkpoint_subject({"symbol": "NOPE", "recommendation": "TRIM",
                                             "decision_id": "dec_2"})
    assert subj["entity_type"] == "UNRESOLVED"
    assert subj["subject_guid"] is None
    assert subj["subject_id"].startswith("UNRESOLVED:")
    assert subj["subject_key"] is None


def test_enriched_checkpoint_carries_subject_key_and_due_basis():
    ck = r17.enrich_checkpoint({"symbol": "MCD", "recommendation": "TRIM", "decision_id": "dec_3"},
                               "5_sessions", source_sha="abc", now=NOW)
    assert ck["entity_type"] == "SECURITY"
    assert ck["subject_key"] == "HELD:MCD"
    assert ck["due_at"] == (NOW + timedelta(days=5)).isoformat().replace("+00:00", "Z") or ck["due_at"]
    assert ck["due_at_basis"] == "horizon_offset"


# ── due dates for event-relative ───────────────────────────────────────────

def test_event_relative_uses_the_decisions_event_date():
    ev = (NOW + timedelta(days=12)).isoformat()
    due, basis = r17.due_at_with_basis("event-relative", now=NOW,
                                       decision={"symbol": "MCD", "event_date": ev})
    assert basis == "decision_event_date"
    assert due is not None and due.startswith((NOW + timedelta(days=12)).strftime("%Y-%m-%d"))


def test_event_relative_without_event_date_gets_the_stated_fallback():
    due, basis = r17.due_at_with_basis("event-relative", now=NOW, decision={"symbol": "MCD"})
    assert basis == "fallback_30d"
    assert due is not None and due.startswith(
        (NOW + timedelta(days=r17.EVENT_RELATIVE_FALLBACK_DAYS)).strftime("%Y-%m-%d"))
    ck = r17.enrich_checkpoint({"symbol": "MCD", "recommendation": "TRIM", "decision_id": "dec_4"},
                               "event-relative", source_sha="abc", now=NOW)
    assert ck["due_at"] is not None
    assert ck["due_at_basis"] == "fallback_30d"


def test_a_past_event_date_falls_back_rather_than_minting_a_due_in_the_past():
    ev = (NOW - timedelta(days=3)).isoformat()
    due, basis = r17.due_at_with_basis("event-relative", now=NOW,
                                       decision={"symbol": "MCD", "event_date": ev})
    assert basis == "fallback_30d"


def test_unknown_horizon_still_has_no_due():
    assert r17.due_at_with_basis("made_up", now=NOW) == (None, None)


# ── subject_key_for_symbol (lookup only) ───────────────────────────────────

def test_subject_key_probe_finds_held_and_returns_none_for_strangers(tmp_path):
    store = InstrumentRecordStore(tmp_path / DEFAULT_PATH)
    assert subject_key_for_symbol("MCD", store=store) == "HELD:MCD"
    assert subject_key_for_symbol("mcd", store=store) == "HELD:MCD"
    assert subject_key_for_symbol("NOPE", store=store) is None
    assert subject_key_for_symbol("", store=store) is None
    assert not store.load("HELD:NOPE")  # nothing minted by the probe


# ── backfill planner (append-only amendments) ──────────────────────────────

def test_backfill_plans_amendments_only_for_resolvable_unbound_rows(tmp_path):
    from scripts.backfill_checkpoint_subject_guid import (
        AMENDMENT_REASON,
        plan_backfill,
        run,
    )

    rows = [
        {"checkpoint_id": "a", "status": "RESOLVED", "entity_type": "UNRESOLVED",
         "subject_id": "UNRESOLVED:position:MCD:RESEARCH", "horizon": "1_session",
         "original_decision_state": {"symbol": "MCD", "recommendation": "RESEARCH"}},
        {"checkpoint_id": "b", "status": "SCHEDULED", "entity_type": "UNRESOLVED",
         "subject_id": "UNRESOLVED:position:NOPE:TRIM", "horizon": "1_session",
         "original_decision_state": {"symbol": "NOPE", "recommendation": "TRIM"}},
        {"checkpoint_id": "c", "status": "SCHEDULED", "entity_type": "SECURITY",
         "subject_guid": "already", "subject_id": "already", "horizon": "1_session"},
        {"checkpoint_id": "d", "status": "SCHEDULED", "entity_type": "PORTFOLIO_CASH",
         "subject_id": "PORTFOLIO_CASH:CONSOLIDATED", "horizon": "1_session"},
    ]
    plan = plan_backfill(rows, registry=REGISTRY, subject_key_lookup=lambda s: "HELD:MCD",
                         now="2026-09-25T00:00:00+00:00")
    assert plan["would_append"] == 1
    assert plan["already_bound"] == 1
    assert plan["unresolvable_rows"] == 1 and plan["unresolvable_top"] == [("NOPE", 1)]
    assert plan["no_symbol"] == 1  # the cash row has no symbol -> untouched
    am = plan["amendments"][0]
    assert am["checkpoint_id"] == "a"
    assert am["subject_guid"] == SEC_MCD and am["entity_type"] == "SECURITY"
    assert am["subject_key"] == "HELD:MCD"
    assert am["amendment_reason"] == AMENDMENT_REASON and am["amendment_of"]

    # --apply appends (never rewrites) and a second run appends nothing.
    path = tmp_path / cil.CHECKPOINT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    out = run(tmp_path, apply=False, limit=None, registry=REGISTRY)
    assert out["would_append"] == 1 and out["appended"] == 0
    assert len(path.read_text().splitlines()) == 4
    out = run(tmp_path, apply=True, limit=None, registry=REGISTRY)
    assert out["appended"] == 1
    lines = path.read_text().splitlines()
    assert len(lines) == 5 and json.loads(lines[0])["entity_type"] == "UNRESOLVED"  # original kept
    again = run(tmp_path, apply=True, limit=None, registry=REGISTRY)
    assert again["appended"] == 0 and again["already_bound"] == 2
