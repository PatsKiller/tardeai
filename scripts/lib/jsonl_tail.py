"""Truncated-final-line handling for append-only JSONL stores (disk-full mid-write).

On 2026-10-30 the host ran out of disk around 00:50 ET. Two append-only stores were left with a half-written final
record, and each reader died on it from then on:

* ``data/runtime/provider_cost/anthropic_credit.jsonl`` -- every read raised ``CREDIT_UNAVAILABLE``, so the Anthropic
  lane failed closed and fell back to grok without a word for 30+ hours (the credit book deliberately stays
  fail-closed on a damaged spend journal; it now reports it);
* ``persistent_wake/state/wakes.jsonl`` -- the hourly persistent-agent wake threw ``JSONDecodeError`` every run.

The rule here is narrow on purpose: only a final segment that is not newline-terminated AND does not parse is a
"truncated tail". It is skipped by readers, and the next writer moves its bytes to a unique ``.corrupt-tail-<ts>``
file beside the store before appending (archive, never delete, never overwrite an earlier fragment). Any other
unparseable line is real corruption and the caller keeps failing loudly. Every detection logs a warning and emits
one structured diagnostic per file per UTC day.

Send authority (AGENTS.md §23.20): this module is inside the advisory planner lane's import reach, so it must not
import or call a Telegram sender. It builds a structured diagnostic and hands it to
``scripts/lib/ops_diagnostics.py``; the already-authorised notification owner
(``scripts/lib/ops_notify_owner.py``) delivers it. A diagnostic is recorded as sent ONLY after the owner confirms
acceptance -- a rejected or raising delivery stays retryable.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from . import ops_diagnostics
except ImportError:  # pragma: no cover - flat import layout
    import ops_diagnostics  # type: ignore[no-redef]

log = logging.getLogger(__name__)

PRODUCER = "jsonl_tail_guard"
CHANNEL = "store_damage"
_alerted: set[tuple[str, str]] = set()


def truncated_tail(raw: bytes) -> tuple[int, bytes] | None:
    """Return (offset, fragment) when ``raw`` ends in an unterminated, unparseable segment, else None."""
    if not raw or raw.endswith(b"\n"):
        return None
    cut = raw.rfind(b"\n") + 1
    if cut == 0:
        return None  # no intact record before it: that is a garbage file, not a truncated tail
    fragment = raw[cut:]
    if not fragment.strip():
        return None
    try:
        json.loads(fragment)
    except ValueError:
        return cut, fragment
    return None  # a complete record that only lacks its newline is not damage


def _unique_archive(path: Path, stamp: int) -> tuple[int, Path]:
    """Exclusively create ``<name>.corrupt-tail-<stamp>[-N]``; never truncate an earlier fragment.

    ``int(time.time())`` has one-second resolution, so two repairs in the same frozen second used to
    open the SAME archive with ``wb`` and destroy the first damaged fragment. O_CREAT|O_EXCL makes
    creation collision-safe: an existing name means another fragment owns it, so the next suffix is
    tried. Every fragment is retained (F2).
    """
    n = 0
    while True:
        suffix = "" if n == 0 else f"-{n}"
        archive = path.with_name(f"{path.name}.corrupt-tail-{stamp}{suffix}")
        try:
            fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            n += 1
            if n > 100_000:  # pathological; fall back to a random suffix rather than spin forever
                archive = path.with_name(f"{path.name}.corrupt-tail-{stamp}-{os.urandom(8).hex()}")
                fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                return fd, archive
            continue
        return fd, archive


def quarantine_tail(path: Path, offset: int, fragment: bytes) -> Path:
    """Move the fragment to a unique ``<name>.corrupt-tail-<epoch>`` beside the store and cut the store back.

    Archive-before-truncate order is preserved: the fragment is written, flushed and fsynced before the
    store is truncated. The caller must hold the store's write lock."""
    path = Path(path)
    fd, archive = _unique_archive(path, int(time.time()))
    with os.fdopen(fd, "wb") as fh:
        fh.write(fragment)
        fh.flush()
        os.fsync(fh.fileno())
    os.truncate(path, offset)
    log.warning("%s: truncated final record (%d bytes) moved to %s", path, len(fragment), archive)
    return archive


def store_damage_diagnostic(path: Path, fragment_len: int, *, action: str, now: datetime | None = None) -> dict:
    """A structured operator diagnostic for one damaged final record (no sender, no side effects)."""
    path = Path(path)
    day = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    return {
        "schema": "StoreDamageDiagnostic@v1",
        "channel": CHANNEL,
        "severity": "P1",
        "priority": "P1",
        "producer": PRODUCER,
        "message_class": "ops_integrity",
        "dedupe_minutes": 1440,
        "path": str(path),
        "day": day,
        "fragment_bytes": int(fragment_len),
        "action": str(action),
        "message": (
            f"🚨 *STORE DAMAGE* — {path.name} ({day})\n"
            f"The last record of `{path}` is half-written ({fragment_len} bytes), most likely from a full disk.\n"
            f"Action taken: {action}.\n"
            "Stores that tolerate it skip it and archive it beside the store on the next write "
            "(.corrupt-tail-<time>); the Anthropic credit book stays closed until the fragment is archived. "
            "Check free disk space and whether other stores were damaged the same night."
        ),
    }


def report(path: Path, fragment_len: int, *, action: str, now: datetime | None = None,
           notify=None) -> bool:
    """Warn and emit one P1 diagnostic per file per UTC day. Returns True only on CONFIRMED delivery.

    ``notify`` is an explicit delivery callable (injection/tests); when omitted the already-authorised
    owner registered on ``ops_diagnostics`` is used. A rejected, raising or absent delivery does NOT add
    the dedupe key, so the next read retries instead of silently suppressing the rest of the day.
    """
    path = Path(path)
    log.warning("%s: truncated final record (%d bytes); %s", path, fragment_len, action)
    diagnostic = store_damage_diagnostic(path, fragment_len, action=action, now=now)
    key = (str(path), diagnostic["day"])
    if key in _alerted:
        return False
    if not ops_diagnostics.deliver(CHANNEL, diagnostic, notify=notify):
        return False  # not delivered: leave it retryable
    _alerted.add(key)
    return True
