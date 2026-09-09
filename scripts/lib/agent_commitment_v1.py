"""Lane H — versioned AGENT_COMMITMENT@v1 + outcome evaluation (non-financial)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import hashlib

NO_CONSUMER_REASON = (
    "maturity-gap-closure-20260909 hermetic lane helpers; serving-SHA producers/"
    "consumers await merge+promote+operator grants (telegram/service/drive). "
    "Zero live consumers is correct until then — not a silent dark contract "
    "(MBI_BEHAVIOR=0; recommendation≠mutation)."
)

SCHEMA = "AGENT_COMMITMENT@v1"
OUTCOME_SCHEMA = "CommitmentOutcome@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0
OUTCOMES = ("CONFIRMED", "REFUTED", "EXPIRED", "INSUFFICIENT_EVIDENCE")


@dataclass
class AgentCommitmentV1:
    commitment_id: str
    subject: str
    claim: str
    confidence: float
    horizon: str
    falsifier: str
    due_at: str
    evidence_refs: list[str] = field(default_factory=list)
    source_sha: str = ""
    view_id: str | None = None
    lifecycle_state: str = "OPEN"
    authority: str = AUTHORITY
    mbi_behavior: int = MBI_BEHAVIOR

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA,
            "commitment_id": self.commitment_id,
            "subject": self.subject,
            "claim": self.claim,
            "confidence": self.confidence,
            "horizon": self.horizon,
            "falsifier": self.falsifier,
            "due_at": self.due_at,
            "evidence_refs": list(self.evidence_refs),
            "source_sha": self.source_sha,
            "view_id": self.view_id,
            "lifecycle_state": self.lifecycle_state,
            "authority": self.authority,
            "mbi_behavior": self.mbi_behavior,
            "is_policy_or_order": False,
        }


def validate_commitment_semantics(row: dict[str, Any]) -> tuple[bool, list[str]]:
    """Table name alone is insufficient — require semantic fields."""

    errs: list[str] = []
    schema = str(row.get("schema_version") or row.get("memory_type") or "")
    if SCHEMA not in schema and row.get("memory_type") != "AGENT_COMMITMENT":
        # Allow durable-memory shaped rows if claim+horizon+falsifier present.
        pass
    for key in ("subject", "claim", "confidence", "horizon", "falsifier", "due_at"):
        # accept claim aliases
        if key == "claim" and not (row.get("claim") or row.get("normalized_claim")):
            errs.append("missing_claim")
        elif key == "subject" and not (row.get("subject") or row.get("subject_guid")):
            errs.append("missing_subject")
        elif key not in ("claim", "subject") and row.get(key) in (None, ""):
            errs.append(f"missing_{key}")
    try:
        c = float(row.get("confidence"))
        if not (0.0 <= c <= 1.0):
            errs.append("confidence_out_of_range")
    except (TypeError, ValueError):
        errs.append("confidence_not_numeric")
    if row.get("is_policy_or_order") is True:
        errs.append("policy_or_order_not_commitment")
    if int(row.get("mbi_behavior", 0) or 0) != 0:
        errs.append("mbi_nonzero")
    return (len(errs) == 0), errs


def mint_commitment_from_view(view: dict[str, Any], *, due_at: str, horizon: str, falsifier: str) -> AgentCommitmentV1:
    subject = str(view.get("subject") or "")
    claim = str(view.get("summary") or "")
    digest = hashlib.sha256(f"{subject}|{claim}|{due_at}".encode()).hexdigest()
    return AgentCommitmentV1(
        commitment_id=f"cmt_{digest[:24]}",
        subject=subject,
        claim=claim,
        confidence=float(view.get("confidence") or 0),
        horizon=horizon,
        falsifier=falsifier,
        due_at=due_at,
        evidence_refs=list(view.get("citations") or []),
        source_sha=str(view.get("source_sha") or ""),
        view_id=view.get("view_id"),
    )


def evaluate_commitment(
    commitment: dict[str, Any],
    *,
    now: datetime | None = None,
    observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Idempotent outcome checkpoint; never mutates broker/policy."""
    ok, errs = validate_commitment_semantics(commitment)
    if not ok:
        return {
            "schema_version": OUTCOME_SCHEMA,
            "outcome": "INSUFFICIENT_EVIDENCE",
            "errors": errs,
            "commitment_id": commitment.get("commitment_id"),
        }
    when = now or datetime.now(timezone.utc)
    due = datetime.fromisoformat(str(commitment["due_at"]).replace("Z", "+00:00"))
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    obs = observation or {}
    if obs.get("refuted") is True:
        outcome = "REFUTED"
    elif obs.get("confirmed") is True:
        outcome = "CONFIRMED"
    elif when > due and not obs:
        outcome = "EXPIRED"
    elif not obs:
        outcome = "INSUFFICIENT_EVIDENCE"
    else:
        outcome = "INSUFFICIENT_EVIDENCE"
    assert outcome in OUTCOMES
    return {
        "schema_version": OUTCOME_SCHEMA,
        "commitment_id": commitment.get("commitment_id"),
        "outcome": outcome,
        "evaluated_at": when.isoformat().replace("+00:00", "Z"),
        "authority": AUTHORITY,
        "mbi_behavior": 0,
        "idempotency_key": hashlib.sha256(
            f"{commitment.get('commitment_id')}|{outcome}|{obs}".encode()
        ).hexdigest()[:32],
    }


def count_valid_evaluated(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid = 0
    evaluated = 0
    for row in rows:
        ok, _ = validate_commitment_semantics(row)
        if ok:
            valid += 1
        if row.get("outcome") in OUTCOMES:
            evaluated += 1
    return {"valid_commitments": valid, "evaluated_outcomes": evaluated, "lane_i_gate": evaluated > 0 and valid > 0}
