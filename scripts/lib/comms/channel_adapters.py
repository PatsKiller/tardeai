"""Gateway channel adapters for Email / Slack / WhatsApp / Telegram.

Typed client over CommunicationEvent + ChannelDelivery. Default is SHADOW
record-only (`deliver=False`). Real provider I/O happens only when
`deliver=True` AND `COMMS_GATEWAY_MODE` is CANARY or ACTIVE, after
`require_event_id`. Underlying sends stay in approved adapters
(`scripts/alerting.py`, `scripts/lib/cio_whatsapp_egress.py`,
`telegram_alert._raw_send_telegram` / `telegram_transport`) via lazy import.

Telegram deliver is fail-closed on message-class allowlists:
  CANARY → COMMS_GATEWAY_CANARY_CLASSES (optional COMMS_GATEWAY_CANARY_CHATS)
  ACTIVE → COMMS_GATEWAY_ACTIVE_CLASSES
Empty allowlist for the active mode blocks Telegram deliver (does not
activate all classes). Other channels keep prior Phase 10 behavior.
COMMS_GATEWAY_MODE default remains OFF — this module never flips it.
"""
from __future__ import annotations

import os
from typing import Any

from scripts.lib.comms.client import publish_communication
from scripts.lib.comms.delivery import settle_delivery
from scripts.lib.comms.enforcement import require_event_id
from scripts.lib.comms.event import CommunicationEvent
from scripts.lib.comms.mode import MODE_ACTIVE, MODE_CANARY, get_gateway_mode
from scripts.lib.comms.vocabulary import normalize_message_class

SUPPORTED_CHANNELS = frozenset(
    {"email", "slack", "whatsapp_twilio", "whatsapp_meta", "telegram"}
)

ADAPTER_VERSIONS = {
    "email": "email@v1",
    "slack": "slack@v1",
    "whatsapp_twilio": "whatsapp_twilio@v1",
    "whatsapp_meta": "whatsapp_meta@v1",
    "telegram": "telegram@v1",
}

_DELIVERABLE_MODES = frozenset({MODE_CANARY, MODE_ACTIVE})

ENV_CANARY_CLASSES = "COMMS_GATEWAY_CANARY_CLASSES"
ENV_CANARY_CHATS = "COMMS_GATEWAY_CANARY_CHATS"
ENV_ACTIVE_CLASSES = "COMMS_GATEWAY_ACTIVE_CLASSES"


def _csv_env(name: str) -> frozenset[str]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def telegram_owned_classes(mode: str | None = None) -> list[str]:
    """Message classes the gateway owns for Telegram under the current/given mode.

    Fail-closed: OFF/SHADOW → []; CANARY/ACTIVE → sorted allowlist (empty if unset).
    """
    m = (mode or get_gateway_mode(refresh=True) or "").strip().upper()
    if m == MODE_CANARY:
        return sorted(_csv_env(ENV_CANARY_CLASSES))
    if m == MODE_ACTIVE:
        return sorted(_csv_env(ENV_ACTIVE_CLASSES))
    return []


def telegram_class_allowed(mode: str, message_class: str) -> bool:
    """Fail-closed class gate for Telegram deliver under CANARY/ACTIVE.

    Wave B: normalizes the class before the allowlist check so ownership agrees
    with the ledger (F3). `operator_alert`/`ops_alert`/`health*` fold into `ops`;
    unknown classes pass through unchanged; protected classes never alias away.
    """
    mc = normalize_message_class(message_class)
    if not mc:
        return False
    return mc in set(telegram_owned_classes(mode))


def _telegram_canary_chats() -> frozenset[str]:
    return _csv_env(ENV_CANARY_CHATS)


def _resolve_telegram_chat_ids(
    mode: str, requested: list[Any] | None
) -> tuple[list[str] | None, str | None]:
    """Apply optional CANARY chat allowlist. None requested → use env default chats.

    Returns (chat_ids_or_None, error). None chat_ids means caller should use
    telegram_alert default TELEGRAM_CHAT_ID list (still subject to canary filter
    when that list is resolved inside the provider send).
    """
    allow = _telegram_canary_chats() if mode == MODE_CANARY else frozenset()
    if requested is not None:
        ids = [str(c).strip() for c in requested if str(c).strip()]
        if mode == MODE_CANARY and allow:
            ids = [c for c in ids if c in allow]
            if not ids:
                return [], "delivery_blocked_canary_chats"
        return ids, None
    if mode == MODE_CANARY and allow:
        # Defer to provider: filter default chat list against allow.
        return None, None
    return None, None


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


