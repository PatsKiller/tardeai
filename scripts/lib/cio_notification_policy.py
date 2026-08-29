"""NotificationPolicy@v1 — decide routing. This module never sends.

Wave 3B. Given a plan, its materiality and a council synthesis, return one of:

    IMMEDIATE | DIGEST | COMMAND_CENTER_ONLY | SUPPRESSED

Defaults are deliberately quiet, because the failure mode of a notification
system is not silence — it is noise that trains the operator to ignore it:

  * S1 observational          -> SUPPRESSED
  * S5 cash duplicates        -> SUPPRESSED  (36 open plans, one question)
  * S6 fire                   -> COMMAND_CENTER_ONLY, never IMMEDIATE
  * anything not material     -> SUPPRESSED

`IMMEDIATE` is reachable by the schema but nothing in this PR returns it
without an explicit operator-directed flag, and even then delivery is the
shadow adapter. There is no Telegram call site here: the delivery layer records
`would_send=False` and a test greps this PR for zero vendor API calls.

`CIO_SITUATION_NOTIFY` and `CIO_TELEGRAM_INTERDICT` are read-only inputs — this
module never sets or clears either.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

NOTIFICATION_POLICY_SCHEMA = "NotificationPolicy@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

IMMEDIATE = "IMMEDIATE"
DIGEST = "DIGEST"
COMMAND_CENTER_ONLY = "COMMAND_CENTER_ONLY"
SUPPRESSED = "SUPPRESSED"
DECISIONS = (IMMEDIATE, DIGEST, COMMAND_CENTER_ONLY, SUPPRESSED)

STORE_REL = "data/cio/cio_notification_policy.jsonl"

# Situation types that are observational by nature: they describe state, they
# do not ask the operator for anything.
_OBSERVATIONAL_S1 = frozenset({"observational", "revisit", "monitor", "watch"})


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def notify_env_state() -> dict[str, Any]:
    """Read the pins. Never write them."""
    notify = os.environ.get("CIO_SITUATION_NOTIFY") or os.environ.get(
        "CIO_SITUATIONS_NOTIFY") or "0"
    interdict = os.environ.get("CIO_TELEGRAM_INTERDICT") or "1"
    return {
        "cio_situation_notify": str(notify),
        "cio_telegram_interdict": str(interdict),
        "notify_enabled": str(notify).strip().lower() in {"1", "true", "yes", "on"},
        "interdicted": str(interdict).strip().lower() in {"1", "true", "yes", "on"},
    }


def notification_id(plan_id: Any, kind: str, as_of: str) -> str:
    raw = f"{plan_id}|{kind}|{as_of[:10]}"
    return "ntf_" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def decide(plan: Optional[dict[str, Any]] = None, *,
           materiality: Any = None,
           synthesis: Optional[dict[str, Any]] = None,
           duplicate_subject: bool = False,
           operator_directed: bool = False,
           now: Optional[datetime] = None) -> dict[str, Any]:
    """Route one notification. Deterministic; sends nothing."""
    plan = plan or {}
    as_of = (now or datetime.now(timezone.utc)).isoformat()
    stype = str(plan.get("situation_type") or "").upper()
    pid = plan.get("plan_id")
    material = bool(plan.get("material") if materiality is None else materiality)
    state = str((synthesis or {}).get("state") or "")

    def out(decision: str, reason: str, **extra: Any) -> dict[str, Any]:
        row = {
            "schema": NOTIFICATION_POLICY_SCHEMA,
            "notification_id": notification_id(pid, stype or "unknown", as_of),
            "plan_id": pid,
            "situation_type": stype or None,
            "decision": decision,
            "reason": reason,
            "as_of": as_of,
            "authority": AUTHORITY,
            "financial_action": False,
            "would_send": False,
            "delivery": "shadow",
            "council_state": state or None,
            "env": notify_env_state(),
        }
        row.update(extra)
        return row

    # Duplicates first: 36 open S5 cash plans are one question, and notifying
    # each would be the loudest possible way to say nothing new.
    if duplicate_subject:
        return out(SUPPRESSED, "duplicate_subject")

    if not material:
        return out(SUPPRESSED, "not_material")

    if stype.startswith("S5"):
        return out(SUPPRESSED, "s5_cash_deployment_default_suppressed")

    if stype.startswith("S1"):
        flavour = str(plan.get("s1_kind") or plan.get("flavour") or "").lower()
        if not flavour or flavour in _OBSERVATIONAL_S1:
            return out(SUPPRESSED, "s1_observational_default_suppressed")

    if stype.startswith("S6"):
        # A concentration fire is worth surfacing where the operator already
        # looks. It is not worth interrupting them.
        return out(COMMAND_CENTER_ONLY, "s6_fire_command_center_not_immediate")

    if state == "DISPUTED":
        return out(COMMAND_CENTER_ONLY, "council_disputed_needs_operator_eyes")

    if operator_directed:
        return out(IMMEDIATE, "operator_directed",
                   note=("delivery remains the shadow adapter in this PR; "
                         "would_send stays False"))

    return out(DIGEST, "material_but_not_urgent")


def persist(root: Path | str, row: dict[str, Any]) -> dict[str, Any]:
    """Record the decision. Recording a decision is not sending anything."""
    p = Path(root) / STORE_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"wrote": True, "path": str(p),
            "notification_id": row.get("notification_id")}


def deliver(row: dict[str, Any], adapter: Any = None) -> dict[str, Any]:
    """Hand the decision to the shadow adapter. Never selects a live adapter.

    The real Telegram adapter exists in cio_notification_delivery and is
    deliberately not importable from here by default — this PR adds no live
    delivery path.
    """
    if row.get("decision") == SUPPRESSED:
        return {"delivered": False, "would_send": False, "reason": "suppressed"}
    if adapter is None:
        from scripts.lib.cio_notification_delivery import FakeDeliveryAdapter

        adapter = FakeDeliveryAdapter()
    if getattr(adapter, "is_live", False):
        raise RuntimeError(
            "live delivery adapter refused: Wave 3B is decision-only")
    result = adapter.send({
        "notification_id": row.get("notification_id"),
        "channel_targets": ["command_center"],
    })
    return {"delivered": bool(result.get("delivered")),
            "would_send": False,
            "delivery_method": result.get("delivery_method"),
            "reason": row.get("reason")}
