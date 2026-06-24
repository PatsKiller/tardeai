#!/usr/bin/env python3
"""generate_analyst_holding_prospectus_weekly.py — weekly BUY/STRONG BUY prospectus refresh.

Regenerates holding prospectus with latest portfolio, enrichment, synthesis, ensemble,
and news data. Refreshes when fingerprint changed OR report is older than --stale-days
(default 6 — weekly Sunday run picks up last week's reports).

Grok OAuth editorial polish enabled by default.

Cron (Sunday 21:15, after symbol_profiles + weekly_docx):
    15 21 * * 0 cd $PROJ && flock -n /tmp/analyst_prospectus_weekly.lock \\
        $PY scripts/generate_analyst_holding_prospectus_weekly.py >> logs/analyst_prospectus_weekly.log 2>&1

Usage:
    .venv/bin/python scripts/generate_analyst_holding_prospectus_weekly.py
    .venv/bin/python scripts/generate_analyst_holding_prospectus_weekly.py --force
    .venv/bin/python scripts/generate_analyst_holding_prospectus_weekly.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import reporting_engine as re  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Weekly holding prospectus batch (delta refresh)")
    ap.add_argument("--force", action="store_true", help="regenerate all eligible holdings")
    ap.add_argument("--stale-days", type=int, default=6, help="refresh if older than N days (default 6)")
    ap.add_argument("--grok", action="store_true", default=True, help="Grok OAuth editorial (default on)")
    ap.add_argument("--no-grok", action="store_true")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--dry-run", action="store_true", help="list eligible only, no generation")
    args = ap.parse_args()

    eligible = re.eligible_holding_symbols()[: args.limit]
    print(f"[prospectus-weekly] eligible holdings: {len(eligible)}")

    if args.dry_run:
        reg = re.load_registry()
        by_sym = {
            r["symbol"]: r
            for r in reg.get("reports", [])
            if r.get("report_type") == "symbol_holding" and r.get("symbol")
        }
        for row in eligible:
            prev = by_sym.get(row["symbol"])
            needs, reason = re.prospectus_needs_refresh(
                prev, row["fingerprint"], stale_days=args.stale_days,
            )
            print(f"  {row['symbol']:6} {row['recommendation']:12} refresh={needs} ({reason})")
        return 0

    out = re.run_autonomous_cycle(
        mode="full" if args.force else "weekly",
        force=args.force,
        grok_edit=not args.no_grok,
        limit=args.limit,
    )
    print(json.dumps({
        "generated": len(out.get("generated") or []),
        "skipped": len(out.get("skipped") or []),
        "failed": len(out.get("failed") or []),
        "batch_log": out.get("batch_log"),
    }, indent=2))
    if out.get("failed"):
        for f in out["failed"]:
            print(f"[prospectus-weekly] FAILED {f.get('symbol')}: {f.get('error')}", file=sys.stderr)
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())