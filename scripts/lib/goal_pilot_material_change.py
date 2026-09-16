"""P8 pilot — material-change corroboration, SHADOW only.

The plan's thesis, made concrete on one goal type: an agent stops because a
PREDICATE OVER EVIDENCE is satisfied, not because a step ran. Every term below
is already computed by shipped, free code; this module composes them and
refuses to invent the ones that are missing.

Three properties this file exists to guarantee, each with a control that goes
red if it is removed:

1. **A missing independent source is UNKNOWABLE, not false.**
   ``evaluate_predicate`` treats a supplied-and-false term as DECISIVE
   (``UNSATISFIED``) and an *absent* term as ``UNEVALUABLE``. Those are
   different claims. "No second source exists" is not "the second source
   disagreed", and asserting the latter would be a fabricated finding. So a
   term whose input is unobtainable is **omitted from the facts**, which routes
   the goal to ``bounded_ignorance`` — a statement of what is NOT knowable.

2. **The pilot cannot spend.** Tier 0 short-circuits before ``CriticPanel`` is
   constructed, so a deterministic block costs nothing; tier 2 is off by
   default (§17 — funding a paid judge is the operator's decision). The cost
   receipt carries ``paid_calls`` straight from the validator, not a constant.

3. **No sixth ID scheme.** Predicate identity is
   ``(goal_id, predicate_version, predicate_hash)`` via the existing helpers.

Authority: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0 — this decides nothing about
positions, sizes, orders or stops, and writes no broker state.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from scripts.lib.cio_goals import (  # noqa: E402
    TERMINATION_OUTCOMES,
    VERDICT_SATISFIED,
    VERDICT_UNEVALUABLE,
    VERDICT_UNSATISFIED,
    evaluate_predicate,
    predicate_hash,
    predicate_identity,
)

SCHEMA = "GoalPilotMaterialChange@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

#: The ONE evaluator cio_goals implements. Spelling anything else here would make
#: every pilot predicate permanently UNEVALUABLE — failing closed, but useless.
PILOT_EVALUATOR = "all_terms_true@v1"

#: The nine conditions. Order is stable because predicate_hash covers the terms:
#: reordering them would mint a different predicate identity for the same meaning.
TERM_SUBJECT_LINKED = "subject_linked"
TERM_INDEPENDENT_PRESENT = "independent_value_present"
TERM_AGREES = "agrees_corroborated"
TERM_NOT_UNCORROBORATED = "not_uncorroborated"
TERM_TIER0 = "tier0_deterministic_pass"
TERM_TIER1 = "tier1_reconciled"
TERM_CALIBRATED = "validator_calibrated"
TERM_FALSIFIER = "falsifier_non_vacuous"
TERM_CHECKPOINT = "checkpoint_bound"
TERM_SECOND_LAP = "second_lap_distinct_dedup_key"

PILOT_TERMS: tuple[str, ...] = (
    TERM_SUBJECT_LINKED,
    TERM_INDEPENDENT_PRESENT,
    TERM_AGREES,
    TERM_NOT_UNCORROBORATED,
    TERM_TIER0,
    TERM_TIER1,
    TERM_CALIBRATED,
    TERM_FALSIFIER,
    TERM_CHECKPOINT,
    TERM_SECOND_LAP,
)

#: Terms whose inputs can be genuinely UNOBTAINABLE rather than merely false.
#: A symbol with no independently-written second source is the canonical case:
#: material_change_detector.agrees() returns "no_independent_source" for it, and
#: the correct response is to state that we cannot know — not to alarm, and not
#: to claim disagreement.
UNOBTAINABLE_CAPABLE: frozenset[str] = frozenset({
    TERM_INDEPENDENT_PRESENT,
    TERM_AGREES,
    TERM_CHECKPOINT,
    TERM_SECOND_LAP,
})

#: agrees() reasons that mean "we could not obtain a second source", as opposed
#: to "we obtained one and it disagreed". Only the former is bounded ignorance.
UNOBTAINABLE_REASONS: frozenset[str] = frozenset({
    "no_independent_source",
})

OUTCOME_SUFFICIENT = "sufficient"
OUTCOME_BOUNDED_IGNORANCE = "bounded_ignorance"
OUTCOME_BUDGET_EXHAUSTED = "budget_exhausted"
OUTCOME_NO_NEW_EVIDENCE = "no_new_evidence"
OUTCOME_ASK_OPERATOR = "ask_operator"

#: Tiered states that are NOT a clean reconciliation.
UNRECONCILED_STATES: frozenset[str] = frozenset({
    "DISAGREEMENT",
    "INSUFFICIENT_EVIDENCE",
    "PARTIAL_PROVIDER_FAILURE",
    "BLOCK_DETERMINISTIC",
})


def build_predicate(*, goal_id: str, predicate_version: int = 1) -> dict[str, Any]:
    """The pilot's predicate, with identity rooted in the goal's own id."""
    phash = predicate_hash(PILOT_EVALUATOR, list(PILOT_TERMS))
    return {
        "schema": SCHEMA,
        "evaluator": PILOT_EVALUATOR,
        "terms": list(PILOT_TERMS),
        "predicate_version": int(predicate_version),
        "predicate_hash": phash,
        "predicate_identity": predicate_identity(goal_id, predicate_version, phash),
    }


def _agrees(observed: float, independent: Optional[float],
            agrees_fn: Optional[Callable[..., tuple[bool, str]]] = None) -> tuple[bool, str]:
    """Delegate to the shipped detector. Imported lazily so this module stays
    importable with no database and no .env — the detector is a script."""
    if agrees_fn is not None:
        return agrees_fn(observed, independent)
    from scripts.material_change_detector import agrees as _real  # noqa: PLC0415
    return _real(observed, independent)


def assemble_facts(
    change: Mapping[str, Any],
    *,
    independent: Optional[float],
    tiered: Any = None,
    calibrated: Optional[bool] = None,
    falsifier_ok: Optional[bool] = None,
    checkpoint: Optional[Mapping[str, Any]] = None,
    second_lap: Optional[bool] = None,
    agrees_fn: Optional[Callable[..., tuple[bool, str]]] = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build the facts dict, OMITTING every term whose input is unobtainable.

    Returns ``(facts, unobtainable)`` where ``unobtainable`` maps term -> reason.
    An omitted term is the whole mechanism by which this pilot reports "not
    knowable" instead of manufacturing a verdict, so nothing here defaults a
    missing input to False.
    """
    facts: dict[str, Any] = {}
    unobtainable: dict[str, str] = {}

    facts[TERM_SUBJECT_LINKED] = bool(change.get("subject_guid"))

    observed = change.get("change_pct")
    if independent is None:
        # With no second source, "is it uncorroborated?" is ALSO unknowable --
        # not false. Marking only two of these three unobtainable left the third
        # merely missing, which routed a genuinely unknowable case to
        # `ask_operator` instead of `bounded_ignorance`. Caught by
        # test_missing_independent_source_terminates_bounded_ignorance_never_achieved.
        unobtainable[TERM_INDEPENDENT_PRESENT] = "no_independent_source"
        unobtainable[TERM_AGREES] = "no_independent_source"
        unobtainable[TERM_NOT_UNCORROBORATED] = "no_independent_source"
    else:
        facts[TERM_INDEPENDENT_PRESENT] = True
        ok, why = _agrees(float(observed or 0.0), float(independent), agrees_fn)
        if why in UNOBTAINABLE_REASONS:
            unobtainable[TERM_AGREES] = why
            unobtainable[TERM_NOT_UNCORROBORATED] = why
        else:
            # A source that disagrees is DECISIVE: both terms are supplied-and-false,
            # which is UNSATISFIED, not unknowable.
            facts[TERM_AGREES] = bool(ok)
            facts[TERM_NOT_UNCORROBORATED] = bool(ok)

    if tiered is not None:
        facts[TERM_TIER0] = bool(getattr(tiered, "deterministic_release_allowed", False))
        state = str(getattr(tiered, "state", ""))
        facts[TERM_TIER1] = state not in UNRECONCILED_STATES
        blind = tuple(getattr(tiered, "blind_lanes", ()) or ())
        if calibrated is None:
            facts[TERM_CALIBRATED] = not blind
    if calibrated is not None:
        facts[TERM_CALIBRATED] = bool(calibrated)

    if falsifier_ok is not None:
        facts[TERM_FALSIFIER] = bool(falsifier_ok)

    if checkpoint is None:
        unobtainable[TERM_CHECKPOINT] = "no_checkpoint_bound"
    else:
        facts[TERM_CHECKPOINT] = bool(checkpoint.get("due_at"))

    if second_lap is None:
        unobtainable[TERM_SECOND_LAP] = "loop_not_available"
    else:
        facts[TERM_SECOND_LAP] = bool(second_lap)

    return facts, unobtainable


