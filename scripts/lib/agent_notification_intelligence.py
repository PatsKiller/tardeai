"""agent_notification_intelligence.py — notification reasoning + follow-up binding.

READ_ONLY_ADVISORY. Implements Phase 2.3 (notification reasoning trace) and
2.4 (durable follow-up binding), shared with Phase 6 (autonomous office).

Invariants:
  * unchanged replays are suppressed (same generation + evidence digest)
  * a prior operator REJECT suppresses the same unchanged recommendation
  * a new evidence generation may reopen with WHAT CHANGED SINCE YOUR REJECT
  * every material non-action binds a durable next review or explicitly
    NEXT_REVIEW_UNAVAILABLE + reason (no bare NEXT REVIEW)
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.agent_context_envelope import sha256_hex

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_NOTIFICATION_TRACE_PATH = PROJECT_ROOT / "data" / "cio" / "agent_notification_traces.jsonl"

# ── Next-review kinds ──────────────────────────────────────────────────────
NEXT_KIND_TIME = "TIME"
NEXT_KIND_CONDITION = "CONDITION"
NEXT_KIND_DATA_FRESHNESS = "DATA_FRESHNESS"
NEXT_KIND_EVENT = "EVENT"
NEXT_REVIEW_UNAVAILABLE = "NEXT_REVIEW_UNAVAILABLE"

# Non-action current actions that require a durable next review.
_NON_ACTION_ACTIONS = frozenset({
    "WAIT", "REVALIDATE", "DATA_UNAVAILABLE", "DEFER", "RESEARCH", "HOLD",
})

# Dispositions that suppress an unchanged recommendation.
_SUPPRESSING_DISPOSITIONS = frozenset({"REJECT", "ACK", "DONE"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def dedupe_identity(decision: dict[str, Any]) -> str:
    """Content identity used to detect unchanged replays."""
    body = {
        "decision_id": decision.get("decision_id"),
        "input_digest": decision.get("decision_input_digest"),
        "evidence_digest": decision.get("decision_evidence_digest"),
        "current_action": decision.get("current_action"),
        "act_now": decision.get("act_now"),
    }
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return "notif_" + sha256_hex(raw, 16)


def build_next_review(
    *,
    kind: Optional[str] = None,
    due_at: Optional[str] = None,
    condition: Optional[str] = None,
    revisit_id: Optional[str] = None,
    unavailable_reason: Optional[str] = None,
) -> dict[str, Any]:
    """Build a durable next-review binding, or an explicit unavailable record.

    A material non-action must either bind kind+revisit_id (TIME/CONDITION/
    DATA_FRESHNESS/EVENT) or explicitly NEXT_REVIEW_UNAVAILABLE with a reason.
    """
    if kind:
        return {
            "kind": kind,
            "due_at": due_at,
            "condition": condition,
            "revisit_id": revisit_id or f"rv_{uuid.uuid4().hex[:16]}",
            "lineage": None,
        }
    if unavailable_reason:
        return {
            "kind": NEXT_REVIEW_UNAVAILABLE,
            "due_at": None,
            "condition": None,
            "revisit_id": None,
            "reason": unavailable_reason,
        }
    # A bare next review is a quality defect — represent it loudly.
    return {
        "kind": NEXT_REVIEW_UNAVAILABLE,
        "due_at": None,
        "condition": None,
        "revisit_id": None,
        "reason": "NO_SCHEDULE_PROVIDED",
    }


def validate_next_review(next_review: Any) -> tuple[bool, str]:
    """Reject a bare/blank next review. Returns (ok, reason)."""
    if not isinstance(next_review, dict):
        return False, "next_review missing"
    kind = next_review.get("kind")
    if not kind:
        return False, "next_review.kind missing"
    if kind == NEXT_REVIEW_UNAVAILABLE:
        if not next_review.get("reason"):
            return False, "NEXT_REVIEW_UNAVAILABLE without reason"
        return True, "explicitly unavailable"
    if kind in (NEXT_KIND_TIME, NEXT_KIND_CONDITION, NEXT_KIND_DATA_FRESHNESS, NEXT_KIND_EVENT):
        if not next_review.get("revisit_id"):
            return False, f"kind={kind} without revisit_id"
        return True, f"bound ({kind})"
    return False, f"unknown kind: {kind}"


def needs_next_review(current_action: Optional[str]) -> bool:
    return str(current_action or "").upper() in _NON_ACTION_ACTIONS


def evaluate_notification(
    *,
    decision: dict[str, Any],
    previous: Optional[dict[str, Any]] = None,
    operator_disposition: Optional[str] = None,
) -> dict[str, Any]:
    """Decide whether to send a notification and why.

    Returns a reasoning record with `send`, `suppressed_reason` (or None),
    `materiality`, `dedupe_key`, `reopen` flag, and a follow-up requirement.
    """
    identity = dedupe_identity(decision)
    disposition = str(operator_disposition or "").upper() if operator_disposition else None
    previous = previous or {}

    same_identity = previous.get("dedupe_key") == identity
    same_decision = previous.get("decision_id") == decision.get("decision_id")
    prev_evidence = previous.get("evidence_digest") or previous.get("decision_evidence_digest")
    evidence_changed = bool(prev_evidence) and prev_evidence != decision.get("decision_evidence_digest")
    prior_reject = (
        disposition in _SUPPRESSING_DISPOSITIONS
        or str(previous.get("disposition") or "").upper() in _SUPPRESSING_DISPOSITIONS
    )

    material = bool(decision.get("act_now")) or str(decision.get("current_action") or "").upper() not in _NON_ACTION_ACTIONS

    send = True
    suppressed_reason = None
    reopen = False

    if not material:
        send = False
        suppressed_reason = "non_material"
    elif same_identity and not evidence_changed:
        send = False
        suppressed_reason = "prior_operator_reject_unchanged" if prior_reject else "unchanged_replay"
    elif same_decision and evidence_changed and prior_reject:
        # New evidence may reopen a prior REJECT, but only with an explicit
        # "what changed" marker — never silently.
        send = True
        reopen = True

    return {
        "considered": True,
        "materiality": "material" if material else "non_material",
        "dedupe_key": identity,
        "send": send,
        "suppressed_reason": suppressed_reason,
        "reopen": reopen,
        "reopen_label": "WHAT CHANGED SINCE YOUR REJECT" if reopen else None,
        "previous_notification": previous.get("notification_id"),
        "operator_disposition": disposition,
        "follow_up_required": needs_next_review(decision.get("current_action")),
    }


def append_notification_reason(
    record: dict[str, Any],
    *,
    trace_id: Optional[str] = None,
    wake_id: Optional[str] = None,
    notification_id: Optional[str] = None,
    path: Path | str | None = None,
) -> bool:
    """Append a notification reasoning record. Fail-soft."""
    try:
        p = Path(path) if path else DEFAULT_NOTIFICATION_TRACE_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        row = dict(record)
        row["trace_id"] = trace_id
        row["wake_id"] = wake_id
        row["notification_id"] = notification_id
        row["ts"] = _now_iso()
        row = {k: v for k, v in row.items() if v is not None}
        line = json.dumps(row, sort_keys=True, separators=(",", ":"), default=str) + "\n"
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()
        return True
    except Exception:
        return False
