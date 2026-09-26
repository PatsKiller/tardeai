#!/usr/bin/env python3
"""Event → effect latency by trigger class, read-only, from the CIO stores.

Joins `cio_events.jsonl` (event `timestamp`) to `cio_wake_jobs.jsonl` streams
whose `trigger_ref` is the event id (EVENT_BUS wakes), and reports per event
type: events seen, events that produced a wake, minutes from event to
enqueue / claim / dispatch / completion (p50, p90, p95, max), and the share of
events whose FIRST effect (dispatch, or enqueue when never dispatched) landed
within an objective (default 10 minutes).

The objective is measured, not enforced: making it an SLA or changing the
cron cadence is an operator decision (AGENTS.md §17). Authority READ_ONLY.

Usage:
  python scripts/report_event_effect_latency.py --root ~/trade-ai-releases/persistent-state --hours 24 --json
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = "EventEffectLatency@v1"
NO_CONSUMER_REASON = (
    "operator latency report; stdout/JSON is the consumer until the served-runtime "
    "maturity digest imports it"
)
DEFAULT_OBJECTIVE_MIN = 10.0


def _parse(ts: Any) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iter_jsonl(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    vals = sorted(values)
    k = max(0, min(len(vals) - 1, int(round(q * (len(vals) - 1)))))
    return round(vals[k], 2)


def measure(root: Path, *, hours: float = 24.0, now: datetime | None = None,
            objective_min: float = DEFAULT_OBJECTIVE_MIN) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    cio = root / "data" / "cio"

    events: dict[str, dict[str, Any]] = {}
    for row in _iter_jsonl(cio / "cio_events.jsonl") or ():
        et = row.get("event_type")
        if not et or et == "CIO_EVENT_BUS_GENESIS":
            continue
        ts = _parse(row.get("timestamp"))
        if ts is None or ts < since:
            continue
        events[str(row.get("event_id"))] = {"type": str(et), "ts": ts}

    # Fold wake streams keyed by trigger_ref (event id) — one pass.
    streams: dict[str, dict[str, Any]] = defaultdict(dict)
    for row in _iter_jsonl(cio / "cio_wake_jobs.jsonl") or ():
        sid = row.get("stream_id")
        et = row.get("event_type")
        pl = row.get("payload") or {}
        if not sid or not et:
            continue
        st = streams[str(sid)]
        if et == "CIO_WAKE_ENQUEUED":
            st["trigger_ref"] = pl.get("trigger_ref")
            st["trigger_type"] = pl.get("trigger_type")
            st["created_at"] = _parse(pl.get("created_at"))
            st["correlation_id"] = (pl.get("context") or {}).get("correlation_id")
        elif et == "CIO_WAKE_CLAIMED":
            st.setdefault("claimed_at", _parse(pl.get("claimed_at") or row.get("occurred_at")))
        elif et == "CIO_WAKE_DISPATCHED":
            st.setdefault("dispatched_at", _parse(pl.get("dispatched_at") or row.get("occurred_at")))
        elif et == "CIO_WAKE_COMPLETED":
            st.setdefault("completed_at", _parse(pl.get("completed_at") or row.get("occurred_at")))
        elif et == "CIO_WAKE_EXPIRED":
            st["expired_reason"] = pl.get("reason")

    by_event: dict[str, dict[str, Any]] = {}
    for sid, st in streams.items():
        ref = str(st.get("trigger_ref") or st.get("correlation_id") or "")
        if ref in events:
            # Keep the earliest wake per event (duplicates are a defect, counted separately).
            prev = by_event.get(ref)
            if prev is None or (st.get("created_at") and prev.get("created_at") and st["created_at"] < prev["created_at"]):
                by_event[ref] = {**st, "wake_job_id": sid}
            events[ref]["wakes"] = events[ref].get("wakes", 0) + 1

    per_type: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for eid, ev in events.items():
        t = ev["type"]
        counts[t]["events"] += 1
        wk = by_event.get(eid)
        if not wk:
            continue
        counts[t]["with_wake"] += 1
        if ev.get("wakes", 0) > 1:
            counts[t]["duplicate_wakes"] += ev["wakes"] - 1
        base = ev["ts"]
        first_effect = None
        for key in ("created_at", "claimed_at", "dispatched_at", "completed_at"):
            ts = wk.get(key)
            if ts is not None:
                mins = (ts - base).total_seconds() / 60.0
                per_type[t][key].append(mins)
                if key in ("created_at", "dispatched_at"):
                    first_effect = mins if key == "dispatched_at" or first_effect is None else first_effect
        if wk.get("dispatched_at") is not None:
            counts[t]["dispatched"] += 1
            eff = (wk["dispatched_at"] - base).total_seconds() / 60.0
        else:
            eff = (wk["created_at"] - base).total_seconds() / 60.0 if wk.get("created_at") else None
        if eff is not None and eff <= objective_min:
            counts[t]["within_objective"] += 1
        if wk.get("expired_reason"):
            counts[t]["expired"] += 1

    report_types: dict[str, Any] = {}
    all_first: list[float] = []
    for t in sorted(counts):
        c = counts[t]
        stages = {}
        for key, label in (("created_at", "enqueue"), ("claimed_at", "claim"),
                            ("dispatched_at", "dispatch"), ("completed_at", "complete")):
            vals = per_type[t].get(key) or []
            stages[label] = {
                "n": len(vals),
                "p50_min": _pct(vals, 0.5), "p90_min": _pct(vals, 0.9),
                "p95_min": _pct(vals, 0.95),
                "max_min": round(max(vals), 2) if vals else None,
                "mean_min": round(statistics.fmean(vals), 2) if vals else None,
            }
        first = per_type[t].get("dispatched_at") or per_type[t].get("created_at") or []
        all_first.extend(first)
        report_types[t] = {
            "events": c["events"], "with_wake": c["with_wake"], "dispatched": c["dispatched"],
            "expired": c["expired"], "duplicate_wakes": c["duplicate_wakes"],
            "within_objective": c["within_objective"],
            "within_objective_share": (round(c["within_objective"] / c["with_wake"], 3)
                                       if c["with_wake"] else None),
            "stages": stages,
        }
    return {
        "schema": SCHEMA,
        "authority": "READ_ONLY_ADVISORY",
        "as_of": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": str(root),
        "window_hours": hours,
        "objective_min": objective_min,
        "objective_status": "MEASURED_NOT_ENFORCED (operator decision to make it an SLA)",
        "events_in_window": len(events),
        "events_with_wake": len(by_event),
        "first_effect_p95_min_all": _pct(all_first, 0.95),
        "first_effect_p50_min_all": _pct(all_first, 0.5),
        "by_event_type": report_types,
        "no_consumer_reason": NO_CONSUMER_REASON,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=str(Path.home() / "trade-ai-releases" / "persistent-state"))
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--objective-min", type=float, default=DEFAULT_OBJECTIVE_MIN)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rep = measure(Path(args.root).expanduser(), hours=args.hours, objective_min=args.objective_min)
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
        return 0
    print(f"Event→effect latency as_of={rep['as_of']} window={rep['window_hours']}h "
          f"events={rep['events_in_window']} with_wake={rep['events_with_wake']} "
          f"first_effect p50={rep['first_effect_p50_min_all']}m p95={rep['first_effect_p95_min_all']}m "
          f"objective={rep['objective_min']}m ({rep['objective_status']})")
    for t, r in rep["by_event_type"].items():
        d = r["stages"]["dispatch"]; e = r["stages"]["enqueue"]
        print(f"  {t:<28} events={r['events']:<4} wake={r['with_wake']:<4} disp={r['dispatched']:<4} "
              f"exp={r['expired']:<3} dup={r['duplicate_wakes']:<3} "
              f"enq p50/p95={e['p50_min']}/{e['p95_min']}m disp p50/p95={d['p50_min']}/{d['p95_min']}m "
              f"≤obj={r['within_objective_share']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
