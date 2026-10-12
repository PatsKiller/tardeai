#!/usr/bin/env python3
"""Momentum lifecycle health monitor. Reads metadata; optional write is its own health receipt only."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.n8n_momentum_lifecycle import (  # noqa: E402
    collect_server_snapshot, evaluate, load_admission, monitor_admitted, plan_recovery, write_monitor,
)
from scripts.market_session import current_market_session, is_trading_day  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot", type=Path, help="explicit sanitized fixture snapshot, never credentials")
    source.add_argument("--host-snapshot", action="store_true", help="fixed server-owned metadata projections")
    parser.add_argument("--code-root", type=Path, required=True, help="served code root or isolated fixture root")
    parser.add_argument("--state-root", type=Path, help="host-owned state root; required for host snapshot/receipt")
    parser.add_argument("--write-monitor", action="store_true", help="write only momentum_lifecycle_last.json")
    parser.add_argument("--dry-run", action="store_true", help="no health write or recovery submission")
    parser.add_argument("--candidate", type=Path, default=ROOT / "config/n8n_momentum_lifecycle_candidate.json")
    parser.add_argument("--now", help="aware ISO timestamp; omitted uses current UTC clock")
    args = parser.parse_args(argv)
    if args.snapshot and (args.snapshot.name.startswith(".env") or "cookie" in args.snapshot.name.lower()):
        parser.error("credential/cookie inputs are refused")
    if (args.host_snapshot or args.write_monitor) and args.state_root is None:
        parser.error("--state-root required")
    candidate = json.loads(args.candidate.read_text())
    admission = load_admission(args.code_root)
    from datetime import timezone
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else datetime.now(timezone.utc)
    snapshot = (collect_server_snapshot(args.state_root, candidate, now=now) if args.host_snapshot
                else json.loads(args.snapshot.read_text()))
    report = evaluate(candidate, snapshot, admission, now=now,
                      trading_day_fn=is_trading_day, session_fn=current_market_session)
    report["recovery"] = plan_recovery(candidate, report, admission, snapshot=snapshot, now=now)
    if args.write_monitor and not args.dry_run:
        if candidate.get("enabled") is not True or not monitor_admitted(admission):
            parser.error("monitor write requires reviewed operative activation at deployed SHA")
        write_monitor(report, args.state_root)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if any(x["severity"] == "P1" for x in report["incidents"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
