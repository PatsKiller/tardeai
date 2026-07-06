#!/usr/bin/env python3
"""run_options_monitor.py — refresh options proposals + position monitor (market-hours cadence).

Pipeline hook (PR4): also runs options paper lifecycle monitor (Alpaca reconcile +
Schwab-chain marks → options_monitored_positions). Install cron via:
  bash scripts/install_options_paper_monitor_cron.sh

Cron example (every 10 min weekdays 9:35–16:05 ET):
  bash linux_launchers/run_options_monitor.sh
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
    lifecycle = {}
    try:
        from lib.options_pipeline.paper_monitor_ops import run_pipeline_hook
        lifecycle = run_pipeline_hook()
    except Exception as e:
        lifecycle = {"ok": False, "error": str(e)[:200]}
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
        "lifecycle_monitor": lifecycle,
        "strategy_counts": {
            k: sum(1 for p in (props.get("proposals") or []) if p.get("strategy") == k)
            for k in ("covered_call", "cash_secured_put", "protective_put", "long_call", "credit_spread")
        },
        "research_bridge": bridge,
    }))


if __name__ == "__main__":
    main()