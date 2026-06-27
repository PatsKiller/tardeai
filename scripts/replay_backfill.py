#!/usr/bin/env python3
"""replay_backfill.py — Keep ALL past + future trade replays aligned.

Run after Schwab journal ingest/build or on a schedule. Steps:
  1. build_trade_execution_quality (Schwab round-trips → fill times + metrics)
  2. replay_chart_audit (backfill journal_trade_reviews.payload.replay_chart)

Usage:
    python scripts/replay_backfill.py --apply              # full pipeline
    python scripts/replay_backfill.py --apply --eq-only    # execution quality only
    python scripts/replay_backfill.py --apply --audit-only # replay snapshots only
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


def _run(cmd: list[str], label: str) -> dict:
    print(f"\n=== {label} ===", flush=True)
    p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    if p.stdout:
        print(p.stdout[-4000:] if len(p.stdout) > 4000 else p.stdout, flush=True)
    if p.returncode != 0:
        print(p.stderr[-2000:] if p.stderr else "", flush=True)
    return {"label": label, "ok": p.returncode == 0, "code": p.returncode}


def main():
    ap = argparse.ArgumentParser(description="Backfill replay alignment for all trades")
    ap.add_argument("--apply", action="store_true", help="Write to DB (required for real backfill)")
    ap.add_argument("--eq-limit", type=int, default=500, help="Max schwab round-trips to process")
    ap.add_argument("--eq-only", action="store_true")
    ap.add_argument("--audit-only", action="store_true")
    args = ap.parse_args()

    if not args.apply:
        print("DRY-RUN — pass --apply to execute. Would run EQ build + replay audit.")
        return 0

    report = {"steps": []}

    if not args.audit_only:
        report["steps"].append(_run(
            [PY, "scripts/build_trade_execution_quality.py", "--source", "schwab",
             "--limit", str(args.eq_limit), "--apply"],
            f"execution_quality (limit={args.eq_limit})",
        ))

    if not args.eq_only:
        report["steps"].append(_run(
            [PY, "scripts/replay_chart_audit.py"],
            "replay_chart_audit (all deduped trades)",
        ))

    ok = all(s["ok"] for s in report["steps"])
    print(json.dumps({"ok": ok, **report}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())