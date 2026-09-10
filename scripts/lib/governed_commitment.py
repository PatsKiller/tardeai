#!/usr/bin/env python3
"""governed_commitment.py — canonical durable commitment contract (Grok-closure Phase 4).

The wake engine mints a thin commitment (commitment_kind + claim). The maturity
bar for a *governed* commitment is higher: a claim that can be falsified, with a
confidence, a horizon, a due window, evidence, source identity, provenance, and a
freeze that happens BEFORE the outcome window opens. This module is the canonical
contract and the scheduled outcome evaluator.

Fields (all required; missing ⇒ fail-closed REFUSE):
  claim, confidence (0..1), horizon, due_at (or due_window), falsifier,
  evidence_refs (non-empty), source_identity, source_sha, served_sha,
  subject_guid, trigger_provenance, created_at, frozen_at.

Freeze rule: ``frozen_at`` must be strictly before the outcome window start
(``due_at``). Once frozen, the commitment is immutable — a later mutation
(a different claim / confidence / falsifier / source_sha) is refused. An outcome
is linked by ``commitment_id`` and is preserved even when REFUTED (never deleted,
never rewritten; append-only).

Prohibited: self-evaluation (an evaluator cannot be the same identity that
produced the commitment, unless it is the deterministic neutral evaluator);
manual/backfill provenance (provenance must name a real trigger producer).

Authority: READ_ONLY_ADVISORY. Never sizes, orders, stops, or writes broker state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA = "GovernedCommitment@v1"
OUTCOME_SCHEMA = "GovernedCommitmentOutcome@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
OUTCOMES = ("CONFIRMED", "REFUTED", "EXPIRED", "INSUFFICIENT_EVIDENCE")

REQUIRED_FIELDS = (
    "claim",
    "confidence",
    "horizon",
    "due_at",
    "falsifier",
    "evidence_refs",
    "source_identity",
    "source_sha",
    "served_sha",
    "subject_guid",
    "trigger_provenance",
    "created_at",
    "frozen_at",
)


class CommitmentError(ValueError):
    """Fail-closed: a governed commitment is malformed, frozen, or unprovenanced."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _commitment_id(c: dict[str, Any]) -> str:
    material = f"{c.get('subject_guid')}|{c.get('claim')}|{c.get('horizon')}|{c.get('due_at')}"
    return "gcmt_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _validate(c: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    if not c.get("claim"):
        errs.append("missing_claim")
    try:
        conf = float(c.get("confidence"))
        if not (0.0 <= conf <= 1.0):
            errs.append("confidence_out_of_range")
    except (TypeError, ValueError):
        errs.append("confidence_not_numeric")
    if not c.get("horizon"):
        errs.append("missing_horizon")
    if not c.get("due_at"):
        errs.append("missing_due_at")
    if not c.get("falsifier"):
        errs.append("missing_falsifier")
    ev = c.get("evidence_refs")
    if not isinstance(ev, list) or not ev:
        errs.append("missing_evidence")
    if not c.get("source_identity"):
        errs.append("missing_source_identity")
    if not c.get("source_sha"):
        errs.append("missing_source_sha")
    if not c.get("served_sha"):
        errs.append("missing_served_sha")
    if not c.get("subject_guid"):
        errs.append("missing_subject_guid")
    tp = c.get("trigger_provenance")
    if not isinstance(tp, Mapping) or not tp.get("producer"):
        errs.append("missing_trigger_provenance")
    # Manual / backfill provenance is prohibited.
    if isinstance(tp, Mapping) and str(tp.get("producer", "")).strip() in ("", "manual", "backfill"):
        errs.append("prohibited_manual_or_backfill_provenance")
    if not c.get("created_at"):
        errs.append("missing_created_at")
    if not c.get("frozen_at"):
        errs.append("missing_frozen_at")
    # Freeze must be strictly before the outcome window starts.
    due = _parse_ts(c.get("due_at"))
    frozen = _parse_ts(c.get("frozen_at"))
    if due is not None and frozen is not None and frozen >= due:
        errs.append("freeze_after_window_start")
    return errs


