#!/usr/bin/env python3
"""Advisory notification broker CLI (Phase 6 Tier D).

Usage:
  .venv/bin/python scripts/advisory_notification_broker.py process [--hours 24]
  .venv/bin/python scripts/advisory_notification_broker.py metrics
  .venv/bin/python scripts/advisory_notification_broker.py proof
  .venv/bin/python scripts/advisory_notification_broker.py seed-demo
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def main(argv: list[str] | None = None) -> int:
    from lib.advisory import notification_broker as nb

    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("process")
    pp.add_argument("--hours", type=float, default=24.0)
    sub.add_parser("metrics")
    sub.add_parser("proof")
    sub.add_parser("seed-demo")
    args = p.parse_args(argv)

    if args.cmd == "process":
        r = nb.process_window(hours=args.hours)
        print(json.dumps(r["metrics"], indent=2))
        print("proof:", r["proof"].get("egress_cutover"))
        return 0
    if args.cmd == "metrics":
        print(json.dumps(nb.load_metrics(), indent=2))
        return 0
    if args.cmd == "proof":
        print(json.dumps(nb.load_proof(), indent=2))
        return 0
    if args.cmd == "seed-demo":
        # Seed material + dupes for compression demo (does not send Telegram)
        nb.ingest("⚠️ ORPHANED STOP AAPL — unprotected", producer="stop_monitor", alert_type="orphaned_stop")
        nb.ingest("⚠️ ORPHANED STOP AAPL — unprotected", producer="stop_monitor", alert_type="orphaned_stop")
        nb.ingest("Research update: SCHD note", producer="hermes", alert_type="research_update")
        nb.ingest("Research update: SCHD note", producer="hermes", alert_type="research_update")
        nb.ingest("Advisory desk brief SCHD TRIM", producer="advisory_brief", alert_type="advisory")
        nb.ingest("Job telemetry ok", producer="health", alert_type="job_telemetry")
        r = nb.process_window(hours=24)
        print(json.dumps(r["metrics"], indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
