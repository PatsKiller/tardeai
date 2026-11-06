"""Already-authorised operator-notification owner for storage/credit diagnostics.

The storage and credit helpers (``jsonl_tail``, ``anthropic_routing``) are in the advisory
planner lane's import reach and therefore may not send (AGENTS.md §23.20, PR #2347 F1). They
emit sender-free structured diagnostics to ``ops_diagnostics``; this module is the owner that
turns each diagnostic into one operator notification.

Only modules that already hold sender authority import this module — today the persistent wake
store consumer (``persistent_wake_store``). It is deliberately NOT imported by anything in the
planner's reach, so the static lane guard sees no sender there.

Transport resolution is lazy and fully guarded: both historical import layouts are attempted
inside the delivery ``try``, so an unavailable or broken ``telegram_alert`` makes delivery fail
visibly (a warning, ``False``) without ever taking the wake reader down (PR #2347 F4).
"""
from __future__ import annotations

import logging

from . import ops_diagnostics

log = logging.getLogger(__name__)

CHANNELS = ("store_damage", "credit_refusal")


def deliver(diagnostic: dict) -> bool:
    """Send one structured diagnostic. Returns True only when the send was ACCEPTED.

    ``send_telegram`` returns True when the platform accepted the event (delivered now,
    queued for a digest, or recorded for the Command Center) and False when it did not.
    An exception, or an unavailable module, is a rejection too: the caller must not record
    a dedupe key for it (F3).
    """
    try:
        try:
            from telegram_alert import send_telegram
        except ImportError:
            from scripts.telegram_alert import send_telegram  # type: ignore[no-redef] -- flat import layout (served scripts/ path), the package import is tried first
        accepted = send_telegram(
            diagnostic["message"],
            priority=diagnostic.get("priority", "P1"),
            dedupe_minutes=diagnostic.get("dedupe_minutes", 1440),
            producer=diagnostic.get("producer", "ops_diagnostics"),
            message_class=diagnostic.get("message_class", "ops_integrity"),
        )
    except Exception as exc:  # unavailable transport or a failed send: visible, never fatal
        log.warning("operator notification not sent: %s: %s", type(exc).__name__, exc)
        return False
    return bool(accepted)


def install() -> None:
    """Register this owner for every diagnostic channel (idempotent)."""
    for channel in CHANNELS:
        ops_diagnostics.register(channel, deliver)


def drain() -> int:
    """Deliver what processes without an owner spooled. Returns the number CONFIRMED.

    The governed bridge and the provider-health check run Anthropic calls but hold no sender
    (AGENTS.md §23.20), so a credit refusal there reached this spool and stopped. The wake consumer owns
    the channels, so its real run drains them; a rejected row stays spooled for the next run.
    """
    return ops_diagnostics.drain(deliver, channels=CHANNELS)
