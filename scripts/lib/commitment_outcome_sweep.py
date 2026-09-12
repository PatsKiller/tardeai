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
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from scripts.lib.governed_commitment import (
    OUTCOME_SCHEMA,
    durable_outcome_ledger_append,
    evaluate_outcome,
)

AUTHORITY = "READ_ONLY_ADVISORY"
LESSON_SCHEMA = "LessonCandidate@v1"
SWEEP_SCHEMA = "CommitmentOutcomeSweep@v1"

SETTLED = ("CONFIRMED", "REFUTED", "EXPIRED")

#: A claim that only asserts its own occurrence cannot be contradicted by any
#: later observation. Matched on the live template, not invented: 96 of 224
#: commitments are this exact shape.
_UNFALSIFIABLE_CLAIM_RE = re.compile(
    r"reviewed subject\s+[0-9a-f-]{8,}\s*;\s*advisory observation only", re.I
)
#: Likewise a falsifier that restates "the claim could be wrong" names no
#: observable and so can never fire.
_VACUOUS_FALSIFIER_RE = re.compile(
    r"^\s*observation contradicts claim within horizon\s*$", re.I
)


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


def is_prediction(commitment: Mapping[str, Any]) -> bool:
    """Does this record predict anything, or merely record that something happened?

    `commitments.jsonl` holds two shapes. 99 rows are GovernedCommitment@v1:
    FROZEN, with due_at, horizon, confidence and a falsifier. The other 125 are
    thin wake commitments -- agent_id / commitment_kind / normalized_claim,
    lifecycle OPEN, claims like "selection:material_change:<guid> warrants
    review" -- with no due_at, no horizon and no confidence. Those are
    observations, not predictions, and were never meant to be scored.

    Counting them as predictions with a missing falsifier would invent 125
    failures out of records that never claimed anything about the future.
    """
    return bool(commitment.get("due_at")) and bool(commitment.get("horizon"))


def claim_is_falsifiable(commitment: Mapping[str, Any]) -> tuple[bool, str]:
    """Can any later observation contradict this claim? Returns (ok, reason)."""
    claim = str(commitment.get("claim") or "")
    falsifier = str(commitment.get("falsifier") or "")
    if not is_prediction(commitment):
        return False, "not_a_prediction"
    if not claim.strip():
        return False, "missing_claim"
    if not falsifier.strip():
        return False, "missing_falsifier"
    if _UNFALSIFIABLE_CLAIM_RE.search(claim):
        return False, "claim_asserts_only_that_a_review_occurred"
    if _VACUOUS_FALSIFIER_RE.match(falsifier):
        return False, "falsifier_names_no_observable"
    return True, "falsifiable"


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
        "rejected_by": None,
        "rejected_at": None,
        "produced_at": _iso(when),
        "changes_production_behaviour": False,
    }


@dataclass
class SweepResult:
    scanned: int = 0
    due: int = 0
    already_settled: int = 0
    scored: int = 0
    unfalsifiable: int = 0
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
        if str(row.get("outcome") or "") in SETTLED
    }
    res = SweepResult()

    for commitment in commitments:
        res.scanned += 1
        due = _parse_ts(commitment.get("due_at"))
        if due is None or due > when:
            continue
        res.due += 1
        cid = str(commitment.get("commitment_id") or "")
        if cid in settled_ids:
            res.already_settled += 1
            continue

        ok, reason = claim_is_falsifiable(commitment)
        if not ok:
            res.unfalsifiable += 1
            outcome = {
                "schema_version": OUTCOME_SCHEMA,
                "commitment_id": cid,
                "outcome": "INSUFFICIENT_EVIDENCE",
                "errors": [f"claim_not_falsifiable:{reason}"],
                "evaluated_at": _iso(when),
                "evaluator_identity": evaluator_identity,
                "authority": AUTHORITY,
                "mbi_behavior": 0,
                "idempotency_key": hashlib.sha256(
                    f"{cid}|unfalsifiable|{reason}".encode()
                ).hexdigest()[:32],
            }
        else:
            outcome = evaluate_outcome(
                dict(commitment),
                observation=provider(commitment),
                now=when,
                evaluator_identity=evaluator_identity,
            )

        before = len(led)
        led = durable_outcome_ledger_append(led, outcome)
        if len(led) > before:
            res.outcomes.append(outcome)
            verdict = str(outcome.get("outcome") or "")
            res.by_outcome[verdict] = res.by_outcome.get(verdict, 0) + 1
            if verdict in SETTLED:
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
