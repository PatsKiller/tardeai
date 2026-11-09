"""A transient sqlite lock during the executor's effect-store claim must not dead-letter a healthy slot.

LQ-20261107-1349. Source: `d:material-change-detector-stage1:live:20261108T2130` — RUN_REFUSED, attempts 1,
`effect.reason effect_store_unavailable`, dead letter at 02:31:02Z, one attempt, ~5.1 s in the receipt (the
connection's busy timeout) while its 21:00 sibling finished in 13 s. A single ``database is locked`` on
``EffectGate.begin()``'s claim became a terminal refusal, so the retry policy (``transient-1-ingest``, 2 attempts)
never ran.

Hermetic: a duck-typed store, no ledger, no scheduler, no child process, no live file.
"""

from __future__ import annotations

import sqlite3

import pytest

from scripts import n8n_run_executor as X
from scripts.lib.effect_claim import ClaimResult

LANE = "material-change-detector-stage1"
PROCESS = LANE
RUN_ID = f"d:{LANE}:live:20261108T2130"
T0 = 1_800_000_000.0
ROW = {"run_id": RUN_ID, "requested_at": T0 - 30, "attempt": 1}
CONFIG = {LANE: {"process": PROCESS, "input_version": "v1"}}


def _ok(key: str) -> ClaimResult:
    return ClaimResult(True, key, None, "n8n", 1, 1)


class FlakyStore:
    """``store.claim`` that yields the given outcomes in order (an Exception is raised, anything else returned)."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def claim(self, key, **kwargs):  # noqa: ANN001 -- mirrors EffectClaimStore.claim
        self.calls += 1
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _gate(store) -> tuple[X.EffectGate, list[float]]:
    slept: list[float] = []
    gate = X.EffectGate(store, CONFIG, clock=lambda: T0, sleep=slept.append)
    return gate, slept


def test_a_transient_lock_is_retried_and_the_claim_succeeds():
    store = FlakyStore([sqlite3.OperationalError("database is locked"), _ok("k")])
    gate, slept = _gate(store)

    block, refusal = gate.begin(ROW, LANE, "live")

    assert refusal is None, "a lock that clears must not refuse the slot"
    assert block["claimed"] is True
    assert block["claim_retries"] == 1
    assert store.calls == 2
    assert slept == [gate.claim_backoff_s[0]]


def test_a_lock_that_clears_after_two_retries_still_runs():
    store = FlakyStore(
        [
            sqlite3.OperationalError("database is locked"),
            sqlite3.OperationalError("database is busy"),
            _ok("k"),
        ]
    )
    gate, slept = _gate(store)

    block, refusal = gate.begin(ROW, LANE, "live")

    assert refusal is None and block["claimed"] is True
    assert block["claim_retries"] == 2
    assert store.calls == 3
    assert slept == list(gate.claim_backoff_s)


def test_a_persistent_lock_is_refused_after_the_bounded_retries():
    store = FlakyStore([sqlite3.OperationalError("database is locked")])
    gate, slept = _gate(store)

    block, refusal = gate.begin(ROW, LANE, "live")

    assert refusal == "effect:effect_store_unavailable", "the receipt reason operators grep must not change"
    assert block["reason"] == "effect_store_unavailable"
    assert block["claimed"] is False
    assert store.calls == gate.claim_attempts, "the retry must be bounded, not unbounded"
    assert len(slept) == gate.claim_attempts - 1


def test_a_non_transient_sqlite_error_is_refused_at_once():
    for error in (
        sqlite3.OperationalError("no such table: effect_claims"),
        sqlite3.DatabaseError("database disk image is malformed"),
    ):
        store = FlakyStore([error])
        gate, slept = _gate(store)

        block, refusal = gate.begin(ROW, LANE, "live")

        assert refusal == "effect:effect_store_unavailable"
        assert store.calls == 1, f"a fault a retry cannot fix must not be retried: {error}"
        assert slept == []


def test_an_already_claimed_refusal_is_not_retried():
    held = ClaimResult(False, "k", "effect_already_claimed", "n8n", 1, 1, {"state": "CLAIMED"})
    store = FlakyStore([held])
    gate, slept = _gate(store)

    block, refusal = gate.begin(ROW, LANE, "live")

    assert refusal == "effect:effect_already_claimed"
    assert block["claimed"] is False
    assert store.calls == 1, "a refusal result is a decision, not a transient fault"
    assert slept == []


def test_the_store_missing_still_refuses_without_a_retry():
    gate = X.EffectGate(None, CONFIG, clock=lambda: T0, sleep=lambda _s: pytest.fail("nothing to retry"))

    block, refusal = gate.begin(ROW, LANE, "live")

    assert refusal == "effect:effect_store_unavailable"
    assert block["reason"] == "effect_store_unavailable"


def test_a_dry_run_never_claims():
    store = FlakyStore([_ok("k")])
    gate, slept = _gate(store)

    block, refusal = gate.begin(ROW, LANE, "dry_run")

    assert (block, refusal) == (None, None)
    assert store.calls == 0 and slept == []
