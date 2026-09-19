#!/usr/bin/env python3
"""hermes_universe_history_retention.py — Prune governed-universe snapshots (audit 2026-09-19).

data/runtime/hermes_governed_universe_history grew unbounded since 2026-07-02 (~75 snapshots
/day, ~60MB/day, 4.7G at first audit) because rotate_runtime_logs.sh only covers logs/*.log
and no retention job referenced the directory. persistent_state_root.py already classes it
CACHE.

Thinning mirrors scripts/hermes_score_history_retention.py rather than a flat delete: the only
reader, load_universe_trend() (scripts/lib/hermes_scope_governor/universe.py), keeps just the
LATEST snapshot per UTC day and is reachable from the api_v2 trend endpoint at up to 90 days.
A flat --days purge would silently truncate that chart, so:

  * newer than --days            keep every snapshot
  * --days .. --trend-days       keep the latest snapshot per UTC day (what the trend reads)
  * older than --trend-days      delete (beyond the endpoint's 90-day clamp, unreachable)

  python3 scripts/hermes_universe_history_retention.py --dry-run
  python3 scripts/hermes_universe_history_retention.py --apply --days 21
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# stamp is generated_at with ":"/"+" stripped, first 15 chars (universe.py:105)
NAME_RE = re.compile(r"^universe_(\d{4}-\d{2}-\d{2})T(\d{4})_.+\.json$")

DEFAULT_DAYS = int(os.environ.get("HERMES_UNIVERSE_HISTORY_RETENTION_DAYS", "21"))
DEFAULT_TREND_DAYS = int(os.environ.get("HERMES_UNIVERSE_TREND_MAX_DAYS", "90"))
DEFAULT_MIN_KEEP = int(os.environ.get("HERMES_UNIVERSE_HISTORY_MIN_KEEP", "50"))


def _history_dir() -> Path:
    # data/runtime is a symlink into persistent-state; resolve so we delete the real files.
    return (PROJECT_ROOT / "data" / "runtime" / "hermes_governed_universe_history").resolve()


def _stamp(path: Path) -> tuple[str, str] | None:
    """(utc_day, hhmm) parsed from the filename, or None if it does not match."""
    m = NAME_RE.match(path.name)
    return (m.group(1), m.group(2)) if m else None


def run(days: int = DEFAULT_DAYS, trend_days: int = DEFAULT_TREND_DAYS,
        min_keep: int = DEFAULT_MIN_KEEP, apply: bool = False) -> dict:
    hist = _history_dir()
    now = datetime.now(timezone.utc)
    keep_all_after = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    keep_daily_after = (now - timedelta(days=trend_days)).strftime("%Y-%m-%d")

    files: list[tuple[str, str, Path, int]] = []
    unparsed: list[str] = []
    if hist.is_dir():
        for p in hist.glob("universe_*.json"):
            st = _stamp(p)
            if st is None:
                unparsed.append(p.name)  # never delete what we cannot date
                continue
            try:
                files.append((st[0], st[1], p, p.stat().st_size))
            except OSError:
                continue

    # Latest snapshot per UTC day is the one load_universe_trend() surfaces.
    latest_of_day: dict[str, tuple[str, Path]] = {}
    for day, hhmm, p, _sz in files:
        cur = latest_of_day.get(day)
        if cur is None or hhmm > cur[0]:
            latest_of_day[day] = (hhmm, p)
    daily_keepers = {p for _h, p in latest_of_day.values()}

    keep: list[tuple[Path, int]] = []
    delete: list[tuple[Path, int]] = []
    for day, _hhmm, p, sz in files:
        if day >= keep_all_after:
            keep.append((p, sz))
        elif day >= keep_daily_after and p in daily_keepers:
            keep.append((p, sz))
        else:
            delete.append((p, sz))

    # Floor: never let a clock/format problem empty the directory.
    floored = False
    if delete and len(files) - len(delete) < min_keep:
        newest_first = sorted(delete, key=lambda t: t[0].name, reverse=True)
        need = min_keep - (len(files) - len(delete))
        rescued = set(p for p, _ in newest_first[:need])
        delete = [(p, sz) for p, sz in delete if p not in rescued]
        floored = True

    freed = 0
    errors: list[str] = []
    if apply:
        for p, sz in delete:
            try:
                p.unlink()
                freed += sz
            except OSError as e:
                errors.append(f"{p.name}: {e}")

    out = {
        "ok": not errors,
        "apply": apply,
        "history_dir": str(hist),
        "retention_days": days,
        "trend_days": trend_days,
        "min_keep": min_keep,
        "min_keep_floor_applied": floored,
        "files_before": len(files),
        "files_kept": len(keep),
        "files_deleted": len(delete) if apply else 0,
        "files_deletable": len(delete),
        "bytes_deletable": sum(sz for _p, sz in delete),
        "bytes_freed": freed,
        "days_covered": len(latest_of_day),
        "unparsed_skipped": len(unparsed),
        "errors": errors,
        "ts": now.isoformat(),
    }
    print(json.dumps(out, indent=2))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--trend-days", type=int, default=DEFAULT_TREND_DAYS)
    ap.add_argument("--min-keep", type=int, default=DEFAULT_MIN_KEEP)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    res = run(days=args.days, trend_days=args.trend_days, min_keep=args.min_keep,
              apply=args.apply and not args.dry_run)
    sys.exit(0 if res["ok"] else 1)


if __name__ == "__main__":
    main()
