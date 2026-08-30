"""Rehydrate an InstrumentRecord into the research gate, then write cognition back.

Slice A made memory exist. This is the slice that makes it USED — the two are
not the same thing, and a record nothing reads is just a slower log.

Every wake for a subject:
    1. load the record
    2. ResearchNeedDecision@v2 is fed FROM THE RECORD, not only the plan.
       The plan knows what fired; only the record knows what the operator
       already said, what the last artifact did, and when the desk agreed to
       look again.
    3. after the product/artifact/lesson lands, apply cognition
    4. persist — and a persist that moved nothing FAILS (CognitionNoOp)

The three write-back rules, from the operator's spec:

  defer honored, no new catalyst
      the next question stops being the one already answered and becomes a
      catalyst/earnings question; next_eligible_at is pushed; the narrative
      says the defer out loud so the CC cannot silently drop it.

  artifact REJECTED / execution language
      the next question must NOT be the same prompt — re-asking a prompt that
      failed closed is how a desk burns a budget learning nothing — and the
      record is flagged research_blocked.

  weight / earnings hash moved
      an event override: the cadence skip is overridden and a run is allowed,
      because the thing the last answer was about has changed.

MBI_BEHAVIOR=0 throughout: this module moves questions, timing, priority and
prose. It never produces a size.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from scripts.lib.cio_instrument_record import (
    apply_cognition, cc_narrative, content_hash, hash_changed,
)

SCHEMA = "InstrumentRehydration@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0

# How far a defer pushes the next look when the operator gave no date. Long
# enough that the desk stops nagging, short enough that a quarter cannot pass
# unexamined.
DEFER_PUSH_DAYS = 7

# Observables whose movement overrides a cadence skip.
EVENT_HASHES = ("weight", "earnings")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def gate_input_from_record(
    record: Optional[dict[str, Any]],
    *,
    plan: Optional[dict[str, Any]] = None,
    observed: Optional[dict[str, Any]] = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Build the ResearchNeedDecision@v2 input from record + plan.

    The record supplies memory (eligibility, last outcome, hashes); the plan
    supplies this wake's facts (materiality, symbol, the fire). Where they
    disagree about WHEN to look again, the record wins — it is the thing that
    remembers the operator agreed to wait.
    """
    rec = record or {}
    pl = plan or {}
    obs = observed or {}

    event_forced = False
    for name in EVENT_HASHES:
        if name in obs and hash_changed(rec, name, obs[name]):
            event_forced = True
            break

    inp: dict[str, Any] = {
        "kind": pl.get("kind") or rec.get("kind") or "default",
        "symbol": (rec.get("symbols") or [None])[0] or pl.get("symbols", [None])[0],
        "plan_id": pl.get("plan_id") or (rec.get("last_operator_turn") or {}).get("plan_id"),
        "material": bool(pl.get("material")),
        # memory, not the plan
        "next_eligible_at": rec.get("next_eligible_at"),
        "prior_outcome": rec.get("last_outcome"),
        "prior_artifact_ids": [rec["last_artifact_id"]] if rec.get("last_artifact_id") else [],
        "content_hash": (rec.get("hashes") or {}).get("price"),
        # an observable that moved overrides the cadence skip
        "event_fired": event_forced,
    }
    if event_forced:
        # The gate skips on cadence before it looks at anything else, so the
        # override has to clear the date as well as set the flag.
        inp["next_eligible_at"] = None
    inp.update({k: v for k, v in overrides.items() if v is not None})
    return inp


def _defer_question(note: str) -> str:
    n = (note or "").strip().rstrip(".")
    return (f"Has a catalyst or earnings event changed the condition behind the "
            f"defer ({n})?" if n else
            "Has a catalyst or earnings event changed the deferred condition?")