def _provider_send_telegram(
    *,
    body: str,
    kwargs: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    """Deliver via approved low-level path — never call send_telegram (no recursion)."""
    chat_ids, chat_err = _resolve_telegram_chat_ids(mode, kwargs.get("chat_ids"))
    if chat_err:
        return {"ok": False, "error": chat_err}

    # Import raw sender — bypasses send_telegram / send_via_gateway re-entry.
    try:
        from scripts.telegram_alert import (
            _raw_send_telegram_result,
            _chat_ids as _default_chats,
        )
    except ImportError:  # pragma: no cover - scripts/ on path in some runners
        from telegram_alert import (  # type: ignore
            _raw_send_telegram_result,
            _chat_ids as _default_chats,
        )

    targets = chat_ids
    if targets is None:
        targets = list(_default_chats())
        allow = _telegram_canary_chats() if mode == MODE_CANARY else frozenset()
        if allow:
            targets = [c for c in targets if c in allow]
            if not targets:
                return {"ok": False, "error": "delivery_blocked_canary_chats"}

    result = _raw_send_telegram_result(
        body,
        chat_ids=targets,
        reply_markup=kwargs.get("reply_markup"),
        thread_id=kwargs.get("thread_id"),
    )
    if not result.get("ok"):
        return {"ok": False, "error": "telegram_send_failed"}
    mids = [str(m) for m in (result.get("message_ids") or []) if str(m).strip()]
    # One ChannelDelivery row may cover multiple chats/chunks — join ids stably.
    provider_message_id = ",".join(mids) if mids else None
    return {
        "ok": True,
        "provider_message_id": provider_message_id,
        "provider_coordinates": {
            "channel": "telegram",
            "adapter_version": ADAPTER_VERSIONS["telegram"],
            "message_ids": mids,
            "chat_ids": list(result.get("chat_ids") or targets or []),
        },
    }


def _provider_send(
    channel: str,
    *,
    body: str,
    subject: str | None,
    kwargs: dict[str, Any],
    mode: str | None = None,
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

    if channel == "telegram":
        return _provider_send_telegram(
            body=body, kwargs=kwargs, mode=mode or get_gateway_mode(refresh=True)
        )

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
    event_id: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Publish + reserve a channel delivery; optionally send via approved adapter.

    Default ``deliver=False`` records the CommunicationEvent and ChannelDelivery
    stub only (no network). Real send requires ``deliver=True`` and gateway mode
    CANARY or ACTIVE; otherwise returns ``error=delivery_blocked_mode``.

    Telegram additionally requires a non-empty class allowlist for the mode
    (``COMMS_GATEWAY_CANARY_CLASSES`` / ``COMMS_GATEWAY_ACTIVE_CLASSES``).

    Optional ``event_id``: when provided, skip minting a new event and bind
    deliver/`require_event_id` to that id (caller already published).
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

    pre_id = (event_id or "").strip() or None
    existing_dlv = kwargs.pop("_existing_delivery_id", None)
    if existing_dlv is not None:
        existing_dlv = str(existing_dlv).strip() or None
    if pre_id:
        # Caller already published — reuse their reservation or mint one.
        base["event_id"] = pre_id
        if existing_dlv:
            base["delivery_id"] = existing_dlv
            base["delivery_ids"] = [existing_dlv]
        else:
            from scripts.lib.comms.delivery import reserve_delivery

            try:
                reserved = reserve_delivery(
                    event_id=pre_id,
                    channel=ch,
                    adapter_version=ADAPTER_VERSIONS.get(ch),
                )
                base["delivery_id"] = reserved.delivery_id
                base["delivery_ids"] = (
                    [reserved.delivery_id] if reserved.delivery_id else []
                )
            except Exception as exc:
                base["error"] = "reserve_failed"
                base["errors"].append(f"reserve_failed:{type(exc).__name__}")
                return base
    else:
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

    # Telegram: fail-closed class allowlist (does not apply to other channels).
    if ch == "telegram" and not telegram_class_allowed(mode, message_class):
        base["ok"] = False
        base["error"] = "delivery_blocked_allowlist"
        base["errors"].append(
            f"delivery_blocked_allowlist:{mode}:{message_class or ''}"
        )
        base["delivery_owned"] = False
        base["delivered"] = False
        return base

    # Gateway owns this attempt once mode (and telegram allowlist) allow deliver.
    base["delivery_owned"] = True
    require_event_id(base["event_id"], adapter=ch)

    delivery_id = base["delivery_id"]
    send_error: str | None = None
    provider_message_id: str | None = None
    provider_coordinates: dict[str, Any] = {
        "channel": ch,
        "adapter_version": ADAPTER_VERSIONS.get(ch),
    }
    try:
        result = _provider_send(
            ch, body=body, subject=subject, kwargs=kwargs, mode=mode
        )
        if result.get("ok"):
            provider_message_id = result.get("provider_message_id")
            extra_coords = result.get("provider_coordinates")
            if isinstance(extra_coords, dict) and extra_coords:
                provider_coordinates = {**provider_coordinates, **extra_coords}
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
                    provider_coordinates=provider_coordinates,
                )
            else:
                settle_delivery(
                    delivery_id,
                    status="SENT",
                    provider_message_id=provider_message_id,
                    provider_coordinates=provider_coordinates,
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
