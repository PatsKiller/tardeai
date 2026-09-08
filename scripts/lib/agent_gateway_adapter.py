"""Lane G — agent output → CommunicationEvent@v2 (gateway path).

Builds a fully identified outbound communication event from agent output
(wake / commitment / advisory text) without performing provider I/O.

Consumes Lane B frozen interfaces only (`scripts.lib.comms.*`). Does not
edit `scripts/lib/comms/**`. Never mints `subject_guid` (identity spine).
Never embeds credentials.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from scripts.lib.campaign_interfaces import mint_thread_id
from scripts.lib.comms.artifact import ALLOWED_HOST, ALLOWED_PATH_PREFIX, validate_link
from scripts.lib.comms.channel_adapters import (
    render_for_channel,
    telegram_class_allowed,
    telegram_owned_classes,
)
from scripts.lib.comms.event import CommunicationEvent, required_missing
from scripts.lib.comms.mode import MODE_CANARY, MODE_OFF, MODE_SHADOW, get_gateway_mode
from scripts.lib.comms.vocabulary import normalize_message_class

CC_BASE = f"https://{ALLOWED_HOST}"
DEFAULT_CC_PATH = "/v3/cio"


class GatewayAdapterError(ValueError):
    """Fail-closed: missing provenance, identity, link contract, or config."""


@dataclass(frozen=True)
class AgentOutboundRequest:
    """Agent output intended for operator delivery."""

    agent_id: str
    subject_guid: str
    body: str
    message_class: str = "ops"
    channel: str = "telegram"
    wake_id: str | None = None
    commitment_id: str | None = None
    correlation_id: str | None = None
    command_center_path: str = DEFAULT_CC_PATH
    authoritative_sources: list[dict[str, Any]] = field(default_factory=list)
    chat_ids: list[str] | None = None
    producer_version: str | None = None
    source_sha: str | None = None


@dataclass(frozen=True)
class OwnershipDecision:
    delivery_owner: str  # gateway | legacy
    gateway_mode: str
    reason: str
    message_class: str
    allowlist_classes: tuple[str, ...]


def command_center_url_for(path: str) -> str:
    """Fully-qualified Command Center URL under the governed Tailscale FQDN."""
    raw = str(path or "").strip() or DEFAULT_CC_PATH
    if not raw.startswith("/"):
        raw = "/" + raw
    if not raw.startswith(ALLOWED_PATH_PREFIX):
        raise GatewayAdapterError(f"cc_path_not_v3:{raw}")
    url = f"{CC_BASE}{raw}"
    return validate_link(url, field="command_center_url")


def format_agent_body(
    body: str,
    *,
    command_center_url: str,
    wake_id: str | None = None,
    commitment_id: str | None = None,
) -> str:
    """Plain-text body with authoritative CC link appended (no credentials)."""
    text = (body or "").strip()
    if not text:
        raise GatewayAdapterError("empty_body")
    lines = [text, "", f"Command Center: {command_center_url}"]
    if wake_id:
        lines.append(f"wake_id: {wake_id}")
    if commitment_id:
        lines.append(f"commitment_id: {commitment_id}")
    return "\n".join(lines)


def decide_ownership(
    *,
    message_class: str,
    channel: str = "telegram",
    mode: str | None = None,
) -> OwnershipDecision:
    """Gateway owns delivery only for explicit CANARY (or ACTIVE) allowlisted classes.

    Outside the allowlist, or when mode is OFF/SHADOW, ownership is ``legacy``
    with a recorded reason — never an unexplained fallback.
    """
    m = (mode or get_gateway_mode(refresh=True) or MODE_OFF).strip().upper()
    mc = normalize_message_class(message_class)
    owned = tuple(telegram_owned_classes(m)) if channel == "telegram" else tuple()
    if m in (MODE_OFF, MODE_SHADOW):
        return OwnershipDecision(
            delivery_owner="legacy",
            gateway_mode=m,
            reason=f"mode_{m.lower()}_not_delivery_owner",
            message_class=mc,
            allowlist_classes=owned,
        )
    if m == MODE_CANARY:
        if not owned:
            return OwnershipDecision(
                delivery_owner="legacy",
                gateway_mode=m,
                reason="canary_allowlist_empty",
                message_class=mc,
                allowlist_classes=owned,
            )
        if channel == "telegram" and not telegram_class_allowed(m, mc):
            return OwnershipDecision(
                delivery_owner="legacy",
                gateway_mode=m,
                reason=f"class_not_in_canary_allowlist:{mc}",
                message_class=mc,
                allowlist_classes=owned,
            )
        return OwnershipDecision(
            delivery_owner="gateway",
            gateway_mode=m,
            reason="canary_allowlist_match",
            message_class=mc,
            allowlist_classes=owned,
        )
    # ACTIVE: same class-gate semantics via telegram_owned_classes
    if not owned:
        return OwnershipDecision(
            delivery_owner="legacy",
            gateway_mode=m,
            reason="active_allowlist_empty",
            message_class=mc,
            allowlist_classes=owned,
        )
    if channel == "telegram" and not telegram_class_allowed(m, mc):
        return OwnershipDecision(
            delivery_owner="legacy",
            gateway_mode=m,
            reason=f"class_not_in_active_allowlist:{mc}",
            message_class=mc,
            allowlist_classes=owned,
        )
    return OwnershipDecision(
        delivery_owner="gateway",
        gateway_mode=m,
        reason="active_allowlist_match",
        message_class=mc,
        allowlist_classes=owned,
    )


def build_outbound_event(req: AgentOutboundRequest) -> tuple[CommunicationEvent, OwnershipDecision]:
    """Mint a CommunicationEvent@v2 from agent output. Fail-closed on gaps."""
    if not str(req.agent_id or "").strip():
        raise GatewayAdapterError("missing_agent_id")
    if not str(req.subject_guid or "").strip():
        raise GatewayAdapterError("missing_subject_guid")
    if not str(req.body or "").strip():
        raise GatewayAdapterError("missing_body")
    if not req.authoritative_sources:
        raise GatewayAdapterError("missing_authoritative_sources")

    cc_url = command_center_url_for(req.command_center_path)
    formatted = format_agent_body(
        req.body,
        command_center_url=cc_url,
        wake_id=req.wake_id,
        commitment_id=req.commitment_id,
    )
    rendered = render_for_channel(formatted, req.channel)
    if not rendered.get("ok"):
        raise GatewayAdapterError(f"channel_format_failed:{rendered.get('error')}")

    ownership = decide_ownership(message_class=req.message_class, channel=req.channel)
    root = req.wake_id or req.commitment_id or "agent_outbound"
    thread_id = mint_thread_id(req.subject_guid, req.channel, root)
    correlation_id = req.correlation_id or thread_id

    event = CommunicationEvent(
        direction="OUTBOUND",
        event_type="agent_outbound",
        message_class=ownership.message_class,
        producer=f"agent:{req.agent_id}",
        producer_version=req.producer_version,
        subject_key=f"subject:{req.subject_guid}",
        subject_guid=req.subject_guid,
        retention_class="operational_30d",
        severity="info",
        audience="operator",
        sanitized_body=rendered.get("text") or formatted,
        short_summary=(req.body or "")[:160],
        channels=[req.channel],
        authoritative_sources=list(req.authoritative_sources),
        command_center_url=cc_url,
        thread_id=thread_id,
        correlation_id=correlation_id,
        causation_id=req.wake_id,
        parent_id=req.wake_id or req.commitment_id,
        parent_kind="wake" if req.wake_id else ("commitment" if req.commitment_id else None),
        delivery_owner=ownership.delivery_owner,
        gateway_mode_at_dispatch=ownership.gateway_mode,
        source_agent=req.agent_id,
        source_sha=req.source_sha,
        produced_at=datetime.now(timezone.utc),
        curation_kind="deterministic",
        payload={
            "wake_id": req.wake_id,
            "commitment_id": req.commitment_id,
            "ownership_reason": ownership.reason,
            "allowlist_classes": list(ownership.allowlist_classes),
            "chat_ids": list(req.chat_ids) if req.chat_ids is not None else None,
        },
        delivery_policy={
            "channels": [req.channel],
            "ownership_reason": ownership.reason,
        },
        provenance={
            "producer": "agent_gateway_adapter",
            "inputs": [
                {"kind": "wake", "id": req.wake_id} if req.wake_id else None,
                {"kind": "commitment", "id": req.commitment_id} if req.commitment_id else None,
            ],
            "policy_decisions": [ownership.reason],
            "llm": None,
        },
    )
    # Drop None inputs
    event.provenance["inputs"] = [x for x in event.provenance["inputs"] if x]
    event.mint_identity()
    missing = required_missing(event)
    if missing:
        raise GatewayAdapterError(f"event_required_missing:{','.join(missing)}")
    if not event.event_id or not event.thread_id or not event.correlation_id:
        raise GatewayAdapterError("identity_incomplete")
    if not event.subject_guid:
        raise GatewayAdapterError("subject_guid_lost")
    return event, ownership


__all__ = [
    "AgentOutboundRequest",
    "OwnershipDecision",
    "GatewayAdapterError",
    "CC_BASE",
    "command_center_url_for",
    "format_agent_body",
    "decide_ownership",
    "build_outbound_event",
]
