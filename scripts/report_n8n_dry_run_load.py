#!/usr/bin/env python3
"""report_n8n_dry_run_load.py — READ-ONLY: where the n8n executor's dry-run capacity goes, per lane, for one day.

Reads the executor's run receipts (``$TRADEAI_STATE_ROOT/data/runtime/n8n_runs/<run_id>.json``, run ids
``d|e:<lane>:<mode>:<YYYYMMDDTHHMM>[:a<n>]``) and the lane registry (``config/lane_registry.json``). Writes nothing.

Every dry_run receipt whose slot falls on ``--day`` (local slot minute, YYYYMMDD) lands in exactly one bucket:

  * ``dry_after_live``  — the lane already has a live RUN_DONE receipt at or before this slot. This is the
    "live lane still pays for a parallel shadow run" waste. The due computation (scripts/lib/n8n_due.py) emits ONE
    mode per lane per slot, so this bucket should stay at the promotion minute only (the dry slot that ran just
    before the live list was reloaded); tests/test_n8n_dry_run_live_invariant_20261016.py pins that.
  * ``live_not_listed`` — the registry row is ``dispatch.mode: live`` but the slot ran dry_run: the lane is not on
    TRADEAI_N8N_RELAY_LIVE_LANES, so n8n_due downgrades it (reason relay_live_not_enabled). Adding it to the list
    is an operator decision (which lanes go live); this report only counts it.
  * ``shadow``          — the registry row is ``dispatch.mode: dry_run`` (stage shadow). Intended.

Executor-seconds = the receipt's ``duration_s`` (subprocess wall time; queue wait excluded).

Usage: report_n8n_dry_run_load.py [--day YYYYMMDD] [--state-root DIR] [--registry PATH] [--lanes N]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
RUNS_REL = Path("data") / "runtime" / "n8n_runs"
DEFAULT_TZ = "America/New_York"
BUCKETS = ("dry_after_live", "live_not_listed", "shadow")


def parse_run_file(name: str) -> tuple[str, str, str, str] | None:
    """(prefix, lane, mode, slot_local) from a receipt file name, or None for anything else (``*_last.json`` ...)."""
    if not name.endswith(".json"):
        return None
    parts = name[: -len(".json")].split(":")
    if len(parts) < 4 or parts[0] not in ("d", "e") or parts[2] not in ("dry_run", "live"):
        return None
    return parts[0], parts[1], parts[2], parts[3]


def registry_modes(registry: Mapping[str, Any]) -> dict[str, tuple[str | None, str | None]]:
    out: dict[str, tuple[str | None, str | None]] = {}
    for row in registry.get("lanes") or []:
        if not isinstance(row, dict) or not row.get("lane_id"):
            continue
        d = row.get("dispatch") if isinstance(row.get("dispatch"), dict) else {}
        s = row.get("scheduler") if isinstance(row.get("scheduler"), dict) else {}
        out[str(row["lane_id"])] = (d.get("mode"), s.get("stage"))
    return out


def summarize(receipts: Iterable[tuple[str, str, str, str, Mapping[str, Any]]],
              modes: Mapping[str, tuple[str | None, str | None]], day: str) -> dict[str, Any]:
    """Pure. ``receipts`` = (prefix, lane, mode, slot_local, receipt) for every receipt on disk (all days: the
    first live RUN_DONE may predate ``day``)."""
    rows = list(receipts)
    first_live: dict[str, str] = {}
    for _p, lane, mode, slot, rec in rows:
        if mode == "live" and rec.get("state") == "RUN_DONE":
            if lane not in first_live or slot < first_live[lane]:
                first_live[lane] = slot
    lanes: dict[str, dict[str, Any]] = defaultdict(lambda: {"dry": 0, "dry_s": 0.0, "live": 0, "live_s": 0.0,
                                                            "bucket": None})
    for _p, lane, mode, slot, rec in rows:
        if not slot.startswith(day):
            continue
        dur = rec.get("duration_s")
        dur = float(dur) if isinstance(dur, (int, float)) else 0.0
        entry = lanes[lane]
        if mode == "live":
            entry["live"] += 1
            entry["live_s"] += dur
            continue
        entry["dry"] += 1
        entry["dry_s"] += dur
        if lane in first_live and first_live[lane] <= slot:
            bucket = "dry_after_live"
        elif (modes.get(lane) or (None, None))[0] == "live":
            bucket = "live_not_listed"
        else:
            bucket = "shadow"
        entry.setdefault("buckets", defaultdict(int))[bucket] += 1
    totals = {b: {"dry_runs": 0, "executor_s": 0.0, "lanes": 0} for b in BUCKETS}
    per_lane = []
    for lane, e in lanes.items():
        buckets = dict(e.pop("buckets", {}))
        for b, n in buckets.items():
            share = e["dry_s"] * n / e["dry"] if e["dry"] else 0.0
            totals[b]["dry_runs"] += n
            totals[b]["executor_s"] += share
            totals[b]["lanes"] += 1
        mode, stage = modes.get(lane) or (None, None)
        per_lane.append({"lane_id": lane, "registry_mode": mode, "stage": stage, "dry_runs": e["dry"],
                         "dry_executor_s": round(e["dry_s"], 1), "live_runs": e["live"],
                         "live_executor_s": round(e["live_s"], 1), "buckets": buckets})
    per_lane.sort(key=lambda r: (-r["dry_runs"], r["lane_id"]))
    for t in totals.values():
        t["executor_s"] = round(t["executor_s"], 1)
    dry = sum(r["dry_runs"] for r in per_lane)
    live = sum(r["live_runs"] for r in per_lane)
    return {
        "schema": "N8nDryRunLoad@v1", "day": day, "dry_runs": dry, "live_runs": live,
        "dry_share": round(dry / (dry + live), 3) if dry + live else None,
        "dry_executor_s": round(sum(r["dry_executor_s"] for r in per_lane), 1),
        "live_executor_s": round(sum(r["live_executor_s"] for r in per_lane), 1),
        "buckets": totals, "lanes": per_lane,
    }


def load_receipts(runs_dir: Path) -> list[tuple[str, str, str, str, dict]]:
    out = []
    for name in sorted(os.listdir(runs_dir)):
        parsed = parse_run_file(name)
        if parsed is None:
            continue
        try:
            rec = json.loads((runs_dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict):
            out.append((*parsed, rec))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--day", default=datetime.now(ZoneInfo(DEFAULT_TZ)).strftime("%Y%m%d"))
    ap.add_argument("--state-root", default=os.environ.get("TRADEAI_STATE_ROOT")
                    or str(Path.home() / "trade-ai-releases" / "persistent-state"))
    ap.add_argument("--registry", default=str(ROOT / "config" / "lane_registry.json"))
    ap.add_argument("--lanes", type=int, default=15, help="per-lane rows to print (0 = all)")
    args = ap.parse_args(argv)
    if not (len(args.day) == 8 and args.day.isdigit()):
        ap.error("--day must be YYYYMMDD")
    runs_dir = Path(args.state_root) / RUNS_REL
    if not runs_dir.is_dir():
        print(json.dumps({"ok": False, "reason": "runs_dir_missing", "path": str(runs_dir)}))
        return 2
    modes = registry_modes(json.loads(Path(args.registry).read_text(encoding="utf-8")))
    out = summarize(load_receipts(runs_dir), modes, args.day)
    if args.lanes:
        out["lanes"] = out["lanes"][: args.lanes]
    print(json.dumps(out, indent=1, sort_keys=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
