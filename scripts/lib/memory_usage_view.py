"""Memory usage view for the Command Center Memory panel (LQ-20261107-1819).

The panel badge "retrievals N" used to read ``memory_shadow_runs.jsonl`` -- the
output of the governed comparator ``compare_memory_shadow``, which has no
production caller (its newest record is a 2026-08-18 test run). Real retrieval
use is written elsewhere: ``memory_consumption_receipts.jsonl`` (one receipt per
consumer retrieval that returned ids) and ``retrieval_receipts.jsonl`` (the
intelligence_client ladder). This module reads those, bounded, and labels each
number with its source so the badge cannot contradict the store.

READ_ONLY_ADVISORY. Never calls a provider, never writes.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scripts.lib.jsonl_bounded import tail_jsonl_lines

MAX_ROWS = 20000


def _parse(ts: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _rows(path: Path, stamp: str, since: datetime):
    out = []
    for line in tail_jsonl_lines(path, MAX_ROWS):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = _parse(r.get(stamp))
        if t is not None and t >= since:
            out.append(r)
    return out


def usage_window(cio_dir: Path | str, *, hours: int = 24, now: datetime | None = None) -> dict[str, Any]:
    cio = Path(cio_dir)
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    cons = _rows(cio / "memory_consumption_receipts.jsonl", "consumed_at", since)
    rr = _rows(cio / "retrieval_receipts.jsonl", "created_at", since)
    by_consumer: dict[str, int] = {}
    ids: set[str] = set()
    for r in cons:
        by_consumer[str(r.get("consumer"))] = by_consumer.get(str(r.get("consumer")), 0) + 1
        for k in ("memory_ids_supporting", "memory_ids_counter"):
            ids.update(str(i) for i in (r.get(k) or []))
    decisions: dict[str, int] = {}
    used = 0
    for r in rr:
        decisions[str(r.get("decision"))] = decisions.get(str(r.get("decision")), 0) + 1
        used += len((r.get("evidence_stages") or {}).get("used_refs") or [])
    return {
        "window_hours": hours,
        "as_of": now.replace(microsecond=0).isoformat(),
        "source": "memory_consumption_receipts.jsonl + retrieval_receipts.jsonl",
        "consumption_receipts": len(cons),
        "by_consumer": by_consumer,
        "distinct_memory_ids": len(ids),
        "ladder_receipts": len(rr),
        "ladder_decisions": decisions,
        "ladder_used_refs": used,
        "bounded_rows_cap": MAX_ROWS,
        "memory_behavior_influence": "0",
    }
