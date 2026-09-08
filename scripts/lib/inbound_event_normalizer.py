"""Lane I — inbound Telegram callback/reply normalization + correlation.

Bounded path (compose, do not redefine Lane B contracts):

  raw Telegram update
    → CommunicationEvent@v2 (via scripts.lib.comms.inbound)
    → dedupe on provider update_id / message_id
    → outbound/thread/subject/commitment correlation when available
    → sender allowlist + CANARY scope gate

Fail-closed: missing identity, unauthorized sender, out-of-scope CANARY chat,
malformed payload, or unavailable persistence → reject (no event published).

Never contacts Telegram. Never writes broker/financial state.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any

from scripts.lib.comms.client import publish_communication
from scripts.lib.comms.event import CommunicationEvent
from scripts.lib.comms.inbound import (
    InboundGateError,
    build_inbound_event,
    claim_update,
    commit_checkpoint,
    is_update_already_processed,
    resolve_event_by_provider_message_id,
)
from scripts.lib.comms.mode import MODE_CANARY, MODE_OFF, get_gateway_mode

SCHEMA = "InboundNormalizedEvent@v1"
ENV_SENDER_ALLOWLIST = "COMMS_INBOUND_SENDER_ALLOWLIST"
ENV_CANARY_CHATS = "COMMS_GATEWAY_CANARY_CHATS"
ENV_STALE_SECONDS = "COMMS_INBOUND_STALE_SECONDS"
DEFAULT_STALE_SECONDS = 7 * 24 * 3600

_SEEN_KEYS: set[str] = set()
_lock = threading.Lock()


class InboundNormalizeError(ValueError):
    """Fail-closed inbound normalization / authorization failure."""


@dataclass
class NormalizeResult:
    ok: bool
    reason: str
    event: CommunicationEvent | None = None
    event_id: str | None = None
    duplicate: bool = False
    correlation: dict[str, Any] = field(default_factory=dict)
    published: bool = False
    schema: str = SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "event_id": self.event_id,
            "duplicate": self.duplicate,
            "correlation": dict(self.correlation),
            "published": self.published,
            "schema": self.schema,
            "provider_coordinates": (
                dict(self.event.provider_coordinates)
                if self.event is not None
                else {}
            ),
        }


def _csv_env(name: str) -> frozenset[str]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return frozenset()
    return frozenset(x.strip() for x in raw.split(",") if x.strip())


def sender_allowlist() -> frozenset[str]:
    return _csv_env(ENV_SENDER_ALLOWLIST)


def canary_chat_allowlist() -> frozenset[str]:
    return _csv_env(ENV_CANARY_CHATS)


def _stale_limit_seconds() -> int:
    raw = (os.getenv(ENV_STALE_SECONDS) or "").strip()
    if not raw:
        return DEFAULT_STALE_SECONDS
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_STALE_SECONDS


def _provider_dedupe_key(event: CommunicationEvent) -> str:
    coords = event.provider_coordinates or {}
    update_id = coords.get("update_id")
    message_id = coords.get("message_id")
    chat_id = coords.get("chat_id")
    return f"tg:{chat_id}:{update_id}:{message_id}"


def _extract_sender_id(update: dict[str, Any]) -> str | None:
    cb = update.get("callback_query")
    if isinstance(cb, dict):
        frm = cb.get("from") or {}
        if isinstance(frm, dict) and frm.get("id") is not None:
            return str(frm["id"])
    msg = update.get("message")
    if isinstance(msg, dict):
        frm = msg.get("from") or {}
        if isinstance(frm, dict) and frm.get("id") is not None:
            return str(frm["id"])
    return None


def _extract_chat_id(update: dict[str, Any]) -> str | None:
    cb = update.get("callback_query")
    if isinstance(cb, dict):
        inner = cb.get("message") or {}
        chat = (inner.get("chat") or {}) if isinstance(inner, dict) else {}
        if isinstance(chat, dict) and chat.get("id") is not None:
            return str(chat["id"])
    msg = update.get("message")
    if isinstance(msg, dict):
        chat = msg.get("chat") or {}
        if isinstance(chat, dict) and chat.get("id") is not None:
            return str(chat["id"])
    return None


def authorize_inbound(
    update: dict[str, Any],
    *,
    mode: str | None = None,
) -> tuple[bool, str]:
    """Sender allowlist + CANARY chat scope. Fail-closed on empty allowlists."""
    m = (mode or get_gateway_mode(refresh=True) or MODE_OFF).upper()
    sender = _extract_sender_id(update)
    chat_id = _extract_chat_id(update)

    allow_senders = sender_allowlist()
    if not allow_senders:
        return False, "authorization_failed:sender_allowlist_empty"
    if not sender or sender not in allow_senders:
        return False, "authorization_failed:sender_not_allowlisted"

    if m == MODE_CANARY:
        chats = canary_chat_allowlist()
        if not chats:
            return False, "authorization_failed:canary_chats_empty"
        if not chat_id or chat_id not in chats:
            return False, "authorization_failed:chat_out_of_canary_scope"

    if m == MODE_OFF:
        # OFF still may normalize for ledger/tests, but only allowlisted senders.
        pass
    return True, "authorized"


def _is_stale(update: dict[str, Any]) -> bool:
    """Reject updates with an explicit stale timestamp when present."""
    # Telegram getUpdates often lack a top-level date; message.date is unix seconds.
    ts = None
    msg = update.get("message")
    if isinstance(msg, dict) and msg.get("date") is not None:
        ts = msg.get("date")
    cb = update.get("callback_query")
    if ts is None and isinstance(cb, dict):
        inner = cb.get("message") or {}
        if isinstance(inner, dict) and inner.get("date") is not None:
            ts = inner.get("date")
    if ts is None:
        return False
    try:
        when = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return True  # unparseable date → fail closed as stale/malformed
    age = datetime.now(timezone.utc) - when
    return age > timedelta(seconds=_stale_limit_seconds())


def correlate_inbound(
    event: CommunicationEvent,
    *,
    commitment_id: str | None = None,
) -> dict[str, Any]:
    """Attach outbound/thread/subject/commitment correlation when resolvable."""
    corr: dict[str, Any] = {
        "reply_to_event_id": event.reply_to_event_id,
        "parent_event_id": event.parent_event_id,
        "thread_id": event.thread_id,
        "correlation_id": event.correlation_id,
        "subject_key": event.subject_key,
        "commitment_id": None,
        "outbound_event_id": None,
        "correlated": False,
    }
    coords = event.provider_coordinates or {}
    reply_to = coords.get("reply_to_message_id")
    chat_id = coords.get("chat_id")
    if reply_to is not None and not event.reply_to_event_id:
        parent = resolve_event_by_provider_message_id(str(reply_to), chat_id=str(chat_id) if chat_id else None)
        if parent and parent.get("event_id"):
            eid = str(parent["event_id"])
            event.reply_to_event_id = eid
            event.parent_event_id = eid
            event.parent_id = eid
            event.parent_kind = "comm_event"
            if parent.get("correlation_id"):
                event.correlation_id = str(parent["correlation_id"])
            if parent.get("thread_id"):
                event.thread_id = str(parent["thread_id"])
            corr["outbound_event_id"] = eid
            corr["correlated"] = True
    elif event.reply_to_event_id:
        corr["outbound_event_id"] = event.reply_to_event_id
        corr["correlated"] = True

    if commitment_id:
        # Carry as payload annotation only — Lane I does not mint CommitmentId.
        event.payload = dict(event.payload or {})
        event.payload["correlated_commitment_id"] = str(commitment_id)
        corr["commitment_id"] = str(commitment_id)
        corr["correlated"] = True

    corr["reply_to_event_id"] = event.reply_to_event_id
    corr["parent_event_id"] = event.parent_event_id
    corr["thread_id"] = event.thread_id
    corr["correlation_id"] = event.correlation_id
    corr["subject_key"] = event.subject_key
    return corr


def normalize_inbound_update(
    update: dict[str, Any],
    *,
    publish: bool = True,
    commitment_id: str | None = None,
    require_correlation: bool = False,
) -> NormalizeResult:
    """Full normalize → authorize → dedupe → correlate → optional publish.

    ``publish=False`` builds and validates without ledger write (dry-run).
    """
    if not isinstance(update, dict):
        return NormalizeResult(ok=False, reason="malformed:update_not_dict")

    if update.get("update_id") is None:
        return NormalizeResult(ok=False, reason="malformed:missing_update_id")

    if _is_stale(update):
        return NormalizeResult(ok=False, reason="stale:update_too_old")

    ok_auth, auth_reason = authorize_inbound(update)
    if not ok_auth:
        return NormalizeResult(ok=False, reason=auth_reason)

    try:
        event = build_inbound_event(update)
    except InboundGateError as exc:
        return NormalizeResult(ok=False, reason=f"malformed:{exc}")
    except Exception as exc:  # noqa: BLE001 — fail closed
        return NormalizeResult(ok=False, reason=f"malformed:{type(exc).__name__}")

    if not event.event_id:
        return NormalizeResult(ok=False, reason="identity_unavailable:event_id")

    # Preserve provider identifiers explicitly on the event payload surface.
    coords = dict(event.provider_coordinates or {})
    if coords.get("update_id") is None or coords.get("message_id") is None:
        return NormalizeResult(ok=False, reason="identity_unavailable:provider_ids")

    # Dedupe: checkpoint + in-process key.
    try:
        uid = int(coords["update_id"])
    except (TypeError, ValueError):
        return NormalizeResult(ok=False, reason="malformed:update_id")

    if is_update_already_processed(uid):
        return NormalizeResult(
            ok=False,
            reason="duplicate:update_already_processed",
            duplicate=True,
            event=event,
            event_id=event.event_id,
        )

    dedupe_key = _provider_dedupe_key(event)
    with _lock:
        if dedupe_key in _SEEN_KEYS:
            return NormalizeResult(
                ok=False,
                reason="duplicate:provider_retry",
                duplicate=True,
                event=event,
                event_id=event.event_id,
            )

    claim = claim_update(uid)
    if claim.already_processed:
        return NormalizeResult(
            ok=False,
            reason="duplicate:checkpoint_race",
            duplicate=True,
            event=event,
            event_id=event.event_id,
        )

    correlation = correlate_inbound(event, commitment_id=commitment_id)
    if require_correlation and not correlation.get("correlated"):
        return NormalizeResult(
            ok=False,
            reason="uncorrelated:no_outbound_parent",
            event=event,
            event_id=event.event_id,
            correlation=correlation,
        )

    published = False
    if publish:
        try:
            result = publish_communication(event)
        except Exception as exc:  # noqa: BLE001
            return NormalizeResult(
                ok=False,
                reason=f"persistence_failure:{type(exc).__name__}",
                event=event,
                event_id=event.event_id,
                correlation=correlation,
            )
        if not getattr(result, "ok", False) and not getattr(result, "duplicate", False):
            return NormalizeResult(
                ok=False,
                reason=f"persistence_failure:{getattr(result, 'reason', 'publish_rejected')}",
                event=event,
                event_id=event.event_id,
                correlation=correlation,
            )
        published = True
        # Advance checkpoint only after successful persist.
        try:
            commit_checkpoint(uid)
        except Exception as exc:  # noqa: BLE001
            return NormalizeResult(
                ok=False,
                reason=f"persistence_failure:checkpoint:{type(exc).__name__}",
                event=event,
                event_id=event.event_id,
                correlation=correlation,
                published=True,
            )

    with _lock:
        _SEEN_KEYS.add(dedupe_key)

    return NormalizeResult(
        ok=True,
        reason="normalized",
        event=event,
        event_id=event.event_id,
        correlation=correlation,
        published=published,
    )


def reset_normalizer_memory() -> None:
    with _lock:
        _SEEN_KEYS.clear()