def classify_outcome(
    verdict: Mapping[str, Any],
    *,
    unobtainable: Mapping[str, str],
    budget_exhausted: bool = False,
    ledger_digest_unchanged: bool = False,
) -> str:
    """Map a predicate verdict onto exactly one termination outcome.

    Only SATISFIED reaches ``sufficient``. UNEVALUABLE whose every missing term
    is unobtainable is ``bounded_ignorance`` — the goal states what is not
    knowable rather than closing on an assumption.
    """
    v = str(verdict.get("verdict") or "")
    if budget_exhausted:
        return OUTCOME_BUDGET_EXHAUSTED
    if v == VERDICT_SATISFIED:
        return OUTCOME_SUFFICIENT
    if v == VERDICT_UNSATISFIED:
        return OUTCOME_ASK_OPERATOR
    if v == VERDICT_UNEVALUABLE:
        missing = _missing_terms(verdict)
        if missing and all(t in unobtainable for t in missing):
            return OUTCOME_BOUNDED_IGNORANCE
        if ledger_digest_unchanged:
            return OUTCOME_NO_NEW_EVIDENCE
        return OUTCOME_ASK_OPERATOR
    return OUTCOME_ASK_OPERATOR


def _missing_terms(verdict: Mapping[str, Any]) -> list[str]:
    reason = str(verdict.get("reason") or "")
    if not reason.startswith("missing_facts:"):
        return []
    return [t for t in reason.split(":", 1)[1].split(",") if t]


