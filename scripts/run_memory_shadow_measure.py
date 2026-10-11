#!/usr/bin/env python3
"""run_memory_shadow_measure.py — Phase 2 weekly/shadow measure CLI.

READ_ONLY_ADVISORY. Never flips MEMORY_BEHAVIOR_INFLUENCE.

Usage:
  python3 scripts/run_memory_shadow_measure.py
  python3 scripts/run_memory_shadow_measure.py --json
  python3 scripts/run_memory_shadow_measure.py --root /path/to/CURRENT
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 2 memory shadow measure (influence OFF)", allow_abbrev=False)
    ap.add_argument("--root", default=None, help="Project root (default: repo root)")
    ap.add_argument("--wake-path", default=None)
    ap.add_argument("--trace-path", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", action="store_true", help="Print full JSON report")
    ap.add_argument("--dry-run", action="store_true", help="offline plan; never reads traces or writes a report")
    args = ap.parse_args(argv)
    if args.dry_run:
        print(f"DRY-RUN cio-memory-shadow-measure: would compare wake/trace metadata and write {args.out or 'data/cio/memory_shadow_measure_latest.json'}; influence remains OFF; no reads, DB, network or writes")
        return 0

    from scripts.lib.agent_memory_shadow_measure import run_measure

    from scripts.lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    try:
        report = run_measure(
            root=args.root,
            wake_path=args.wake_path,
            trace_path=args.trace_path,
            out_path=args.out,
        )
    except Exception as exc:
        write_lane_receipt("cio-memory-shadow-measure", ok=False, exit_code=1,
                           started_at=started, error=type(exc).__name__)
        raise
    ok = bool(report.get("written_to")) and not bool(report.get("write_error"))
    code = 0 if ok else 1
    write_lane_receipt("cio-memory-shadow-measure", ok=ok, exit_code=code,
                       started_at=started, error=None if ok else "REPORT_NOT_PERSISTED",
                       summary={"report_written": bool(report.get("written_to"))})
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        m = report.get("metrics") or {}
        g = report.get("promotion_gate") or {}
        print(f"as_of={report.get('as_of')}")
        print(f"payload_v1={m.get('decision_payload_v1_count')} coverage={m.get('decision_payload_coverage_on_traces')}")
        print(f"wakes={m.get('wakes_compared')} retrieval_rate={m.get('memory_retrieval_rate')}")
        print(f"changed_decision={m.get('memory_changed_decision')} flips={report.get('shadow',{}).get('memory_attributable_action_flips')}")
        print(f"dual_path={report.get('shadow',{}).get('dual_path_executed')} gate={g.get('verdict')}")
        print(f"influence_active={m.get('behavior_influence_active')} (must stay False)")
        if report.get("written_to"):
            print(f"wrote={report['written_to']}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
