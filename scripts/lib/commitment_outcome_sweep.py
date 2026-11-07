"""Revisit governed commitments after their horizon, and score them.

The gap this closes
-------------------
The L4 contract already existed and is sound: `governed_commitment.py` defines
GovernedCommitmentOutcome@v1, the CONFIRMED/REFUTED/EXPIRED/INSUFFICIENT_EVIDENCE
vocabulary, a freeze rule, a prohibition on self-evaluation, and an append-only
ledger helper that preserves refuted outcomes. `prior_calibration_v1` scores
them. None of that was missing.

What was missing is *later*. `evaluate_outcome` had exactly one caller --
`cortex_shadow_pipeline` -- which invokes it on the same line that mints the
commitment, passing whatever observation it happened to hold at freeze time. A
seven-day prediction was therefore "scored" the instant it was made, and no
scheduled job anywhere re-examined it:

    cron entries running an outcome evaluator over due commitments   0
    systemd units doing so                                           0
    (tradeai-advisory-outcome-scorer is the advisory desk's 30/60/90d
     scorer and references governed commitments zero times)

So of 224 durable commitments, 0 carried any outcome field -- not because
there was nowhere to put one, but because nothing ever looked again. The loop
was broken at the join to later outcomes, not at the schema.

What this module does, and deliberately does not do
---------------------------------------------------
Selects commitments whose due_at has passed and which have no settled outcome
in the ledger, asks a DETERMINISTIC observation provider what actually happened,
and appends an immutable outcome record joined by commitment_id.

It never mutates a commitment: a frozen prediction stays exactly as written,
including when it is refuted. Refuted outcomes are preserved and are never
rewritten. No model is consulted -- an outcome is a question about what
happened, and an LLM is not truth for market, position or account state. And it
produces candidate lessons only, marked PROPOSED, which change no production
behaviour and require a separate ratification this module cannot issue.

Unfalsifiable claims are reported, not quietly passed
----------------------------------------------------
96 of the 224 live commitments carry the template claim "Scheduled persistent
wake reviewed subject <GUID>; advisory observation only" with the falsifier
"observation contradicts claim within horizon". That asserts only that a review
occurred, so no observation could ever contradict it. Scoring such a row
CONFIRMED would manufacture a success rate out of boilerplate, so it is scored
INSUFFICIENT_EVIDENCE with reason `claim_not_falsifiable` and counted
separately. A calibration curve built from unfalsifiable claims is worse than
no curve.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from scripts.lib.governed_commitment import (
    OUTCOME_SCHEMA,
    UNSCOREABLE,
    durable_outcome_ledger_append,
    evaluate_outcome,
    claim_is_falsifiable,
    horizon_closes_at,
    is_prediction,  # public compatibility import

)

AUTHORITY = "READ_ONLY_ADVISORY"
LESSON_SCHEMA = "LessonCandidate@v1"
SWEEP_SCHEMA = "CommitmentOutcomeSweep@v1"

SETTLED = ("CONFIRMED", "REFUTED", "EXPIRED")
#: Outcomes after which a commitment is never re-evaluated. UNSCOREABLE is
#: terminal but is not a score: it never counts toward `scored`, calibration or
#: lessons (2026-10-09; 883 template rows were re-evaluated nightly forever).
TERMINAL = SETTLED + (UNSCOREABLE,)

#: A claim that only asserts its own occurrence cannot be contradicted by any
#: later observation. Matched on the live template, not invented: 96 of 224
#: commitments are this exact shape.


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")




def _lesson_id(commitment_id: str, outcome: str) -> str:
    return "lsn_" + hashlib.sha256(f"{commitment_id}|{outcome}".encode()).hexdigest()[:24]


def build_lesson_candidate(
    commitment: Mapping[str, Any], outcome: Mapping[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """A PROPOSED lesson. Never a rule, never applied, never self-ratified.

    `status` starts and stays PROPOSED here. Ratification is a separate act by a
    different identity -- this module cannot perform it, which is the point:
    an agent may not validate its own artifact.
    """
    when = now or _now()
    cid = str(commitment.get("commitment_id") or "")
    verdict = str(outcome.get("outcome") or "")
    return {
        "schema_version": LESSON_SCHEMA,
        "lesson_id": _lesson_id(cid, verdict),
        "authority": AUTHORITY,
        "mbi_behavior": 0,
        "status": "PROPOSED",
        "commitment_id": cid,
        "subject_guid": commitment.get("subject_guid"),
        "outcome": verdict,
        "observed_claim": commitment.get("claim"),
        "stated_falsifier": commitment.get("falsifier"),
        "stated_confidence": commitment.get("confidence"),
        "proposed_lesson": (
            f"A commitment held at confidence {commitment.get('confidence')} was "
            f"{verdict.lower()} at its horizon. Review whether the stated falsifier "
            "was the right observable before trusting that confidence again."
        ),
        "ratified_by": None,
        "ratified_at": None,
        "outcome_evidence_refs": (outcome.get("observation") or {}).get("source_refs") or [],
        "advisory_use": {"state": "NOT_YET_OBSERVED", "broker_behavior_authorized": False},
        "rejected_by": None,
        "rejected_at": None,
        "produced_at": _iso(when),
        "changes_production_behaviour": False,
        # Read by outcome_to_lesson.project_lesson_provenance: this lesson exists
        # because a settled outcome (CONFIRMED / REFUTED) was observed, not
        # because research suggested it. Was unset before 2026-09-24.
        "lesson_provenance": "OUTCOME_DERIVED",
        "supporting_outcome_ids": [str(oid)] if (oid := (outcome.get("outcome_id") or outcome.get("idempotency_key"))) else [],
    }


@dataclass
class SweepResult:
    scanned: int = 0
    due: int = 0
    already_settled: int = 0
    scored: int = 0
    unfalsifiable: int = 0
    unscoreable: int = 0
    horizon_guarded: int = 0
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    lessons: list[dict[str, Any]] = field(default_factory=list)
    by_outcome: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SWEEP_SCHEMA,
            "authority": AUTHORITY,
            "mbi_behavior": 0,
            "scanned": self.scanned,
            "due": self.due,
            "already_settled": self.already_settled,
            "scored": self.scored,
            "unfalsifiable": self.unfalsifiable,
            "unscoreable": self.unscoreable,
            "horizon_guarded": self.horizon_guarded,
            "by_outcome": dict(self.by_outcome),
            "lessons_proposed": len(self.lessons),
            "financial_action": False,
        }


def no_observation_provider(_commitment: Mapping[str, Any]) -> dict[str, Any]:
    """Default provider: knows nothing, and says so.

    Returning {} rather than a fabricated verdict is deliberate. With no
    observation and a passed due date, evaluate_outcome returns EXPIRED, which
    is the truthful statement that the horizon closed unobserved. Inventing
    `confirmed: True` here would be exactly the manufactured evidence this
    campaign is forbidden to produce.
    """
    return {}


def sweep_due_commitments(
    commitments: Iterable[Mapping[str, Any]],
    *,
    ledger: list[dict[str, Any]] | None = None,
    observation_provider: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None,
    now: datetime | None = None,
    evaluator_identity: str = "deterministic_neutral",
) -> SweepResult:
    when = now or _now()
    provider = observation_provider or no_observation_provider
    led = list(ledger or [])
    settled_ids = {
        str(row.get("commitment_id"))
        for row in led
        if str(row.get("outcome") or "") in TERMINAL
    }
    res = SweepResult()

    for commitment in commitments:
        res.scanned += 1
        due = _parse_ts(commitment.get("due_at"))
        if due is None:
            continue
        # 2026-10-09: never close a window before created_at + horizon. The
        # cortex producer minted due_at = now+7d whatever the horizon, so a 14d
        # claim (XLB, gcmt_c300f64e4756a9b68285d474) was due at half-time. The
        # frozen row is not rewritten; the sweep reads the later of the two.
        closes = horizon_closes_at(commitment)
        effective_due = max(due, closes) if closes is not None else due
        if effective_due > when:
            if due <= when:
                res.horizon_guarded += 1
            continue
        res.due += 1
        cid = str(commitment.get("commitment_id") or "")
        if cid in settled_ids:
            res.already_settled += 1
            continue
        # Provider and evaluator see the effective window close (an in-memory
        # view; the commitment itself is never mutated).
        scoring_view: Mapping[str, Any] = commitment
        if effective_due != due:
            scoring_view = {**commitment, "due_at": _iso(effective_due),
                            "minted_due_at": commitment.get("due_at")}

        ok, reason = claim_is_falsifiable(commitment)
        marker = commitment.get("scoreability")
        unscoreable_reason = None
        if not ok:
            unscoreable_reason = f"claim_not_falsifiable:{reason}"
        elif isinstance(marker, Mapping) and str(marker.get("state") or "") == UNSCOREABLE:
            unscoreable_reason = f"unscoreable_at_mint:{marker.get('reason') or 'unspecified'}"
        if unscoreable_reason is not None:
            # Terminal and append-only: one row, then the commitment is in
            # settled_ids and is never re-evaluated. A legacy
            # INSUFFICIENT_EVIDENCE/claim_not_falsifiable row is left untouched.
            outcome = {
                "schema_version": OUTCOME_SCHEMA,
                "commitment_id": cid,
                "outcome": UNSCOREABLE,
                "errors": [unscoreable_reason],
                "evaluated_at": _iso(when),
                "evaluator_identity": evaluator_identity,
                "authority": AUTHORITY,
                "mbi_behavior": 0,
                "idempotency_key": hashlib.sha256(
                    f"{cid}|{UNSCOREABLE}|{unscoreable_reason}".encode()
                ).hexdigest()[:32],
            }
        else:
            try:
                observation = provider(scoring_view)
            except Exception as exc:
                observation = {"available": False, "reason": "observation_provider_unavailable:" + type(exc).__name__}
            outcome = evaluate_outcome(
                dict(scoring_view),
                observation=observation,
                now=when,
                evaluator_identity=evaluator_identity,
            )

        before = len(led)
        led = durable_outcome_ledger_append(led, outcome)
        if len(led) > before:
            res.outcomes.append(outcome)
            verdict = str(outcome.get("outcome") or "")
            res.by_outcome[verdict] = res.by_outcome.get(verdict, 0) + 1
            if verdict == UNSCOREABLE:
                settled_ids.add(cid)
                res.unscoreable += 1
                # Counted after dedupe (was before it: the same 883 rows were
                # re-counted "unfalsifiable" every night with nothing appended).
                if not ok:
                    res.unfalsifiable += 1
            if verdict in SETTLED:
                settled_ids.add(cid)
                res.scored += 1
            # A lesson is proposed only where something was actually learned:
            # a prediction that closed against a real observable.
            if verdict in ("CONFIRMED", "REFUTED"):
                res.lessons.append(build_lesson_candidate(commitment, outcome, now=when))

    res.ledger = led  # type: ignore[attr-defined]
    return res


def read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            # A malformed line is skipped and counted by the caller, never
            # silently treated as absence of data.
            continue
    return rows


def append_jsonl(path: Path | str, rows: Iterable[Mapping[str, Any]]) -> int:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
            n += 1
    return n


# --- LQ-20261107-54: one effective outcome per commitment -------------------------
#: The dedupe key of the outcome ledger is the commitment, not the idempotency key.
#: The idempotency key hashes the observation, so a re-evaluation with a different
#: reason lands a second row: 883 commitments carry a legacy INSUFFICIENT_EVIDENCE
#: (claim_not_falsifiable) row AND the UNSCOREABLE row the 2026-10-09 fix writes.
#: Readers that count rows double-count them; readers must use `effective_outcomes`.
#: Precedence, strongest first: a real score beats UNSCOREABLE beats the legacy row.
_RANK = {"CONFIRMED": 0, "REFUTED": 0, "EXPIRED": 1, UNSCOREABLE: 2, "INSUFFICIENT_EVIDENCE": 3}


def outcome_dedupe_key(row: Mapping[str, Any]) -> str:
    return str(row.get("commitment_id") or "")


def _rank(row: Mapping[str, Any]) -> int:
    return _RANK.get(str(row.get("outcome") or ""), 9)


def effective_outcomes(ledger: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """One outcome per commitment_id. Among duplicates the lowest rank wins; ties
    keep the earliest row (append-only: the first settled word stands)."""
    best: dict[str, dict[str, Any]] = {}
    for row in ledger:
        key = outcome_dedupe_key(row)
        if not key:
            continue
        cur = best.get(key)
        if cur is None or _rank(row) < _rank(cur):
            best[key] = dict(row)
    return best


def outcome_summary(commitments: list[Mapping[str, Any]], ledger: list[Mapping[str, Any]],
                    *, now: datetime | None = None) -> dict[str, Any]:
    """Row counts versus effective counts, and the scoring state of every commitment.

    `scored` = CONFIRMED + REFUTED only; EXPIRED (horizon closed unobserved),
    UNSCOREABLE and legacy INSUFFICIENT_EVIDENCE are not scores.
    """
    when = now or _now()
    eff = effective_outcomes(ledger)
    rows_by_id: dict[str, int] = {}
    for r in ledger:
        k = outcome_dedupe_key(r)
        rows_by_id[k] = rows_by_id.get(k, 0) + 1
    dated = [c for c in commitments if c.get("due_at")]
    dated_ids = {str(c.get("commitment_id")) for c in dated}
    due = [c for c in dated if (_parse_ts(c.get("due_at")) or when) <= when]
    by_eff: dict[str, int] = {}
    for r in eff.values():
        by_eff[str(r.get("outcome"))] = by_eff.get(str(r.get("outcome")), 0) + 1
    newest = max((str(c.get("produced_at") or c.get("created_at") or "") for c in dated), default="")
    return {
        "schema": "CommitmentOutcomeSummary@v1",
        "commitments": len(commitments),
        "dated_commitments": len(dated),
        "due": len(due),
        "due_without_outcome": sum(1 for c in due if str(c.get("commitment_id")) not in eff),
        "newest_dated_commitment_produced_at": newest or None,
        "ledger_rows": len(ledger),
        "effective_outcomes": len(eff),
        "commitments_with_duplicate_outcomes": sum(1 for v in rows_by_id.values() if v > 1),
        "effective_by_outcome": by_eff,
        "scored": by_eff.get("CONFIRMED", 0) + by_eff.get("REFUTED", 0),
        "orphan_outcomes": sum(1 for k in eff if k not in dated_ids),
    }


def plan_ledger_cleanup(ledger: list[Mapping[str, Any]]) -> dict[str, Any]:
    """DRY-RUN PLAN ONLY. Names the superseded rows; performs no I/O.

    Never delete: the proposed action is to archive each superseded row to a side
    file with a `supersedes` link, leaving the live ledger append-only.
    """
    eff = effective_outcomes(ledger)
    superseded = []
    for r in ledger:
        k = outcome_dedupe_key(r)
        keep = eff.get(k)
        if keep is not None and r.get("idempotency_key") != keep.get("idempotency_key"):
            superseded.append({"commitment_id": k, "superseded_outcome": r.get("outcome"),
                               "superseded_idempotency_key": r.get("idempotency_key"),
                               "kept_outcome": keep.get("outcome"),
                               "kept_idempotency_key": keep.get("idempotency_key")})
    pairs: dict[str, int] = {}
    for i in superseded:
        k = f"{i['superseded_outcome']}->{i['kept_outcome']}"
        pairs[k] = pairs.get(k, 0) + 1
    return {"schema": "CommitmentOutcomeCleanupPlan@v1", "dry_run": True, "writes": 0,
            "rows": len(ledger), "keep": len(eff), "superseded": len(superseded),
            "superseded_by_pair": pairs, "items": superseded}
