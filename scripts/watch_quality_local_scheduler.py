#!/usr/bin/env python3
"""Bounded Watch quality scheduler: synchronous LOCAL_QUANT only.

Each pass first creates a fresh forced-read-only watch-quality-projection-v2
snapshot, then builds and persists only the selected local packets from that
exact admission evidence. OAuth, premium, blind-model and inline-critic lanes
are all withheld. No legacy worker is spawned, so quality cannot be re-derived
under a different evidence contract after scheduling.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(1, str(PROJECT_ROOT / "scripts" / "lib"))

import shadow_decision_service as decision_service  # noqa: E402
import watch_decision_refresh as refresh  # noqa: E402
import watch_decision_scheduler as scheduler  # noqa: E402
import watch_quality_governed_builder as governed_builder  # noqa: E402
import watch_quality_projection as projection_v1  # noqa: E402
import watch_quality_projection_v2 as projection_v2  # noqa: E402

CONTRACT = "watch-quality-local-scheduler-v1"
BUILDER_CONTRACT = "watch-quality-governed-builder-v1"
ACK_REQUIRED = "ACTIVATE_BOUNDED_LOCAL_QUANT"
DEFAULT_LIMIT = 20
MAX_LIMIT = 40
PROJECTION_LIMIT = 200


def _source_commit() -> str:
    value = str(os.getenv("WATCH_QUALITY_SOURCE_COMMIT") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise RuntimeError("WATCH_QUALITY_SOURCE_COMMIT must be an exact 40-character SHA")
    return value


def _fresh_projection(limit: int = PROJECTION_LIMIT) -> dict:
    old_contract = projection_v1.CONTRACT
    old_assembler = projection_v1.assemble_projection_facts
    try:
        projection_v1.CONTRACT = projection_v2.CONTRACT
        projection_v1.assemble_projection_facts = projection_v2.assemble_projection_facts
        report = projection_v1.build_projection(
            refresh._conn(),
            limit=max(limit, PROJECTION_LIMIT),
            sample_limit=0,
        )
    finally:
        projection_v1.CONTRACT = old_contract
        projection_v1.assemble_projection_facts = old_assembler
    if report.get("contract") != "watch-quality-projection-v2" or report.get("read_only") is not True:
        raise RuntimeError("fresh scheduler projection did not prove watch-quality-projection-v2 read-only evidence")
    if any(bool(value) for value in (report.get("authority") or {}).values()):
        raise RuntimeError("fresh scheduler projection exposed mutation authority")
    generated = report.get("generated_at")
    for row in report.get("all_rows") or []:
        if isinstance(row, dict):
            row["projection_generated_at"] = generated
    return report


def build_local_plan(limit: int = DEFAULT_LIMIT) -> dict:
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    source_commit = _source_commit()
    plan = scheduler.build_plan(refresh._conn())
    projection = _fresh_projection()
    projection_rows = {
        str(row.get("symbol") or "").upper(): row
        for row in projection.get("all_rows") or []
        if row.get("symbol")
    }
    local_candidates = list(plan.get("local") or [])
    local = [
        {**item, "projection": projection_rows.get(str(item.get("symbol") or "").upper())}
        for item in local_candidates
        if str(item.get("symbol") or "").upper() in projection_rows
    ][:limit]
    blind = list(plan.get("blind") or [])
    missing_projection = [
        str(item.get("symbol") or "").upper()
        for item in local_candidates
        if str(item.get("symbol") or "").upper() not in projection_rows
    ]
    return {
        "contract": CONTRACT,
        "governed_builder_contract": BUILDER_CONTRACT,
        "source_commit": source_commit,
        "dry_run": True,
        "limit": limit,
        "local": local,
        "local_symbols": [item.get("symbol") for item in local],
        "projection_contract": projection.get("contract"),
        "projection_generated_at": projection.get("generated_at"),
        "projection_quality_counts": projection.get("projected_quality_counts") or {},
        "missing_projection_symbols": missing_projection,
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
            "scheduler_can_persist_bounded_local_packets": True,
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
    selected = list(plan.get("local") or [])
    if not selected:
        return {
            **plan,
            "dry_run": False,
            "status": "PASS_LOCAL_SCHEDULER_NOTHING_DUE",
            "persisted": [],
        }

    conn = refresh._conn()
    persisted: list[dict] = []
    try:
        for item in selected:
            symbol = str(item.get("symbol") or "").upper()
            projection_row = item.get("projection") or {}
            packet = governed_builder.build_packet(
                symbol,
                conn,
                projection_row,
                source_commit=plan["source_commit"],
                origin="watch_quality_local_scheduler_v1",
                requested_by="watch_quality_local_scheduler_v1",
            )
            packet_id = decision_service.persist(
                packet,
                origin="watch_quality_local_scheduler_v1",
                run_id=None,
            )
            persisted.append({
                "symbol": symbol,
                "packet_id": packet_id,
                "quality": (packet.get("quality_admission") or {}).get("state"),
                "model_lane_calls": len((packet.get("model_review") or {}).get("lanes_completed") or []),
                "inline_ticket_reviews": sorted(((packet.get("ticket_review") or {}).get("reviews") or {}).keys()),
            })
    except BaseException as exc:
        return {
            **plan,
            "dry_run": False,
            "status": "BLOCKED_LOCAL_SCHEDULER_PARTIAL_WRITE",
            "persisted": persisted,
            "error": f"{type(exc).__name__}: {str(exc)[:500]}",
        }

    return {
        **plan,
        "dry_run": False,
        "status": "PASS_LOCAL_SCHEDULER_COMPLETED",
        "persisted": persisted,
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
