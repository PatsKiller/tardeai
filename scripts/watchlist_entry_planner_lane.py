#!/usr/bin/env python3
"""watchlist_entry_planner_lane.py — the n8n (dispatcher) entry of the watchlist entry planner. PLANS ONLY.

Lane repair 2026-10-15 (AGENTS.md §23.23: n8n owns flow, the host owns authority and every send). The cron entry
``scripts/watchlist_entry_planner.py`` plans AND sends the advisory entry alert through ``send_telegram``; a dispatched
lane may not send (onboarding standard §2.7, the dispatcher sender gate in
``tests/test_agents_policy_7_0_0_advisory_market_data.py``, which scans the lane entry script's static reach). This
entry imports only the planner's selection and planning definitions (``preview``, ``plan_run``, ``receipt_name``) —
never ``_alert`` — so its reach holds no sender:

* ``--dry-run``: ``preview`` — the same candidate selection on a READ ONLY session; returns before price bars, the
  LLM, the plan INSERT and any alert (AGENTS.md §6). Prints the preview JSON on stdout and one ``LANE_OUTPUT`` line on
  stderr (``attempted_count`` = candidates; a dry run produces nothing).
* live (NOT allowlisted: ``live_arg`` is null at shadow): ``plan_run(alerter=None)`` writes the plans and the lane
  receipt and counts alert-eligible plans as ``alerts_not_sent``. Entry alerts stay on the cron line until a host
  notification intent consumer delivers them (a canary prerequisite, recorded in the packet).

Argv mirrors the cron lines minus ``--lane`` (a provider-selecting token is refused on a dispatched argv, §23.18):
  python3 scripts/watchlist_entry_planner_lane.py --limit 60 --buy-rated-cap 400 [--dry-run]
  python3 scripts/watchlist_entry_planner_lane.py --scope proposals [--dry-run]

ADVISORY ONLY — no order, no proposal-state change, no execution, no send. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from watchlist_entry_planner import plan_run, preview, receipt_name  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--scope", default="watchlist", choices=["watchlist", "proposals"])
    ap.add_argument("--buy-rated-cap", type=int, default=20,
                    help="also plan up to N strongest BUY-rated researched names (0=off)")
    ap.add_argument("--dry-run", action="store_true",
                    help="read-only: list the candidates it would plan; no bars/LLM/writes/alerts")
    return ap


def main(argv=None) -> int:
    a = _parser().parse_args(argv)
    from lib.lane_last_receipt import now_iso
    from lib.lane_output import emit, output_block

    name = receipt_name(a.scope)
    started = now_iso()
    kw = dict(symbols=None, limit=a.limit, scope=a.scope, buy_rated_cap=a.buy_rated_cap)
    if a.dry_run:
        report = preview(alert=False, **kw)
        emit(name, "dry_run", output_block(unit="watchlist_entry_plans rows inserted", produced=0,
                                           attempted=int(report.get("candidates") or 0), empty_reason="dry_run"),
             started_at=started)
        return 0
    from lib.lane_last_receipt import write_receipt

    try:
        res = plan_run(alerter=None, **kw)
    except Exception as exc:  # noqa: BLE001 -- recorded in the receipt, then a non-zero exit
        write_receipt(name, ok=False, error=f"{type(exc).__name__}: {exc}", started_at=started)
        print(f"entry planner FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    failed = res["candidates"] > 0 and res["planned"] == 0
    write_receipt(name, ok=not failed, started_at=started,
                  summary={**{k: res[k] for k in ("candidates", "planned", "failed", "alerts", "lane")},
                           "alerts_not_sent": res.get("alerts_not_sent", 0), "output": res.get("output")},
                  error="every candidate failed" if failed else None)
    emit(name, "live", res["output"], started_at=started)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
