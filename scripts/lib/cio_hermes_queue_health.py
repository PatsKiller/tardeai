"""cio_hermes_queue_health.py — the CIO Hermes research queue as a research-lane-health lane.

WHY
---
Operator, 2026-09-14: "This is the heartbeat that can't go down." Measured the same day:
136 of 219 requests in the CIO Hermes research queue failed in 7 days (62%).
- 63 were execution-language refusals.
- 40 hit the cost cap.
- 22 were bridge circuit-open or dropped connections.
- 8 were provider errors.

Nothing alarmed. `research_lane_health` and `hermes_pipeline_health` both read
`hermes_external_research` (healthy, 56/57), and no monitor read
`data/cio/hermes_research_requests.jsonl`. The tool that classifies these failures
(`cio_research_fail_histogram.py`) existed but was never scheduled.

WHAT
----
One lane row, in the same shape as every other collector, built from the request ledger over the
last 24 hours:
- terminal outcome per research_id (the latest event wins);
- the failure share;
- failures by class (`cio_research_fail_policy.classify_failure`);
- requests left queued past the stall window.

FIRING
------
failure_rate_24h    failed / (failed + completed) >= 30%, with at least 5 outcomes
no_completions_24h  at least 3 failures and no completions
queue_stalled       a request queued for longer than 3 hours (the worker timer runs every 15 minutes)
unclassified_24h    3 or more failures the classifier cannot place (a new failure shape — read it)

Deterministic: no model, no writes. READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

LANE = "cio-hermes-queue"
SCHEMA = "CioHermesQueueHealth@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
REQUEST_LEDGER = PROJECT_ROOT / "data" / "cio" / "hermes_research_requests.jsonl"
TERMINAL = {"completed", "failed", "superseded", "cancelled"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def _ts(row: dict[str, Any]) -> Optional[datetime]:
    raw = row.get("ts") or row.get("updated_ts") or row.get("completed_ts")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _status(row: dict[str, Any]) -> Optional[str]:
    status = row.get("status")
    if status:
        return str(status)
    event = str(row.get("event") or "")
    if event.endswith("_REAPED") or event.endswith("_REPLAYED"):
        return "queued"
    return None


def load_events(path: Path, *, since: datetime) -> list[dict[str, Any]]:
    """Rows at or after `since`, in file order. A missing ledger is an empty list."""
    out: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                ts = _ts(row)
                if ts is not None and ts >= since and row.get("research_id"):
                    row["_ts"] = ts
                    out.append(row)
    except OSError:
        return []
    return out


def _ledger_state(path: Path) -> str:
    """Classify the request ledger: ``ok | absent | empty | unreadable | invalid``.

    An unreadable input is "I could not tell", never "no requests": reading it as an empty
    ledger made a missing or corrupt file report a healthy lane with zero lost requests
    (lead ruling, 2026-11-03, after cx-openai-2 and cc-deepseek-3 reached it independently).
    """
    try:
        if path.is_dir():
            return "unreadable"
        raw = path.read_bytes()
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "unreadable"
    if not raw.strip():
        return "empty"
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            if isinstance(json.loads(line), dict):
                return "ok"
        except (ValueError, RecursionError):
            continue
    return "invalid"


def _projection_state(path: Path) -> tuple[Optional[dict[str, Any]], str]:
    """``(document, state)`` for the projection: ok | absent | empty | unparseable | not_object | unreadable."""
    try:
        if path.is_dir():
            return None, "unreadable"
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, "absent"
    except OSError:
        return None, "unreadable"
    if not raw.strip():
        return None, "empty"
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        return None, "unparseable"
    if not isinstance(doc, dict):
        return None, "not_object"
    return doc, "ok"


def summarise(events: Iterable[dict[str, Any]], *, now: datetime, stall_hours: float = 3.0,
              classify=None) -> dict[str, Any]:
    """Latest status per research_id, failure classes, stalled queue. Pure."""
    if classify is None:
        try:
            from scripts.lib.cio_research_fail_policy import classify_failure as classify
        except ImportError:                                           # pragma: no cover
            from lib.cio_research_fail_policy import classify_failure as classify  # type: ignore
    latest: dict[str, dict[str, Any]] = {}
    for row in events:
        status = _status(row)
        if status is None:
            continue
        rid = str(row["research_id"])
        prev = latest.get(rid)
        if prev is None or row["_ts"] >= prev["_ts"]:
            latest[rid] = {**row, "status": status}
    by_status = Counter(r["status"] for r in latest.values())
    failed = [r for r in latest.values() if r["status"] == "failed"]
    by_class = Counter(classify(r.get("error"))["class"] for r in failed)
    stalled = sorted(
        (r for r in latest.values()
         if r["status"] == "queued" and (now - r["_ts"]) > timedelta(hours=stall_hours)),
        key=lambda r: r["_ts"],
    )
    return {
        "by_status": dict(by_status),
        "completed": by_status.get("completed", 0),
        "failed": len(failed),
        "by_class": dict(by_class),
        "dominant_class": by_class.most_common(1)[0][0] if by_class else None,
        "stalled": [{"research_id": r["research_id"], "queued_hours": round((now - r["_ts"]).total_seconds() / 3600, 1)}
                    for r in stalled[:5]],
        "stalled_n": len(stalled),
        "last_failure": (max(failed, key=lambda r: r["_ts"]).get("error") or "")[:160] if failed else None,
    }


# ── Question ownership: the exact predicate the restore path uses ────────────────────────────────────────────
# `restore_lost_requests` (scripts/lib/cio_hermes_research.py) suppresses a candidate only when the question is
# genuinely owned: an OPEN row with the same fingerprint, or a COMPLETED row whose completion clock is >= the asked
# clock. It never treats a failed, cancelled, superseded or expired row as an owner, and it never suppresses on an
# answer that predates the question. This function mirrors that rule so the health check cannot be silenced by
# history the restore path would still restore.
#
# The vocabulary is the QUEUE's, imported rather than re-typed (cx-openai-4 P1, 2026-11-03): invented aliases
# (pending/claimed/open/queued_running) suppressed requests the native lookup does not consider in flight, and the
# native legacy "started" state was missing, so a real owner's duplicate was reported lost. One constant, two
# consumers, no drift. Import through the SAME package prefix as this module so the repo's dual lib./scripts.lib.
# imports cannot create a second copy of the constant.
if __package__ and __package__.startswith("scripts."):
    from scripts.lib.hermes_research_queue import IN_FLIGHT as _OPEN_STATES, TERMINAL as _TERMINAL_STATES
else:  # pragma: no cover - depends on how the caller set sys.path
    from lib.hermes_research_queue import IN_FLIGHT as _OPEN_STATES, TERMINAL as _TERMINAL_STATES  # type: ignore

# A terminal row owns a question only when it actually ANSWERED it; failed/cancelled/superseded never do.
_DONE_STATES = frozenset(_TERMINAL_STATES - {"failed", "cancelled", "superseded"})


def _parse_clock(value: Any) -> Optional[datetime]:
    """One clock, parsed once — the same accepted shape as the oracle's `parse_ts`."""
    if not value:
        return None
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _completion_clock(record: dict[str, Any]) -> Optional[datetime]:
    """The oracle's exact completion expression: `parse_ts(completed_ts or as_of or updated_ts)`.

    The FIRST POPULATED field is selected before parsing, so a populated-but-invalid
    `completed_ts` does NOT fall through to a later field (cx-openai-4 R3). Falling through
    suppressed requests the restore path would genuinely restore — a false all-clear. A row
    carrying only a generic `ts` has no completion clock at all.
    """
    return _parse_clock(record.get("completed_ts") or record.get("as_of") or record.get("updated_ts"))


