#!/usr/bin/env python3
"""run_options_monitor.py — refresh options proposals + position monitor (market-hours cadence).

Cron example (every 10 min weekdays 9:35–16:05 ET):
  35,45,55 9 * * 1-5  cd $PROJECT && flock -n /tmp/tradeai_options_monitor.lock .venv/bin/python scripts/run_options_monitor.py
  */10 10-15 * * 1-5  ...
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import options_engine as oe


def main():
    props = oe.generate_proposals(force=True)
    mon = oe.monitor_positions(force=True)
    bridge = {}
    try:
        import options_research_bridge as orb
        bridge = orb.run(apply=True, force=False)
    except Exception as e:
        bridge = {"ok": False, "error": str(e)[:120]}
    print(json.dumps({
        "ok": True,
        "proposals": props.get("count", 0),
        "positions": mon.get("position_count", 0),
        "needs_action": mon.get("needs_action_count", 0),
        "strategy_counts": {
            k: sum(1 for p in (props.get("proposals") or []) if p.get("strategy") == k)
            for k in ("covered_call", "cash_secured_put", "protective_put", "long_call", "credit_spread")
        },
        "research_bridge": bridge,
    }))


if __name__ == "__main__":
    main()