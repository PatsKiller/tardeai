#!/usr/bin/env python3
"""A wake must be able to find memory that is about its subject.

Measured on the live durable store, 2026-09-10 (930 rows,
persistent-state/data/cio/aif_memory.jsonl):

    442  rows carry an explicit subject_guid
    488  carry none
    485  of those 488 carry `symbols`
    137  of 139 distinct symbols resolve through the identity registry
    145  rows are about subjects the scheduled wakes actually select
      0  facts were loaded by any wake

PR #956 stopped the loader refusing these rows outright (MEMORY_MALFORMED).
It did not make them findable: matching required an explicit subject_guid, so
half the store was invisible and every wake decided with zero facts.

Producer of those numbers:
`trade-ai-audits/cursor-independent-closure-20260910/memory_overlap_probe.py`
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib import persistent_agent_wake as paw  # noqa: E402

NVDA = "245a0597-2bf6-5d3a-a84a-737d39fb1648"
AES = "a2ee84b5-e1bc-5288-8402-7c1fbca65657"
AS_OF = datetime(2026, 9, 10, 22, 0, tzinfo=timezone.utc)


def _fake_registry(monkeypatch, mapping: dict[str, str | None]):
    """Replace the registry lookup. Clears the cache both ways."""
    paw._guid_for_symbol.cache_clear()
    monkeypatch.setattr(
        paw, "_guid_for_symbol", lambda s: mapping.get(str(s).upper())
    )


def _row(**over):
    row = {
        "memory_id": "m1",
        "content": "AES guidance raised",
        "as_of": "2026-09-10T12:00:00Z",
    }
    row.update(over)
    return row


# ------------------------------------------------------------- disposition

def test_explicit_guid_still_wins(monkeypatch):
    """An explicit stamp is authoritative and symbols must not override it."""
    _fake_registry(monkeypatch, {"NVDA": NVDA})
    row = _row(subject_guid=AES, symbols=["NVDA"])
    assert paw._row_subject_disposition(row, AES) == "match"
    assert paw._row_subject_disposition(row, NVDA) == "cross"


def test_symbol_resolves_onto_the_wake_subject(monkeypatch):
    _fake_registry(monkeypatch, {"AES": AES})
    assert paw._row_subject_disposition(_row(symbols=["AES"]), AES) == "match_resolved"


def test_symbol_for_another_issuer_is_cross_not_match(monkeypatch):
    _fake_registry(monkeypatch, {"NVDA": NVDA})
    assert paw._row_subject_disposition(_row(symbols=["NVDA"]), AES) == "cross"


def test_several_subjects_in_one_row_is_ambiguous_never_guessed(monkeypatch):
    """Attributing a multi-issuer row to one subject is a judgment.

    Getting it wrong files another issuer's history under this one, and every
    join downstream inherits it.
    """
    _fake_registry(monkeypatch, {"AES": AES, "NVDA": NVDA})
    row = _row(symbols=["AES", "NVDA"])
    assert paw._row_subject_disposition(row, AES) == "ambiguous"
    assert paw._row_subject_disposition(row, NVDA) == "ambiguous"


def test_repeated_symbol_is_one_subject_not_ambiguous(monkeypatch):
    _fake_registry(monkeypatch, {"AES": AES})
    row = _row(symbols=["AES", "aes", " AES "])
    assert paw._row_subject_disposition(row, AES) == "match_resolved"


def test_unresolvable_symbol_is_unmatched_not_matched(monkeypatch):
    _fake_registry(monkeypatch, {"AES": AES})
    assert paw._row_subject_disposition(_row(symbols=["NOSUCH"]), AES) == "unmatched"


def test_no_symbols_and_no_guid_is_unmatched(monkeypatch):
    _fake_registry(monkeypatch, {})
    assert paw._row_subject_disposition(_row(subject="a title"), AES) == "unmatched"


def test_title_is_never_read_as_a_guid(monkeypatch):
    """The PR #956 rule holds: a human title must not default-match."""
    _fake_registry(monkeypatch, {})
    row = _row(subject="Research observation AES")
    assert paw._row_subject_disposition(row, AES) == "unmatched"


