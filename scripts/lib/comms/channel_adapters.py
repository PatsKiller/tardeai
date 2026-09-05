"""Gateway channel adapters for Email / Slack / WhatsApp (Phase 10).

Typed client over CommunicationEvent + ChannelDelivery. Default is SHADOW
record-only (`deliver=False`). Real provider I/O happens only when
`deliver=True` AND `COMMS_GATEWAY_MODE` is CANARY or ACTIVE, after
`require_event_id`. Underlying sends stay in approved adapters
(`scripts/alerting.py`, `scripts/lib/cio_whatsapp_egress.py`) via lazy import.
"""
from __future__ import annotations

from typing import Any

from scripts.lib.comms.client import publish_communication
from scripts.lib.comms.delivery import settle_delivery
from scripts.lib.comms.enforcement import require_event_id
from scripts.lib.comms.event import CommunicationEvent
from scripts.lib.comms.mode import MODE_ACTIVE, MODE_CANARY, get_gateway_mode

SUPPORTED_CHANNELS = frozenset(
    {"email", "slack", "whatsapp_twilio", "whatsapp_meta"}
)

ADAPTER_VERSIONS = {
    "email": "email@v1",
    "slack": "slack@v1",
    "whatsapp_twilio": "whatsapp_twilio@v1",
    "whatsapp_meta": "whatsapp_meta@v1",
}

_DELIVERABLE_MODES = frozenset({MODE_CANARY, MODE_ACTIVE})


def _build_event(
    channel: str,
    *,
    body: str,
    subject: str | None,
    producer: str,
    subject_key: str,
    event_type: str,
    message_class: str,
    retention_class: str,
    severity: str,
    payload: dict[str, Any] | None,
) -> CommunicationEvent:
    summary = (body or "")[:160]
    if subject and channel == "email":
        summary = subject[:160]
    return CommunicationEvent(
        direction="OUTBOUND",
        event_type=event_type,
        message_class=message_class,
        producer=producer,
        subject_key=subject_key,
        retention_class=retention_class,
        severity=severity,
        sanitized_body=body,
        short_summary=summary,
        channels=[channel],
        payload=dict(payload or {}),
        provider_coordinates={"adapter_version": ADAPTER_VERSIONS.get(channel)},
    )


