"""next_eligible_at is the ordinary output of a completed wake, not a failure marker.

Until 2026-08-31 `apply_after_cycle` set it only when something went wrong: a
rejected artifact (+1d) or an operator defer (+7d). A cadence field that exists
only after a failure describes failures, not cadence.

Measured on the live store that day:

    records                       40
    next_eligible_at NEVER set    38   and none of those 38 carried a
                                       next_research_question either
    set but in the PAST            0   nothing expires or clears it
    set and in the FUTURE          2   both from the rejection path

The routine writer that would have populated it — `cio_residual_web`, whose
NEXT_LOOK_DAYS is the same 7 — is NEVER_SCHEDULED and has never run. So M5's
last mile was starved, not waiting.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.lib.cio_instrument_record import (
    BehaviorWriteRefused, CognitionNoOp, apply_cognition, new_record,
)
from scripts.lib.cio_rehydrate import (
    DEFER_PUSH_DAYS, ROUTINE_LOOK_DAYS, apply_after_cycle,
)

NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def _days_out(rec):
    v = rec.get("next_eligible_at")
    if not v:
        return None
    d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    return round((d - NOW).total_seconds() / 86400.0, 2)


def _cycle(**kw):
    return apply_after_cycle(new_record("HELD", "TEST"), now=NOW, **kw)[0]


# ── the change ────────────────────────────────────────────────────────────

def test_a_normal_completion_now_carries_a_future_cadence():
    rec = _cycle(artifact={"verdict": "VALID", "artifact_id": "a1"})
    assert _days_out(rec) == ROUTINE_LOOK_DAYS
    assert rec["next_eligible_at"] > NOW.isoformat()


def test_the_record_did_not_carry_one_before():
    """Before and after, on the same record."""
    before = new_record("HELD", "TEST")
    assert before.get("next_eligible_at") is None
    after, _ = apply_after_cycle(before, now=NOW,
                                 artifact={"verdict": "VALID", "artifact_id": "a1"})
    assert after["next_eligible_at"] is not None


# ── the two existing branches keep their own values ───────────────────────

def test_a_rejected_artifact_still_pushes_one_day():
    assert _days_out(_cycle(artifact={"verdict": "REJECTED", "artifact_id": "a"})) == 1


def test_execution_language_still_pushes_one_day():
    rec = _cycle(artifact={"verdict": "VALID", "execution_language": True,
                           "artifact_id": "a"})
    assert _days_out(rec) == 1


def test_an_operator_defer_still_pushes_its_own_interval():
    rec = _cycle(artifact={"verdict": "VALID", "artifact_id": "a"},
                 lesson={"claim": "operator defer honored, no new catalyst"})
    assert _days_out(rec) == DEFER_PUSH_DAYS


def test_a_moved_event_is_still_due_now_and_not_pushed():
    """An event override must void the cadence skip, not extend it.

    The record needs a PRIOR hash to have something to move away from: an unset
    hash is deliberately not a change, because first contact gave the desk no
    prior belief to contradict and was firing a spurious override on every
    freshly migrated record. My first version of this test omitted the prior and
    proved nothing — it exercised the no-op path instead.
    """
    from scripts.lib.cio_instrument_record import content_hash
    rec = new_record("HELD", "TEST")
    rec["hashes"] = {"weight": content_hash(0.10)}
    out, _ = apply_after_cycle(rec, now=NOW, observed={"weight": 0.42})
    d = _days_out(out)
    assert d is not None and d <= 0, "a moved event must be due now, never deferred"


def test_first_contact_is_not_an_event_and_does_not_push_a_cadence():
    """An unset hash is not a change, so a bare observation moves nothing."""
    with pytest.raises(CognitionNoOp):
        apply_after_cycle(new_record("HELD", "TEST"), now=NOW,
                          observed={"weight": 0.42})


def test_a_positive_delta_still_carries_a_cadence():
    """The cadence is set before the positive-delta block, so a CONFIRMS result
    does not lose it."""
    rec = _cycle(artifact={"verdict": "VALID", "delta_classification": "CONFIRMS",
                           "artifact_id": "a"})
    assert _days_out(rec) == ROUTINE_LOOK_DAYS
    assert rec.get("notify_priority") == "cc"


# ── the cadence is declared, not magic ────────────────────────────────────

def test_the_routine_cadence_matches_the_designed_routine_writer():
    """7 is not a new number. cio_residual_web.NEXT_LOOK_DAYS — the lane built
    to be the routine writer — already uses 7 for a completed hop and 1 for a
    blocked one, the same two values this module uses."""
    from scripts.lib.cio_residual_web import BLOCKED_NEXT_LOOK_DAYS, NEXT_LOOK_DAYS
    assert ROUTINE_LOOK_DAYS == NEXT_LOOK_DAYS == 7
    assert BLOCKED_NEXT_LOOK_DAYS == 1


def test_the_constant_carries_its_reasoning():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent
           / "scripts" / "lib" / "cio_rehydrate.py").read_text(encoding="utf-8")
    block = src[:src.index("ROUTINE_LOOK_DAYS = 7")]
    assert "describes failures, not cadence" in block
    assert "NEVER_SCHEDULED" in block


# ── MBI guards unchanged ──────────────────────────────────────────────────

def test_cognition_noop_still_raises_when_a_write_moves_nothing():
    with pytest.raises(CognitionNoOp):
        apply_cognition(new_record("HELD", "TEST"))


def test_a_cycle_that_completes_nothing_still_moves_nothing():
    """No artifact, no lesson, no observed event: the routine cadence must not
    fire just because a wake ran."""
    with pytest.raises(CognitionNoOp):
        apply_after_cycle(new_record("HELD", "TEST"), now=NOW)


def test_mbi_behavior_is_still_zero():
    with pytest.raises(BehaviorWriteRefused):
        apply_cognition(new_record("HELD", "TEST"),
                        next_research_question="q", size_usd=100)


def test_a_caller_supplied_cadence_beats_the_routine_default():
    """Precedence, most specific first: moved event > rejection > defer >
    the caller's own decision > the routine default.

    The first version of this change set the routine value inline, which
    pre-empted `decision.next_eligible_at` — its branch reads
    `if decision and not nxt_at`, so a caller that had computed its own cadence
    silently lost it. An existing test caught that regression."""
    from datetime import timedelta
    rec = _cycle(artifact={"verdict": "VALID", "artifact_id": "a"},
                 decision={"next_eligible_at": (NOW + timedelta(days=2)).isoformat()})
    assert _days_out(rec) == 2, "the caller's decision must win over the default"


def test_the_default_still_applies_when_the_caller_has_no_opinion():
    rec = _cycle(artifact={"verdict": "VALID", "artifact_id": "a"}, decision={})
    assert _days_out(rec) == ROUTINE_LOOK_DAYS


def test_a_rejection_beats_a_caller_decision():
    from datetime import timedelta
    rec = _cycle(artifact={"verdict": "REJECTED", "artifact_id": "a"},
                 decision={"next_eligible_at": (NOW + timedelta(days=30)).isoformat()})
    assert _days_out(rec) == 1
