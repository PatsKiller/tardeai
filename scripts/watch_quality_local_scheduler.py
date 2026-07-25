#!/usr/bin/env python3
"""Bounded Watch quality scheduler: LOCAL_QUANT only.

This adapter reuses the governed priority plan but deliberately withholds every
OAuth and premium item. Dry-run performs no write. Run mode enqueues one bounded
LOCAL_QUANT refresh run; workers persist decision packets with zero model lanes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(1, str(PROJECT_ROOT / "scripts" / "lib"))

import watch_decision_refresh as refresh  # noqa: E402
import watch_decision_scheduler as scheduler  # noqa: E402

CONTRACT = "watch-quality-local-scheduler-v1"
ACK_REQUIRED = "ACTIVATE_BOUNDED_LOCAL_QUANT"
DEFAULT_LIMIT = 20
MAX_LIMIT = 40


def build_local_plan(limit: int = DEFAULT_LIMIT) -> dict:
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    plan = scheduler.build_plan(refresh._conn())
    local = list(plan.get("local") or [])[:limit]
    blind = list(plan.get("blind") or [])
    return {
        "contract": CONTRACT,
        "dry_run": True,
        "limit": limit,
        "local": local,
        "local_symbols": [item.get("symbol") for item in local],
        "oauth_withheld": blind,
        "oauth_withheld_count": len(blind),
        "quality_deferred": plan.get("quality_deferred") or [],
        "estimates": {
            **(plan.get("estimates") or {}),
            "selected_local_symbols": len(local),
            "selected_model_lane_calls": 0,
            "selected_paid_cost_usd": 0,
        },
        "authority": {
            "analysis_tier": "LOCAL_QUANT",
            "model_provider_call": False,
            "oauth_lane_call": False,
            "paid_lane_call": False,
            "proposal_or_execution_action": False,
            "scheduler_can_enqueue_local_packet_work": True,
            "market_data_reads_may_occur": True,
        },
    }


def run_local(limit: int = DEFAULT_LIMIT) -> dict:
    if os.getenv("WATCH_QUALITY_LOCAL_SCHEDULER_ACK") != ACK_REQUIRED:
        raise RuntimeError(f"WATCH_QUALITY_LOCAL_SCHEDULER_ACK must equal {ACK_REQUIRED}")
    pause = PROJECT_ROOT / "data" / "runtime" / "WATCH_SCHEDULER_PAUSED"
    if pause.exists():
        return {
            "contract": CONTRACT,
            "status": "BLOCKED_LOCAL_SCHEDULER_PAUSED",
            "reason": pause.read_text()[:200] or "operator pause",
        }
    plan = build_local_plan(limit)
    symbols = [str(symbol).upper() for symbol in plan.get("local_symbols") or [] if symbol]
    if not symbols:
        return {
            **plan,
            "dry_run": False,
            "status": "PASS_LOCAL_SCHEDULER_NOTHING_DUE",
            "run": None,
        }
    result = refresh.enqueue_run(
        symbols,
        scope="AFFECTED_DIMENSIONS",
        analysis_tier="LOCAL_QUANT",
        include_options=False,
        force=False,
        requested_by="watch_quality_local_scheduler_v1",
        reason="quality_governance_local_only_cadence",
        priority=80,
        spawn_workers=True,
    )
    return {
        **plan,
        "dry_run": False,
        "status": "PASS_LOCAL_SCHEDULER_ENQUEUED" if result.get("ok") else "BLOCKED_LOCAL_SCHEDULER_ENQUEUE",
        "run": result,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args()
    report = build_local_plan(args.limit) if args.dry_run else run_local(args.limit)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    status = report.get("status") or "PASS_LOCAL_SCHEDULER_DRY_RUN"
    print(f"final_status|{status}")
    if str(status).startswith("BLOCKED"):
        raise SystemExit(6)


if __name__ == "__main__":
    main()
