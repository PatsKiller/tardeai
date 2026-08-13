"""CIO decision pipeline — InvestmentDecision@v1 → action → notification.

Phase 4 wiring. Converts a canonical InvestmentDecision@v1 into exactly one
action (action ledger) and, when the decision is operator-facing (material +
READY_FOR_OPERATOR), exactly one notification (outbox). Both key off
decision_id, so re-running the pipeline for the same decision is idempotent.

READ_ONLY_ADVISORY. No broker/order/stop/2FA writes. Dry-testable via injectable
stores (defaults build real stores; tests inject temp-path fakes).
"""
from __future__ import annotations

import hashlib
from typing import Any, Optional

from scripts.lib.cio_investment_decision import (
    InvestmentDecision,
    ACTIONABILITY_READY,
    decision_to_action_payload,
)


def publish_decision(
    decision: InvestmentDecision,
    *,
    action_ledger: Any = None,
    notification_outbox: Any = None,
    title: str = "",
    notify_subject: str = "",
) -> dict[str, Any]:
    """Publish a decision to the action ledger and (if operator-facing) the outbox.

    Returns a summary with action_event and notification_event (or None). Both
    are idempotent on decision.decision_id. A decision that is not
    READY_FOR_OPERATOR is recorded as an action but produces NO notification.
    """
    errors = decision.validate()
    if errors:
        return {"ok": False, "errors": errors, "action_event": None, "notification_event": None}

    if action_ledger is None:
        from scripts.lib.cio_action_ledger import CIOActionLedger
        action_ledger = CIOActionLedger()

    payload = decision_to_action_payload(decision, title=title)

    # Idempotency: an existing action with the same decision idempotency_key
    # returns the prior event instead of creating a duplicate.
    action_event = action_ledger.create_action(payload, actor_id="alex")

    notification_event = None
    if decision.actionability == ACTIONABILITY_READY:
        if notification_outbox is None:
            from scripts.lib.cio_notification_outbox import NotificationOutbox
            notification_outbox = NotificationOutbox()

        body = (
            f"{decision.final_position} {','.join(decision.symbols) or 'book'} — "
            f"{decision.rationale_linked_to_evidence}"
        )
        note = {
            "notification_id": f"n_{decision.decision_id[:16]}",
            "idempotency_key": f"decision:{decision.decision_id}",
            "dedupe_key": f"decision:{decision.decision_id}",
            "message_class": "advisory",
            "channel_targets": ["telegram"],
            "subject": notify_subject or f"CIO decision · {decision.final_position}",
            "body": body,
            "body_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "cio_action_id": payload["cio_action_id"],
        }
        notification_event = notification_outbox.enqueue(note, actor_id="alex")

    return {
        "ok": True,
        "decision_id": decision.decision_id,
        "action_event": action_event,
        "notification_event": notification_event,
    }
