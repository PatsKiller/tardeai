"""Completion transaction for CIO-owner stance reviews, never an acquisition result.

Existing C3 publication/readback validation calls this only after proving the CIO
authored a new canonical stance. A durable decision alone never clears a finding.
"""
from __future__ import annotations

from .ledger import DECISION_SCHEMA
from .adapters import timestamp


def record_review_queued(ledger, key, *, request_id, queue_readback, at, apply=False):
    """Owner calls after enqueue; verify the persisted GUID-bound request first."""
    record = ledger.records().get(key)
    if not record:
        raise KeyError(key)
    saved = queue_readback(request_id) or {}
    if (saved.get("request_id") != request_id or saved.get("identity_status") != "CONFIRMED" or
            saved.get("security_guid") != record["subject"]["id"] or
            str(saved.get("symbol") or "").upper() != str(record["subject"]["label"]).upper()):
        raise ValueError("persisted review request identity/lineage unproven")
    return ledger.transition(key, "review_queued", at=at, expected_revision=record["revision"],
                             review_request_id=request_id, apply=apply)


def complete_review(ledger, key, *, request_id, canonical, reason, evidence_refs, producer_update,
                    producer_readback, at, expires_at, apply=False):
    record = ledger.records().get(key)
    if not record:
        raise KeyError(key)
    if record["subject"]["kind"] != "security" or record.get("kind") != "CONFLICT" or record.get("rule") not in {"U2", "U3", "U7", "R11"}:
        raise ValueError("review completion is limited to CIO stance conflicts")
    if not request_id or not reason or not evidence_refs:
        raise ValueError("linked request, reason and evidence are required")
    if canonical.get("security_guid") != record["subject"]["id"] or not canonical.get("stance") or not canonical.get("as_of"):
        raise ValueError("canonical publication identity/stance/time unproven")
    canonical_at = timestamp(canonical["as_of"])
    if canonical_at is None or canonical_at > at:
        raise ValueError("canonical publication timestamp unproven")
    patch = {"verdict": canonical["stance"], "completed_at": canonical["as_of"], "request_id": request_id,
             "conflict_key": key, "reason": reason, "evidence_refs": list(evidence_refs)}
    decision = {"schema": DECISION_SCHEMA, "actor_kind": "cio", "actor": "cio", "chosen_side": canonical["stance"],
                "reason": reason, "evidence_refs": list(evidence_refs), "request_id": request_id, "at": at.isoformat(),
                "expires_at": expires_at.isoformat(), "clears_when": record.get("clears_when"),
                "key": key, "subject": record["subject"]}
    # Validate transition without effects before any producer mutation.
    ledger.transition(key, "review_completed", at=at, decision=decision, apply=False)
    if not apply:
        return {"decision": decision, "producer_patch": patch, "applied": False, "resolution_proven": False}
    prior = record.get("decision") or {}
    if prior.get("request_id") != request_id:
        ledger.transition(key, "decided", at=at, decision=decision, expected_revision=record["revision"], apply=True)
    if producer_update(patch) is not True:
        return {"applied": False, "resolution_proven": False, "reason": "superseded_input_update_failed"}
    saved = producer_readback() or {}
    if any(saved.get(k) != v for k, v in patch.items()):
        return {"applied": False, "resolution_proven": False, "reason": "superseded_input_readback_failed"}
    # The owner records the completion; only the next engine evaluation clears.
    ledger.transition(key, "review_completed", at=at, decision=decision, apply=True)
    return {"applied": True, "resolution_proven": True, "decision": decision, "producer_patch": patch,
            "cleared": False, "next": "re-evaluate canonical and updated producer input"}
