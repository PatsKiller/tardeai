"""Governed admission pipeline for durable AIF memory.

candidate → schema → secret → authority → provenance → contradiction → expiry → write
Fail-closed for admission. Fail-soft for the wider wake (caller catches None).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from scripts.lib.agent_feature_flags import load_feature_flags
from scripts.lib.agent_memory_governance import (
    ADMIT_ACTIVE_TYPES,
    MEMORY_TYPES,
    STATUS_DISPUTED,
    STATUS_REJECT,
    STATUS_SUPERSEDED,
    admit_status,
    build_memory_record,
    is_adversarial_instruction,
    is_forbidden_authoritative,
)
from scripts.lib.agent_durable_memory import (
    STATUS_ADMITTED,
    DurableJsonlMemoryProvider,
    default_ttl,
    display_status,
)
from scripts.lib.agent_memory_provider import MEMORY_AUTHORITY

VALID_SOURCE_CLASSES = frozenset({
    "agent_run", "decision", "operator_feedback", "operator_disposition",
    "case", "outcome", "review", "score", "ratified_lesson",
    "research_artifact", "financial_senses_receipt",
})


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def admit_candidate(
    raw: dict[str, Any],
    *,
    provider: DurableJsonlMemoryProvider,
    admitted_by: str = "system",
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "candidate_id": raw.get("candidate_id") or raw.get("memory_id"),
        "accepted": False,
        "reason": "",
        "authority_class": MEMORY_AUTHORITY,
        "source_count": 0,
        "provenance_valid": False,
        "secret_scan": "not_run",
        "forbidden_truth_scan": "not_run",
        "adversarial_scan": "not_run",
        "contradiction_count": 0,
        "expires_at": None,
        "admitted_at": None,
        "admitted_by": admitted_by,
        "memory_id": None,
    }
    try:
        rec = build_memory_record(
            memory_type=str(raw.get("memory_type") or ""),
            subject=str(raw.get("subject") or ""),
            content=str(raw.get("content") or raw.get("statement") or ""),
            memory_id=raw.get("memory_id"),
            scope=raw.get("scope"),
            symbols=raw.get("symbols"),
            source_event_ids=raw.get("source_event_ids"),
            source_refs=raw.get("source_refs"),
            source_kind=raw.get("source_kind"),
            confidence=float(raw.get("confidence") or 0.5),
            supersedes=raw.get("supersedes"),
            contradicts=raw.get("contradicts"),
            expires_at=raw.get("expires_at"),
            provider="durable",
        )
    except ValueError as e:
        msg = str(e)
        receipt["reason"] = msg
        receipt["secret_scan"] = "reject" if "secret" in msg.lower() else "pass"
        receipt["provenance_valid"] = "provenance" not in msg.lower()
        if "secret" in msg.lower():
            receipt["secret_scan"] = "reject"
        provider._append_receipt(provider.receipts_path, receipt)
        return receipt

    if rec.get("memory_type") not in MEMORY_TYPES:
        receipt["reason"] = "invalid_memory_type"
        provider._append_receipt(provider.receipts_path, receipt)
        return receipt

    receipt["secret_scan"] = "pass"
    forbidden = is_forbidden_authoritative(rec.get("subject")) or is_forbidden_authoritative(rec.get("content"))
    receipt["forbidden_truth_scan"] = "reject" if forbidden else "pass"
    if forbidden:
        receipt["reason"] = "forbidden_authoritative_truth"
        provider._append_receipt(provider.receipts_path, receipt)
        return receipt

    adversarial = is_adversarial_instruction(rec.get("subject")) or is_adversarial_instruction(
        rec.get("content")
    )
    flags = load_feature_flags()
    scan_on = int(flags.get("MEMORY_ADVERSARIAL_SCAN") or 0) == 1
    if scan_on:
        receipt["adversarial_scan"] = "reject" if adversarial else "pass"
        if adversarial:
            receipt["reason"] = "adversarial_instruction"
            provider._append_receipt(provider.receipts_path, receipt)
            return receipt
    else:
        receipt["adversarial_scan"] = "shadow_reject" if adversarial else "shadow_pass"

    refs = list(rec.get("source_refs") or []) + list(rec.get("source_event_ids") or [])
    receipt["source_count"] = len(refs)
    receipt["provenance_valid"] = bool(refs)
    kind = rec.get("source_kind")
    if kind and kind not in VALID_SOURCE_CLASSES:
        receipt["reason"] = f"invalid_source_class:{kind}"
        provider._append_receipt(provider.receipts_path, receipt)
        return receipt
    if not refs:
        receipt["reason"] = "provenance_missing"
        provider._append_receipt(provider.receipts_path, receipt)
        return receipt

    status = admit_status(
        rec["memory_type"],
        subject=rec.get("subject"),
        source_kind=kind,
        provenance_ok=True,
    )
    if status == STATUS_REJECT:
        receipt["reason"] = "admission_rejected"
        provider._append_receipt(provider.receipts_path, receipt)
        return receipt
    rec["status"] = status
    if not rec.get("expires_at"):
        rec["expires_at"] = default_ttl(rec.get("memory_type")).replace(microsecond=0).isoformat()
    rec["admission_reason"] = raw.get("admission_reason") or "governed_admission"
    rec["authority_class"] = MEMORY_AUTHORITY
    rec["schema_version"] = rec.get("memory_version") or "1.0"
    rec["content_hash"] = rec.get("content_digest")
    rec["as_of"] = rec.get("valid_from") or rec.get("created_at")
    rec["observed_at"] = raw.get("observed_at") or rec.get("created_at")
    rec["producer"] = raw.get("producer") or raw.get("agent") or "system"
    rec["agent"] = raw.get("agent")
    rec["reviewer"] = raw.get("reviewer")
    rec["metadata"] = dict(raw.get("metadata") or {})

    # contradiction scan against existing store
    contra = []
    for other in provider._store.values():
        if other.get("memory_id") == rec.get("memory_id"):
            continue
        if other.get("status") in (STATUS_DISPUTED, STATUS_SUPERSEDED) or (
            other.get("subject") and other.get("subject") == rec.get("subject")
            and other.get("content") != rec.get("content")
        ):
            contra.append(other.get("memory_id"))
    rec["contradicts"] = list(dict.fromkeys(list(rec.get("contradicts") or []) + contra))
    receipt["contradiction_count"] = len(rec["contradicts"])

    mid = provider.add_candidate(rec)
    if not mid:
        receipt["reason"] = "persist_rejected"
        provider._append_receipt(provider.receipts_path, receipt)
        return receipt
    stored = provider.get(mid) or rec
    # The receipt records WHAT WAS OFFERED, not only what happened to it.
    # Without memory_type, a receipt reading CANDIDATE is ambiguous: it may be a
    # promotion that failed, or a class that governance never promotes. Every
    # receipt ever written carries authority_class NON_AUTHORITATIVE_CONTEXT,
    # which is a constant and discriminates nothing, so the audit trail could
    # not tell those apart -- and the liveness reporter concluded STARVED for a
    # lane that was behaving exactly as designed.
    stored_type = str(stored.get("memory_type") or rec.get("memory_type") or "")
    receipt.update({
        "accepted": True,
        "reason": "admitted" if display_status(stored.get("status")) == STATUS_ADMITTED else "candidate",
        "memory_id": mid,
        "memory_type": stored_type or None,
        # Whether this class of memory can EVER reach ACTIVE. False is not a
        # failure: research context is deliberately never policy.
        "promotable": stored_type in ADMIT_ACTIVE_TYPES if stored_type else None,
        "expires_at": stored.get("expires_at"),
        "admitted_at": _now(),
        "display_status": display_status(stored.get("status")),
    })
    provider._append_receipt(provider.receipts_path, receipt)
    return receipt
