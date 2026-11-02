"""Scoped code context for a due watchdog reminder, never payload authentication.

The watchdog already decides when a send is due. Its selected sender may scope
an editor duplicate identity to those findings and the configured cadence. No
message field, JSON marker, producer label or dedupe_minutes value can issue it.
It changes only content dedupe identity; routing, holds and transport still run.
No I/O, provider call, persistent grant or credential is involved.
"""
from __future__ import annotations

from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
import hashlib
from pathlib import Path
import re
import sys

_SCRIPTS = Path(__file__).resolve().parents[1]
_TOKEN = object()
_ISSUED = ContextVar("watchdog_reminder_issued", default=None)
_OUTCOME = ContextVar("watchdog_reminder_outcome", default=None)
_CHUNKS = ContextVar("watchdog_reminder_chunks", default=None)


@dataclass(frozen=True)
class _Reminder:
    token: object
    body: str
    identity: str
    family: str
    reminder_seconds: int


def _owner(frame, filename: str, function: str) -> bool:
    return (frame.f_code.co_name == function
            and Path(frame.f_code.co_filename).resolve() == _SCRIPTS / filename)


def _valid(value) -> bool:
    return type(value) is _Reminder and value.token is _TOKEN


@contextmanager
def _issued(reminder):
    token = _ISSUED.set(reminder)
    try:
        yield
    finally:
        _ISSUED.reset(token)


def watchdog_reminder(body: str, *, finding_key: str, now: datetime, reminder_seconds: int):
    """Issue only from the watchdog's actual selected-send function.

    A private in-process capability against accidental/untrusted payload input,
    not a security boundary against arbitrary Python execution in this process.
    """
    frame = sys._getframe(1)
    if (not _owner(frame, "cron_outage_watchdog.py", "deliver")
            or not isinstance(body, str) or not body
            or not isinstance(finding_key, str) or not re.fullmatch(r"[a-f0-9]{64}", finding_key)
            or not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None
            or type(reminder_seconds) is not int or reminder_seconds <= 0):
        return nullcontext()
    slot = int(now.timestamp()) // reminder_seconds
    identity = hashlib.sha256(f"watchdog-reminder/v1:{finding_key}:{reminder_seconds}:{slot}".encode()).hexdigest()
    family = hashlib.sha256(f"watchdog-reminder/v1:{finding_key}:{reminder_seconds}".encode()).hexdigest()
    return _issued(_Reminder(_TOKEN, body, identity, family, reminder_seconds))


def outcome_message(message: str):
    """Bind the exact selected message before any normal transport formatting."""
    frame = sys._getframe(1)
    current = _ISSUED.get()
    value = current if (_owner(frame, "telegram_alert.py", "send_telegram_outcome")
                        and _valid(current) and message == current.body) else None
    return _outcome(value)


@contextmanager
def _outcome(value):
    token = _OUTCOME.set(value)
    try:
        yield
    finally:
        _OUTCOME.reset(token)


def editor_chunks(original: str, wire: str, chunks: list[str], *, normalise):
    """Bind only chunks produced by the real Telegram wire/split path.

    The normalized plane may already supply operator_wire_text(original). Other
    body enrichment fails closed to ordinary duplicate detection. Nested alerts
    cannot inherit a different message's scoped identity.
    """
    frame = sys._getframe(1)
    current = _OUTCOME.get()
    permitted = None
    if _owner(frame, "telegram_alert.py", "_raw_send_telegram_result") and _valid(current):
        if original in (current.body, normalise(current.body)) and wire == normalise(original):
            permitted = (current, frozenset(hashlib.sha256(chunk.encode()).hexdigest() for chunk in chunks))
    return _editor_chunks(permitted)


@contextmanager
def _editor_chunks(permitted):
    token = _CHUNKS.set(permitted)
    try:
        yield
    finally:
        _CHUNKS.reset(token)


def editor_fingerprint(original: str, content_fingerprint: str) -> tuple[str, str | None, int | None]:
    """Scoped identity plus a stable family cooldown, including across slot boundaries."""
    frame = sys._getframe(1)
    permitted = _CHUNKS.get()
    if not _owner(frame, "lib/comms_editor.py", "edit") or not permitted:
        return content_fingerprint, None, None
    current, hashes = permitted
    if not _valid(current) or hashlib.sha256(original.encode()).hexdigest() not in hashes:
        return content_fingerprint, None, None
    identity = hashlib.sha256(f"{content_fingerprint}:{current.identity}".encode()).hexdigest()[:20]
    family = hashlib.sha256(f"{content_fingerprint}:{current.family}".encode()).hexdigest()[:20]
    return identity, family, current.reminder_seconds
