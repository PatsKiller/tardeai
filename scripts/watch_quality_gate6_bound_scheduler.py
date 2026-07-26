#!/usr/bin/env python3
"""Gate 6 bounded Watch backfill over the complete active Watch population.

This entrypoint is deliberately separate from the legacy cadence planner. It:
- plans over every active/researched watchlist symbol, not only existing packets;
- requires exact population equality with the read-only quality projection;
- emits a stable reviewed-selection hash during dry-run;
- refuses every write unless RUN presents that exact hash;
- reuses the proven all-or-nothing atomic persistence boundary;
- withholds every model, OAuth, paid, proposal, and execution lane.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(1, str(PROJECT_ROOT / "scripts" / "lib"))

import packet_invalidation as invalidation  # noqa: E402
import watch_decision_refresh as refresh  # noqa: E402
import watch_packet_quality as packet_quality  # noqa: E402
import watch_quality_gate6_selection as selection  # noqa: E402
import watch_quality_local_scheduler as atomic  # noqa: E402
import watch_quality_projection as projection_v1  # noqa: E402
import watch_quality_projection_v2 as projection_v2  # noqa: E402

CONTRACT = "watch-quality-local-scheduler-v1"
POPULATION_CONTRACT = "watch-quality-active-population-v1"
TRANSACTION_CONTRACT = atomic.TRANSACTION_CONTRACT
SELECTION_CONTRACT = selection.CONTRACT
ACK_REQUIRED = atomic.ACK_REQUIRED
DEFAULT_LIMIT = 20
MAX_LIMIT = 40
PROJECTION_LIMIT = 1000
TIER_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
QUALITY_ORDER = {"ADMITTED": 0, "UNASSESSED": 1, "RESEARCH_ONLY": 2, "QUARANTINED": 3}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _source_commit() -> str:
    value = str(os.getenv("WATCH_QUALITY_SOURCE_COMMIT") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise RuntimeError("WATCH_QUALITY_SOURCE_COMMIT must be an exact 40-character SHA")
    return value


def _priority_key(item: dict) -> tuple:
    return (
        TIER_ORDER.get(item.get("tier"), 9),
        QUALITY_ORDER.get(item.get("quality"), 9),
        str(item.get("symbol") or ""),
    )


def _active_population(conn: Any) -> list[str]:
    cur = conn.cursor()
    cur.execute(
        """SELECT upper(symbol)
             FROM watchlist_items
            WHERE symbol IS NOT NULL
              AND coalesce(status, 'active') IN ('active', 'researched')
            GROUP BY upper(symbol)
            ORDER BY min(hermes_rank) NULLS LAST, upper(symbol)"""
    )
    symbols = [str(row[0]).upper() for row in cur.fetchall() if row and row[0]]
    if not symbols:
        raise RuntimeError("active Watch population is empty")
    if len(symbols) > PROJECTION_LIMIT:
        raise RuntimeError(
            f"active Watch population {len(symbols)} exceeds projection ceiling {PROJECTION_LIMIT}"
        )
    return symbols


def _build_active_plan(conn: Any) -> dict:
    policy = refresh.load_policy()
    tiers = policy.get("tiers") or {}
    limits = policy.get("limits") or {}
    cap = min(MAX_LIMIT, int(limits.get("max_symbols_per_scheduler_pass", MAX_LIMIT)))
    population = _active_population(conn)
    cur = conn.cursor()

    cur.execute(
        """SELECT upper(symbol), generated_at, model_review_mode, packet
             FROM decision_packets
            WHERE superseded_by IS NULL
              AND upper(symbol) = ANY(%s)""",
        (population,),
    )
    packets = {
        str(row[0]).upper(): {
            "generated_at": row[1],
            "mode": row[2],
            "packet": row[3] or {},
            "gate": packet_quality.packet_gate(row[3] or {}),
        }
        for row in cur.fetchall()
    }

    cur.execute("SELECT upper(symbol) FROM operator_starred_symbols")
    starred = {str(row[0]).upper() for row in cur.fetchall() if row and row[0]}
    cur.execute(
        """SELECT DISTINCT upper(symbol)
             FROM watch_decision_refresh_jobs
            WHERE state IN ('QUEUED','RUNNING')"""
    )
    in_flight = {str(row[0]).upper() for row in cur.fetchall() if row and row[0]}

    plan = {
        "local": [],
        "blind": [],
        "skipped_in_flight": [],
        "quality_deferred": [],
        "not_due": [],
        "population_symbols": population,
    }
    quality_counts = {state: 0 for state in QUALITY_ORDER}
    now = _now()

    for symbol in population:
        packet_info = packets.get(symbol)
        gate = packet_info["gate"] if packet_info else {
            "quality": "UNASSESSED",
            "new_entry_allowed": None,
            "deterministic": "NOT_RUN",
            "held": False,
            "quality_reasons": [],
            "hard_failures": [],
            "validation_source": None,
        }
        quality_state = gate["quality"] if gate["quality"] in QUALITY_ORDER else "UNASSESSED"
        quality_counts[quality_state] += 1
        held_or_starred = bool(gate.get("held") or symbol in starred)

        if symbol in in_flight:
            plan["skipped_in_flight"].append(symbol)
            continue

        tier = refresh.classify_priority(symbol, conn)
        tier_config = tiers.get(tier) or {}

        if quality_state == "QUARANTINED" and not held_or_starred:
            plan["quality_deferred"].append({
                "symbol": symbol,
                "tier": tier,
                "quality": quality_state,
                "deterministic": gate.get("deterministic"),
                "validation_source": gate.get("validation_source"),
                "why": (
                    gate.get("quality_reasons")
                    or gate.get("hard_failures")
                    or ["quality gate refused active entry"]
                )[0],
            })
            continue

        local_ceiling = tier_config.get("full_local_packet_max_minutes")
        due_local = False
        due_reason = ""

        if packet_info is None:
            due_local = True
            due_reason = "PACKET_ABSENT — deterministic quality assessment required"
        elif quality_state == "UNASSESSED":
            due_local = True
            due_reason = "QUALITY_UNASSESSED — rebuild locally before any model lane"
        else:
            age_min = (now - packet_info["generated_at"]).total_seconds() / 60
            due_local = bool(local_ceiling and age_min > float(local_ceiling))
            if due_local:
                due_reason = f"age {age_min:.0f}m > ceiling {local_ceiling}m"
            else:
                try:
                    snapshot = invalidation.build_current_input_snapshot(symbol, conn)
                    comparison = invalidation.compare_packet_inputs(packet_info["packet"], snapshot)
                    if not comparison.get("inputs_match"):
                        due_local = True
                        due_reason = "inputs changed"
                except Exception:
                    conn.rollback()

        if not due_local:
            plan["not_due"].append({
                "symbol": symbol,
                "tier": tier,
                "quality": quality_state,
                "deterministic": gate.get("deterministic"),
            })
            continue

        plan["local"].append({
            "symbol": symbol,
            "tier": tier,
            "quality": quality_state,
            "deterministic": gate.get("deterministic"),
            "validation_source": gate.get("validation_source"),
            "held_or_starred": held_or_starred,
            "why": due_reason,
        })

    plan["local"].sort(key=_priority_key)
    plan["local"] = plan["local"][:cap]
    plan["quality_deferred"].sort(key=_priority_key)
    plan["estimates"] = {
        "local_symbols": len(plan["local"]),
        "blind_symbols": 0,
        "lane_calls": 0,
        "paid_cost_usd": 0,
        "population": len(population),
        "packets_present": len(packets),
        "packet_absent": len(population) - len(packets),
        "in_flight": len(plan["skipped_in_flight"]),
        "not_due": len(plan["not_due"]),
        "quality_deferred": len(plan["quality_deferred"]),
        "quality_counts": quality_counts,
        "policy_version": refresh.policy_version(),
        "quality_policy_version": "watch-quality-admission-v1",
        "authority": (
            "complete active Watch population; local deterministic only; "
            "OAuth and premium withheld"
        ),
    }
    return plan


def _fresh_projection() -> dict:
    old_contract = projection_v1.CONTRACT
    old_assembler = projection_v1.assemble_projection_facts
    conn = refresh._conn()
    try:
        projection_v1.CONTRACT = projection_v2.CONTRACT
        projection_v1.assemble_projection_facts = projection_v2.assemble_projection_facts
        report = projection_v1.build_projection(
            conn,
            limit=PROJECTION_LIMIT,
            sample_limit=0,
        )
    finally:
        projection_v1.CONTRACT = old_contract
        projection_v1.assemble_projection_facts = old_assembler
        atomic._close_quietly(conn)

    if report.get("contract") != "watch-quality-projection-v2":
        raise RuntimeError("Gate 6 projection contract is not watch-quality-projection-v2")
    if report.get("read_only") is not True:
        raise RuntimeError("Gate 6 projection did not prove read-only evidence")
    if any(bool(value) for value in (report.get("authority") or {}).values()):
        raise RuntimeError("Gate 6 projection exposed mutation authority")
    generated = report.get("generated_at")
    for row in report.get("all_rows") or []:
        if isinstance(row, dict):
            row["projection_generated_at"] = generated
    return report


def build_plan(limit: int = DEFAULT_LIMIT) -> dict:
    if limit < 1 or limit > MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    source_commit = _source_commit()
    plan_conn = refresh._conn()
    try:
        active_plan = _build_active_plan(plan_conn)
    finally:
        atomic._close_quietly(plan_conn)

    projection = _fresh_projection()
    projection_rows = {
        str(row.get("symbol") or "").upper(): row
        for row in projection.get("all_rows") or []
        if row.get("symbol")
    }
    active_symbols = set(active_plan["population_symbols"])
    projection_symbols = set(projection_rows)
    if active_symbols != projection_symbols:
        missing = sorted(active_symbols - projection_symbols)
        extra = sorted(projection_symbols - active_symbols)
        raise RuntimeError(
            "active Watch population differs from quality projection: "
            f"missing={missing[:20]} extra={extra[:20]}"
        )

    local_candidates = list(active_plan.get("local") or [])
    missing_candidates = [
        str(item.get("symbol") or "").upper()
        for item in local_candidates
        if str(item.get("symbol") or "").upper() not in projection_rows
    ]
    if missing_candidates:
        raise RuntimeError(
            f"Gate 6 candidates lack projection evidence: {missing_candidates}"
        )

    selected = [
        {
            **item,
            "projection": projection_rows[str(item.get("symbol") or "").upper()],
        }
        for item in local_candidates[:limit]
    ]
    reviewed_hash = selection.selection_hash(source_commit, limit, selected)
    return {
        "contract": CONTRACT,
        "population_contract": POPULATION_CONTRACT,
        "transaction_contract": TRANSACTION_CONTRACT,
        "selection_contract": SELECTION_CONTRACT,
        "selection_hash": reviewed_hash,
        "source_commit": source_commit,
        "dry_run": True,
        "limit": limit,
        "local": selected,
        "local_symbols": [item["symbol"] for item in selected],
        "projection_contract": projection.get("contract"),
        "projection_generated_at": projection.get("generated_at"),
        "projection_quality_counts": projection.get("projected_quality_counts") or {},
        "missing_projection_symbols": [],
        "oauth_withheld": [],
        "oauth_withheld_count": 0,
        "quality_deferred": active_plan.get("quality_deferred") or [],
        "estimates": {
            **(active_plan.get("estimates") or {}),
            "selected_local_symbols": len(selected),
            "selected_model_lane_calls": 0,
            "selected_paid_cost_usd": 0,
        },
        "authority": {
            "analysis_tier": "LOCAL_QUANT",
            "database_write_in_dry_run": False,
            "market_data_reads_may_occur": True,
            "model_provider_call": False,
            "oauth_lane_call": False,
            "paid_lane_call": False,
            "proposal_or_execution_action": False,
            "scheduler_can_persist_reviewed_atomic_batch": True,
        },
    }


def _expected_selection_hash() -> str:
    value = str(os.getenv("WATCH_QUALITY_EXPECTED_SELECTION_HASH") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise RuntimeError(
            "WATCH_QUALITY_EXPECTED_SELECTION_HASH must equal the reviewed dry-run SHA-256"
        )
    return value


def run_reviewed(limit: int = DEFAULT_LIMIT) -> dict:
    if os.getenv("WATCH_QUALITY_LOCAL_SCHEDULER_ACK") != ACK_REQUIRED:
        raise RuntimeError(
            f"WATCH_QUALITY_LOCAL_SCHEDULER_ACK must equal {ACK_REQUIRED}"
        )
    pause = PROJECT_ROOT / "data" / "runtime" / "WATCH_SCHEDULER_PAUSED"
    if pause.exists():
        return {
            "contract": CONTRACT,
            "population_contract": POPULATION_CONTRACT,
            "selection_contract": SELECTION_CONTRACT,
            "status": "BLOCKED_LOCAL_SCHEDULER_PAUSED",
            "reason": pause.read_text()[:200] or "operator pause",
        }

    expected_hash = _expected_selection_hash()
    plan = build_plan(limit)
    if plan["selection_hash"] != expected_hash:
        return {
            **plan,
            "dry_run": False,
            "status": "BLOCKED_GATE6_SELECTION_DRIFT",
            "expected_selection_hash": expected_hash,
            "observed_selection_hash": plan["selection_hash"],
            "persisted": [],
            "database_commit_count": 0,
        }

    selected = list(plan.get("local") or [])
    if not selected:
        return {
            **plan,
            "dry_run": False,
            "status": "PASS_LOCAL_SCHEDULER_NOTHING_DUE",
            "persisted": [],
            "database_commit_count": 0,
        }

    conn = refresh._conn()
    persisted: list[dict] = []
    prepared: list[dict] = []
    deferred = atomic._DeferredCommitConnection(conn)
    try:
        prepared = atomic._build_all_packets(selected, conn, plan["source_commit"])
        for item in prepared:
            packet = item["packet"]
            packet_id = atomic.decision_service.persist(
                packet,
                conn=deferred,
                origin="watch_quality_gate6_reviewed_batch_v1",
                requested_by="watch_quality_gate6_reviewed_batch_v1",
                run_id=None,
            )
            persisted.append({
                "symbol": item["symbol"],
                "packet_id": int(packet_id),
                "quality": (packet.get("quality_admission") or {}).get("state"),
                "model_lane_calls": len(
                    (packet.get("model_review") or {}).get("lanes_completed") or []
                ),
                "inline_ticket_reviews": sorted(
                    ((packet.get("ticket_review") or {}).get("reviews") or {}).keys()
                ),
            })

        verification_errors = atomic._verify_pending_batch(
            conn,
            prepared,
            persisted,
            plan["source_commit"],
        )
        if verification_errors:
            raise RuntimeError("; ".join(verification_errors[:10]))
        if deferred.deferred_commit_calls != len(prepared):
            raise RuntimeError(
                "canonical persist commit calls "
                f"{deferred.deferred_commit_calls} != {len(prepared)}"
            )
        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        return {
            **plan,
            "dry_run": False,
            "status": "BLOCKED_LOCAL_SCHEDULER_ATOMIC_ROLLBACK",
            "expected_selection_hash": expected_hash,
            "prepared_symbols": [item.get("symbol") for item in prepared],
            "attempted_packet_ids": [item.get("packet_id") for item in persisted],
            "persisted": [],
            "database_commit_count": 0,
            "atomic_rollback": True,
            "error": f"{type(exc).__name__}: {str(exc)[:500]}",
        }
    finally:
        atomic._close_quietly(conn)

    return {
        **plan,
        "dry_run": False,
        "status": "PASS_LOCAL_SCHEDULER_COMPLETED",
        "expected_selection_hash": expected_hash,
        "prepared_symbols": [item["symbol"] for item in prepared],
        "persisted": persisted,
        "database_commit_count": 1,
        "atomic_rollback": False,
        "precommit_verification_errors": [],
        "deferred_inner_commit_calls": deferred.deferred_commit_calls,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    args = parser.parse_args()

    report = build_plan(args.limit) if args.dry_run else run_reviewed(args.limit)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    status = report.get("status") or "PASS_LOCAL_SCHEDULER_DRY_RUN"
    print(f"selection_hash|{report.get('selection_hash') or ''}")
    print(f"final_status|{status}")
    if str(status).startswith("BLOCKED"):
        raise SystemExit(6)


if __name__ == "__main__":
    main()
