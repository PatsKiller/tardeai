"""Read projections for restored desks; no jobs, providers, or durable writes.

Research lineage reads the challenge event ledger directly. It never constructs
HermesChallengeQueue: constructing that writer can create a genesis record.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import intelligence_lineage as L

_EVENT_STATUS = {
    "ENQUEUED": "PENDING", "CLAIMED": "CLAIMED", "STARTED": "IN_PROGRESS",
    "RELEASED": "RELEASED", "RESOLVED": "RESOLVED", "FAILED": "FAILED",
    "EXPIRED": "EXPIRED", "CANCELLED": "CANCELLED", "DEAD_LETTER": "DEAD_LETTER",
}
_TERMINAL = {"RESOLVED", "FAILED", "EXPIRED", "CANCELLED", "DEAD_LETTER"}
_LIMIT_BYTES = 32 * 1024 * 1024


def _time(raw: Any) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return stamp.astimezone(timezone.utc) if stamp.tzinfo else None
    except (TypeError, ValueError):
        return None


def _read(path: Path, *, jsonl: bool = False) -> tuple[Any, str | None]:
    try:
        with path.open("rb") as handle:
            raw = handle.read(_LIMIT_BYTES + 1)
        if len(raw) > _LIMIT_BYTES:
            return None, "Source exceeds the read limit; a writer projection is needed."
        text = raw.decode("utf-8")
        data = [json.loads(line) for line in text.splitlines() if line.strip()] if jsonl else json.loads(text)
        if jsonl and any(not isinstance(row, dict) for row in data):
            return None, "Challenge history contains a malformed record."
        if not jsonl and not isinstance(data, dict):
            return None, "Lineage snapshot is not an object."
        return data, None
    except FileNotFoundError:
        return None, "Source has not been produced."
    except (OSError, UnicodeError, ValueError):
        return None, "Source could not be read or validated."


def _page(raw: Any, default: int, maximum: int) -> int:
    try:
        return max(1, min(maximum, int(raw)))
    except (TypeError, ValueError, OverflowError):
        return default


def research_authority() -> dict:
    """A policy view, separate from dashboard data. No auto-expiry writer."""
    return {
        "ok": True, "schema": L.SCHEMA, "authority": L.AUTHORITY,
        "mutation": False, "financial_action": False,
        "auto_expire": {"enabled": False, "days": None, "editable": False,
                        "reason": "Operator decision pending: choose an expiry age before enabling a rule."},
        "rules": [
            {"actor": "Operator", "action": "Close with a recorded reason; preserve challenge history."},
            {"actor": "CIO reviewer", "action": "Resolve a started challenge with an evidence artifact."},
            {"actor": "Research lineage page", "action": "Read evidence; never change trading authority."},
        ],
    }


def research_lineage(query: dict | None = None, *, root: Path | None = None,
                     now: datetime | None = None) -> dict:
    """Paged backlog/lineage/completed views and seven-day stream throughput.