def _asked_clock(record: dict[str, Any]) -> Optional[datetime]:
    """The oracle's asked clock: `parse_ts(created_ts or updated_ts)`.

    Never the event `ts` the ledger row was loaded on (cx-openai-4 R4): the event clock moves
    with every update, so comparing an answer against it reported an already-answered request
    as lost.
    """
    return _parse_clock(record.get("created_ts") or record.get("updated_ts"))


def _question_owned(fingerprint: str, asked: Optional[datetime],
                    by_rid: dict[str, Any], open_fp: dict[str, Any],
                    done_fp: dict[str, Any]) -> bool:
    """True only when an open or completed-before-now owner genuinely holds this question."""
    if not fingerprint:
        return False
    if fingerprint in open_fp:
        return True
    done = done_fp.get(fingerprint)
    if isinstance(done, dict):
        completed = _completion_clock(done)
        if completed is not None and asked is not None and completed >= asked:
            return True
    for row in by_rid.values():
        if not isinstance(row, dict) or str(row.get("fingerprint") or "") != fingerprint:
            continue
        state = str(row.get("status") or row.get("state") or "").strip().lower()
        if state in _OPEN_STATES:
            return True
        if state in _DONE_STATES:
            completed = _completion_clock(row)
            if completed is not None and asked is not None and completed >= asked:
                return True
        # failed / cancelled / superseded / expired / unknown: never owns the question
    return False


