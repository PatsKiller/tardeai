#!/usr/bin/env python3
"""hermes-research-worker-pool — STEP 3: shadow parity, n8n dry_run plan vs the cron live run (read-only).

    python3 03_parity.py --since 2026-10-16T00:00:00+00:00 [--slots 24] [--state-root DIR] [--log PATH]

Pairs each dispatcher dry_run fire (coordination ledger `runs`, stdout_tail last line DRY-RUN-SUMMARY) with the cron
live run of the same ET hour (logs/hermes_worker_pool.log JSON reports, `lane_outcomes`). Per slot:

  match       the two agree on which lanes have no runner, and every lane the dry plan calls output_overdue is
              also failing (or produced, i.e. the live run in the same minute cleared it) in the live report
  mismatch    anything else — listed with both sides
  unpaired    one side missing for that hour (cron did not run, or the fire was lock-skipped)

Pass: >= --slots consecutive paired slots, zero mismatches. Exit 0 pass, 1 not yet / mismatch, 2 unreadable input.
Opens the ledger with mode=ro and the log read-only; writes nothing.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
LANE = "hermes-research-worker-pool"


def hour_key(ts: str) -> str:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(ET).strftime("%Y-%m-%dT%H")


def dry_fires(ledger: Path, since: str) -> dict[str, dict]:
    c = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
    out = {}
    for run_id, state, exit_code, at, receipt in c.execute(
            "SELECT run_id, state, exit_code, requested_at, receipt_json FROM runs WHERE lane_id=? AND mode='dry_run' "
            "AND requested_at >= ? AND state NOT IN ('REQUESTED','RUNNING') ORDER BY requested_at", (LANE, since)):
        tail = (json.loads(receipt or "{}").get("stdout_tail") or "").strip().splitlines()
        summary = None
        if tail and tail[-1].startswith("DRY-RUN-SUMMARY "):
            summary = json.loads(tail[-1][len("DRY-RUN-SUMMARY "):])
        out[hour_key(at)] = {"run_id": run_id, "state": state, "exit": exit_code, "summary": summary}
    return out


def live_runs(log: Path, since: str) -> dict[str, dict]:
    text = log.read_text(encoding="utf-8", errors="replace")
    dec, i, out = json.JSONDecoder(), 0, {}
    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
    while True:
        j = text.find('{\n  "mode": "worker_pool"', i)
        if j < 0:
            return out
        try:
            obj, i = dec.raw_decode(text, j)
        except ValueError:
            i = j + 1
            continue
        at = obj.get("generated_at")
        if at and "lane_outcomes" in obj and datetime.fromisoformat(at) >= since_dt:
            out[hour_key(at)] = obj


def compare(dry: dict, live: dict) -> tuple[str, dict]:
    status = (dry.get("summary") or {}).get("status")
    if status is None:
        return "mismatch", {"why": "dry fire has no DRY-RUN-SUMMARY (old code or truncated)", "dry": dry}
    outcomes = {k: v.get("outcome") for k, v in (live.get("lane_outcomes") or {}).items()}
    dry_nr = {k for k, v in status.items() if v == "no_runner"}
    live_nr = {k for k, v in outcomes.items() if v == "no_runner"}
    live_bad = {k for k, v in outcomes.items() if v in ("no_runner", "runner_error", "output_overdue")}
    dry_over = {k for k, v in status.items() if v == "output_overdue"}
    unexplained = {k for k in dry_over if k not in live_bad and outcomes.get(k) != "produced"}
    detail = {"dry_status": status, "live_outcomes": outcomes}
    if dry_nr != live_nr or unexplained:
        detail.update(no_runner_dry=sorted(dry_nr), no_runner_live=sorted(live_nr), overdue_unexplained=sorted(unexplained))
        return "mismatch", detail
    return "match", detail


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--since", required=True, help="ISO timestamp (the served promote time)")
    ap.add_argument("--slots", type=int, default=24)
    ap.add_argument("--state-root", default=str(Path.home() / "trade-ai-releases/persistent-state"))
    ap.add_argument("--log", default=None)
    args = ap.parse_args(argv)
    root = Path(args.state_root)
    ledger = root / "data/governance/n8n_coordination_ledger.sqlite"
    log = Path(args.log) if args.log else root / "logs/hermes_worker_pool.log"
    try:
        dry, live = dry_fires(ledger, args.since), live_runs(log, args.since)
    except (OSError, sqlite3.Error, ValueError) as exc:
        print(f"unreadable input: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    rows, streak, best, mismatches = [], 0, 0, 0
    for hour in sorted(set(dry) | set(live)):
        if hour not in dry or hour not in live:
            rows.append({"hour": hour, "verdict": "unpaired", "dry": hour in dry, "live": hour in live})
            streak = 0
            continue
        verdict, detail = compare(dry[hour], live[hour])
        rows.append({"hour": hour, "verdict": verdict, "dry_exit": dry[hour]["exit"], **(detail if verdict != "match" else {})})
        if verdict == "match":
            streak += 1
            best = max(best, streak)
        else:
            mismatches += 1
            streak = 0
    for r in rows:
        print(json.dumps(r, sort_keys=True))
    ok = mismatches == 0 and best >= args.slots
    print(json.dumps({"paired_streak_best": best, "required": args.slots, "mismatches": mismatches,
                      "verdict": "PASS" if ok else "NOT_YET" if mismatches == 0 else "MISMATCH"}))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
