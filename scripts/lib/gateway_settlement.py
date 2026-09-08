"""Lane G — reserve → Telegram transport → provider ack → SETTLED.

Orchestrates gateway-owned CANARY delivery for agent outbound events.
Durable attempt (ChannelDelivery RESERVED) is recorded **before** transport.
Provider message / settlement id is stamped only after acknowledgement.

Transport is injected. This module never opens a network socket and never
reads bot tokens. Live wiring injects the approved adapter at integration
time (SFR); tests inject an isolated fake.

Idempotent retry: a second call with the same event idempotency key reuses the
existing delivery and does **not** invoke transport again once SETTLED.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from scripts.lib.agent_gateway_adapter import (
    AgentOutboundRequest,
    GatewayAdapterError,
    OwnershipDecision,
    build_outbound_event,
    filter_canary_chats,
)
from scripts.lib.comms.client import PublishResult, publish_communication
from scripts.lib.comms.delivery import (
    ChannelDelivery,
    DeliveryGateError,
    find_delivery_by_provider_message_id,
    reserve_delivery,
    settle_delivery,
)
from scripts.lib.comms.event import CommunicationEvent

TransportFn = Callable[..., dict[str, Any]]


class SettlementError(ValueError):
    """Fail-closed settlement / persistence / config error."""


@dataclass
class SettlementResult:
    ok: bool
    event_id: str | None = None
    delivery_id: str | None = None
    thread_id: str | None = None
    correlation_id: str | None = None
    subject_guid: str | None = None
    delivery_owner: str | None = None
    gateway_mode: str | None = None
    ownership_reason: str | None = None
    provider_message_id: str | None = None
    provider_settlement_state: str | None = None
    delivered: bool = False
    duplicate: bool = False
    transport_invoked: bool = False
    errors: list[str] = field(default_factory=list)
    command_center_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "event_id": self.event_id,
            "delivery_id": self.delivery_id,
            "thread_id": self.thread_id,
            "correlation_id": self.correlation_id,
            "subject_guid": self.subject_guid,
            "delivery_owner": self.delivery_owner,
            "gateway_mode": self.gateway_mode,
            "ownership_reason": self.ownership_reason,
            "provider_message_id": self.provider_message_id,
            "provider_settlement_state": self.provider_settlement_state,
            "delivered": self.delivered,
            "duplicate": self.duplicate,
            "transport_invoked": self.transport_invoked,
            "errors": list(self.errors),
            "command_center_url": self.command_center_url,
        }


# Process-local index: event_id -> last settlement outcome (for idempotent retry
# without a second transport call). Cleared by tests via reset_settlement_index().
_SETTLED_BY_EVENT: dict[str, SettlementResult] = {}
_TRANSPORT_COUNT_BY_EVENT: dict[str, int] = {}


def reset_settlement_index() -> None:
    _SETTLED_BY_EVENT.clear()
    _TRANSPORT_COUNT_BY_EVENT.clear()


def transport_invoke_count(event_id: str) -> int:
    return int(_TRANSPORT_COUNT_BY_EVENT.get(event_id, 0))


def _require_transport(transport: TransportFn | None) -> TransportFn:
    if transport is None:
        raise SettlementError("missing_transport")
    return transport


def _legacy_result(
    event: CommunicationEvent,
    ownership: OwnershipDecision,
    *,
    publish: PublishResult,
    errors: list[str] | None = None,
) -> SettlementResult:
    return SettlementResult(
        ok=True,
        event_id=event.event_id,
        delivery_id=(publish.delivery_ids[0] if publish.delivery_ids else None),
        thread_id=event.thread_id,
        correlation_id=event.correlation_id,
        subject_guid=event.subject_guid,
        delivery_owner="legacy",
        gateway_mode=ownership.gateway_mode,
        ownership_reason=ownership.reason,
        provider_message_id=None,
        provider_settlement_state="UNKNOWN_LEGACY",
        delivered=False,
        duplicate=bool(publish.duplicate),
        transport_invoked=False,
        errors=list(errors or []),
        command_center_url=event.command_center_url,
    )


def deliver_agent_outbound(
    req: AgentOutboundRequest,
    *,
    deliver: bool = False,
    transport: TransportFn | None = None,
) -> SettlementResult:
    """Full path: build event → publish → reserve → (optional) transport → settle.

    ``deliver=False`` (default): ledger + RESERVED attempt only; no transport.
    ``deliver=True``: requires an injected ``transport`` callable. Never sends
    on the network itself.
    """
    try:
        event, ownership = build_outbound_event(req)
    except GatewayAdapterError as exc:
        return SettlementResult(ok=False, errors=[f"adapter:{exc}"])

    # Idempotent retry: already SETTLED for this event_id → no transport.
    prior = _SETTLED_BY_EVENT.get(str(event.event_id or ""))
    if prior and prior.provider_settlement_state == "SETTLED" and prior.ok:
        dup = SettlementResult(**{**prior.to_dict(), "duplicate": True, "transport_invoked": False})
        return dup

    try:
        published = publish_communication(event)
    except Exception as exc:
        return SettlementResult(
            ok=False,
            errors=[f"persist_failed:{type(exc).__name__}:{exc}"],
            subject_guid=req.subject_guid,
            gateway_mode=ownership.gateway_mode,
            ownership_reason=ownership.reason,
        )

    if not published.ok or not published.event_id:
        return SettlementResult(
            ok=False,
            event_id=published.event_id,
            errors=list(published.errors) or ["publish_failed"],
            gateway_mode=ownership.gateway_mode,
            ownership_reason=ownership.reason,
            subject_guid=event.subject_guid,
            command_center_url=event.command_center_url,
        )

    # Align event_id with persisted row (idempotent collide may return existing).
    event.event_id = published.event_id

    # Legacy outside allowlist: record ownership reason; do not gateway-send.
    if ownership.delivery_owner != "gateway":
        event.apply_provider_settlement(
            provider_message_id=None,
            status="LEGACY_DELIVERED",
            delivery_owner="legacy",
            gateway_mode=ownership.gateway_mode,
            failure_reason=ownership.reason,
        )
        return _legacy_result(event, ownership, publish=published)

    # Gateway path: durable attempt BEFORE transport.
    try:
        reserved = reserve_delivery(
            event_id=event.event_id,
            channel=req.channel,
            attempt_id="1",
            adapter_version="telegram@v1" if req.channel == "telegram" else None,
            reply_thread_coordinates={
                "thread_id": event.thread_id,
                "correlation_id": event.correlation_id,
                "subject_guid": event.subject_guid,
            },
        )
    except DeliveryGateError as exc:
        return SettlementResult(
            ok=False,
            event_id=event.event_id,
            errors=[f"reserve_failed:{exc}"],
            gateway_mode=ownership.gateway_mode,
            ownership_reason=ownership.reason,
            subject_guid=event.subject_guid,
            delivery_owner="gateway",
            command_center_url=event.command_center_url,
        )

    if reserved.duplicate and reserved.status in ("SENT", "DELIVERED", "ACKNOWLEDGED"):
        # Already settled attempt — do not re-send.
        return SettlementResult(
            ok=True,
            event_id=event.event_id,
            delivery_id=reserved.delivery_id,
            thread_id=event.thread_id,
            correlation_id=event.correlation_id,
            subject_guid=event.subject_guid,
            delivery_owner="gateway",
            gateway_mode=ownership.gateway_mode,
            ownership_reason=ownership.reason,
            provider_message_id=reserved.provider_message_id,
            provider_settlement_state="SETTLED",
            delivered=True,
            duplicate=True,
            transport_invoked=False,
            command_center_url=event.command_center_url,
        )

    if not deliver:
        return SettlementResult(
            ok=True,
            event_id=event.event_id,
            delivery_id=reserved.delivery_id,
            thread_id=event.thread_id,
            correlation_id=event.correlation_id,
            subject_guid=event.subject_guid,
            delivery_owner="gateway",
            gateway_mode=ownership.gateway_mode,
            ownership_reason=ownership.reason,
            provider_message_id=None,
            provider_settlement_state="UNSETTLED",
            delivered=False,
            duplicate=bool(published.duplicate or reserved.duplicate),
            transport_invoked=False,
            command_center_url=event.command_center_url,
        )

    # deliver=True: injected transport only.
    try:
        txn = _require_transport(transport)
    except SettlementError as exc:
        return SettlementResult(
            ok=False,
            event_id=event.event_id,
            delivery_id=reserved.delivery_id,
            errors=[str(exc)],
            delivery_owner="gateway",
            gateway_mode=ownership.gateway_mode,
            ownership_reason=ownership.reason,
            subject_guid=event.subject_guid,
            provider_settlement_state="UNSETTLED",
            command_center_url=event.command_center_url,
        )

    # Explicit CANARY chat allowlist (fail-closed when configured).
    chat_ids, chat_err = filter_canary_chats(req.chat_ids, mode=ownership.gateway_mode)
    if chat_err:
        settle_delivery(
            str(reserved.delivery_id),
            status="FAILED",
            error_taxonomy=chat_err,
            delivery_owner="gateway",
            gateway_mode=ownership.gateway_mode,
        )
        return SettlementResult(
            ok=False,
            event_id=event.event_id,
            delivery_id=reserved.delivery_id,
            errors=[chat_err],
            delivery_owner="gateway",
            gateway_mode=ownership.gateway_mode,
            ownership_reason=ownership.reason,
            subject_guid=event.subject_guid,
            provider_settlement_state="FAILED",
            transport_invoked=False,
            command_center_url=event.command_center_url,
        )

    eid = str(event.event_id)
    _TRANSPORT_COUNT_BY_EVENT[eid] = _TRANSPORT_COUNT_BY_EVENT.get(eid, 0) + 1
    try:
        ack = txn(
            body=event.sanitized_body or "",
            chat_ids=chat_ids,
            thread_id=event.thread_id,
            correlation_id=event.correlation_id,
            event_id=event.event_id,
            delivery_id=reserved.delivery_id,
        )
    except Exception as exc:
        settle_delivery(
            str(reserved.delivery_id),
            status="FAILED",
            error_taxonomy=f"transport_exception:{type(exc).__name__}",
            delivery_owner="gateway",
            gateway_mode=ownership.gateway_mode,
        )
        return SettlementResult(
            ok=False,
            event_id=event.event_id,
            delivery_id=reserved.delivery_id,
            errors=[f"transport_exception:{type(exc).__name__}"],
            delivery_owner="gateway",
            gateway_mode=ownership.gateway_mode,
            ownership_reason=ownership.reason,
            subject_guid=event.subject_guid,
            provider_settlement_state="FAILED",
            transport_invoked=True,
            command_center_url=event.command_center_url,
        )

    if not isinstance(ack, dict) or not ack.get("ok"):
        err = str((ack or {}).get("error") or "transport_failed")
        settle_delivery(
            str(reserved.delivery_id),
            status="FAILED",
            error_taxonomy=err,
            delivery_owner="gateway",
            gateway_mode=ownership.gateway_mode,
        )
        return SettlementResult(
            ok=False,
            event_id=event.event_id,
            delivery_id=reserved.delivery_id,
            errors=[err],
            delivery_owner="gateway",
            gateway_mode=ownership.gateway_mode,
            ownership_reason=ownership.reason,
            subject_guid=event.subject_guid,
            provider_settlement_state="FAILED",
            transport_invoked=True,
            command_center_url=event.command_center_url,
        )

    pmid = str(ack.get("provider_message_id") or "").strip() or None
    if not pmid:
        settle_delivery(
            str(reserved.delivery_id),
            status="FAILED",
            error_taxonomy="missing_provider_message_id",
            delivery_owner="gateway",
            gateway_mode=ownership.gateway_mode,
        )
        return SettlementResult(
            ok=False,
            event_id=event.event_id,
            delivery_id=reserved.delivery_id,
            errors=["missing_provider_message_id"],
            delivery_owner="gateway",
            gateway_mode=ownership.gateway_mode,
            ownership_reason=ownership.reason,
            subject_guid=event.subject_guid,
            provider_settlement_state="FAILED",
            transport_invoked=True,
            command_center_url=event.command_center_url,
        )

    # Collision on provider id → treat as duplicate settlement, no second logical send.
    existing = find_delivery_by_provider_message_id(pmid)
    if existing and existing.delivery_id and existing.delivery_id != reserved.delivery_id:
        return SettlementResult(
            ok=True,
            event_id=event.event_id,
            delivery_id=existing.delivery_id,
            thread_id=event.thread_id,
            correlation_id=event.correlation_id,
            subject_guid=event.subject_guid,
            delivery_owner="gateway",
            gateway_mode=ownership.gateway_mode,
            ownership_reason=ownership.reason,
            provider_message_id=pmid,
            provider_settlement_state="SETTLED",
            delivered=True,
            duplicate=True,
            transport_invoked=True,
            command_center_url=event.command_center_url,
        )

    # Legal transition: RESERVED → SENT (ACKNOWLEDGED is not reachable directly).
    settled = settle_delivery(
        str(reserved.delivery_id),
        status="SENT",
        provider_message_id=pmid,
        provider_coordinates=dict(ack.get("provider_coordinates") or {}),
        delivery_owner="gateway",
        gateway_mode=ownership.gateway_mode,
    )
    event.apply_provider_settlement(
        provider_message_id=pmid,
        status="SENT",
        delivery_owner="gateway",
        gateway_mode=ownership.gateway_mode,
    )
    result = SettlementResult(
        ok=True,
        event_id=event.event_id,
        delivery_id=settled.delivery_id,
        thread_id=event.thread_id,
        correlation_id=event.correlation_id,
        subject_guid=event.subject_guid,
        delivery_owner="gateway",
        gateway_mode=ownership.gateway_mode,
        ownership_reason=ownership.reason,
        provider_message_id=pmid,
        provider_settlement_state="SETTLED",
        delivered=True,
        duplicate=False,
        transport_invoked=True,
        command_center_url=event.command_center_url,
    )
    _SETTLED_BY_EVENT[eid] = result
    return result


__all__ = [
    "SettlementError",
    "SettlementResult",
    "deliver_agent_outbound",
    "reset_settlement_index",
    "transport_invoke_count",
]
