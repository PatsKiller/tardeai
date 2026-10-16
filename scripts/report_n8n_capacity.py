#!/usr/bin/env python3
"""report_n8n_capacity.py — READ-ONLY: n8n executor load per lane over a window, dry and live kept apart.

Operator 2026-10-16 (process consolidation): "Report dry/live worker time as well as execution counts. Measure queue
wait and runtime before changing worker capacity." This tool measures; it changes nothing (no worker count, no
retry timeout, no registry row). Companion of scripts/report_n8n_dry_run_load.py (PR #1822: one day, dry-run
buckets); this one covers a window of N days and adds queue wait, worker-seconds and executor concurrency.

Input: the executor's RunReceipt files ``$STATE_ROOT/data/runtime/n8n_runs/*.json`` (every receipt that carries
``lane_id``, ``mode``, ``started_at`` and ``finished_at``: dispatcher ``d:``, event ``e:``, fabric ``f:``/``p:`` and
n8n-execution ``n8n-wf-*`` keys alike). A receipt is in the window when its ``started_at`` is.

Per lane and mode: runs, states, worker-seconds (sum of ``duration_s``, subprocess wall time), queue_wait_s and
duration_s p50 / p95 / max, and the trigger mix (``schedule`` d:, ``event`` e:, ``fabric`` f:/p:, ``n8n`` other).

Executor: the distinct ``worker_id`` slots seen (``host:pid:w<n>`` -> w<n>), the busy-interval sweep over
[started_at, finished_at] giving peak concurrency, the share of the window with k workers busy, and the share at
saturation (busy == observed slots). Queue wait is the saturation signal that matters: a run that waits longer than
``--queue-alarm-s`` (default 30 s, 15x the executor poll_s 2) waited for a worker, not for the poll.

Usage: report_n8n_capacity.py [--days 7] [--now ISO] [--state-root DIR] [--registry PATH] [--lanes N] [--json]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
RUNS_REL = Path("data") / "runtime" / "n8n_runs"
SCHEMA = "N8nCapacityReport@v1"
MODES = ("dry_run", "live")


def parse_ts(v: Any) -> Optional[datetime]:
    if not isinstance(v, str) or not v:
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def pct(values: list[float], q: float) -> Optional[float]:
    """Nearest-rank percentile (q in 0..100); None for an empty list."""
    if not values:
        return None
    s = sorted(values)
    k = max(1, math.ceil(q / 100.0 * len(s)))
    return round(s[k - 1], 3)


def trigger_of(run_id: str) -> str:
    head = run_id.split(":", 1)[0] if ":" in run_id else ""
    return {"d": "schedule", "e": "event", "f": "fabric", "p": "fabric"}.get(head, "n8n")


def worker_slot(worker_id: Any) -> Optional[str]:
    if not isinstance(worker_id, str) or not worker_id:
        return None
    return worker_id.rsplit(":", 1)[-1]


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def normalize(rec: Mapping[str, Any], name: str = "") -> Optional[dict]:
    lane = rec.get("lane_id")
    mode = rec.get("mode")
    start = parse_ts(rec.get("started_at"))
    end = parse_ts(rec.get("finished_at"))
    if not isinstance(lane, str) or mode not in MODES or start is None:
        return None
    if end is None or end < start:
        dur = _num(rec.get("duration_s"))
        end = start + timedelta(seconds=dur) if dur is not None else start
    run_id = str(rec.get("run_id") or (name[:-5] if name.endswith(".json") else name))
    return {"lane_id": lane, "mode": mode, "state": str(rec.get("state") or "?"), "start": start, "end": end,
            "duration_s": _num(rec.get("duration_s")), "queue_wait_s": _num(rec.get("queue_wait_s")),
            "trigger": trigger_of(run_id), "slot": worker_slot(rec.get("worker_id")),
            "output_verdict": (rec.get("output_verdict") or {}).get("verdict")
            if isinstance(rec.get("output_verdict"), Mapping) else None}


def concurrency(runs: list[dict], lo: datetime, hi: datetime, slots: int) -> dict[str, Any]:
    """Busy-interval sweep clipped to [lo, hi]: peak, seconds per busy level, saturation share."""
    events: list[tuple[datetime, int]] = []
    for r in runs:
        s, e = max(r["start"], lo), min(r["end"], hi)
        if e > s:
            events += [(s, 1), (e, -1)]
    events.sort(key=lambda x: (x[0], x[1]))
    level, peak, prev = 0, 0, lo
    at_level: dict[int, float] = defaultdict(float)
    for t, d in events:
        at_level[level] += (t - prev).total_seconds()
        level += d
        peak = max(peak, level)
        prev = t
    at_level[level] += (hi - prev).total_seconds()
    total = (hi - lo).total_seconds() or 1.0
    busy_s = sum(k * v for k, v in at_level.items())
    sat = sum(v for k, v in at_level.items() if slots and k >= slots)
    return {"peak_concurrency": peak, "observed_worker_slots": slots,
            "mean_busy_workers": round(busy_s / total, 4),
            "utilization": round(busy_s / (total * slots), 4) if slots else None,
            "share_by_busy_workers": {str(k): round(v / total, 5) for k, v in sorted(at_level.items()) if v > 0},
            "saturated_share": round(sat / total, 6), "saturated_s": round(sat, 1)}


def summarize(records: Iterable[Mapping[str, Any]], now: datetime, days: float,
              stages: Optional[Mapping[str, tuple]] = None, queue_alarm_s: float = 30.0) -> dict[str, Any]:
    """Pure. ``records`` = normalized runs (see ``normalize``); ``stages`` lane -> (registry mode, stage)."""
    lo = now - timedelta(days=days)
    runs = [r for r in records if lo <= r["start"] <= now]
    stages = stages or {}
    lanes: dict[str, dict[str, Any]] = {}
    for r in runs:
        lane = lanes.setdefault(r["lane_id"], {m: [] for m in MODES})
        lane[r["mode"]].append(r)
    rows = []
    for lane_id, by_mode in lanes.items():
        row: dict[str, Any] = {"lane_id": lane_id}
        mode, stage = (stages.get(lane_id) or (None, None))
        row["registry_mode"], row["stage"] = mode, stage
        for m in MODES:
            rs = by_mode[m]
            durs = [r["duration_s"] for r in rs if r["duration_s"] is not None]
            waits = [r["queue_wait_s"] for r in rs if r["queue_wait_s"] is not None]
            states: dict[str, int] = defaultdict(int)
            trig: dict[str, int] = defaultdict(int)
            for r in rs:
                states[r["state"]] += 1
                trig[r["trigger"]] += 1
            row[m] = {"runs": len(rs), "worker_s": round(sum(durs), 1),
                      "duration_s": {"p50": pct(durs, 50), "p95": pct(durs, 95), "max": max(durs) if durs else None},
                      "queue_wait_s": {"p50": pct(waits, 50), "p95": pct(waits, 95),
                                       "max": max(waits) if waits else None},
                      "queue_wait_over_alarm": sum(1 for w in waits if w > queue_alarm_s),
                      "states": dict(states), "triggers": dict(trig)}
        rows.append(row)
    rows.sort(key=lambda r: (-(r["dry_run"]["worker_s"] + r["live"]["worker_s"]), r["lane_id"]))
    slots = sorted({r["slot"] for r in runs if r["slot"]})
    totals = {}
    for m in MODES:
        rs = [r for r in runs if r["mode"] == m]
        durs = [r["duration_s"] for r in rs if r["duration_s"] is not None]
        waits = [r["queue_wait_s"] for r in rs if r["queue_wait_s"] is not None]
        totals[m] = {"runs": len(rs), "worker_s": round(sum(durs), 1), "lanes": sum(1 for x in rows if x[m]["runs"]),
                     "duration_s": {"p50": pct(durs, 50), "p95": pct(durs, 95), "max": max(durs) if durs else None},
                     "queue_wait_s": {"p50": pct(waits, 50), "p95": pct(waits, 95),
                                      "max": max(waits) if waits else None},
                     "queue_wait_over_alarm": sum(1 for w in waits if w > queue_alarm_s)}
    by_stage: dict[str, dict[str, Any]] = defaultdict(lambda: {"lanes": 0, "dry_runs": 0, "dry_worker_s": 0.0,
                                                               "live_runs": 0, "live_worker_s": 0.0})
    for x in rows:
        b = by_stage[str(x["stage"])]
        b["lanes"] += 1
        b["dry_runs"] += x["dry_run"]["runs"]
        b["dry_worker_s"] = round(b["dry_worker_s"] + x["dry_run"]["worker_s"], 1)
        b["live_runs"] += x["live"]["runs"]
        b["live_worker_s"] = round(b["live_worker_s"] + x["live"]["worker_s"], 1)
    return {"schema": SCHEMA, "window": {"from": lo.isoformat(), "to": now.isoformat(), "days": days},
            "queue_alarm_s": queue_alarm_s, "runs": len(runs), "totals": totals, "by_stage": dict(by_stage),
            "executor": concurrency(runs, lo, now, len(slots)) | {"worker_slots": slots},
            "lanes": rows}


def load_records(runs_dir: Path) -> list[dict]:
    out = []
    for name in sorted(os.listdir(runs_dir)):
        if not name.endswith(".json"):
            continue
        try:
            rec = json.loads((runs_dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict):
            n = normalize(rec, name)
            if n is not None:
                out.append(n)
    return out


def registry_stages(registry: Mapping[str, Any]) -> dict[str, tuple]:
    out = {}
    for row in registry.get("lanes") or []:
        if isinstance(row, dict) and row.get("lane_id"):
            d = row.get("dispatch") if isinstance(row.get("dispatch"), dict) else {}
            s = row.get("scheduler") if isinstance(row.get("scheduler"), dict) else {}
            out[str(row["lane_id"])] = (d.get("mode"), s.get("stage"))
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--now", default=None, help="ISO timestamp (default: now, UTC)")
    ap.add_argument("--state-root", default=os.environ.get("TRADEAI_STATE_ROOT")
                    or str(Path.home() / "trade-ai-releases" / "persistent-state"))
    ap.add_argument("--registry", default=str(ROOT / "config" / "lane_registry.json"))
    ap.add_argument("--queue-alarm-s", type=float, default=30.0)
    ap.add_argument("--lanes", type=int, default=25, help="per-lane rows to print (0 = all)")
    args = ap.parse_args(argv)
    now = parse_ts(args.now) if args.now else datetime.now(timezone.utc)
    if now is None:
        ap.error("--now must be an ISO timestamp")
    runs_dir = Path(args.state_root) / RUNS_REL
    if not runs_dir.is_dir():
        print(json.dumps({"ok": False, "reason": "runs_dir_missing", "path": str(runs_dir)}))
        return 2
    try:
        stages = registry_stages(json.loads(Path(args.registry).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        stages = {}
    out = summarize(load_records(runs_dir), now, args.days, stages, args.queue_alarm_s)
    if args.lanes:
        out["lanes"] = out["lanes"][: args.lanes]
    print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
