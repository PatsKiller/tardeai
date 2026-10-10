"""Derived lesson counters for the advisory KB (2026-10-09).

Before this change every ``record_application`` / ``record_hit`` re-appended the
whole lesson row (with its 768/4096-float embedding) to
``advisory_kb_lessons.jsonl`` just to bump ``applications`` / ``hits`` /
``scored`` / ``citations``: ~110 rows and ~8 MB a day, and two concurrent
writers could both read N and both write N+1 (lost increment).

Now the lesson log holds *content* rows only (propose → ratify / retire), each
carrying a counter **baseline** (the counters as of that row), and every
application or hit is one small event in ``advisory_kb_lesson_applications.jsonl``
marked ``counter_v``. A reader's counters are::

    baseline (latest content row) + marked events with ts > that row's ts

which is exactly what the old writer would have stored, including its
semantics that a re-ratification from a candidate resets the counters (the
candidate row's zeros become the new baseline) while a retire carries them.

Legacy rows (the ~4.4k already on disk) are content rows whose baseline already
includes every legacy (unmarked) event, so unmarked events are never counted
again. This module is stdlib-only so readers outside the advisory package
(``maturity_control.lessons``) can share it without importing the advisory package.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

COUNTER_EVENT_KEY = "counter_v"
COUNTER_EVENT_VERSION = 2


def parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def is_counter_event(row: dict[str, Any]) -> bool:
    return row.get(COUNTER_EVENT_KEY) == COUNTER_EVENT_VERSION and bool(row.get("lesson_id"))


def counter_events_by_lesson(path: Path) -> dict[str, list[dict[str, Any]]]:
    """Marked counter events grouped by lesson id (streamed; unmarked rows skipped)."""
    out: dict[str, list[dict[str, Any]]] = {}
    if not path.is_file():
        return out
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if COUNTER_EVENT_KEY not in line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and is_counter_event(row):
                out.setdefault(str(row["lesson_id"]), []).append(row)
    return out


def base_counts(row: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        int(row.get("applications") or 0),
        int(row.get("hits") or 0),
        int(row.get("scored") or 0),
        int(row.get("citations") or 0),
    )


def hit_rate(hits: int, scored: int) -> float | None:
    return (hits / scored) if scored else None


def apply_events(row: dict[str, Any], events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Counters of ``row`` plus the marked events written after it.

    Returns ``row`` unchanged (same object) when no event applies, so legacy
    data reads byte-identically to the old latest-row-wins reader.
    """
    base_ts = parse_ts(row.get("ts"))
    applied: list[tuple[datetime, dict[str, Any]]] = []
    for ev in events:
        ets = parse_ts(ev.get("ts"))
        if ets is None:
            continue
        if base_ts is None or ets > base_ts:
            applied.append((ets, ev))
    if not applied:
        return row
    applied.sort(key=lambda x: x[0])
    apps, hits, scored, citations = base_counts(row)
    for _, ev in applied:
        kind = ev.get("kind", "application")
        hit = ev.get("hit")
        if kind == "application":
            apps += 1
            citations += 1 if ev.get("cited") else 0
            if hit is not None:
                scored += 1
                hits += 1 if hit else 0
        elif kind == "hit":
            scored += 1
            hits += 1 if hit else 0
    out = dict(row)
    out.update({
        "applications": apps,
        "hits": hits,
        "scored": scored,
        "hit_rate": hit_rate(hits, scored),
        "citations": citations,
        "ts": applied[-1][1].get("ts"),
        "status": row.get("status") or "ratified",
    })
    return out


def apply_counter_events(rows: Iterable[dict[str, Any]], applications_path: Path,
                         *, key: str = "id") -> list[dict[str, Any]]:
    """Latest-by-id rows → rows with derived counters (order preserved)."""
    rows = list(rows)
    events = counter_events_by_lesson(applications_path)
    if not events:
        return rows
    out = []
    for r in rows:
        lid = str(r.get(key) or r.get("lesson_id") or "")
        out.append(apply_events(r, events.get(lid, ())) if lid in events else r)
    return out
