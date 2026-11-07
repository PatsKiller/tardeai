#!/usr/bin/env python3
"""ANCHOR: RUN_QUALITY_20261106 — append one RunQualitySample@v1 per new lane run to data/runtime/run_quality_history.jsonl.

The ONLY writer of that file. It reads each ACTIVE lane's own last-run receipt (read-only) and appends a sample when the
lane's newest receipt run is not the one already recorded, so the jobs-history quality grade can compare a run's item
count and duration with the lane's own history.

Dry-run by default: prints what it would append and writes nothing. ``--apply`` appends under ``--history-root``
(default: the state root). Never touches a broker, credentials or any other store. Not scheduled yet.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import run_quality as Q  # noqa: E402

DEFAULT_STATE_ROOT = Path.home() / "trade-ai-releases/persistent-state"


def last_recorded(path: Path) -> dict[str, str]:
    """lane_id -> run_started_at of its newest recorded sample."""
    out: dict[str, str] = {}
    for row in Q._tail_jsonl(path, Q.HISTORY_TAIL_BYTES):
        if row.get("schema") == Q.HISTORY_SCHEMA and row.get("lane_id"):
            out[str(row["lane_id"])] = str(row.get("run_started_at"))
    return out


def collect(registry: dict, state_root: Path, history_path: Path, *, now: datetime) -> tuple[list[dict], int]:
    seen = last_recorded(history_path)
    samples, active = [], 0
    for lane in registry.get("lanes") or []:
        if lane.get("state") != "ACTIVE":
            continue
        active += 1
        receipt, rel = Q.read_receipt(lane, state_root)
        row = Q.sample(lane, receipt, rel, now=now)
        if row and seen.get(row["lane_id"]) != row["run_started_at"]:
            samples.append(row)
    return samples, active


def append(history_path: Path, samples: list[dict]) -> None:
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            for row in samples:
                stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="print what would be appended (default)")
    mode.add_argument("--apply", action="store_true", help="append the samples")
    parser.add_argument("--state-root", default=os.environ.get("TRADEAI_STATE_ROOT") or str(DEFAULT_STATE_ROOT),
                        help="where receipts are READ from")
    parser.add_argument("--history-root", default=None, help="where the history file is WRITTEN (default: --state-root)")
    parser.add_argument("--registry", default=str(ROOT / "config/lane_registry.json"))
    parser.add_argument("--limit", type=int, default=10, help="samples to print")
    args = parser.parse_args(argv)
    state_root = Path(args.state_root)
    history_path = Path(args.history_root or args.state_root) / Q.HISTORY_FILE
    registry = Q._read_json(Path(args.registry), 32 * 1024 * 1024) or {}
    if not registry.get("lanes"):
        print(f"ERROR: no lanes in {args.registry}", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc)
    samples, active = collect(registry, state_root, history_path, now=now)
    verb = "appended" if args.apply else "would append"
    print(json.dumps({"mode": "apply" if args.apply else "dry_run", "active_lanes": active, verb.replace(" ", "_"): len(samples),
                      "history": str(history_path)}))
    for row in samples[:args.limit]:
        print("  " + json.dumps({k: row[k] for k in ("lane_id", "run_started_at", "mode", "status", "count", "count_key",
                                                      "duration_s")}))
    if args.apply and samples:
        append(history_path, samples)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
