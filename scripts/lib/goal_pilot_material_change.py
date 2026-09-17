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
#:
#: ENFORCED by assemble_facts, not merely declared. Until 2026-09-17 this set had
#: zero readers — a constant naming a policy nothing checked, which is the
#: "named like a control, isn't one" pattern this programme exists to remove.
UNOBTAINABLE_CAPABLE: frozenset[str] = frozenset({
    TERM_INDEPENDENT_PRESENT,
    TERM_AGREES,
    TERM_NOT_UNCORROBORATED,
    TERM_TIER0,
    TERM_TIER1,
    TERM_CALIBRATED,
    TERM_FALSIFIER,
    TERM_CHECKPOINT,
    TERM_SECOND_LAP,
})

#: `material_changes.kind` values whose `magnitude` is a PRICE PERCENT MOVE, and
#: therefore comparable against `corroborate()`, which returns
#: `max(abs(change_pct))` from watchlist_items. Every other kind carries a
#: different unit — a news_burst `magnitude` is a burst score (measured range
#: 3.18 to 90.00) and its `observed_value` is a headline count. The shipped
#: detector only ever calls `agrees()` on price-excursion candidates; this set
#: keeps that restriction when the pilot generalises over all kinds.
PRICE_COMPARABLE_KINDS: frozenset[str] = frozenset({"price_excursion"})

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
    independent_reason: str = "no_independent_source",
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
    if independent is None and independent_reason != "no_independent_source":
        # A named reason distinguishes "no second source exists" from "no
        # COMPARABLE second source exists". Adversarial review 2026-09-17 found
        # the driver comparing a news-burst score (90.0) against a price percent
        # move (0.78) and recording `disagree_90.00_vs_0.78` — a fabricated
        # operator finding, from two quantities that were never in the same
        # units. Both are unknowable; only one is "nobody published a second
        # source". Conflating them is how six corrupt rows became six alerts.
        unobtainable[TERM_INDEPENDENT_PRESENT] = independent_reason
        unobtainable[TERM_AGREES] = independent_reason
        unobtainable[TERM_NOT_UNCORROBORATED] = independent_reason
    elif independent is None:
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
    else:
        # No validator ran. Silently omitting these left them missing-but-not-
        # unobtainable, so classify_outcome could not tell "we could not check"
        # from "we forgot to record a check" and fell through to ask_operator.
        # Every absent term must carry a REASON, exactly as checkpoint and
        # second_lap already do below. Measured 2026-09-17: the driver returned
        # ask_operator for a change with no independent source, which is the one
        # case bounded_ignorance exists to describe.
        unobtainable[TERM_TIER0] = "no_validator_run"
        unobtainable[TERM_TIER1] = "no_validator_run"

    if calibrated is not None:
        facts[TERM_CALIBRATED] = bool(calibrated)
    elif TERM_CALIBRATED not in facts:
        unobtainable[TERM_CALIBRATED] = "no_calibration_window"

    if falsifier_ok is not None:
        facts[TERM_FALSIFIER] = bool(falsifier_ok)
    else:
        unobtainable[TERM_FALSIFIER] = "no_falsifier_supplied"

    if checkpoint is None:
        unobtainable[TERM_CHECKPOINT] = "no_checkpoint_bound"
    else:
        facts[TERM_CHECKPOINT] = bool(checkpoint.get("due_at"))

    if second_lap is None:
        unobtainable[TERM_SECOND_LAP] = "loop_not_available"
    else:
        facts[TERM_SECOND_LAP] = bool(second_lap)

    # The set is the authority, so a term reported unknowable must be one the
    # design admits can be unknowable. `subject_linked` never can: it is read
    # straight off the change row, so an "unobtainable" there would mean the
    # driver lost its own input and should fail loudly, not report ignorance.
    rogue = sorted(set(unobtainable) - UNOBTAINABLE_CAPABLE)
    if rogue:
        raise ValueError(
            f"terms marked unobtainable but not in UNOBTAINABLE_CAPABLE: {rogue}")

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
    independent_reason: str = "no_independent_source",
) -> dict[str, Any]:
    """One SHADOW lap over one material change. Writes nothing."""
    predicate = build_predicate(goal_id=goal_id)
    facts, unobtainable = assemble_facts(
        change, independent=independent, tiered=tiered, calibrated=calibrated,
        falsifier_ok=falsifier_ok, checkpoint=checkpoint, second_lap=second_lap,
        agrees_fn=agrees_fn, independent_reason=independent_reason,
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


def run_shadow(
    *,
    limit: int = 25,
    hours: int = 24,
    conn: Any = None,
) -> dict[str, Any]:
    """Drive the pilot over recent material changes. SHADOW; writes nothing here.

    This is the API `scripts/run_goal_pilot_material_change.py` probes for with
    ``hasattr(pilot, "run_shadow")``. Until it existed the armed hourly cron wrote
    ``status: "library_loaded"`` and evaluated NOTHING — a scheduled job proving
    invocation rather than work, which is the exact defect this programme exists
    to remove. 14 receipts looked healthy (``ok: true``) while carrying no verdict.

    Two honesty rules, both load-bearing:

    * **No database is `unavailable`, never an empty pass.** A driver that cannot
      read `material_changes` has measured nothing; reporting ``laps: 0`` would be
      indistinguishable from "there were no changes".
    * **Tier-1 validation and the multi-lap loop are not wired to this driver**,
      so `assemble_facts` records those terms as UNOBTAINABLE with a named reason
      and the goal terminates ``bounded_ignorance`` — stating what is not yet
      knowable rather than asserting a check that never ran.

    Independence is real: the observed move comes from `material_changes`, the
    corroborating value from `corroborate()` reading `watchlist_items` — a
    DIFFERENT pipeline, which is what makes the second source independent rather
    than the same number fetched twice.
    """
    owns_conn = conn is None
    if conn is None:
        try:
            from scripts.material_change_detector import _db  # noqa: PLC0415
            conn = _db()
        except Exception as exc:  # noqa: BLE001
            return {
                "schema": SCHEMA,
                "authority": AUTHORITY,
                "mode": "SHADOW",
                "status": "unavailable",
                "why": f"no database: {type(exc).__name__}: {exc}"[:200],
                "laps": 0,
                "cost": {"paid_calls": 0, "critic_calls": 0, "cost_usd": 0.0},
            }
    try:
        from scripts.material_change_detector import corroborate  # noqa: PLC0415
        with conn.cursor() as cur:
            cur.execute(
                """SELECT change_guid, subject_guid, symbol, kind, magnitude,
                          baseline, observed_value, observed_at
                     FROM material_changes
                    WHERE subject_guid IS NOT NULL
                      AND observed_at > NOW() - INTERVAL '%s hours'
                    ORDER BY observed_at DESC
                    LIMIT %s""",
                (int(hours), int(limit)),
            )
            cols = ("change_guid", "subject_guid", "symbol", "kind", "magnitude",
                    "baseline", "observed_value", "observed_at")
            changes = [dict(zip(cols, r)) for r in cur.fetchall()]
            # Only price-comparable kinds may be corroborated against
            # corroborate(), which returns a PRICE percent move. Asking for the
            # others would compare a burst score to a percent.
            price_symbols = sorted({
                str(c["symbol"]).upper() for c in changes
                if c.get("symbol") and str(c.get("kind") or "") in PRICE_COMPARABLE_KINDS
            })
            independent = corroborate(cur, price_symbols) if price_symbols else {}
    except Exception as exc:  # noqa: BLE001
        # A query that failed measured NOTHING. Letting this propagate meant the
        # runner caught it and still wrote an envelope with a hardcoded
        # `ok: true` and no verdict — the precise "14 receipts, no verdict"
        # defect this driver exists to end, recurring on the first schema drift
        # or statement timeout. Same shape as the no-connection branch above.
        return {
            "schema": SCHEMA,
            "authority": AUTHORITY,
            "mode": "SHADOW",
            "status": "unavailable",
            "why": f"query failed: {type(exc).__name__}: {exc}"[:200],
            "laps": 0,
            "changes_read": 0,
            "not_price_comparable": 0,
            "independent_found": 0,
            "outcomes": {},
            "achieved": 0,
            "cost": {"paid_calls": 0, "critic_calls": 0, "cost_usd": 0.0},
            "rows": [],
        }
    finally:
        if owns_conn:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    rows: list[dict[str, Any]] = []
    not_comparable = 0
    for c in changes:
        sym = str(c.get("symbol") or "").upper()
        kind = str(c.get("kind") or "")
        comparable = kind in PRICE_COMPARABLE_KINDS
        observed = c.get("magnitude")
        if observed is None:
            observed = c.get("observed_value")
        change = {
            "change_guid": str(c.get("change_guid") or ""),
            "subject_guid": str(c.get("subject_guid") or ""),
            "symbol": sym,
            "kind": kind,
            "change_pct": float(observed) if observed is not None else 0.0,
        }
        if comparable:
            indep, reason = independent.get(sym), "no_independent_source"
        else:
            # `magnitude` for a news_burst is a burst score, not a percent.
            # Measured 2026-09-17: burst 90.00 vs price 0.78 produced
            # `disagree_90.00_vs_0.78` — a fabricated operator finding from two
            # quantities never in the same units. 81% of rows over 30 days.
            indep, reason = None, f"kind_not_price_comparable:{kind or 'unknown'}"
            not_comparable += 1
        rows.append(run_pilot(
            change,
            goal_id=f"pilot:{change['subject_guid'] or sym}",
            independent=indep,
            independent_reason=reason,
            tiered=None, calibrated=None, falsifier_ok=None,
            checkpoint=None, second_lap=None,
        ))

    outcomes: dict[str, int] = {}
    for r in rows:
        outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "mode": "SHADOW",
        "status": "ok",
        "laps": len(rows),
        "changes_read": len(changes),
        "not_price_comparable": not_comparable,
        "independent_found": sum(
            1 for c in changes
            if str(c.get("kind") or "") in PRICE_COMPARABLE_KINDS
            and independent.get(str(c.get("symbol") or "").upper()) is not None),
        "outcomes": outcomes,
        # Structurally 0 until tier-1 validation, calibration, a falsifier and
        # the multi-lap loop are wired to this driver: `evaluate_predicate`
        # requires EVERY term supplied and true, and this driver supplies none
        # of those four. Only bounded_ignorance and ask_operator are reachable.
        "achieved": sum(1 for r in rows if r.get("achieved")),
        "cost": pilot_cost(rows),
        "rows": rows,
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
