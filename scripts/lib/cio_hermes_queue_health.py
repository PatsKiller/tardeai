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


def collect_cio_hermes_queue_health(*, now: Optional[datetime] = None, path: Optional[Path] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    ledger = Path(path or os.getenv("CIO_HERMES_REQUEST_LEDGER") or REQUEST_LEDGER)
    window_h = _env_float("CIO_HERMES_QUEUE_WINDOW_HOURS", 24.0)
    fail_share = _env_float("CIO_HERMES_QUEUE_FAIL_SHARE", 0.30)
    min_outcomes = int(_env_float("CIO_HERMES_QUEUE_MIN_OUTCOMES", 5))
    stall_h = _env_float("CIO_HERMES_QUEUE_STALL_HOURS", 3.0)
    row: dict[str, Any] = {"lane": LANE, "schema": SCHEMA, "authority": AUTHORITY,
                           "as_of": now.replace(microsecond=0).isoformat(), "ledger": str(ledger),
                           "ledger_present": ledger.exists(), "window_hours": window_h}
    if not ledger.exists():
        return {**row, "ok": True, "firing": [], "note": "request ledger absent (no CIO Hermes queue on this host)"}
    events = load_events(ledger, since=now - timedelta(hours=window_h))
    s = summarise(events, now=now, stall_hours=stall_h)
    # A request the ledger recorded but the projection does not hold is invisible to the worker.
    # Measured 2026-09-14: 7 that day, lost to unlocked writers. The worker now restores those
    # under 48h on its next claim; this signal staying on means a writer still bypasses the lock.
    projection = Path(os.getenv("CIO_HERMES_PROJECTION") or ledger.with_name("hermes_research_projection.json"))
    try:
        known = set(json.loads(projection.read_text(encoding="utf-8")).get("by_research_id") or {})
    except (OSError, ValueError):
        known = None
    grace = now - timedelta(minutes=10)
    lost = sorted({str(r["research_id"]) for r in events
                   if known is not None and r.get("event") == "HERMES_RESEARCH_REQUESTED"
                   and r["_ts"] <= grace and str(r["research_id"]) not in known})
    s["lost"], s["lost_n"] = lost[:5], len(lost)
    outcomes = s["completed"] + s["failed"]
    firing: list[str] = []
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