Missing or malformed sources yield null totals, never a fabricated empty queue.
Opening age uses the original enqueue, rather than resetting at every claim.
"""
    query = query or {}
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    root = root or L.cio_dir()
    page = _page(query.get("page"), 1, 1_000_000)
    per_page = _page(query.get("per_page"), 50, 50)
    view = str(query.get("view") or "backlog")
    if view not in {"backlog", "lineage", "completed"}:
        view = "backlog"
    events, event_gap = _read(root / "hermes_challenge_queue.jsonl", jsonl=True)
    snap, lineage_gap = _read(root / "intelligence_lineages.json")
    gaps = []
    if event_gap:
        gaps.append({"source": "Challenge history", "reason": event_gap})
    if lineage_gap:
        gaps.append({"source": "Lineage snapshot", "reason": lineage_gap})
    streams: dict[str, dict] = {}
    for event in events or []:
        sid = event.get("stream_id")
        kind = str(event.get("event_type") or "").removeprefix("HERMES_CHALLENGE_")
        if not isinstance(sid, str) or not sid or kind == "GENESIS":
            continue
        if kind not in _EVENT_STATUS:
            event_gap = "Challenge history contains an unknown lifecycle event."
            continue
        if any(not isinstance(event.get(key) or {}, dict) for key in ("metadata", "payload")):
            event_gap = "Challenge history contains malformed evidence."
            continue
        row = streams.setdefault(sid, {"stream_id": sid, "metadata": {}, "payload": {}})
        row["metadata"].update(event.get("metadata") or {})
        row["payload"].update(event.get("payload") or {})
        if kind == "ENQUEUED":
            row.setdefault("opened_at", event.get("occurred_at"))
        row.update(status=_EVENT_STATUS[kind], updated_at=event.get("occurred_at"))
    if event_gap and not any(gap["source"] == "Challenge history" for gap in gaps):
        gaps.append({"source": "Challenge history", "reason": event_gap})
    window_start = now - timedelta(days=7)
    opened = closed = 0
    pending = []
    completed = []
    ages = []
    reasons: Counter[str] = Counter()
    for row in streams.values():
        payload, meta = row.pop("payload"), row.pop("metadata")
        opened_at, updated_at = _time(row.get("opened_at")), _time(row.get("updated_at"))
        opened += int(opened_at is not None and window_start <= opened_at <= now)
        is_closed = row.get("status") in _TERMINAL
        closed += int(is_closed and updated_at is not None and window_start <= updated_at <= now)
        symbols = meta.get("symbols") or payload.get("symbols") or []
        if isinstance(symbols, str):
            symbols = [symbols]
        row.update(symbols=symbols, challenge_type=payload.get("challenge_type"),
                   description=payload.get("description"), research_id=meta.get("research_id"),
                   plan_id=meta.get("plan_id"), reviewer=payload.get("claimed_by"),
                   age_hours=round((now - opened_at).total_seconds() / 3600, 2)
                   if opened_at and opened_at <= now else None)
        if is_closed:
            row["resolution_reason"] = (payload.get("resolution_note") or payload.get("failure_reason")
                                        or payload.get("cancellation_reason") or payload.get("reason"))
            completed.append(row)
            continue
        if not opened_at or opened_at > now:
            reason = "Opening time is missing or invalid."
        elif not payload.get("source") and not payload.get("evidence_refs"):
            reason = "No source evidence is recorded."
        elif row.get("status") in {"PENDING", "RELEASED"}:
            reason = "No reviewer has claimed this challenge."
        elif row.get("status") == "CLAIMED":
            reason = "Claimed by a reviewer; no start is recorded."
        else:
            reason = "Research started; no result is recorded."
        row["stuck_reason"] = reason
        reasons[reason] += 1
        if row["age_hours"] is not None:
            ages.append(row["age_hours"])
        pending.append(row)
    ages.sort()
    pending.sort(key=lambda row: (row["age_hours"] is not None, row["age_hours"] or 0), reverse=True)
    completed.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    lineages = (snap or {}).get("lineages")
    if not isinstance(lineages, list) or any(not isinstance(row, dict) for row in lineages):
        lineages = []
        if not lineage_gap:
            lineage_gap = "Lineage snapshot has no valid lineage list."
            gaps.append({"source": "Lineage snapshot", "reason": lineage_gap})
    # The snapshot's transition/evidence arrays can be megabytes. Lists expose
    # only their table fields; the existing lineage/<id> route owns the detail.
    lineages = [{
        "lineage_id": row.get("lineage_id"), "symbol": row.get("symbol"),
        "status": row.get("status"), "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "research_request_count": len(row["research_request_ids"])
        if isinstance(row.get("research_request_ids"), list) else None,
        "memory_count": len(row["memory_ids"]) if isinstance(row.get("memory_ids"), list) else None,
        "cio_case_id": row.get("cio_case_id"), "outcome_id": row.get("outcome_id"),
        "decision_id": row.get("decision_id"),
        "decision_changed": row["advisory_use"].get("what_changed_material")
        if isinstance(row.get("advisory_use"), dict) else None,
    } for row in lineages]
    rows = {"backlog": pending, "completed": completed, "lineage": lineages}[view]
    unavailable = lineage_gap if view == "lineage" else event_gap
    start = (page - 1) * per_page
    def percentile(p: float):
        return ages[max(0, math.ceil(p * len(ages)) - 1)] if ages else None
    return {
        "ok": unavailable is None, "schema": L.SCHEMA, "authority": L.AUTHORITY,
        "mutation": False, "financial_action": False, "as_of": now.isoformat(),
        "snapshot_as_of": (snap or {}).get("generated_at"),
        "view": view, "page": page, "per_page": per_page,
        "total": None if unavailable else len(rows),
        "items": [] if unavailable else rows[start:start + per_page],
        "has_more": False if unavailable else start + per_page < len(rows),
        "backlog": {"pending": None if event_gap else len(pending),
                    "oldest_age_hours": max(ages) if ages and not event_gap else None,
                    "median_age_hours": percentile(.5) if not event_gap else None,
                    "p95_age_hours": percentile(.95) if not event_gap else None,
                    "by_reason": dict(reasons) if not event_gap else {}},
        "throughput": {"window_start": window_start.isoformat(), "window_end": now.isoformat(),
                       "opened": None if event_gap else opened, "closed": None if event_gap else closed,
                       "net_change": None if event_gap else opened - closed},
        "auto_expire": research_authority()["auto_expire"], "gaps": gaps,
    }