def build_governed_commitment(
    *,
    claim: str,
    confidence: float,
    horizon: str,
    due_at: datetime | str,
    falsifier: str,
    evidence_refs: list[str],
    source_identity: str,
    source_sha: str,
    served_sha: str,
    subject_guid: str,
    trigger_provenance: dict[str, Any],
    created_at: datetime | None = None,
    frozen_at: datetime | None = None,
    authority: str = AUTHORITY,
) -> dict[str, Any]:
    """Build + validate the canonical commitment. Fail-closed on any missing field."""
    now = created_at or _now()
    created = _parse_ts(now) or _now()
    frozen = _parse_ts(frozen_at) or created
    commitment = {
        "schema_version": SCHEMA,
        "claim": str(claim).strip(),
        "confidence": float(confidence),
        "horizon": str(horizon).strip(),
        "due_at": _iso(_parse_ts(due_at) or created),
        "falsifier": str(falsifier).strip(),
        "evidence_refs": [str(e) for e in evidence_refs],
        "source_identity": str(source_identity).strip(),
        "source_sha": str(source_sha).strip(),
        "served_sha": str(served_sha).strip(),
        "subject_guid": str(subject_guid).strip(),
        "trigger_provenance": dict(trigger_provenance),
        "created_at": _iso(created),
        "frozen_at": _iso(frozen),
        "authority": authority,
        "mbi_behavior": 0,
        "lifecycle_state": "FROZEN",
    }
    errs = _validate(commitment)
    if errs:
        raise CommitmentError(";".join(errs))
    commitment["commitment_id"] = _commitment_id(commitment)
    return commitment


def assert_not_mutated(original: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    """Return the mutated fields. An empty list means no mutation."""
    changed: list[str] = []
    for k in (
        "claim",
        "confidence",
        "horizon",
        "due_at",
        "falsifier",
        "source_sha",
        "served_sha",
        "subject_guid",
        "created_at",
        "frozen_at",
    ):
        if original.get(k) != candidate.get(k):
            changed.append(k)
    return changed


def evaluate_outcome(
    commitment: dict[str, Any],
    *,
    observation: dict[str, Any] | None = None,
    now: datetime | None = None,
    evaluator_identity: str = "deterministic_neutral",
) -> dict[str, Any]:
    """Scheduled outcome evaluator. Durable result linked by commitment_id.

    Prohibited self-evaluation: the evaluator may not be the commitment producer
    identity (unless it is the neutral deterministic evaluator).
    """
    errs = _validate(commitment)
    if errs:
        return {
            "schema_version": OUTCOME_SCHEMA,
            "commitment_id": commitment.get("commitment_id"),
            "outcome": "INSUFFICIENT_EVIDENCE",
            "errors": errs,
            "evaluated_at": _iso(now or _now()),
            "authority": AUTHORITY,
        }

    producer = (commitment.get("trigger_provenance") or {}).get("producer")
    if evaluator_identity not in ("deterministic_neutral",) and evaluator_identity == producer:
        return {
            "schema_version": OUTCOME_SCHEMA,
            "commitment_id": commitment.get("commitment_id"),
            "outcome": "INSUFFICIENT_EVIDENCE",
            "errors": ["prohibited_self_evaluation"],
            "evaluated_at": _iso(now or _now()),
            "authority": AUTHORITY,
        }

    when = now or _now()
    due = _parse_ts(commitment.get("due_at"))
    obs = observation or {}
    if obs.get("refuted") is True:
        outcome = "REFUTED"
    elif obs.get("confirmed") is True:
        outcome = "CONFIRMED"
    elif due is not None and when > due and not obs:
        outcome = "EXPIRED"
    else:
        outcome = "INSUFFICIENT_EVIDENCE"

    return {
        "schema_version": OUTCOME_SCHEMA,
        "commitment_id": commitment.get("commitment_id"),
        "outcome": outcome,
        "evaluated_at": _iso(when),
        "evaluator_identity": evaluator_identity,
        "observation": dict(obs),
        "authority": AUTHORITY,
        "mbi_behavior": 0,
        "idempotency_key": hashlib.sha256(
            f"{commitment.get('commitment_id')}|{outcome}|{json.dumps(obs, sort_keys=True, default=str)}".encode()
        ).hexdigest()[:32],
    }


def durable_outcome_ledger_append(ledger: list[dict[str, Any]], outcome: dict[str, Any]) -> list[dict[str, Any]]:
    """Append-only outcome ledger: refuted outcomes are preserved, never rewritten.

    Idempotent on the outcome idempotency_key (a re-evaluation of the same
    commitment + observation is a no-op).
    """
    key = outcome.get("idempotency_key")
    for row in ledger:
        if row.get("idempotency_key") == key:
            return ledger
    return ledger + [outcome]


__all__ = [
    "SCHEMA",
    "OUTCOME_SCHEMA",
    "OUTCOMES",
    "REQUIRED_FIELDS",
    "CommitmentError",
    "build_governed_commitment",
    "evaluate_outcome",
    "assert_not_mutated",
    "durable_outcome_ledger_append",
]
