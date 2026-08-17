"""Canonical material-decision publisher.

Input: decision + optional capital plan + research context.
Dedupe: decision_id + input digest + evidence digest + material_state.
Opens a production case. Delivers via deliver_decision (dry by default).

Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

from scripts.lib.cio_alex_telegram import (
    deliver_decision,
    evaluate_outbound,
    is_material_event,
    rejected_unchanged,
)
from scripts.lib.cio_production_case import open_case_from_decision
from scripts.lib.cio_symbol_research import retrieve_symbol_research

AUTHORITY = "READ_ONLY_ADVISORY"

MATERIAL_ACTIONS = frozenset({
    "ADD", "TRIM", "EXIT", "WAIT", "RE_ENTER", "ROTATE",
    "DEPLOY_CASH", "RAISE_CASH", "HOLD_CASH", "RESEARCH", "NO_ACTION", "DEFER",
    "HOLD",
})


def publisher_dedupe_key(decision: dict[str, Any]) -> str:
    body = {
        "decision_id": str(decision.get("decision_id") or ""),
        "in": str(decision.get("decision_input_digest") or ""),
        "ev": str(decision.get("decision_evidence_digest") or ""),
        "stance": str(decision.get("stance_code") or decision.get("action") or "").upper(),
        "delta": decision.get("recommended_delta_usd") or decision.get("delta_usd"),
        "urgency": str(decision.get("urgency") or ""),
    }
    raw = json.dumps(body, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(f"pub|{raw}".encode()).hexdigest()[:32]


def _hold_is_material(decision: dict[str, Any]) -> bool:
    if str(decision.get("stance") or decision.get("action") or "").upper() not in {"HOLD", "HOLD-WITH-MATERIAL-CHANGE"}:
        return False
    return bool(decision.get("material_hold") or decision.get("why_now"))


def publish_material_decision(
    decision: dict[str, Any],
    *,
    capital_plan: Optional[dict[str, Any]] = None,
    holdings_row: Optional[dict[str, Any]] = None,
    dry_run: bool = True,
    event_type: str = "DECISION",
    body: Optional[str] = None,
    notification: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    did = str(decision.get("decision_id") or "").strip()
    if not did:
        return {"ok": False, "error": "missing_decision_id", "authority": AUTHORITY}

    if rejected_unchanged(decision):
        return {
            "ok": True,
            "published": False,
            "reason": "rejected_unchanged",
            "decision_id": did,
            "authority": AUTHORITY,
        }

    action = str(decision.get("stance_code") or decision.get("action") or "").upper()
    mat = is_material_event(kind="decision", decision=decision)
    if action == "HOLD" and not _hold_is_material(decision):
        if not mat.get("material"):
            return {"ok": True, "published": False, "reason": "hold_not_material", "authority": AUTHORITY}

    research = retrieve_symbol_research(
        str(decision.get("symbol") or ""),
        holdings_row=holdings_row,
        decision=decision,
    )
    case = open_case_from_decision(decision, research=research)
    ev = evaluate_outbound(decision, kind="decision")
    delivered = deliver_decision(decision, kind="decision", dry_run=dry_run, body=body)

    # Notification-gate awareness: a non-IMMEDIATE decision is never delivered,
    # even though its canonical decision is still opened/evaluated for parity.
    result: dict[str, Any] = {
        "ok": True,
        "published": bool(delivered.get("delivered") or (dry_run and ev.get("would_send"))),
        "dry_run": dry_run,
        "event_type": event_type,
        "dedupe_key": publisher_dedupe_key(decision),
        "evaluate": ev,
        "delivery": delivered,
        "case_id": case.get("case_id"),
        "research_audit": (research.get("decision_use_audit") or {}),
        "capital_plan_digest": (capital_plan or {}).get("digest"),
        "authority": AUTHORITY,
    }
    if notification is not None:
        result["notification"] = notification
        result["delivery_class"] = notification.get("notification_class")
        result["suppressed_reason"] = notification.get("suppressed_reason")
        if notification.get("notification_class") != "IMMEDIATE":
            result["published"] = False
    return result
