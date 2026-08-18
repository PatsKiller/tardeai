"""HermesQueueHealth@v1 — latest-per-stream classification. Never deletes."""
from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from lib.intelligence_lineage import (
        _challenge_symbols,
        _parse_ts,
        _read_jsonl,
        challenge_latest,
        challenge_pending,
        cio_dir,
    )
except ImportError:
    from scripts.lib.intelligence_lineage import (  # type: ignore
        _challenge_symbols,
        _parse_ts,
        _read_jsonl,
        challenge_latest,
        challenge_pending,
        cio_dir,
    )

AUTHORITY = "READ_ONLY_ADVISORY"


def _classify(rec: dict[str, Any], *, now: datetime, max_age_days: int = 7) -> str:
    syms = _challenge_symbols(rec)
    if any("TEST" in s or s in {"SPACEX", "SPACEX_TEST"} for s in syms):
        return "fixture_test"
    if not syms:
        md = rec.get("metadata") or {}
        if md.get("plan_id") or md.get("research_id"):
            return "missing_symbol"
        return "missing_parent"
    if any(not s.replace(".", "").isalnum() or len(s) > 8 for s in syms):
        return "invalid_symbol"
    ts = _parse_ts(rec.get("occurred_at"))
    if ts and (now - ts).days > max_age_days:
        return "stale"
    pl = rec.get("payload") or {}
    desc = str(pl.get("description") or "")
    if "Material CIO situation" in desc:
        return "legitimate_current"
    return "legitimate_current"


def build(*, max_age_days: int = 7) -> dict[str, Any]:
    path = cio_dir() / "hermes_challenge_queue.jsonl"
    rows = _read_jsonl(path)
    latest = challenge_latest(rows)
    pending = challenge_pending(latest)
    now = datetime.now(timezone.utc)
    ages = []
    reasons: Counter[str] = Counter()
    items = []
    for rec in pending:
        reason = _classify(rec, now=now, max_age_days=max_age_days)
        reasons[reason] += 1
        ts = _parse_ts(rec.get("occurred_at"))
        age_h = ((now - ts).total_seconds() / 3600.0) if ts else None
        if age_h is not None:
            ages.append(age_h)
        items.append({
            "stream_id": rec.get("stream_id"),
            "symbols": _challenge_symbols(rec),
            "reason": reason,
            "occurred_at": rec.get("occurred_at"),
            "age_hours": round(age_h, 2) if age_h is not None else None,
            "challenge_type": (rec.get("payload") or {}).get("challenge_type"),
            "plan_id": (rec.get("metadata") or {}).get("plan_id"),
            "research_id": (rec.get("metadata") or {}).get("research_id"),
        })
    ages_sorted = sorted(ages)
    def pct(p: float) -> float | None:
        if not ages_sorted:
            return None
        i = min(len(ages_sorted) - 1, max(0, int(round((p / 100.0) * (len(ages_sorted) - 1)))))
        return round(ages_sorted[i], 2)
    return {
        "schema": "HermesQueueHealth@v1",
        "authority": AUTHORITY,
        "pending": len(pending),
        "events": len(rows),
        "unique_streams": len([k for k in latest if k != "hermes_challenge_queue"]),
        "oldest_age_hours": round(max(ages), 2) if ages else None,
        "median_age_hours": pct(50),
        "p95_age_hours": pct(95),
        "by_reason": dict(reasons),
        "history_preserved": True,
        "deleted": 0,
        "items": items[:80],
        "cio_dir": str(cio_dir()),
    }
