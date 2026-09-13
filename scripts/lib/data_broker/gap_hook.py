"""Projection-side gap hook — a projection that finds itself STALE may say so.

A projection answers a page load. It must never block that load on a producer,
a search or a model, so this hook does exactly one thing: it appends the gap to
``data/cio/gap_queue.jsonl`` and returns. Nothing here resolves anything.
``scripts/check_gap_resolution.py`` reads the queue and reports a gap that has
sat there more than two hours with no receipt against it, which is the signal
that the resolver is not being run for projection gaps (today it is run only
from the operator desk).

Dedupe: the same gap (domain, subject, question) is enqueued at most once per
``DEDUPE_HOURS``; a page that renders every 30 seconds does not write a row
every 30 seconds.

READ_ONLY_ADVISORY. No broker, order, stop or 2FA authority. No DB write.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.gap_resolver import DataGap  # the one spelling production code uses

PROJECT_ROOT = Path(__file__).resolve().parents[3]
AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "GapQueueEntry@v1"
QUEUE_PATH = PROJECT_ROOT / "data" / "cio" / "gap_queue.jsonl"
DEDUPE_HOURS = 1.0


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def read_queue(path: Optional[Path] = None) -> list[dict[str, Any]]:
    p = path or QUEUE_PATH
    if not p.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    return rows


def enqueue_gap(
    domain: str,
    subject: str,
    question: str,
    *,
    why: str = "stale_hours",
    requester: str = "projection",
    stale_age_hours: Optional[float] = None,
    path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Record the gap and return immediately. Never raises, never blocks."""
    p = path or QUEUE_PATH
    ts = now or _now()
    gap = DataGap(domain=domain, subject=subject, question=question, why=why,
                  requester=requester, stale_age_hours=stale_age_hours)
    try:
        for row in reversed(read_queue(p)):
            if row.get("gap_id") != gap.gap_id:
                continue
            try:
                prev = datetime.fromisoformat(str(row.get("ts")).replace("Z", "+00:00"))
                if prev.tzinfo is None:
                    prev = prev.replace(tzinfo=timezone.utc)
            except Exception:
                break
            if (ts - prev).total_seconds() < DEDUPE_HOURS * 3600:
                return {"ok": True, "enqueued": False, "reason": "deduped", "gap_id": gap.gap_id}
            break
        row = {
            "schema": SCHEMA,
            "authority": AUTHORITY,
            "ts": ts.isoformat(),
            "gap_id": gap.gap_id,
            "domain": gap.domain,
            "subject": gap.subject,
            "question": gap.question[:300],
            "why": gap.why,
            "requester": gap.requester,
            "stale_age_hours": gap.stale_age_hours,
            "status": "open",
        }
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        return {"ok": True, "enqueued": True, "gap_id": gap.gap_id}
    except Exception as exc:  # noqa: BLE001 -- a page load must never fail on bookkeeping
        return {"ok": False, "enqueued": False, "reason": f"{type(exc).__name__}:{exc}", "gap_id": gap.gap_id}


__all__ = ["SCHEMA", "QUEUE_PATH", "DEDUPE_HOURS", "enqueue_gap", "read_queue"]