def _provider_send(
    channel: str,
    *,
    body: str,
    subject: str | None,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Invoke approved underlying adapter. Lazy-import to avoid heavy deps."""
    if channel == "email":
        from scripts.alerting import send_email

        send_email(
            subject or kwargs.get("email_subject") or "(no subject)",
            body,
            html=str(kwargs.get("html") or ""),
            attachments=kwargs.get("attachments"),
        )
        return {"ok": True, "provider_message_id": None}

    if channel == "slack":
        from scripts.alerting import send_slack

        send_slack(body)
        return {"ok": True, "provider_message_id": None}

    if channel == "whatsapp_twilio":
        from scripts.alerting import send_whatsapp

        send_whatsapp(body)
        return {"ok": True, "provider_message_id": None}

    if channel == "whatsapp_meta":
        from scripts.lib.cio_whatsapp_egress import send_whatsapp_text

        to_wa_id = kwargs.get("to_wa_id") or kwargs.get("to")
        if not to_wa_id:
            return {"ok": False, "error": "missing_to_wa_id"}
        result = send_whatsapp_text(
            str(to_wa_id),
            body,
            reply_to=kwargs.get("reply_to"),
            dry_run=bool(kwargs.get("dry_run", False)),
            http_post=kwargs.get("http_post"),
            token=kwargs.get("token"),
            phone_number_id=kwargs.get("phone_number_id"),
        )
        if not isinstance(result, dict):
            return {"ok": False, "error": "invalid_provider_result"}
        if not result.get("ok"):
            return {
                "ok": False,
                "error": str(result.get("error") or "provider_failed"),
                "provider_message_id": result.get("message_id"),
            }
        return {
            "ok": True,
            "provider_message_id": result.get("message_id"),
            "provider_result": result,
        }

    return {"ok": False, "error": f"unsupported_channel:{channel}"}


def send_via_gateway(
    channel: str,
    *,
    body: str,
    subject: str | None = None,
    producer: str,
    subject_key: str,
    event_type: str = "operator_message",
    message_class: str = "operator_alert",
    retention_class: str = "operational_30d",
    deliver: bool = False,
    severity: str = "info",
    payload: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Publish + reserve a channel delivery; optionally send via approved adapter.

    Default ``deliver=False`` records the CommunicationEvent and ChannelDelivery
    stub only (no network). Real send requires ``deliver=True`` and gateway mode
    CANARY or ACTIVE; otherwise returns ``error=delivery_blocked_mode``.
    """
    ch = str(channel or "").strip().lower()
    mode = get_gateway_mode(refresh=True)

    base: dict[str, Any] = {
        "ok": False,
        "event_id": None,
        "delivery_id": None,
        "delivery_ids": [],
        "delivery_owned": False,
        "delivered": False,
        "gateway_mode": mode,
        "channel": ch,
        "errors": [],
    }

    if ch not in SUPPORTED_CHANNELS:
        base["error"] = "unsupported_channel"
        base["errors"].append(f"unsupported_channel:{ch}")
        return base

    event = _build_event(
        ch,
        body=body,
        subject=subject,
        producer=producer,
        subject_key=subject_key,
        event_type=event_type,
        message_class=message_class,
        retention_class=retention_class,
        severity=severity,
        payload=payload,
    )
    published = publish_communication(event)
    base["event_id"] = published.event_id
    base["delivery_ids"] = list(published.delivery_ids or [])
    base["delivery_id"] = (
        published.delivery_ids[0] if published.delivery_ids else None
    )
    base["gateway_mode"] = published.gateway_mode or mode
    if published.errors:
        base["errors"].extend(list(published.errors))

    if not published.ok or not published.event_id:
        base["error"] = "publish_failed"
        base["errors"].append("publish_failed")
        return base

    if not deliver:
        base["ok"] = True
        base["delivery_owned"] = False
        base["delivered"] = False
        return base

    # Explicit deliver requested — mode gate before any provider I/O.
    mode = get_gateway_mode(refresh=True)
    base["gateway_mode"] = mode
    if mode not in _DELIVERABLE_MODES:
        base["ok"] = False
        base["error"] = "delivery_blocked_mode"
        base["errors"].append(f"delivery_blocked_mode:{mode}")
        base["delivery_owned"] = False
        base["delivered"] = False
        return base

    # Gateway owns this attempt once mode allows deliver.
    base["delivery_owned"] = True
    require_event_id(published.event_id, adapter=ch)

    delivery_id = base["delivery_id"]
    send_error: str | None = None
    provider_message_id: str | None = None
    try:
        result = _provider_send(ch, body=body, subject=subject, kwargs=kwargs)
        if result.get("ok"):
            provider_message_id = result.get("provider_message_id")
        else:
            send_error = str(result.get("error") or "provider_failed")
    except Exception as exc:
        send_error = f"{type(exc).__name__}:{exc}"

    if delivery_id:
        try:
            if send_error:
                settle_delivery(
                    delivery_id,
                    status="FAILED",
                    error_taxonomy=send_error[:200],
                    provider_coordinates={
                        "channel": ch,
                        "adapter_version": ADAPTER_VERSIONS.get(ch),
                    },
                )
            else:
                settle_delivery(
                    delivery_id,
                    status="SENT",
                    provider_message_id=provider_message_id,
                    provider_coordinates={
                        "channel": ch,
                        "adapter_version": ADAPTER_VERSIONS.get(ch),
                    },
                )
        except Exception as exc:
            base["errors"].append(f"settle_failed:{type(exc).__name__}")

    if send_error:
        base["ok"] = False
        base["error"] = send_error
        base["errors"].append(send_error)
        base["delivered"] = False
        return base

    base["ok"] = True
    base["delivered"] = True
    if provider_message_id:
        base["provider_message_id"] = provider_message_id
    return base
