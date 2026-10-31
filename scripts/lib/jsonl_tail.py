"""Truncated-final-line handling for append-only JSONL stores (disk-full mid-write).

On 2026-10-30 the host ran out of disk around 00:50 ET. Two append-only stores were left with a half-written final
record, and each reader died on it from then on:

* ``data/runtime/provider_cost/anthropic_credit.jsonl`` -- every read raised ``CREDIT_UNAVAILABLE``, so the Anthropic
  lane failed closed and fell back to grok without a word for 30+ hours (the credit book deliberately stays
  fail-closed on a damaged spend journal; it now reports it);
* ``persistent_wake/state/wakes.jsonl`` -- the hourly persistent-agent wake threw ``JSONDecodeError`` every run.

The rule here is narrow on purpose: only a final segment that is not newline-terminated AND does not parse is a
"truncated tail". It is skipped by readers, and the next writer moves its bytes to a ``.corrupt-tail-<ts>`` file
beside the store before appending (archive, never delete). Any other unparseable line is real corruption and the
caller keeps failing loudly. Every detection logs a warning and sends one P1 operator alert per file per day.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

PRODUCER = "jsonl_tail_guard"
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


def quarantine_tail(path: Path, offset: int, fragment: bytes) -> Path:
    """Move the fragment to ``<name>.corrupt-tail-<epoch>`` beside the store and cut the store back to ``offset``.

    The caller must hold the store's write lock."""
    path = Path(path)
    archive = path.with_name(f"{path.name}.corrupt-tail-{int(time.time())}")
    with open(archive, "wb") as fh:
        fh.write(fragment)
        fh.flush()
        os.fsync(fh.fileno())
    os.truncate(path, offset)
    log.warning("%s: truncated final record (%d bytes) moved to %s", path, len(fragment), archive)
    return archive


def report(path: Path, fragment_len: int, *, action: str, now: datetime | None = None) -> bool:
    """Warn and send one P1 per file per UTC day. Returns True when an alert was sent."""
    path = Path(path)
    day = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    log.warning("%s: truncated final record (%d bytes); %s", path, fragment_len, action)
    key = (str(path), day)
    if key in _alerted:
        return False
    _alerted.add(key)
    message = (
        f"🚨 *STORE DAMAGE* — {path.name} ({day})\n"
        f"The last record of `{path}` is half-written ({fragment_len} bytes), most likely from a full disk.\n"
        f"Action taken: {action}.\n"
        "Stores that tolerate it skip it and archive it beside the store on the next write "
        "(.corrupt-tail-<time>); the Anthropic credit book stays closed until the fragment is archived. "
        "Check free disk space and whether other stores were damaged the same night."
    )
    try:
        from telegram_alert import send_telegram
    except ImportError:
        from scripts.telegram_alert import send_telegram  # type: ignore[no-redef]
    try:
        send_telegram(message, priority="P1", dedupe_minutes=1440, producer=PRODUCER, message_class="ops_integrity")
    except Exception as exc:  # the alert path must never take the store down; it must be visible
        log.warning("%s: store-damage alert not sent: %s: %s", path, type(exc).__name__, exc)
        return False
    return True
