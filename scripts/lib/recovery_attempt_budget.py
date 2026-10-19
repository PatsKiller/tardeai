"""Host-only durable attempt accounting shared by bounded recovery owners.

This module creates neither authority nor initial history. The health namespace additionally requires a
host history source; no such production source is provisioned by this change. Reservations never refund.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import math
import os
import re
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

SUPERVISOR = "supervisor_recovery"
HEALTH = "system_health_retry"
LOCK_WAIT_S = 3.0
_HEALTH_FIELDS = {"schema", "namespace", "component", "ts", "attempt_id", "command_digest"}


def _closed_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_history_field")
        result[key] = value
    return result


def _policy(now, limit, window_s, namespace):
    if (
        type(limit) is not int
        or limit < 0
        or type(window_s) is not int
        or window_s <= 0
        or not isinstance(now, dt.datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or namespace not in (SUPERVISOR, HEALTH)
    ):
        raise ValueError("invalid_budget_or_clock")
    return now.astimezone(dt.timezone.utc)


def counts(path: Path, now, *, limit: int, window_s: int, namespace: str, text=None) -> dict[str, int]:
    """Count a trusted history snapshot. Supervisor reservation/result rows retain v1 identity semantics."""
    instant = _policy(now, limit, window_s, namespace)
    cutoff = instant - dt.timedelta(seconds=window_s)
    raw = path.read_text(encoding="utf-8") if text is None else text
    if type(raw) is not str:
        raise ValueError("unavailable_history_source")
    attempts = set()
    identities = {}
    for index, line in enumerate(raw.splitlines()):
        if not line.strip():
            continue
        row = json.loads(line, object_pairs_hook=_closed_object)
        if not isinstance(row, dict):
            raise ValueError("malformed_budget_history")
        if namespace == HEALTH:
            if (
                set(row) != _HEALTH_FIELDS
                or row.get("schema") != "HealthRetryAttempt@v1"
                or row.get("namespace") != HEALTH
                or not isinstance(row.get("component"), str)
                or not row["component"].strip()
                or not isinstance(row.get("attempt_id"), str)
                or re.fullmatch(r"[0-9a-f]{32}", row["attempt_id"]) is None
                or not isinstance(row.get("command_digest"), str)
                or re.fullmatch(r"[0-9a-f]{64}", row["command_digest"]) is None
            ):
                raise ValueError("malformed_health_attempt")
            lane, attempt, attempted = row["component"], row["attempt_id"], True
            identity = tuple(row[key] for key in sorted(_HEALTH_FIELDS))
            if attempt in identities:
                raise ValueError("duplicate_health_attempt_identity")
        else:
            if (
                row.get("schema") != "Recovery@v1"
                or type(row.get("executed")) is not bool
                or not isinstance(row.get("lane_id"), str)
                or not row["lane_id"]
                or row.get("mode") not in ("live", "shadow")
            ):
                raise ValueError("malformed_budget_history")
            if any(field in row and type(row[field]) is not bool for field in ("attempted", "attempt_reserved")):
                raise ValueError("malformed_attempt_flags")
            lane, attempt = row["lane_id"], row.get("attempt_id")
            identity = (lane, row.get("action"), row.get("level"), row.get("mode"), row.get("ts"))
            if "attempt_id" in row:
                if not isinstance(attempt, str) or not attempt or row.get("attempt_reserved") is not True:
                    raise ValueError("malformed_attempt_identity")
                if attempt in identities and identities[attempt] != identity:
                    raise ValueError("conflicting_attempt_identity")
            # Legacy timeout/spawn failures count even though executed=false.
            attempted = (
                row.get("attempt_reserved") is True
                or row.get("attempted") is True
                or row["executed"]
                or (row["mode"] == "live" and bool(row.get("error")))
            )
        if attempt:
            identities[attempt] = identity
        at = dt.datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00"))
        if at.tzinfo is None or at.utcoffset() is None or at > instant:
            raise ValueError("invalid_budget_history_clock")
        if attempted and at >= cutoff:
            attempts.add((lane, attempt if attempt else f"legacy-line-{index}"))
    result = {}
    for lane, _ in attempts:
        result[lane] = result.get(lane, 0) + 1
    return result


def append(path: Path, row: dict) -> None:
    """Caller owns the journal lock; append and fsync before invoking any effect."""
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def journal_lock(path: Path, *, deadline=None):
    """Bound reservation/settlement contention by both a small host cap and the caller's deadline."""
    end = time.monotonic() + LOCK_WAIT_S
    if deadline is not None:
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            raise ValueError("invalid_lock_deadline")
        end = min(end, deadline)
    with path.with_suffix(".lock").open("a", encoding="utf-8") as lock:
        while True:
            if time.monotonic() >= end:
                raise TimeoutError("attempt_budget_lock_deadline")
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(min(0.01, max(0, end - time.monotonic())))
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def reserve(
    path: Path,
    row: dict,
    now,
    *,
    limit: int,
    window_s: int,
    namespace: str,
    live: bool,
    history_source=None,
    deadline=None,
    observed_count=0,
) -> tuple[bool, str]:
    """One lock/read/validate/reserve/fsync owner. A missing or unknown source never initializes zero."""
    try:
        _policy(now, limit, window_s, namespace)
        if type(live) is not bool or type(observed_count) is not int or observed_count < 0:
            raise ValueError("invalid_admission")
        with journal_lock(path, deadline=deadline):
            # Existing bytes must survive; no initializer or empty replacement is permitted.
            disk = path.read_text(encoding="utf-8")
            if namespace == HEALTH:
                if history_source is None:
                    return False, "uninitialized"
                try:
                    text = history_source(path, now)
                except Exception:
                    return False, "unavailable"
                if text is None:
                    return False, "uninitialized"
                if type(text) is not str or text != disk:
                    raise ValueError("unbound_history_source")
                lane = row.get("component")
            else:
                text, lane = disk, row.get("lane_id")
            recent = counts(path, now, limit=limit, window_s=window_s, namespace=namespace, text=text)
            if not isinstance(lane, str) or not lane:
                raise ValueError("invalid_admission_lane")
            allowed = max(recent.get(lane, 0), observed_count) < limit
            if namespace == SUPERVISOR:
                row["would_execute"] = allowed
                if live and allowed:
                    row["attempt_id"] = uuid.uuid4().hex
                    if any(
                        json.loads(line).get("attempt_id") == row["attempt_id"]
                        for line in text.splitlines()
                        if line.strip()
                    ):
                        raise ValueError("duplicate_reservation_identity")
                    record = {**row, "attempt_reserved": True, "attempted": False}
                else:
                    record = row
                # Validate new rows as well as historical rows before persisting or acting.
                counts(path, now, limit=limit, window_s=window_s, namespace=namespace, text=json.dumps(record))
                append(path, record)
            elif live and allowed:
                record = {**row, "attempt_id": uuid.uuid4().hex}
                counts(
                    path,
                    now,
                    limit=limit,
                    window_s=window_s,
                    namespace=namespace,
                    text=text + "\n" + json.dumps(record),
                )
                append(path, record)
                row.update(record)
            return allowed, "known"
    except (OSError, ValueError, TypeError, OverflowError):
        return False, "unavailable"