def test_kill_switch_restores_the_previous_behaviour(monkeypatch):
    """Rollback must not need a deploy."""
    _fake_registry(monkeypatch, {"AES": AES})
    row = _row(symbols=["AES"])
    assert paw._row_subject_disposition(row, AES, env={"WAKE_MEMORY_SYMBOL_RESOLVE": "0"}) == "unmatched"
    assert paw._row_subject_disposition(row, AES, env={"WAKE_MEMORY_SYMBOL_RESOLVE": "1"}) == "match_resolved"


# ------------------------------------------------------------------ loader

def test_loader_loads_the_resolved_row_and_counts_it_separately(monkeypatch):
    _fake_registry(monkeypatch, {"AES": AES, "NVDA": NVDA})
    rows = [
        _row(memory_id="explicit", subject_guid=AES),
        _row(memory_id="by_symbol", symbols=["AES"]),
        _row(memory_id="other_issuer", symbols=["NVDA"]),
        _row(memory_id="both", symbols=["AES", "NVDA"]),
        _row(memory_id="title_only", subject="Advisory Desk heartbeat"),
    ]
    snap = paw.MemoryLoader(lambda _g: rows).load(AES, now=AS_OF)

    assert snap.malformed is False
    assert snap.empty is False
    assert {f.fact_id for f in snap.facts} == {"explicit", "by_symbol"}
    m = snap.metrics
    assert m.loaded == 2
    assert m.resolved_by_symbol == 1, "explicit matches must not inflate this"
    assert m.cross_subject_prevented == 1
    assert m.ambiguous_prevented == 1
    assert m.unmatched == 1


def test_loader_with_the_switch_off_loads_only_explicit_rows(monkeypatch):
    _fake_registry(monkeypatch, {"AES": AES})
    monkeypatch.setenv("WAKE_MEMORY_SYMBOL_RESOLVE", "0")
    rows = [_row(memory_id="explicit", subject_guid=AES),
            _row(memory_id="by_symbol", symbols=["AES"])]
    snap = paw.MemoryLoader(lambda _g: rows).load(AES, now=AS_OF)
    assert {f.fact_id for f in snap.facts} == {"explicit"}
    assert snap.metrics.resolved_by_symbol == 0


def test_registry_failure_does_not_break_the_wake(monkeypatch):
    """A lookup outage degrades recall; it must never refuse the snapshot.

    Patches `lookup_subject` — the real boundary that can fail — rather than
    `_guid_for_symbol`, which is the function holding the guard. Patching the
    guard itself would simulate a failure that cannot occur and fail for a
    reason production never would.
    """
    paw._guid_for_symbol.cache_clear()
    import scripts.lib.cio_subject_guid as csg

    def boom(_s):
        raise RuntimeError("registry down")

    monkeypatch.setattr(csg, "lookup_subject", boom)
    rows = [_row(memory_id="explicit", subject_guid=AES),
            _row(memory_id="by_symbol", symbols=["AES"])]
    try:
        snap = paw.MemoryLoader(lambda _g: rows).load(AES, now=AS_OF)
    except RuntimeError:
        raise AssertionError("registry failure must not propagate into the wake")
    assert {f.fact_id for f in snap.facts} == {"explicit"}
    assert snap.malformed is False


def test_resolution_never_mints_a_guid(monkeypatch):
    """The registry is the only authority. Memory may read it, never write it."""
    import scripts.lib.security_identity as si

    called = []
    for name in ("security_guid", "issuer_guid", "listing_guid"):
        if hasattr(si, name):
            monkeypatch.setattr(
                si, name, lambda *a, _n=name, **k: called.append(_n)
            )
    _fake_registry(monkeypatch, {"AES": AES})
    paw.MemoryLoader(lambda _g: [_row(symbols=["AES"])]).load(AES, now=AS_OF)
    assert called == [], f"minting called during a read-only load: {called}"
