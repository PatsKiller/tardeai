#!/usr/bin/env python3
"""
deploy_session34_hotfix.py
==========================
Orchestrates the Session 34 hotfix deployment in two phases:

  PHASE 1 — DIAGNOSE (always run, never destructive):
    - Iron Rule pre-flight check
    - Run session34_diagnose.py -> backups/session34_diagnose.md
    - Print the diagnostic to stdout for the operator to read
    - STOP and wait for human to inspect

  PHASE 2 — APPLY (only after operator confirms the diagnostic):
    - Queue triage (reset stuck running, skip pending covered_call)
    - Bump timeouts for risk_synthesis / growth_strategy_scan
    - (Operator must run schema/RAG fixes manually with --table and
      --replacement-column args derived from the diagnostic)
    - Iron Rule post-flight check

This split is intentional: schema changes are too high-stakes to run
in the same blast as everything else.

Usage:
    cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

    # Phase 1: read-only diagnostic
    python3 scripts/deploy_session34_hotfix.py --phase diagnose

    # Phase 2: triage + timeouts (DRY-RUN first, always)
    python3 scripts/deploy_session34_hotfix.py --phase apply --dry-run --skip-covered-call
    python3 scripts/deploy_session34_hotfix.py --phase apply --apply --skip-covered-call
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def iron_rule():
    holdings_file = Path("data/portfolios/state/holdings.json")
    if not holdings_file.exists():
        print(f"FAIL: holdings.json not found")
        return False
    with open(holdings_file) as f:
        d = json.load(f)
    total = d.get("portfolio_totals", {}).get("total_value", 0)
    count = len(d.get("holdings", []))
    print(f"  Holdings: ${total:,.0f} / {count} positions")
    if total < 1_000_000:
        print(f"FAIL: holdings ${total:,.0f} too low")
        return False
    if count < 30:
        print(f"FAIL: only {count} positions")
        return False
    return True


def run_step(name, cmd, tolerate_nonzero=False):
    print(f"\n{'=' * 70}\nSTEP: {name}\n{'=' * 70}")
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        if tolerate_nonzero:
            print(f"(exit {result.returncode} tolerated)")
            return True
        print(f"FAIL: exit {result.returncode}")
        return False
    return True


def phase_diagnose(scripts_dir):
    print("\n" + "=" * 70)
    print("PHASE 1: DIAGNOSE (read-only)")
    print("=" * 70)

    print("\nPre-flight (Iron Rule):")
    if not iron_rule():
        print("ABORTING")
        sys.exit(1)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = Path("backups") / f"session34_diagnose_{ts}.md"

    if not run_step(
        "Run diagnostic",
        [sys.executable, str(scripts_dir / "session34_diagnose.py"), "--output", str(report)],
        tolerate_nonzero=True,
    ):
        sys.exit(1)

    print(f"\nDiagnostic report: {report}")
    print("\n" + "=" * 70)
    print(f"OPEN THIS FILE NOW: {report}")
    print("=" * 70)
    print("""
You need three pieces of info from the report before running Phase 2:

  1. From Section 1 — the table and column name where the LLM tried to
     write '1.5-3.0' into a numeric column. Look for a row with
     data_type='numeric' that should be free-form.

  2. From Section 2 — the file containing 'ORDER BY created_at DESC LIMIT 8'
     and the actual timestamp column on its target table.

  3. From Section 3 — verify the 180s timeout location matches what
     session34_bump_timeouts.py will patch.

Once you have these, run:

    # Tonight (urgent — before 23:00 window):
    python3 scripts/deploy_session34_hotfix.py --phase apply --dry-run --skip-covered-call
    python3 scripts/deploy_session34_hotfix.py --phase apply --apply --skip-covered-call

    # Then separately (when you have time to be careful):
    python3 scripts/session34_fix_covered_call_schema.py \\
        --table <TABLE_FROM_REPORT> --column <COL_FROM_REPORT> --dry-run
    python3 scripts/session34_fix_rag_sql.py \\
        --file <FILE_FROM_REPORT> --replacement-column <ACTUAL_COL> --dry-run
""")


def phase_apply(scripts_dir, dry_run, apply_flag, skip_covered_call):
    print("\n" + "=" * 70)
    print(f"PHASE 2: APPLY ({'DRY-RUN' if dry_run else 'APPLY'})")
    print("=" * 70)

    print("\nPre-flight (Iron Rule):")
    if not iron_rule():
        sys.exit(1)

    mode_flag = "--dry-run" if dry_run else "--apply"

    # Step 1: queue triage
    triage_cmd = [
        sys.executable, str(scripts_dir / "session34_queue_triage.py"), mode_flag,
    ]
    if skip_covered_call:
        triage_cmd.append("--skip-covered-call")
    if not run_step("Queue triage", triage_cmd):
        print("Queue triage failed. Aborting.")
        sys.exit(1)

    # Step 2: timeout bump
    if not run_step(
        "Bump heavy-job timeouts",
        [sys.executable, str(scripts_dir / "session34_bump_timeouts.py"), mode_flag],
    ):
        print("Timeout bump failed. Aborting.")
        sys.exit(1)

    # Step 3: post-flight
    print("\nPost-flight (Iron Rule):")
    if not iron_rule():
        print("CRITICAL: holdings state degraded! Investigate immediately.")
        sys.exit(2)

    print("\n" + "=" * 70)
    print(f"Phase 2 complete ({'DRY-RUN' if dry_run else 'APPLIED'})")
    print("=" * 70)
    if dry_run:
        print("Re-run with --apply to commit changes.")
    else:
        print("""
Done. Remaining work (NOT automated — must be run manually with args):

  1. covered_call_scoring schema fix:
       python3 scripts/session34_fix_covered_call_schema.py \\
           --table <TABLE> --column <COL> --dry-run
       (then --apply)

  2. rag_content_curation SQL fix:
       python3 scripts/session34_fix_rag_sql.py \\
           --file <FILE> --replacement-column <COL> --dry-run
       (then --apply)

Both can wait until tomorrow morning. Tonight's 23:00 window is safe
because (a) covered_call jobs are skipped and (b) heavy-job timeouts
are bumped.
""")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["diagnose", "apply"], required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--skip-covered-call", action="store_true",
                        help="In apply phase, also mark pending covered_call jobs as skipped")
    parser.add_argument("--scripts-dir", default="scripts")
    args = parser.parse_args()

    scripts_dir = Path(args.scripts_dir).resolve()

    if args.phase == "diagnose":
        phase_diagnose(scripts_dir)
    else:
        if not args.dry_run and not args.apply:
            print("ERROR: --phase apply requires --dry-run or --apply")
            sys.exit(1)
        phase_apply(scripts_dir, args.dry_run, args.apply, args.skip_covered_call)


if __name__ == "__main__":
    main()
