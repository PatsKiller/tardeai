"""Canonical schemas for the maturity control plane (Phase 11).

READ_ONLY_ADVISORY. Promotion never grants financial_action / broker_write /
order_write / stop_write / risk_policy_write / 2FA / credential authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"

LESSON_STATES = (
    "CANDIDATE",
    "RATIFIED_CONTEXT",
    "SHADOW_INFLUENCE",
    "ADVISORY_ACTIVE",
    "RESTRICTED",
    "RETIRED",
)

PROMOTION_STATES = (
    "DRAFT",
    "PREFLIGHT_FAILED",
    "READY_FOR_SIGNOFF",
    "SIGNED",
    "CANARY",
    "ACTIVE",
    "RESTRICTED",
    "ROLLED_BACK",
    "EXPIRED",
)

# Advisory-only capability types. Anything else is an authority violation.
ALLOWED_CAPABILITY_TYPES = frozenset({
    "agent_shadow_to_operational_advisory",
    "lesson_ratified_to_shadow_influence",
    "lesson_shadow_to_advisory_active",
})

ALLOWED_REQUESTED_STATES = frozenset({
    "OPERATIONAL_ADVISORY",
    "SHADOW_INFLUENCE",
    "ADVISORY_ACTIVE",
    "RESTRICTED",
    "ROLLED_BACK",
})

FORBIDDEN_AUTHORITIES = (
    "financial_action",
    "broker_write",
    "order_write",
    "stop_write",
    "risk_policy_write",
    "two_fa",
    "2FA",
    "credential_authority",
    "service_control",
    "unrestricted_mutation",
)

ACK_TOKEN = "PHASE11-ADVISORY-PROMOTE"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"PREFLIGHT_FAILED", "READY_FOR_SIGNOFF"}),
    "PREFLIGHT_FAILED": frozenset({"DRAFT", "READY_FOR_SIGNOFF"}),
    "READY_FOR_SIGNOFF": frozenset({"SIGNED", "EXPIRED", "DRAFT"}),
    "SIGNED": frozenset({"CANARY", "RESTRICTED", "EXPIRED", "ROLLED_BACK"}),
    "CANARY": frozenset({"ACTIVE", "RESTRICTED", "ROLLED_BACK", "EXPIRED"}),
    "ACTIVE": frozenset({"RESTRICTED", "ROLLED_BACK"}),
    "RESTRICTED": frozenset({"ROLLED_BACK", "SIGNED"}),
    "ROLLED_BACK": frozenset(),
    "EXPIRED": frozenset(),
}

REQUIRED_PROMOTION_FIELDS = (
    "promotion_id",
    "capability_type",
    "from_state",
    "requested_state",
    "exact_source_sha",
    "evidence_bundle_hash",
    "requested_by",
    "requested_at",
    "expires_at",
    "rollback_target",
    "status",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def evidence_bundle_hash(bundle: dict[str, Any]) -> str:
    return content_hash(bundle)


def signoff_signature(*, promotion_id: str, exact_source_sha: str,
                      evidence_bundle_hash: str, operator: str, ack: str,
                      requested_state: str) -> str:
    payload = {
        "ack": ack,
        "evidence_bundle_hash": evidence_bundle_hash,
        "exact_source_sha": exact_source_sha,
        "operator": operator,
        "promotion_id": promotion_id,
        "requested_state": requested_state,
    }
    return content_hash(payload)


def authority_violations(rec: dict[str, Any]) -> list[str]:
    found: list[str] = []
    blob = canonical_json(rec).lower()
    for token in FORBIDDEN_AUTHORITIES:
        if token.lower() in blob and token.lower() not in (
            "financial_action=false",
            "broker_write=false",
        ):
            # allow explicit denials
            if f'"{token.lower()}":false' in blob or f'"{token.lower()}": false' in blob:
                continue
            if f"{token.lower()}=false" in blob:
                continue
            found.append(token)
    grants = rec.get("grants") or rec.get("authorities_granted") or []
    if isinstance(grants, (list, tuple)):
        for g in grants:
            gs = str(g)
            if gs in FORBIDDEN_AUTHORITIES or gs.lower() in {x.lower() for x in FORBIDDEN_AUTHORITIES}:
                found.append(gs)
    cap = str(rec.get("capability_type") or "")
    if cap and cap not in ALLOWED_CAPABILITY_TYPES:
        found.append(f"disallowed_capability_type:{cap}")
    req = str(rec.get("requested_state") or "")
    if req and req not in ALLOWED_REQUESTED_STATES:
        found.append(f"disallowed_requested_state:{req}")
    if rec.get("financial_action") is True:
        found.append("financial_action")
    return sorted(set(found))


def validate_promotion_record(rec: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(rec, dict):
        return ["record_not_object"]
    for field in REQUIRED_PROMOTION_FIELDS:
        if not rec.get(field):
            errors.append(f"missing:{field}")
    sha = str(rec.get("exact_source_sha") or "")
    if sha and not SHA_RE.match(sha):
        errors.append("exact_source_sha_malformed")
    st = str(rec.get("status") or "")
    if st and st not in PROMOTION_STATES:
        errors.append(f"unknown_status:{st}")
    cap = str(rec.get("capability_type") or "")
    if cap and cap not in ALLOWED_CAPABILITY_TYPES:
        errors.append(f"capability_type_not_advisory:{cap}")
    target = rec.get("agent_id") or rec.get("lesson_id")
    if not target:
        errors.append("missing:agent_id_or_lesson_id")
    errors.extend(f"authority:{v}" for v in authority_violations(rec))
    return errors


def can_transition(src: str, dest: str) -> bool:
    return dest in TRANSITIONS.get(src, frozenset())


def map_kb_status_to_lesson_state(status: str | None, overlay: str | None = None) -> str:
    if overlay and overlay in LESSON_STATES:
        return overlay
    s = str(status or "").strip().lower()
    if s in {"retired", "retire"}:
        return "RETIRED"
    if s in {"restricted"}:
        return "RESTRICTED"
    if s in {"shadow_influence", "shadow"}:
        return "SHADOW_INFLUENCE"
    if s in {"advisory_active", "active"}:
        return "ADVISORY_ACTIVE"
    if s in {"ratified", "ratified_context"}:
        return "RATIFIED_CONTEXT"
    return "CANDIDATE"
