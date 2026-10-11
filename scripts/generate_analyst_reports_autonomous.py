#!/usr/bin/env python3
"""generate_analyst_reports_autonomous.py — repeatable autonomous prospectus pipeline.

Builds each new report on the prior archived generation (lineage + continuity).
Publishes stable prospectus_{SYMBOL}_latest.* paths for Holdings UI links.

Modes:
  daily   — update living doc only when fingerprint changes (Mon–Fri cron)
  weekly  — same gate as daily; runs Sunday for symbols that changed that week
  full    — force in-place refresh all eligible holdings

Cron examples:
  # Weekdays 7:30 AM — catch mid-week intelligence changes
  30 7 * * 1-5 cd $PROJ && flock -n /tmp/analyst_reports_daily.lock \\
      $PY scripts/generate_analyst_reports_autonomous.py --mode daily >> logs/analyst_reports_autonomous.log 2>&1

  # Sunday 21:15 — weekly full refresh (replaces prospectus_weekly)
  15 21 * * 0 cd $PROJ && flock -n /tmp/analyst_reports_weekly.lock \\
      $PY scripts/generate_analyst_reports_autonomous.py --mode weekly >> logs/analyst_reports_autonomous.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))



def _execute() -> int:
    ap = argparse.ArgumentParser(description="Autonomous analyst prospectus pipeline")
    ap.add_argument("--mode", default="weekly", choices=("daily", "weekly", "full"))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--grok", action="store_true", default=True)
    ap.add_argument("--no-grok", action="store_true")
    ap.add_argument("--limit", type=int, default=200, help="max holdings + watchlist symbols per run")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import reporting_engine as re
    eligible = re.eligible_holding_symbols()[: args.limit]
    print(f"[autonomous/{args.mode}] eligible: {len(eligible)}")

    if args.dry_run:
        from report_lineage import canonical_registry_map

        reg = re.load_registry()
        by_sym = canonical_registry_map(reg.get("reports") or [], "symbol_holding")
        for row in eligible:
            prev = by_sym.get(row["symbol"])
            needs, reason = re.prospectus_needs_refresh(
                prev, row["fingerprint"], stale_days=None,
            )
            if args.mode == "full":
                needs, reason = True, "full_mode"
            print(f"  {row['symbol']:6} gen={((prev or {}).get('generation') or 0)} refresh={needs} ({reason})")
        return 0

    out = re.run_autonomous_cycle(
        mode=args.mode,
        force=args.force or args.mode == "full",
        grok_edit=not args.no_grok,
        limit=args.limit,
    )
    summary = {
        "mode": args.mode,
        "generated": len(out.get("generated") or []),
        "skipped": len(out.get("skipped") or []),
        "failed": len(out.get("failed") or []),
        "batch_log": out.get("batch_log"),
    }
    print(json.dumps(summary, indent=2))
    if out.get("failed"):
        for f in out["failed"]:
            print(f"[autonomous] FAILED {f.get('symbol')}: {f.get('error')}", file=sys.stderr)
    return 0 if out.get("ok") else 1


def main(argv=None) -> int:
    """Strict offline inspection before the legacy business execution path."""
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description="Autonomous analyst prospectus pipeline", allow_abbrev=False)
    ap.add_argument("--mode", default="weekly", choices=("daily", "weekly", "full"))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--grok", action="store_true", default=True)
    ap.add_argument("--no-grok", action="store_true")
    ap.add_argument("--limit", type=int, default=200, help="max holdings + watchlist symbols per run")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    lane = "generate-analyst-reports-autonomous-" + args.mode
    if args.dry_run:
        print(f"DRY-RUN {lane}: would refresh selected report mode with existing governed routing and lineage; no model or report writes; options={vars(args)}; inputs NOT_MEASURED")
        return 0
    try:
        from scripts.lib.lane_last_receipt import now_iso, write_lane_receipt
    except ImportError:
        from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    previous = sys.argv
    sys.argv = [previous[0], *argv]
    try:
        result = _execute()
        rc = int(result) if isinstance(result, int) else 0
    except SystemExit as exc:
        rc = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        write_lane_receipt(lane, ok=rc == 0, exit_code=rc, started_at=started, script="generate_analyst_reports_autonomous.py", summary={"completed": rc == 0})
        raise
    except Exception as exc:
        write_lane_receipt(lane, ok=False, exit_code=1, started_at=started, script="generate_analyst_reports_autonomous.py", error=type(exc).__name__)
        raise
    finally:
        sys.argv = previous
    write_lane_receipt(lane, ok=rc == 0, exit_code=rc, started_at=started, script="generate_analyst_reports_autonomous.py", summary={"completed": rc == 0})
    return rc


if __name__ == "__main__":
    raise SystemExit(main())