def run_pilot(
    change: Mapping[str, Any],
    *,
    goal_id: str,
    independent: Optional[float],
    tiered: Any = None,
    calibrated: Optional[bool] = None,
    falsifier_ok: Optional[bool] = None,
    checkpoint: Optional[Mapping[str, Any]] = None,
    second_lap: Optional[bool] = None,
    budget_exhausted: bool = False,
    ledger_digest_unchanged: bool = False,
    agrees_fn: Optional[Callable[..., tuple[bool, str]]] = None,
) -> dict[str, Any]:
    """One SHADOW lap over one material change. Writes nothing."""
    predicate = build_predicate(goal_id=goal_id)
    facts, unobtainable = assemble_facts(
        change, independent=independent, tiered=tiered, calibrated=calibrated,
        falsifier_ok=falsifier_ok, checkpoint=checkpoint, second_lap=second_lap,
        agrees_fn=agrees_fn,
    )
    verdict = evaluate_predicate(predicate, facts)
    outcome = classify_outcome(
        verdict, unobtainable=unobtainable,
        budget_exhausted=budget_exhausted,
        ledger_digest_unchanged=ledger_digest_unchanged,
    )
    if outcome not in TERMINATION_OUTCOMES:  # pragma: no cover - guards a typo
        raise ValueError(f"outcome {outcome!r} is not one of {sorted(TERMINATION_OUTCOMES)}")
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "mode": "SHADOW",
        "goal_id": goal_id,
        "change_guid": change.get("change_guid"),
        "subject_guid": change.get("subject_guid"),
        "predicate_identity": predicate["predicate_identity"],
        "verdict": verdict,
        "facts": facts,
        "unobtainable": dict(unobtainable),
        "outcome": outcome,
        "achieved": outcome == OUTCOME_SUFFICIENT,
        "cost": {
            "paid_calls": int(getattr(tiered, "paid_calls", 0) or 0),
            "critic_calls": int(getattr(tiered, "critic_calls", 0) or 0),
            "cost_usd": float(getattr(tiered, "cost_usd", 0.0) or 0.0),
        },
    }


def pilot_cost(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate cost receipt. `paid_calls: 0` is the plan's pass condition."""
    rows = list(rows)
    return {
        "schema": "GoalPilotCost@v1",
        "laps": len(rows),
        "paid_calls": sum(int((r.get("cost") or {}).get("paid_calls", 0)) for r in rows),
        "critic_calls": sum(int((r.get("cost") or {}).get("critic_calls", 0)) for r in rows),
        "cost_usd": round(sum(float((r.get("cost") or {}).get("cost_usd", 0.0)) for r in rows), 6),
    }
