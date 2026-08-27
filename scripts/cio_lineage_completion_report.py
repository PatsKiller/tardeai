#!/usr/bin/env python3
"""Report CIO workflow lineage completion. Read-only; writes nothing.

    python scripts/cio_lineage_completion_report.py            # human summary
    python scripts/cio_lineage_completion_report.py --json     # machine readable
    python scripts/cio_lineage_completion_report.py --path X   # a specific lineage file

Exit 0 always in report mode. With --fail-on-finding, exits 1 when a finding
fires, so a cron or CI job can gate on it.

AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Run as `python scripts/cio_lineage_completion_report.py` puts scripts/ on
# sys.path[0], not the repo root, so the scripts.-prefixed imports below fail
# without this. Same bootstrap as portfolio_server.py.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.cio_lineage_health import completion_report, findings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="CIO lineage completion report (read-only)")
    ap.add_argument("--path", default=None, help="lineage jsonl (default: canonical store)")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--fail-on-finding", action="store_true",
                    help="exit 1 if a finding fires (for cron/CI gating)")
    ap.add_argument("--min-workflows", type=int, default=10,
                    help="stay silent below this many workflows (default 10)")
    args = ap.parse_args()

    report = completion_report(args.path)
    found = findings(report, min_workflows=args.min_workflows)

    if args.json:
        print(json.dumps({"report": report, "findings": found}, indent=2, sort_keys=True))
    else:
        total = report["workflows"]
        done = report["complete_to_checkpoint"]
        rate = report["completion_rate"]
        print(f"workflows                {total}")
        print(f"complete_to_checkpoint   {done}" + (f"  ({rate:.1%})" if rate is not None else ""))
        print(f"with checkpoint_id       {report['with_checkpoint_id']}")
        print(f"arcs                     {report['arcs'] or '{}'}")
        print(f"first open stage         {report['stalled_at']}")
        if report["identity_fork_suspected"]:
            print("\nIDENTITY FORK SUSPECTED — the two arcs never join, so no workflow")
            print("can complete. This needs an identity decision, not a retry.")
        for f in found:
            print(f"\n[{f['severity'].upper()}] {f['check']}\n  {f['message']}")

    return 1 if (found and args.fail_on_finding) else 0


if __name__ == "__main__":
    raise SystemExit(main())
