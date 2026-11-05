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

Absence of an owner is also *not* "forget it". A process with no owner (the CIO governed model
bridge, the provider-health check) spools the diagnostic here instead, keyed so a caller that
retries every call adds one line rather than thousands; an authorised owner drains the spool.
Without that, a credit outage inside the bridge produced a diagnostic, recorded nothing, sent
nothing and told nobody — silently the same as before the 2026-10-30 postmortem.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
from pathlib import Path
from typing import Callable, Iterable, Optional

log = logging.getLogger(__name__)

#: channel -> delivery callable; a callable returns True only when delivery is CONFIRMED.
_NOTIFIERS: dict[str, Callable[[dict], bool]] = {}

#: Where a process with no owner spools diagnostics. TRADEAI_OPS_DIAGNOSTICS_SPOOL names the FILE and lets
#: a test keep its writes inside its own tmp dir; the state roots name the DIRECTORY.
SPOOL_ENV = "TRADEAI_OPS_DIAGNOSTICS_SPOOL"
STATE_ENV_VARS = ("TRADEAI_STATE_ROOT", "PROJECT_ROOT")
SPOOL_NAME = "ops_diagnostics_spool.jsonl"

#: Non-None means "this process must not deliver" (a dry run). Suppressed events are RECORDED so the caller
#: can report what it would have sent; ``deliver`` still returns False, so no dedupe key is recorded.
_SUPPRESSION: Optional[str] = None
_SUPPRESSED: list[dict] = []


def spool_path() -> Path:
    """Where a diagnostic is retained when this process has no owner."""
    override = os.environ.get(SPOOL_ENV)
    if override:
        return Path(override)
    for var in STATE_ENV_VARS:
        supplied = os.environ.get(var)
        if supplied:
            return Path(supplied) / "data" / "runtime" / SPOOL_NAME
    return Path(__file__).resolve().parents[2] / "data" / "runtime" / SPOOL_NAME


def suppress(reason: str) -> None:
    """Deliver nothing for the rest of this process run; record what would have been delivered.

    A suppressed run does not spool either: ``run_persistent_wake --dry-run`` promises to write nothing,
    and an outbox line is a write.
    """
    global _SUPPRESSION
    _SUPPRESSION = str(reason)


def resume() -> None:
    """Undo :func:`suppress` and forget the recorded events."""
    global _SUPPRESSION
    _SUPPRESSION = None
    _SUPPRESSED.clear()


def suppression() -> Optional[str]:
    return _SUPPRESSION


def suppressed_events() -> list[dict]:
    """The diagnostics a suppressed run would have delivered, in order."""
    return list(_SUPPRESSED)


def spool_key(diagnostic: dict) -> str:
    """Identity of a diagnostic for spool dedupe: the same broken book on the same day is one line."""
    return "|".join(
        str(diagnostic.get(k, ""))
        for k in ("channel", "code", "path", "day", "where", "action")
    )


def _spool(diagnostic: dict) -> None:
    """Retain one diagnostic on disk. Never raises: an unavailable spool must not take the caller down."""
    if _SUPPRESSION is not None:
        return
    path = spool_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        key = spool_key(diagnostic)
        with path.open("a+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                fh.seek(0)
                existing = fh.read()
                for line in existing.splitlines():
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict) and spool_key(row) == key:
                        return
                # Terminate an interrupted final record before appending. Without this the broken
                # fragment stays glued to the next entry, so the spool never becomes readable again
                # and every diagnostic written after the crash is lost with it.
                if existing and not existing.endswith("\n"):
                    fh.write("\n")
                fh.write(json.dumps(dict(diagnostic), sort_keys=True, default=str) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception as exc:  # a read-only or full disk is a warning, never the caller's exception
        log.warning("diagnostic spool %s unavailable: %s: %s", path, type(exc).__name__, exc)


def spooled() -> list[dict]:
    """Read the spool without delivering anything (tests and operator inspection)."""
    path = spool_path()
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def drain(deliver_one: Callable[[dict], bool], *, channels: Optional[Iterable[str]] = None) -> int:
    """Deliver spooled diagnostics through ``deliver_one``; return how many were CONFIRMED.

    Only rows the delivery callable confirms are removed. A rejected row stays spooled, so a temporary
    transport failure delays the alert instead of discarding it.
    """
    path = spool_path()
    if not path.exists():
        return 0
    allowed = set(channels) if channels is not None else None
    try:
        with path.open("r", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
            try:
                raw = fh.read()
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        log.warning("diagnostic spool %s unreadable: %s: %s", path, type(exc).__name__, exc)
        return 0
    # Per line, not all-or-nothing. A disk-full write leaves a partial FINAL record, and a single
    # json.loads over the whole file then delivered NOTHING — every intact diagnostic behind one
    # truncated fragment. That is the exact failure this PR exists to stop, in the outbox itself.
    rows = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue

    delivered: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        channel = str(row.get("channel", ""))
        if allowed is not None and channel not in allowed:
            continue
        try:
            ok = bool(deliver_one(row))
        except Exception as exc:
            log.warning("diagnostic spool delivery failed: %s: %s", type(exc).__name__, exc)
            ok = False
        if ok:
            delivered.append(spool_key(row))
    if not delivered:
        return 0

    try:
        with path.open("r+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                keep = []
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(row, dict) and spool_key(row) in delivered:
                        continue
                    keep.append(line if line.endswith("\n") else line + "\n")
                fh.seek(0)
                fh.truncate()
                fh.writelines(keep)
                fh.flush()
                os.fsync(fh.fileno())
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        log.warning("diagnostic spool %s could not be rewritten: %s: %s", path, type(exc).__name__, exc)
    return len(delivered)


def register(channel: str, notifier: Callable[[dict], bool]) -> None:
    """Install the delivery callable for a channel (called by the notification owner)."""
    _NOTIFIERS[str(channel)] = notifier


def unregister(channel: str) -> None:
    """Remove a channel's owner (tests and shutdown)."""
    _NOTIFIERS.pop(str(channel), None)


def registered(channel: str) -> bool:
    return str(channel) in _NOTIFIERS


def emit(channel: str, diagnostic: dict) -> bool:
    """Deliver through the registered owner, or SPOOL when this process has none. Never raises.

    ``False`` means NOT delivered. The caller still keeps the diagnostic retryable; the spool is what
    keeps it recoverable, because the caller's retry only helps while the process is alive.
    """
    notifier: Optional[Callable[[dict], bool]] = _NOTIFIERS.get(str(channel))
    if notifier is None:
        # No authorised owner in this process (the bridge, the health check). Retain the event durably so
        # the next drain by an owner delivers it; the caller may retry as well, and the spool dedupes.
        _spool({**dict(diagnostic), "channel": str(channel)})
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

    Under :func:`suppress` (a dry run) nothing is sent and nothing is spooled: the event is recorded in
    memory for the caller to report, and ``False`` keeps the caller's dedupe key unset.
    """
    if _SUPPRESSION is not None:
        _SUPPRESSED.append({"channel": str(channel), "diagnostic": dict(diagnostic), "reason": _SUPPRESSION})
        return False
    if notify is not None:
        try:
            return bool(notify(dict(diagnostic)))
        except Exception as exc:
            log.warning("diagnostic channel %s explicit delivery failed: %s: %s",
                        channel, type(exc).__name__, exc)
            return False
    return emit(channel, diagnostic)