def apply_after_cycle(
    record: dict[str, Any],
    *,
    lesson: Optional[dict[str, Any]] = None,
    artifact: Optional[dict[str, Any]] = None,
    decision: Optional[dict[str, Any]] = None,
    observed: Optional[dict[str, Any]] = None,
    operator_turn: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
    strict: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    """Apply one cycle's outcome as COGNITION. Returns (record, changed_fields).

    Raises CognitionNoOp under strict when the cycle moved nothing — which is
    the point: a wake that produced no change to what the desk will ask, when
    it will look, how loudly it will speak, or what it says, did not learn.
    """
    now = now or _now()
    rec = dict(record)

    nxt_q: Optional[str] = None
    nxt_at: Optional[str] = None
    narrative: Optional[dict[str, Any]] = None
    priority: Optional[str] = None
    outcome: Optional[str] = None
    artifact_id: Optional[str] = None
    hashes: dict[str, Any] = {}

    # ── rule 3 first: a moved observable outranks a defer ────────────────
    event_moved = None
    for name in EVENT_HASHES:
        if observed and name in observed and hash_changed(rec, name, observed[name]):
            event_moved = name
            break
    if observed:
        hashes.update({k: content_hash(v) for k, v in observed.items()})

    if event_moved:
        nxt_at = now.isoformat()          # due now; the cadence skip is void
        nxt_q = (f"{event_moved.capitalize()} changed since the last answer — "
                 f"does it change the thesis?")
        outcome = "event_override"

    # ── rule 2: a rejected or instruction-bearing artifact ───────────────
    elif artifact:
        verdict = str(artifact.get("verdict") or artifact.get("outcome") or "").upper()
        blocked = (verdict in {"REJECT", "REJECTED", "FAILED"}
                   or bool(artifact.get("execution_language"))
                   or "EXECUTION_LANGUAGE" in verdict)
        artifact_id = artifact.get("artifact_id") or artifact.get("research_id")
        if blocked:
            rec["research_blocked"] = True
            outcome = "execution_language" if "EXECUTION" in verdict or artifact.get(
                "execution_language") else "rejected"
            prev = str(rec.get("next_research_question") or "")
            # Must not be the same prompt. Re-asking a prompt that failed closed
            # is how a desk spends a budget learning nothing.
            nxt_q = (f"Prior research was refused ({outcome}). What INDEPENDENT "
                     f"evidence would settle this without restating it?")
            if nxt_q == prev:
                nxt_q = prev + " (reframed)"
            nxt_at = (now + timedelta(days=1)).isoformat()
        else:
            rec["research_blocked"] = False
            outcome = verdict.lower() or "attached"

    # ── rule 1: defer honored, no new catalyst ───────────────────────────
    if lesson and not event_moved:
        claim = str(lesson.get("claim") or "").lower()
        if "defer" in claim and ("no new catalyst" in claim or "no catalyst" in claim
                                 or "honored" in claim or "honoured" in claim):
            turn = operator_turn or rec.get("last_operator_turn") or {}
            note = str(turn.get("note") or lesson.get("note") or "").strip()
            nxt_q = _defer_question(note)
            nxt_at = (now + timedelta(days=DEFER_PUSH_DAYS)).isoformat()
            priority = "cc"
            old = dict(rec.get("cc_narrative") or {})
            what = str(old.get("what") or "")
            defer_line = (f"Operator deferred: {note}." if note
                          else "Operator deferred.")
            if not what.startswith("Operator deferred"):
                what = (defer_line + (f" {what}" if what else "")).strip()
            narrative = cc_narrative(
                what=what,
                thesis_fit=str(old.get("thesis_fit") or ""),
                recommendation_option_id=old.get("recommendation_option_id"),
                risks=list(old.get("risks") or []),
                evidence_refs=list(old.get("evidence_refs") or []),
                writer="cognition:defer_honored",
            )

    if decision and not nxt_at:
        nxt_at = decision.get("next_eligible_at")
        outcome = outcome or decision.get("decision")

    return apply_cognition(
        rec,
        next_research_question=nxt_q,
        next_eligible_at=nxt_at,
        notify_priority=priority,
        narrative=narrative,
        lesson=lesson,
        operator_turn=operator_turn,
        artifact_id=artifact_id,
        outcome=outcome,
        hashes=hashes or None,
        strict=strict,
    )


def attach_operator_turn(
    record: dict[str, Any],
    *,
    intent: str,
    text: str = "",
    plan_id: Optional[str] = None,
    ts: Optional[str] = None,
    now: Optional[datetime] = None,
    strict: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    """S0: a question/ack/defer lands on the RECORD and carries its plan_id.

    Attaching to the plan alone is what lost the SCHD defer: the plan closed
    and the disposition went with it.
    """
    now = now or _now()
    turn = {
        "intent": str(intent or "").lower(),
        "text_hash": content_hash(text),
        "note": text,
        "plan_id": plan_id,
        "ts": ts or now.isoformat(),
    }
    if turn["intent"] == "defer":
        return apply_after_cycle(
            record,
            lesson={"lesson_id": f"defer:{turn['text_hash']}",
                    "claim": "operator defer honored, no new catalyst"},
            operator_turn=turn, now=now, strict=strict)
    return apply_cognition(
        record,
        next_research_question=(f"Operator asked: {text}" if text else None),
        notify_priority="cc",
        operator_turn=turn,
        strict=strict,
    )