def collect_cio_hermes_queue_health(*, now: Optional[datetime] = None, path: Optional[Path] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    ledger = Path(path or os.getenv("CIO_HERMES_REQUEST_LEDGER") or REQUEST_LEDGER)
    window_h = _env_float("CIO_HERMES_QUEUE_WINDOW_HOURS", 24.0)
    fail_share = _env_float("CIO_HERMES_QUEUE_FAIL_SHARE", 0.30)
    min_outcomes = int(_env_float("CIO_HERMES_QUEUE_MIN_OUTCOMES", 5))
    stall_h = _env_float("CIO_HERMES_QUEUE_STALL_HOURS", 3.0)
    projection = Path(os.getenv("CIO_HERMES_PROJECTION") or ledger.with_name("hermes_research_projection.json"))
    ledger_state = _ledger_state(ledger)
    proj_doc, projection_state = _projection_state(projection)
    row: dict[str, Any] = {
        "lane": LANE,
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "as_of": now.replace(microsecond=0).isoformat(),
        "ledger": str(ledger),
        "ledger_present": ledger_state != "absent",
        "window_hours": window_h,
        # The read state travels with the numbers: a consumer must be able to
        # tell "zero lost" from "could not read" (lead ruling, 2026-11-03).
        "ledger_state": ledger_state,
        "projection": str(projection),
        "projection_state": projection_state,
    }
    if ledger_state != "ok":
        # NEVER healthy when the input could not be read, and never a count from a file we did not
        # read: an absent/empty/corrupt ledger is "I could not tell", not "no requests".
        return {
            **row,
            "ok": False,
            "firing": [f"request_ledger_unreadable:{ledger_state}"],
            "lost": None,
            "lost_n": None,
            "note": f"request ledger is {ledger_state}; no outcome or lost-request count was measured",
        }
    events = load_events(ledger, since=now - timedelta(hours=window_h))
    s = summarise(events, now=now, stall_hours=stall_h)
    # A request the ledger recorded but the projection does not hold is invisible to the worker.
    # Measured 2026-09-14: 7 that day, lost to unlocked writers. The worker now restores those
    # under 48h on its next claim; this signal staying on means a writer still bypasses the lock.
    if projection_state == "ok":
        assert proj_doc is not None
        by_rid = proj_doc.get("by_research_id") or {}
        known = set(by_rid)
        # A request is NOT lost when its QUESTION is already owned by an open or completed
        # projection entry: `restore_lost_requests` dedups on fingerprint, so a same-question
        # row is intentionally not re-projected. 2026-11-03: `res_c30a22ae6af8` was reported
        # lost while `res_cfaa3b471ead` (2.7 s earlier, same fingerprint) was in the projection.
        open_fp = {str(k): v for k, v in (proj_doc.get("by_fingerprint_open") or {}).items() if k}
        done_fp = {str(k): v for k, v in (proj_doc.get("by_fingerprint_completed") or {}).items() if k}
    else:
        # Ownership cannot be determined without the projection. Report the measured lane signals,
        # flag the unreadable input, and publish NO lost count rather than a zero we did not read.
        by_rid, known, open_fp, done_fp = {}, None, {}, {}
    grace = now - timedelta(minutes=10)
    lost = sorted(
        {
            str(r["research_id"])
            for r in events
            if known is not None
            and r.get("event") == "HERMES_RESEARCH_REQUESTED"
            and r["_ts"] <= grace
            and str(r["research_id"]) not in known
            and not _question_owned(str(r.get("fingerprint") or ""), _asked_clock(r), by_rid, open_fp, done_fp)
        }
    )
    s["lost"], s["lost_n"] = (lost[:5], len(lost)) if known is not None else (None, None)
    outcomes = s["completed"] + s["failed"]
    firing: list[str] = []
    if projection_state != "ok":
        firing.append(f"projection_unreadable:{projection_state}")
    if lost:
        firing.append(f"requests_lost:{len(lost)}")
    if outcomes >= min_outcomes and s["failed"] / outcomes >= fail_share:
        firing.append(f"failure_rate_24h:{s['failed']}/{outcomes}")
    if s["failed"] >= 3 and s["completed"] == 0:
        firing.append("no_completions_24h")
    if s["stalled_n"]:
        firing.append(f"queue_stalled:{s['stalled_n']}")
    if s["by_class"].get("other", 0) >= 3:
        firing.append(f"unclassified_24h:{s['by_class']['other']}")
    return {**row, **s, "ok": not firing, "firing": firing,
            "attempts_24h": outcomes, "non_error_24h": s["completed"], "error_24h": s["failed"]}


__all__ = ["LANE", "collect_cio_hermes_queue_health", "load_events", "summarise"]
