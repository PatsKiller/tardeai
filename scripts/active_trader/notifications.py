"""Active Trader Stage 3 — notification events, routing policy, and TEST sinks.

Nothing in this module can send a real alert: channel dispatch goes through sink
objects, and the only sinks provided are in-memory/test-database sinks that
capture payloads. The production Telegram/email lanes
(scripts/telegram_alert.py, alert_dispatcher_unified.py, gog gmail) are never
imported here. Wiring a real sink is a LATER, separately-authorized stage.

Severity model (launcher): INFO / WARNING / ACTION_REQUIRED / CRITICAL.
Stage 1 DB CHECK stores (INFO/WARN/BLOCKING/CRITICAL); mapping is explicit below
and documented in NOTIFICATION_POLICY.md.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from active_trader.contracts import ContractViolation
from active_trader.rejections import Classification, RawBrokerEvent, redact


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    CRITICAL = "CRITICAL"


SEVERITY_DB_MAP = {"INFO": "INFO", "WARNING": "WARN",
                   "ACTION_REQUIRED": "BLOCKING", "CRITICAL": "CRITICAL"}

CHANNELS = ("COMMAND_CENTER", "AUDIBLE_UI", "TELEGRAM", "EMAIL", "JOURNAL")


def route_channels(severity: Severity, *, telegram_configured: bool = True,
                   audible_pref: bool = False, broker_call_required: bool = False,
                   unresolved: bool = True) -> tuple:
    """Deterministic channel policy — no send occurs here."""
    channels = ["COMMAND_CENTER", "JOURNAL"]
    if audible_pref and severity in (Severity.ACTION_REQUIRED, Severity.CRITICAL):
        channels.append("AUDIBLE_UI")
    if telegram_configured and severity in (Severity.ACTION_REQUIRED, Severity.CRITICAL):
        channels.append("TELEGRAM")
    if (broker_call_required and unresolved) or severity is Severity.CRITICAL:
        channels.append("EMAIL")
    return tuple(channels)


def severity_for(cls: Classification) -> Severity:
    if cls.requires_broker_call:
        return Severity.ACTION_REQUIRED
    if cls.normalized_code == "UNKNOWN_BROKER_REJECTION":
        return Severity.ACTION_REQUIRED
    if cls.normalized_code in ("MARKET_CLOSED", "RATE_LIMITED", "STALE_ACCOUNT_STATE"):
        return Severity.WARNING          # transient, self-resolving — visible but not paging
    if cls.requires_operator:
        return Severity.ACTION_REQUIRED
    return Severity.INFO


@dataclass
class NotificationEvent:
    notification_event_id: str
    rejection_event_id: str
    severity: Severity
    channel_policy: tuple
    title: str
    operator_summary: str
    broker: str
    account_label: str
    masked_account_id: str
    symbol: Optional[str]
    requested_quantity: Optional[float]
    filled_quantity: Optional[float]
    remaining_quantity: Optional[float]
    normalized_code: str
    raw_message_redacted: str
    protection_state: str
    authorized_fallback_accounts: tuple
    operator_actions: tuple
    dedupe_key: str
    created_at: datetime
    expires_at: Optional[datetime]
    status: str = "OPEN"             # OPEN | UPDATED | ESCALATED | ACKNOWLEDGED | RESOLVED | EXPIRED
    escalation_count: int = 0

    def __post_init__(self):
        if not isinstance(self.severity, Severity):
            raise ContractViolation(f"invalid severity {self.severity!r}")
        forbidden = ("submitted", "order placed", "order sent")
        low = self.operator_summary.lower()
        if any(f"alternate {w}" in low or f"fallback {w}" in low for w in ("submitted",)):
            raise ContractViolation("notification may not claim an alternate order was submitted")


def dedupe_key_for(event: RawBrokerEvent, cls: Classification) -> str:
    return hashlib.sha256("|".join([
        event.broker, event.account_label, str(event.symbol), cls.normalized_code]).encode()
    ).hexdigest()


def render_operator_summary(event: RawBrokerEvent, cls: Classification, *,
                            requested_qty: Optional[float], protection_state: str,
                            fallback_accounts: tuple, actions: tuple) -> str:
    lines = [
        f"{event.broker.upper()} rejected {event.symbol or '(no symbol)'} on "
        f"{event.account_label} ({event.masked_account_id}).",
        f"Requested: {requested_qty} · filled: {event.filled_quantity} · "
        f"remaining: {event.remaining_quantity}",
        f"Broker said (redacted): {redact(event.raw_message)}",
        f"Normalized: {cls.normalized_code} — {cls.reason}",
        f"Retry allowed: {'yes (bounded backoff)' if cls.retryable else 'NO'} · "
        f"Broker call required: {'YES' if cls.requires_broker_call else 'no'}",
        f"Protection state: {protection_state}",
        f"Authorized fallback accounts: {', '.join(fallback_accounts) or 'none in envelope'}",
        f"Required operator action: {'; '.join(actions) or 'review'}",
    ]
    return "\n".join(lines)


class NotificationCenter:
    """Dedupe/escalation/ack/resolution engine over pluggable TEST sinks."""

    def __init__(self, sinks=None, now=None):
        self.sinks = sinks or [InMemorySink()]
        self._by_dedupe: dict[str, NotificationEvent] = {}
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._seq = 0

    def publish(self, event: RawBrokerEvent, cls: Classification, *,
                requested_qty: Optional[float] = None, protection_state: str = "NONE",
                fallback_accounts: tuple = (), actions: tuple = ("review rejection",),
                telegram_configured: bool = True, audible_pref: bool = False,
                ttl_hours: int = 24) -> NotificationEvent:
        sev = severity_for(cls)
        dk = dedupe_key_for(event, cls)
        existing = self._by_dedupe.get(dk)
        summary = render_operator_summary(event, cls, requested_qty=requested_qty,
                                          protection_state=protection_state,
                                          fallback_accounts=fallback_accounts, actions=actions)
        if existing and existing.status in ("OPEN", "UPDATED", "ESCALATED"):
            if existing.filled_quantity == event.filled_quantity \
                    and existing.remaining_quantity == event.remaining_quantity:
                existing.escalation_count += 1          # counted, NOT re-emitted (no flooding)
                return existing
            existing.filled_quantity = event.filled_quantity
            existing.remaining_quantity = event.remaining_quantity
            existing.operator_summary = summary
            existing.status = "UPDATED"
            self._emit(existing, kind="update")
            return existing
        self._seq += 1
        note = NotificationEvent(
            notification_event_id=f"note-{self._seq:06d}",
            rejection_event_id=event.idempotency_key[:16],
            severity=sev,
            channel_policy=route_channels(sev, telegram_configured=telegram_configured,
                                          audible_pref=audible_pref,
                                          broker_call_required=cls.requires_broker_call),
            title=f"{event.broker}: {cls.normalized_code} on {event.symbol or event.account_label}",
            operator_summary=summary, broker=event.broker,
            account_label=event.account_label, masked_account_id=event.masked_account_id,
            symbol=event.symbol, requested_quantity=requested_qty,
            filled_quantity=event.filled_quantity, remaining_quantity=event.remaining_quantity,
            normalized_code=cls.normalized_code, raw_message_redacted=redact(event.raw_message),
            protection_state=protection_state,
            authorized_fallback_accounts=fallback_accounts, operator_actions=actions,
            dedupe_key=dk, created_at=self._now(),
            expires_at=self._now() + timedelta(hours=ttl_hours))
        self._by_dedupe[dk] = note
        self._emit(note, kind="create")
        return note

    def escalate(self, note: NotificationEvent) -> None:
        note.status = "ESCALATED"
        note.escalation_count += 1
        if note.severity is not Severity.CRITICAL:
            note.severity = Severity.CRITICAL
            note.channel_policy = route_channels(Severity.CRITICAL)
        self._emit(note, kind="escalate")

    def acknowledge(self, note: NotificationEvent, operator: str) -> None:
        note.status = "ACKNOWLEDGED"
        self._emit(note, kind="ack")

    def resolve(self, note: NotificationEvent, reason: str) -> None:
        note.status = "RESOLVED"
        self._emit(note, kind="resolve")

    def expire_stale(self) -> int:
        n = 0
        for note in self._by_dedupe.values():
            if note.status in ("OPEN", "UPDATED") and note.expires_at and self._now() >= note.expires_at:
                note.status = "EXPIRED"
                n += 1
        return n

    def _emit(self, note: NotificationEvent, kind: str) -> None:
        for sink in self.sinks:
            sink.deliver(note, kind)


# ---------------------------------------------------------------- TEST sinks

class InMemorySink:
    def __init__(self):
        self.delivered = []

    def deliver(self, note: NotificationEvent, kind: str) -> None:
        self.delivered.append((kind, note))


class MockTelegramSink:
    """Captures the payload that WOULD be sent. Never touches the network."""

    def __init__(self):
        self.payloads = []

    def deliver(self, note: NotificationEvent, kind: str) -> None:
        if "TELEGRAM" not in note.channel_policy:
            return
        self.payloads.append({
            "chat": "[TEST-SINK]", "parse_mode": "Markdown",
            "text": f"⚠️ {note.title}\n{note.operator_summary}"[:4000],
            "kind": kind, "dedupe_key": note.dedupe_key})


class MockGmailSink:
    """Captures the MIME-ish payload that WOULD be sent. Never sends."""

    def __init__(self):
        self.payloads = []

    def deliver(self, note: NotificationEvent, kind: str) -> None:
        if "EMAIL" not in note.channel_policy:
            return
        self.payloads.append({
            "to": "[TEST-SINK-OPERATOR]",
            "subject": f"ACTION REQUIRED: {note.title}",
            "body": note.operator_summary, "kind": kind})


class LabDbSink:
    """Persists notification rows to the LAB database only (guarded DSN)."""

    def __init__(self, dsn: str):
        from active_trader.migrate import _resolve_dsn
        self._dsn = _resolve_dsn(dsn)

    def deliver(self, note: NotificationEvent, kind: str) -> None:
        import psycopg2, uuid
        conn = psycopg2.connect(self._dsn)
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT INTO active_trader_notification_events
                       (notification_event_id, environment, severity, category, title, body,
                        requires_operator_action, channels, related_ref, dedupe_key,
                        rejection_event_id, status, expires_at)
                   VALUES (%s,'SIMULATION',%s,'rejection',%s,%s,%s,%s,%s,%s,NULL,%s,%s)
                   ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL
                       AND status IN ('OPEN','UPDATED','ESCALATED')
                   DO UPDATE SET body = EXCLUDED.body, status = 'UPDATED'""",
                (str(uuid.uuid4()), SEVERITY_DB_MAP[note.severity.value], note.title,
                 note.operator_summary, note.severity in (Severity.ACTION_REQUIRED, Severity.CRITICAL),
                 __import__("json").dumps(list(note.channel_policy)), note.rejection_event_id,
                 note.dedupe_key, note.status, note.expires_at))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
