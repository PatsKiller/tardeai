"""Canonical advisory notification pipeline: prepare → send → receipt.

Uses existing outbox + delivery adapters. Never manufactures a financial
condition. Synthetic fixture delivery is the default test path.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any

from scripts.lib.cio_advisory_message import assert_not_json_dump, render_advisory_message
from scripts.lib.cio_notification_delivery import FakeDeliveryAdapter
from scripts.lib.cio_notification_outbox import NotificationOutbox as CIONotificationOutbox

AUTHORITY = "READ_ONLY_ADVISORY"
SENDER = "alex_cio"


def _body_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def prepare_advisory_notification(
    situation: dict[str, Any],
    *,
    message: str | None = None,
    channel: str = "telegram",
) -> dict[str, Any]:
    body = message or render_advisory_message(situation)
    assert_not_json_dump(body)
    nid = f"ntf_{uuid.uuid4().hex[:16]}"
    return {
        "notification_id": nid,
        "message_class": "advisory",
        "channel_targets": [channel],
        "subject": "Alex · CIO advisory",
        "body": body,
        "body_hash": _body_hash(body),
        "sender": SENDER,
        "situation_id": situation.get("situation_id"),
        "decision_id": situation.get("situation_id"),
        "trace_id": f"trace_{nid}",
        "dedupe_key": f"cio:{situation.get('fingerprint') or situation.get('situation_id')}",
        "idempotency_key": f"cio:{situation.get('fingerprint') or nid}",
        "authority": AUTHORITY,
        "financial_action": False,
        "parse_mode": None,
    }


def deliver_prepared(
    notification: dict[str, Any],
    *,
    outbox: CIONotificationOutbox | None = None,
    adapter: Any | None = None,
    live: bool = False,
) -> dict[str, Any]:
    if live:
        raise RuntimeError("LIVE_DELIVERY_REQUIRES_EXPLICIT_OPERATOR_AUTHORIZATION")
    adapter = adapter or FakeDeliveryAdapter()
    prepared = dict(notification)
    sent = adapter.send(prepared)
    receipt = {
        "schema": "CIOAdvisoryDeliveryReceipt@v1",
        "prepared": True,
        "sent": bool(sent.get("delivered")),
        "delivery_receipt": sent,
        "sender": SENDER,
        "sender_attribution": SENDER,
        "trace_id": prepared.get("trace_id"),
        "situation_id": prepared.get("situation_id"),
        "decision_id": prepared.get("decision_id"),
        "semantic_dedupe_key": prepared.get("dedupe_key"),
        "live": bool(getattr(adapter, "is_live", False)),
        "authority": AUTHORITY,
        "financial_action": False,
    }
    if outbox is not None:
        try:
            outbox.enqueue(prepared, actor_id="alex", actor_type="agent", authority="advisory")
        except Exception as exc:
            receipt["outbox_error"] = f"{type(exc).__name__}:{exc}"
    return receipt
