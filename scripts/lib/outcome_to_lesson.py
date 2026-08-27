"""OutcomeToLesson@v1 — turn recorded outcomes into lesson candidates.

The lesson lane is busy and healthy: 1,617 lessons, 1,467 applications, active
yesterday. **Not one of them references an outcome.** They come from the
advisory knowledge base, so the system has been learning from something other
than its own recorded results — which looks like a working feedback loop from
outside and is not one.

`lesson_candidate_v2` already models the link, with `supporting_outcome_ids` and
real epistemic discipline: PROVISIONAL below `MIN_LESSON_SAMPLES`, PROVISIONAL
if counterexamples were never searched, CONTRADICTED when they outweigh support.
Its only caller is a demo endpoint. This module is the real one.

## The trap this exists to avoid

`lesson_candidate_v2` decides status from `len(supporting_outcome_ids)`. The
first five outcomes the resolver produced were five distinct `decision_id`s
that were all **SCHD / TRIM / decided 2026-08-26 / 1_session / +0.314%** — one
event observed five times. Passing all five would have hit
`MIN_LESSON_SAMPLES = 5` exactly and stamped the lesson **SUPPORTED**, asserting
n=5 when the effective n is 1.

That is pseudo-replication, and it is worse than having no lesson: a confident
false generalisation is indistinguishable from a real one downstream.

So the epistemics function is not changed. It is fed correct input instead: one
representative outcome per **independent** observation, with the correlated
siblings recorded alongside so nothing is hidden.

AUTHORITY: READ_ONLY_ADVISORY. Observational; proposes candidates, ratifies
nothing.
"""
from __future__ import annotations

from typing import Any, Iterable

SCHEMA = "OutcomeToLesson@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0


def observation_key(observation: dict[str, Any]) -> tuple[str, str, str, str]:
    """What makes two outcomes the *same* observation rather than two samples.

    Same subject, same decision date, same horizon means one event measured
    once — however many decision_ids it carries. The recommendation is included
    because the same security decided differently on the same day genuinely is
    two observations.
    """
    realized = observation.get("realized_state") or {}
    return (
        str(realized.get("symbol") or observation.get("subject_guid") or ""),
        str(realized.get("recommendation") or ""),
        str(realized.get("decision_price_date") or ""),
        str(observation.get("horizon") or ""),
    )


def independent_groups(observations: Iterable[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group correlated observations. Each group counts as ONE sample."""
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for obs in observations:
        groups.setdefault(observation_key(obs), []).append(obs)
    return [groups[k] for k in sorted(groups)]


def _direction(change_pct: float | None, recommendation: str) -> str | None:
    """Did the move go the way the recommendation implied?

    Deliberately narrow: only recommendations with an unambiguous directional
    reading are scored. A HOLD or WAIT has no implied direction, and inventing
    one would manufacture a result.
    """
    if change_pct is None:
        return None
    rec = str(recommendation or "").upper()
    if rec in {"TRIM", "SELL", "SELL_TAXABLE", "REDUCE"}:
        return "CONFIRMED" if change_pct < 0 else "CONTRADICTED"
    if rec in {"BUY", "ADD", "ACCUMULATE"}:
        return "CONFIRMED" if change_pct > 0 else "CONTRADICTED"
    return None


def build_candidates(
    observations: list[dict[str, Any]],
    *,
    searched_counterexamples: bool = True,
) -> list[dict[str, Any]]:
    """Lesson candidates keyed on (scope, task_class), one per recommendation.

    `searched_counterexamples` is passed through honestly: this scans the whole
    supplied observation set for contradicting cases, so it is True when the
    caller hands over the full corpus and must be False when it hands a slice.
    """
    from scripts.lib.cio_institutional_learning import lesson_candidate_v2

    by_task: dict[tuple[str, str], list[list[dict[str, Any]]]] = {}
    for group in independent_groups(observations):
        realized = group[0].get("realized_state") or {}
        symbol = str(realized.get("symbol") or "")
        rec = str(realized.get("recommendation") or "")
        if not symbol or not rec:
            continue
        by_task.setdefault((symbol, rec), []).append(group)

    candidates = []
    for (symbol, rec), groups in sorted(by_task.items()):
        supporting: list[str] = []
        counterexamples: list[str] = []
        correlated: list[str] = []
        moves: list[float] = []

        for group in groups:
            # One representative per independent observation. The rest are
            # recorded, not counted — that is the whole point.
            representative = group[0]
            oid = str(representative.get("outcome_id") or "")
            correlated.extend(str(o.get("outcome_id")) for o in group[1:] if o.get("outcome_id"))

            realized = representative.get("realized_state") or {}
            change = realized.get("change_pct")
            if isinstance(change, (int, float)):
                moves.append(float(change))
            verdict = _direction(change, rec)
            if verdict == "CONTRADICTED":
                counterexamples.append(oid)
            elif verdict == "CONFIRMED" and oid:
                supporting.append(oid)

        if not supporting and not counterexamples:
            continue  # no directional reading; nothing honest to say

        avg = round(sum(moves) / len(moves), 3) if moves else None
        # The statement must read the move RELATIVE to what the recommendation
        # implied. A TRIM followed by a price rise is the decision looking
        # wrong, not a "favourable move" -- describing it as favourable would
        # invert the lesson, which is the failure this whole lane guards
        # against.
        if counterexamples and not supporting:
            verdict = "did not hold"
        elif supporting and not counterexamples:
            verdict = "held"
        else:
            verdict = "held inconsistently"
        statement = (
            f"{rec} on {symbol} {verdict}: the subsequent move averaged "
            f"{avg}% over the observed horizon, across "
            f"{len(supporting) + len(counterexamples)} independent observation(s)."
        )
        candidate = lesson_candidate_v2(
            scope=symbol,
            task_class=rec,
            statement=statement,
            supporting_outcome_ids=supporting,
            counterexamples=counterexamples,
            searched_counterexamples=searched_counterexamples,
            confidence=0.5,
        )
        # Everything the status did NOT count, kept visible.
        candidate["correlated_outcome_ids"] = correlated
        candidate["independent_samples"] = len(supporting) + len(counterexamples)
        candidate["total_observations"] = (
            len(supporting) + len(counterexamples) + len(correlated)
        )
        candidate["authority"] = AUTHORITY
        candidate["memory_behavior_influence"] = MBI
        candidate["observational_only"] = True
        candidates.append(candidate)

    return candidates
