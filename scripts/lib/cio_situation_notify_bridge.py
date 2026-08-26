"""Feed CIOSituationState@v1 into the production decide_notification chokepoint.

Does not create a second notification brain. Converts situation rows into the
decision shape `decide_notification` already consumes, then classifies one
auditable scan result.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Any

from scripts.lib.cio_advisory_message import render_advisory_message
from scripts.lib.cio_notification_signal import (
    DELIVERY_COMMAND_CENTER_ONLY,
    DELIVERY_DIGEST,
    DELIVERY_IMMEDIATE,
    DELIVERY_SUPPRESSED,
)
from scripts.lib.cio_situation_state import detect_office_situations

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "SituationNotifyBridge@v1"

AUDITABLE_RESULTS = (
    "NOTIFICATION_DELIVERED",
    "NOTIFICATION_QUEUED",
    "NOTIFICATION_DIGESTED",
    "COMMAND_CENTER_ONLY",
    "NOTIFICATION_SUPPRESSED",
    "POLICY_GAP_QUESTION",
    "NO_MATERIAL_CHANGE",
    "DELIVERY_FAILED_RETRYING",
    "DEAD_LETTERED",
    "DRY_RUN_INTERDICTED",
)


def _digest(value: Any, length: int = 16) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:length]


def situation_to_decision(situation: dict[str, Any]) -> dict[str, Any]:
    """Map a CIOSituationState@v1 row to a material-scan decision dict."""
    klass = str(situation.get("situation_class") or "NO_MATERIAL_CHANGE")
    eligibility = str(situation.get("notification_eligibility") or "SUPPRESS")
    sit_id = str(situation.get("situation_id") or f"sit_{_digest(klass)}")
    conclusion = str(situation.get("cio_conclusion") or klass)
    act_now = eligibility == "NOTIFY" and klass not in {"NO_MATERIAL_CHANGE", "OUTCOME_MATURITY"}
    if klass == "POLICY_GAP":
        standing = "POLICY_QUESTION"
        action = "POLICY_QUESTION"
        act_now = True  # bounded operator question is the page
    elif klass == "NO_MATERIAL_CHANGE":
        standing = "HOLD_CASH" if situation.get("cash_situation") else "NO_ACTION"
        action = standing
        act_now = False
    elif klass == "EXCESS_CASH":
        standing = str((situation.get("cash_situation") or {}).get("conclusion") or "HOLD_CASH")
        action = standing
        act_now = standing == "DEPLOY_STAGED" and eligibility == "NOTIFY"
    elif klass == "CONTRADICTION":
        standing = "REVIEW"
        action = "REVIEW"
        act_now = False
    else:
        standing = conclusion
        action = conclusion
    new_state = situation.get("new_state") if isinstance(situation.get("new_state"), dict) else {}
    lineage_symbol = "CASH" if klass in {"EXCESS_CASH", "POLICY_GAP", "ALLOCATION_DRIFT"} else (
        str(new_state.get("symbol") or klass)
    )
    why = str(situation.get("what_changed") or klass)
    body = render_advisory_message(situation)
    created = datetime.now(timezone.utc)
    return {
        "decision_id": f"dec_sit_{sit_id[-16:]}",
        "symbol": lineage_symbol if klass in {"EXCESS_CASH", "POLICY_GAP", "ALLOCATION_DRIFT"} else str(
            new_state.get("symbol") or "BOOK"
        ),
        "action": action,
        "standing_recommendation": standing,
        "current_action": action,
        "act_now": act_now,
        "why_now": why,
        "what_changed": why,
        "counter_thesis": (situation.get("counterevidence") or [None])[0],
        "what_changes_call": "New verified facts, confirmed policy, or a later material delta.",
        "next_review": (created + timedelta(hours=24)).isoformat(),
        "situation_id": sit_id,
        "situation_class": klass,
        "situation_type": klass,
        "material_delta": situation.get("what_changed"),
        "portfolio_relevance": "primary",
        "severity": situation.get("materiality"),
        "confidence": situation.get("confidence"),
        "novelty": "NEW",
        "freshness": situation.get("freshness"),
        "evidence_refs": situation.get("support") or [],
        "contradictions": situation.get("counterevidence") or [],
        "policy_dependencies": situation.get("policy_references") or [],
        "recommended_operator_action": conclusion,
        "notification_eligibility": eligibility,
        "suppression_reason": situation.get("suppression_reason"),
        "dedupe_key": situation.get("fingerprint"),
        "created_at": created.isoformat(),
        "expires_at": (created + timedelta(hours=24)).isoformat(),
        "next_review_at": (created + timedelta(hours=24)).isoformat(),
        "deep_link": "/cio/brain",
        "context_receipt_id": None,
        "operator_message": body,
        "authority": AUTHORITY,
        "financial_action": False,
        "executable_order": None,
        "memory_behavior_influence": 0,
    }


def situation_decisions_from_office(office: dict[str, Any], *, evaluated_at=None) -> list[dict[str, Any]]:
    scan = detect_office_situations(office, evaluated_at=evaluated_at)
    out = []
    for row in scan.get("situations") or []:
        out.append(situation_to_decision(row))
    return out


def classify_auditable_result(
    *,
    notification_counts: dict[str, int],
    suppressed_by_reason: dict[str, int],
    dry_run: bool,
    canary: bool,
    policy_gap: bool,
    delivered: bool,
    delivery_failed: bool = False,
    dead_lettered: bool = False,
) -> str:
    if dead_lettered:
        return "DEAD_LETTERED"
    if delivery_failed:
        return "DELIVERY_FAILED_RETRYING"
    if delivered:
        return "NOTIFICATION_DELIVERED"
    if int(notification_counts.get(DELIVERY_IMMEDIATE) or 0) > 0:
        if dry_run or not canary:
            return "DRY_RUN_INTERDICTED"
        return "NOTIFICATION_QUEUED"
    if policy_gap and int(notification_counts.get(DELIVERY_IMMEDIATE) or 0) == 0:
        # gap may be suppressed as unchanged; still name the situation
        if "POLICY_GAP" in json.dumps(suppressed_by_reason) or policy_gap:
            if int(notification_counts.get(DELIVERY_SUPPRESSED) or 0) and not int(notification_counts.get(DELIVERY_DIGEST) or 0):
                if list(suppressed_by_reason.keys()) == ["unchanged_replay"] or "unchanged_replay" in suppressed_by_reason:
                    return "NOTIFICATION_SUPPRESSED"
            return "POLICY_GAP_QUESTION"
    if int(notification_counts.get(DELIVERY_DIGEST) or 0) > 0:
        return "NOTIFICATION_DIGESTED"
    if int(notification_counts.get(DELIVERY_COMMAND_CENTER_ONLY) or 0) > 0:
        return "COMMAND_CENTER_ONLY"
    if int(notification_counts.get(DELIVERY_SUPPRESSED) or 0) > 0:
        reasons = set(suppressed_by_reason)
        if reasons <= {"unchanged_replay", "NO_MATERIAL_CHANGE", "non_action_state"} or "unchanged_replay" in reasons:
            return "NOTIFICATION_SUPPRESSED"
        return "NOTIFICATION_SUPPRESSED"
    return "NO_MATERIAL_CHANGE"
