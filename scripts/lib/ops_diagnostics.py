"""Sender-free structured-diagnostic sink for storage/credit recovery paths.

Why this exists (AGENTS.md §23.20, PR #2347 F1): ``jsonl_tail`` and ``anthropic_routing`` are
inside the advisory planner lane's import reach. A planning lane may never send, so neither
module may import or call a Telegram sender. They emit a structured diagnostic here instead;
an **already-authorised notification owner** (``scripts/lib/ops_notify_owner.py``, installed by
the wake consumer) registers the delivery callable.

Absence of an owner is *not* "delivered". ``deliver`` returns ``False`` when no owner is
registered, and the caller must keep the diagnostic retryable rather than recording a dedupe
key for a message nobody accepted. That is the difference between a failure recorded as
success and a failure that can still be reported.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

log = logging.getLogger(__name__)

#: channel -> delivery callable; a callable returns True only when delivery is CONFIRMED.
_NOTIFIERS: dict[str, Callable[[dict], bool]] = {}


def register(channel: str, notifier: Callable[[dict], bool]) -> None:
    """Install the delivery callable for a channel (called by the notification owner)."""
    _NOTIFIERS[str(channel)] = notifier


def unregister(channel: str) -> None:
    """Remove a channel's owner (tests and shutdown)."""
    _NOTIFIERS.pop(str(channel), None)


def registered(channel: str) -> bool:
    return str(channel) in _NOTIFIERS


def emit(channel: str, diagnostic: dict) -> bool:
    """Deliver through the registered owner. Never raises; ``False`` means NOT delivered."""
    notifier: Optional[Callable[[dict], bool]] = _NOTIFIERS.get(str(channel))
    if notifier is None:
        # No authorised owner in this process (e.g. the planner). The diagnostic stays
        # retryable; the caller already logged it, and the health lane owns the outage.
        return False
    try:
        return bool(notifier(dict(diagnostic)))
    except Exception as exc:  # an unavailable transport must never take the caller down
        log.warning("diagnostic channel %s delivery failed: %s: %s", channel, type(exc).__name__, exc)
        return False


def deliver(channel: str, diagnostic: dict, *, notify: Optional[Callable[[dict], bool]] = None) -> bool:
    """Deliver via an explicit notifier (tests/injection) or the registered owner.

    Both the notifier returning a false value and the notifier raising are rejections:
    they return ``False`` so the caller does not record a dedupe key and can retry.
    """
    if notify is not None:
        try:
            return bool(notify(dict(diagnostic)))
        except Exception as exc:
            log.warning("diagnostic channel %s explicit delivery failed: %s: %s",
                        channel, type(exc).__name__, exc)
            return False
    return emit(channel, diagnostic)
