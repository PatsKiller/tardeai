"""Forward R18–R22+ program controls.

Engineering may run ahead of evidence. Activation must never run ahead of evidence.
All live switches default OFF. R17 production wiring is out of scope here.
"""
from __future__ import annotations

from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
EVIDENCE_CLASSES = (
    "SOURCE_ONLY",
    "UNIT_TEST",
    "HISTORICAL_REPLAY",
    "GOLDEN_SHADOW",
    "LIVE",
)
ROUNDS = ("R18", "R19", "R20", "R21", "R22", "OFFICE")

# Production activation. Keep every round false until a later, separate authorization.
ACTIVATION: dict[str, bool] = {r: False for r in ROUNDS}

CANONICAL_CONTRACT = "TransfersonUniverseManifest@v1"
IDENTITY_SPINE = "issuer_guid → security_guid → listing_guid → ticker alias"
PROMOTION_CEILING = "REVIEW_READY"

# Two lanes. Cognition may be retrieved for advisory reasoning.
# It may never become holdings/prices/cash/broker/risk truth.
OFFICE_TRUTH = "OFFICE_TRUTH"
INSTITUTIONAL_COGNITION = "INSTITUTIONAL_COGNITION"
COGNITION_MAY_MUTATE_OFFICE_TRUTH = False
# Production remains 0. Architecture records retrieval use; promotion of influence is separate.
ADVISORY_INFLUENCE_PROMOTION = "SHADOW_ACCEPTANCE_REQUIRED"


def require_evidence_class(value: str) -> str:
    cls = str(value or "").strip().upper()
    if cls not in EVIDENCE_CLASSES:
        raise ValueError("evidence_class_required")
    return cls


def refuse_mixed_maturity(classes: list[str]) -> dict[str, Any]:
    uniq = sorted({require_evidence_class(c) for c in classes if c})
    return {
        "schema": "EvidenceClassGuard@v1",
        "classes": uniq,
        "mixed": len(uniq) > 1,
        "may_not_blend_into_one_maturity_number": True,
        "authority": AUTHORITY,
    }


def live_activation_allowed(round_id: str) -> bool:
    return bool(ACTIVATION.get(str(round_id).upper(), False))


def gated_live_run(round_id: str, *, evidence_class: str) -> dict[str, Any]:
    """Refuse LIVE claims while the round is inactive."""
    cls = require_evidence_class(evidence_class)
    active = live_activation_allowed(round_id)
    if cls == "LIVE" and not active:
        return {
            "ok": False,
            "activated": False,
            "round": round_id,
            "reason": "LIVE_ACTIVATION_OFF",
            "evidence_class": "SOURCE_ONLY",
            "authority": AUTHORITY,
            "memory_behavior_influence": MBI,
            "financial_action": False,
        }
    return {
        "ok": True,
        "activated": active,
        "round": round_id,
        "evidence_class": cls,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def identity_roll_up(row: dict[str, Any] | None) -> dict[str, Any]:
    """Ticker is alias only. Unresolved stays unresolved. Never mint from symbol text."""
    src = dict(row or {})
    sg = src.get("security_guid") or src.get("subject_guid")
    unresolved = (not sg) or src.get("identity_status") == "UNRESOLVED_WITH_REASON"
    return {
        "schema": "IdentityRollup@v1",
        "issuer_guid": src.get("issuer_guid"),
        "security_guid": sg if not unresolved or src.get("security_guid") else None,
        "listing_guid": src.get("listing_guid"),
        "ticker_alias": src.get("symbol") or src.get("ticker_alias"),
        "identity_status": src.get("identity_status") or ("UNRESOLVED_WITH_REASON" if not sg else src.get("identity_status")),
        "unresolved": not bool(sg),
        "ticker_guid_is_not_security": True,
        "authority": AUTHORITY,
    }
