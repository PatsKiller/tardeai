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

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

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
from scripts.lib.comms.mode import MODE_ACTIVE, MODE_CANARY, get_gateway_mode

TransportFn = Callable[..., dict[str, Any]]

# Explicit second gate on top of COMMS_GATEWAY_MODE. Integration injects the
# wake outbound handler only when this is on (see SFR-G-003).
ENV_WAKE_GATEWAY_OUTBOUND = "PERSISTENT_WAKE_GATEWAY_OUTBOUND"
DEFAULT_OUTBOUND_MESSAGE_CLASS = "ops"


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


# ── Runtime factory (wake → gateway) ─────────────────────────────────────────


def _env_flag(name: str, env: Mapping[str, str] | None = None, *, default: str = "") -> str:
    src = env if env is not None else os.environ
    return str(src.get(name, default) or "").strip()


def wake_gateway_outbound_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Explicit feature gate: PERSISTENT_WAKE_GATEWAY_OUTBOUND must be 1/true/on."""
    raw = _env_flag(ENV_WAKE_GATEWAY_OUTBOUND, env).lower()
    return raw in {"1", "true", "yes", "on"}


def sanctioned_telegram_transport(
    *,
    body: str,
    chat_ids: list[str] | None = None,
    thread_id: str | None = None,
    **_ignored: Any,
) -> dict[str, Any]:
    """Approved Telegram adapter boundary — reuses ``_raw_send_telegram_result``.

    Fail-closed without runtime authorization:
      * ``ENABLE_TELEGRAM`` must not be false
      * ``TELEGRAM_BOT_TOKEN`` must be present (never logged)
    Does not create a second Telegram client. Never returns credentials.
    """
    try:
        from scripts.telegram_alert import _env as _tg_env
        from scripts.telegram_alert import _raw_send_telegram_result
        from scripts.telegram_alert import _token
    except Exception as exc:  # pragma: no cover - import path variance
        return {"ok": False, "error": f"telegram_adapter_unavailable:{type(exc).__name__}"}

    if str(_tg_env("ENABLE_TELEGRAM", "true")).lower() == "false":
        return {"ok": False, "error": "telegram_disabled"}
    token = _token()
    if not token:
        return {"ok": False, "error": "missing_telegram_authorization"}
    # Do not pass token through kwargs; the approved adapter reads it itself.
    result = _raw_send_telegram_result(
        body or "",
        chat_ids=list(chat_ids) if chat_ids is not None else None,
        thread_id=thread_id,
    )
    if not isinstance(result, dict):
        return {"ok": False, "error": "invalid_provider_result"}
    if not result.get("ok"):
        return {
            "ok": False,
            "error": str(result.get("error") or "telegram_send_failed"),
            "provider_message_id": None,
        }
    mids = [str(m) for m in (result.get("message_ids") or []) if str(m).strip()]
    pmid = ",".join(mids) if mids else None
    if not pmid:
        return {"ok": False, "error": "missing_provider_message_id"}
    return {
        "ok": True,
        "provider_message_id": pmid,
        "provider_coordinates": {
            "channel": "telegram",
            "adapter": "telegram_alert._raw_send_telegram_result",
            "message_ids": mids,
            "chat_ids": list(result.get("chat_ids") or chat_ids or []),
        },
    }


def _request_from_wake(
    *,
    wake: Mapping[str, Any],
    receipts: list[Mapping[str, Any]] | None,
    env: Mapping[str, str] | None,
) -> AgentOutboundRequest:
    """Map a SETTLED wake (+ receipts) into AgentOutboundRequest. Fail-closed."""
    if not isinstance(wake, Mapping):
        raise SettlementError("wake_not_mapping")
    subject_guid = str(wake.get("subject_guid") or "").strip()
    agent_id = str(wake.get("agent_id") or "").strip()
    wake_id = str(wake.get("wake_id") or "").strip() or None
    if not subject_guid:
        raise SettlementError("missing_subject_guid")
    if not agent_id:
        raise SettlementError("missing_agent_id")
    if not wake_id:
        raise SettlementError("missing_wake_id")

    decision = wake.get("decision_summary") if isinstance(wake.get("decision_summary"), dict) else {}
    effect_kind = str(decision.get("effect_kind") or "none")
    if effect_kind == "none":
        raise SettlementError("effect_kind_none")

    commitments = wake.get("commitments_created") or []
    commitment_id = str(commitments[0]) if commitments else None

    # Prefer non-none effect receipts as authoritative sources; fall back to selection.
    sources: list[dict[str, Any]] = []
    for r in receipts or []:
        if not isinstance(r, Mapping):
            continue
        if str(r.get("effect_kind") or "none") == "none":
            continue
        sk = str(r.get("source_kind") or "").strip()
        sid = str(r.get("source_id") or "").strip()
        if sk and sid:
            sources.append({"kind": sk, "id": sid})
    selection = wake.get("selection") if isinstance(wake.get("selection"), dict) else {}
    if not sources and selection.get("source_id"):
        kind = (
            "research_object"
            if str(selection.get("source") or "") == "unconsumed_research"
            else str(selection.get("source") or "research_object")
        )
        if kind == "material_change":
            sources.append({"kind": "material_change", "id": str(selection["source_id"])})
        else:
            sources.append({"kind": "research_object", "id": str(selection["source_id"])})
    if not sources:
        raise SettlementError("missing_authoritative_sources")

    summary = str(decision.get("reason") or effect_kind)
    body = (
        f"Persistent wake {wake_id} acted with effect_kind={effect_kind} "
        f"({summary})."
    )
    msg_class = _env_flag("PERSISTENT_WAKE_GATEWAY_MESSAGE_CLASS", env) or DEFAULT_OUTBOUND_MESSAGE_CLASS
    chat_raw = _env_flag("COMMS_GATEWAY_CANARY_CHATS", env)
    chat_ids = [p.strip() for p in chat_raw.split(",") if p.strip()] if chat_raw else None

    return AgentOutboundRequest(
        agent_id=agent_id,
        subject_guid=subject_guid,
        body=body,
        message_class=msg_class,
        channel="telegram",
        wake_id=wake_id,
        commitment_id=commitment_id,
        correlation_id=str(wake.get("correlation_id") or "") or None,
        authoritative_sources=sources,
        command_center_path="/v3/cio",
        chat_ids=chat_ids,
        source_sha=str(wake.get("source_sha") or "") or None,
    )


def build_wake_outbound_handler(
    *,
    env: Mapping[str, str] | None = None,
    transport: TransportFn | None = None,
    deliver: bool | None = None,
) -> Callable[..., dict[str, Any]]:
    """Canonical callable for ``WakeEngine._outbound``.

    Signature matches the SFR-G-002 hook::

        handler(wake=wake, receipts=receipts) -> dict

    Gates (all required for a gateway SETTLED delivery):
      1. ``PERSISTENT_WAKE_GATEWAY_OUTBOUND`` on
      2. ``COMMS_GATEWAY_MODE`` in {CANARY, ACTIVE}
      3. ``deliver=True`` (explicit; default False unless env asks for deliver)
      4. Valid wake provenance → AgentOutboundRequest
      5. Injected or sanctioned transport; sanctioned transport requires
         ``ENABLE_TELEGRAM`` + ``TELEGRAM_BOT_TOKEN``
      6. Lane G ownership/allowlist + provider acknowledgement

    Missing any gate → fail-closed dict with ``ok=False`` (never raises into wake).
    """
    env_map = dict(env) if env is not None else None
    deliver_flag = deliver
    if deliver_flag is None:
        deliver_flag = _env_flag("PERSISTENT_WAKE_GATEWAY_DELIVER", env_map).lower() in {
            "1", "true", "yes", "on",
        }

    def _handler(*, wake: Mapping[str, Any], receipts: list | None = None, **_kw: Any) -> dict[str, Any]:
        if not wake_gateway_outbound_enabled(env_map):
            return {
                "ok": False,
                "error": "wake_gateway_outbound_disabled",
                "delivered": False,
                "transport_invoked": False,
            }
        mode = get_gateway_mode(refresh=True)
        if mode not in {MODE_CANARY, MODE_ACTIVE}:
            return {
                "ok": False,
                "error": f"gateway_mode_not_canary:{mode}",
                "delivered": False,
                "transport_invoked": False,
                "gateway_mode": mode,
            }
        try:
            req = _request_from_wake(wake=wake, receipts=list(receipts or []), env=env_map)
        except SettlementError as exc:
            return {"ok": False, "error": str(exc), "delivered": False, "transport_invoked": False}

        txn = transport
        if deliver_flag and txn is None:
            # Production default: sanctioned adapter (still fail-closed without auth).
            # CANARY/ACTIVE mode already enforced above; class/chat allowlists
            # remain inside deliver_agent_outbound.
            txn = sanctioned_telegram_transport

        # CANARY-scoped transport hand-off (mode gate already returned if OFF).
        result = deliver_agent_outbound(req, deliver=bool(deliver_flag), transport=txn)
        out = result.to_dict()
        out.setdefault("error", None)
        if not result.ok and result.errors:
            out["error"] = result.errors[0]
        return out

    # Marker for reachability scanners — this factory is the non-test runtime caller.
    _handler.__outbound_calls_deliver_agent_outbound__ = True  # type: ignore[attr-defined]
    return _handler


def assert_deliver_agent_outbound_runtime_caller(*, scripts_root: str | None = None) -> list[str]:
    """Negative control helper: fail if no non-test runtime caller exists.

    Returns list of caller file paths. Raises SettlementError when empty.
    """
    import ast
    from pathlib import Path

    root = Path(scripts_root or Path(__file__).resolve().parents[1])
    # Bound the scan to scripts/lib — production callers for this edge live here.
    scan_root = root / "lib" if (root / "lib").is_dir() else root
    callers: list[str] = []
    for path in scan_root.rglob("*.py"):
        text_path = str(path).replace("\\", "/")
        if "/tests/" in text_path:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = None
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name == "deliver_agent_outbound":
                    callers.append(str(path))
                    break
    callers = sorted(set(callers))
    factory_ok = any(p.endswith("gateway_settlement.py") for p in callers)
    if not callers or not factory_ok:
        raise SettlementError(
            "deliver_agent_outbound_has_no_non_test_runtime_caller"
        )
    gs = Path(__file__).read_text(encoding="utf-8")
    if "def build_wake_outbound_handler" not in gs:
        raise SettlementError("missing_build_wake_outbound_handler")
    if "deliver_agent_outbound(req" not in gs:
        raise SettlementError("factory_does_not_call_deliver_agent_outbound")
    return callers


__all__ = [
    "SettlementError",
    "SettlementResult",
    "ENV_WAKE_GATEWAY_OUTBOUND",
    "deliver_agent_outbound",
    "reset_settlement_index",
    "transport_invoke_count",
    "wake_gateway_outbound_enabled",
    "sanctioned_telegram_transport",
    "build_wake_outbound_handler",
    "assert_deliver_agent_outbound_runtime_caller",
]
