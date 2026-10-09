#!/usr/bin/env python3
"""check_scalp_cycles.py — market-hours-aware health of the 5-minute scalp lane (trade-ai-scalp-live).

Reads the day's ScalpCycleReceipt@v1 ledger ($TRADEAI_STATE_ROOT/data/runtime/scalp_cycle_receipts/<day>.jsonl)
and prints ScalpCycleMonitor@v1 (scripts/lib/scalp_cycle_monitor.py): slots due/ok, missed tail, RTH gap,
stale flag (RTH only, 2x cadence), P2 MISSED_CYCLES / P1 NO_CYCLES_30M incidents, the clean-day verdict used
by the 3-clean-market-day n8n cutover gate, and a one-line summary for the Command Center / digest.

Report only: no Telegram, no network. The incident fan-in (scripts/n8n_incident_fanin.py source 3h) raises the
same incidents; this CLI is the heartbeat watcher's and the operator's view.

    python3 scripts/check_scalp_cycles.py                 # today, human summary line
    python3 scripts/check_scalp_cycles.py --json          # full ScalpCycleMonitor@v1
    python3 scripts/check_scalp_cycles.py --write         # also data/runtime/scalp_cycle_monitor_last.json
    python3 scripts/check_scalp_cycles.py --exit-code     # exit 2 on P1, 1 on P2, else 0
    python3 scripts/check_scalp_cycles.py --date 2026-10-09 --now 2026-10-09T16:05:00-04:00
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import scalp_cycle_monitor as scm  # noqa: E402
import scalp_cycle_receipt as scr  # noqa: E402

ET = ZoneInfo("America/New_York")
MONITOR_REL = "data/runtime/scalp_cycle_monitor_last.json"


def run(date: str | None = None, now: datetime | None = None, state_root: Path | None = None) -> dict:
    now = now or datetime.now(ET)
    day = date or now.astimezone(ET).date().isoformat()
    doc = scm.evaluate(scr.read_day(day, state_root), now, day=day)
    doc["ledger_present"] = scr.ledger_path(day, state_root).exists()
    if not doc["ledger_present"] and doc["slots_total"]:
        doc["summary_line"] = f"Scalp lane {day}: no ScalpCycleReceipt@v1 ledger (receipts not deployed or lane not run)"
    return doc


def write(doc: dict, state_root: Path | None = None) -> Path:
    p = (state_root or scr.state_root()) / MONITOR_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, sort_keys=True), encoding="utf-8")
    tmp.replace(p)
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", help="ET day YYYY-MM-DD (default today)")
    ap.add_argument("--now", help="evaluate as of this ISO time (default now)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true", help=f"write {MONITOR_REL}")
    ap.add_argument("--exit-code", action="store_true", help="exit 2 on P1, 1 on P2")
    a = ap.parse_args(argv)
    now = datetime.fromisoformat(a.now) if a.now else None
    doc = run(a.date, now)
    if a.write:
        write(doc)
    print(json.dumps(doc, indent=2, sort_keys=True) if a.json else doc["summary_line"])
    if a.exit_code:
        sev = {i["severity"] for i in doc["incidents"]}
        return 2 if "P1" in sev else 1 if "P2" in sev else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
