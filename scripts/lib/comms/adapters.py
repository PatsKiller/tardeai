"""Adapters from existing producer shapes into CommunicationEvent.

These do not send. They only construct ledger events for SHADOW/OFF recording.
"""
from __future__ import annotations

from typing import Any

from scripts.lib.comms.event import CommunicationEvent


def from_alert_event(alert: Any, *, sanitized_body: str | None = None) -> CommunicationEvent:
    """Map operator_alert_policy_v2.AlertEvent → CommunicationEvent."""
    alert_type = getattr(alert, "alert_type", None) or "operator_alert"
    producer = getattr(alert, "source_producer", None) or "unknown"
    source_system = getattr(alert, "source_system", None) or "trade_ai"
    symbol = getattr(alert, "symbol", None)
    account_id = getattr(alert, "account_id", None)
    entity_id = getattr(alert, "entity_id", None)
    severity = getattr(alert, "severity", None) or "info"
    action_required = bool(getattr(alert, "operator_action_required", False))
    payload = dict(getattr(alert, "payload", None) or {})

    entity_refs: dict[str, Any] = {}
    if symbol:
        entity_refs["symbol"] = symbol
    if account_id:
        entity_refs["account_id"] = account_id
    if entity_id:
        entity_refs["entity_id"] = entity_id

    subject_key = (
        f"alert:{alert_type}:{symbol or account_id or entity_id or producer}"
    )
    message_class = "protection_incident" if "protect" in alert_type or "orphan" in alert_type else "operator_alert"
    protected: dict[str, Any] = {}
    if action_required:
        protected["operator_action_required"] = True
        protected["operator_action_type"] = getattr(alert, "operator_action_type", None)
    if getattr(alert, "authorization_or_order_id", None):
        protected["authorization_or_order_id"] = alert.authorization_or_order_id
        message_class = "approval"

    return CommunicationEvent(
        direction="OUTBOUND",
        event_type=alert_type,
        message_class=message_class,
        producer=str(producer),
        subject_key=subject_key,
        retention_class="operational_30d",
        severity=str(severity),
        audience="operator",
        source_system=str(source_system),
        entity_refs=entity_refs,
        protected_facts=protected,
        authoritative_sources=(
            [{"source_type": "internal_alert", "uri": f"alert:{alert_type}", "authority_reason": "producer"}]
            if message_class in ("approval", "protection_incident")
            else []
        ),
        sanitized_body=sanitized_body,
        observation_version=str(getattr(alert, "state_version", "1") or "1"),
        intended_action="notify",
        channels=["telegram"],
        payload=payload,
    )


def from_plain_message(
    *,
    producer: str,
    body: str,
    subject_key: str,
    event_type: str = "operator_message",
    message_class: str = "operator_alert",
    retention_class: str = "operational_30d",
    severity: str = "info",
) -> CommunicationEvent:
    return CommunicationEvent(
        direction="OUTBOUND",
        event_type=event_type,
        message_class=message_class,
        producer=producer,
        subject_key=subject_key,
        retention_class=retention_class,
        severity=severity,
        sanitized_body=body,
        short_summary=(body or "")[:160],
        channels=["telegram"],
    )
