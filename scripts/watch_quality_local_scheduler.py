#!/usr/bin/env python3
"""Bounded Watch quality scheduler: synchronous LOCAL_QUANT only.

Each pass first creates a fresh forced-read-only watch-quality-projection-v2
snapshot, then builds and persists only the selected local packets from that
exact admission evidence. OAuth, premium, blind-model and inline-critic lanes
are all withheld. No legacy worker is spawned, so quality cannot be re-derived
under a different evidence contract after scheduling.

The write phase is one all-or-nothing database transaction. Every candidate is
built and contract-checked before the first INSERT. Calls into the canonical
persistence service receive a connection wrapper whose per-packet commit is
deferred; exact packet IDs, packet contents, and singleton-live status are
verified inside the same transaction before the one final commit.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

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
TRANSACTION_CONTRACT = "watch-quality-local-atomic-batch-v1"
ACK_REQUIRED = "ACTIVATE_BOUNDED_LOCAL_QUANT"
DEFAULT_LIMIT = 20
MAX_LIMIT = 40
PROJECTION_LIMIT = 200


class _DeferredCommitConnection:
    """Proxy a DB connection while deferring canonical per-packet commits.

    ``shadow_decision_service.persist`` is intentionally atomic for one symbol
    and commits before returning. Gate 6 needs a stronger batch boundary:
    either every selected symbol is verified and committed, or none is. This
    proxy preserves the canonical SQL and rollback behavior while making each
    inner ``commit()`` a no-op. The scheduler commits the real connection once,
    after pre-commit verification of the complete batch.
    """

    def __init__(self, conn: Any):
        self._conn = conn
        self.deferred_commit_calls = 0

    def cursor(self, *args: Any, **kwargs: Any):
        return self._conn.cursor(*args, **kwargs)

    def commit(self) -> None:
        self.deferred_commit_calls += 1

    def rollback(self) -> None:
        self._conn.rollback()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def _close_quietly(conn: Any) -> None:
    try:
        conn.close()
    except Exception:
        pass


def _source_commit() -> str:
    value = str(os.getenv("WATCH_QUALITY_SOURCE_COMMIT") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise RuntimeError("WATCH_QUALITY_SOURCE_COMMIT must be an exact 40-character SHA")
    return value


def _fresh_projection(limit: int = PROJECTION_LIMIT) -> dict:
    old_contract = projection_v1.CONTRACT
    old_assembler = projection_v1.assemble_projection_facts
    conn = refresh._conn()
    try:
        projection_v1.CONTRACT = projection_v2.CONTRACT
        projection_v1.assemble_projection_facts = projection_v2.assemble_projection_facts
        report = projection_v1.build_projection(
            conn,
            limit=max(limit, PROJECTION_LIMIT),
            sample_limit=0,
        )
    finally:
        projection_v1.CONTRACT = old_contract
        projection_v1.assemble_projection_facts = old_assembler
        _close_quietly(conn)
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
    plan_conn = refresh._conn()
    try:
        plan = scheduler.build_plan(plan_conn)
    finally:
        _close_quietly(plan_conn)
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
        "transaction_contract": TRANSACTION_CONTRACT,
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


def _assert_packet_contract(packet: dict, symbol: str, source_commit: str) -> None:
    if str(packet.get("symbol") or "").upper() != symbol:
        raise RuntimeError(f"{symbol}: governed builder returned a different symbol")
    if packet.get("source_commit_sha") != source_commit:
        raise RuntimeError(f"{symbol}: packet source commit differs from scheduler source")
    if not (packet.get("quality_admission") or {}).get("state"):
        raise RuntimeError(f"{symbol}: packet lacks quality admission")
    presentation = packet.get("operator_presentation") or {}
    if presentation.get("contract") != "watch-quality-governance-v1":
        raise RuntimeError(f"{symbol}: packet lacks governed operator presentation")
    if presentation.get("one_sovereign_decision") is not True:
        raise RuntimeError(f"{symbol}: packet does not enforce one sovereign decision")
    model_calls = len((packet.get("model_review") or {}).get("lanes_completed") or [])
    inline_reviews = sorted(((packet.get("ticket_review") or {}).get("reviews") or {}).keys())
    if model_calls:
        raise RuntimeError(f"{symbol}: governed LOCAL_QUANT packet recorded model lane calls")
    if inline_reviews:
        raise RuntimeError(f"{symbol}: governed LOCAL_QUANT packet recorded inline ticket reviews")


def _build_all_packets(selected: list[dict], conn: Any, source_commit: str) -> list[dict]:
    prepared: list[dict] = []
    seen: set[str] = set()
    for item in selected:
        symbol = str(item.get("symbol") or "").upper()
        if not symbol:
            raise RuntimeError("selected scheduler item has no symbol")
        if symbol in seen:
            raise RuntimeError(f"duplicate selected scheduler symbol: {symbol}")
        seen.add(symbol)
        projection_row = item.get("projection") or {}
        packet = governed_builder.build_packet(
            symbol,
            conn,
            projection_row,
            source_commit=source_commit,
            origin="watch_quality_local_scheduler_v1",
            requested_by="watch_quality_local_scheduler_v1",
        )
        _assert_packet_contract(packet, symbol, source_commit)
        prepared.append({"symbol": symbol, "packet": packet})
    return prepared


def _verify_pending_batch(conn: Any, prepared: list[dict], persisted: list[dict], source_commit: str) -> list[str]:
    errors: list[str] = []
    expected_ids = [int(item["packet_id"]) for item in persisted]
    if len(expected_ids) != len(prepared) or len(set(expected_ids)) != len(expected_ids):
        errors.append("persisted packet IDs are missing or duplicated")
        return errors

    placeholders = ",".join(["%s"] * len(expected_ids))
    cur = conn.cursor()
    cur.execute(
        f"""SELECT packet_id, upper(symbol), packet
              FROM decision_packets
             WHERE packet_id IN ({placeholders})
             ORDER BY packet_id""",
        tuple(expected_ids),
    )
    rows = cur.fetchall()
    by_id = {int(row[0]): {"symbol": str(row[1]), "packet": row[2] or {}} for row in rows}
    if set(by_id) != set(expected_ids):
        errors.append(f"exact packet readback IDs {sorted(by_id)} != {sorted(expected_ids)}")

    expected_by_symbol = {item["symbol"]: item["packet"] for item in prepared}
    for item in persisted:
        packet_id = int(item["packet_id"])
        symbol = str(item["symbol"]).upper()
        row = by_id.get(packet_id)
        if not row:
            continue
        if row["symbol"] != symbol:
            errors.append(f"{symbol}: exact packet ID {packet_id} read back as {row['symbol']}")
            continue
        packet = row["packet"] if isinstance(row["packet"], dict) else json.loads(row["packet"])
        try:
            _assert_packet_contract(packet, symbol, source_commit)
        except Exception as exc:
            errors.append(f"{symbol}: readback contract failure: {type(exc).__name__}: {str(exc)[:300]}")
        expected_quality = (expected_by_symbol[symbol].get("quality_admission") or {}).get("state")
        actual_quality = (packet.get("quality_admission") or {}).get("state")
        if actual_quality != expected_quality:
            errors.append(f"{symbol}: readback quality {actual_quality} != {expected_quality}")

        cur.execute(
            """SELECT packet_id
                 FROM decision_packets
                WHERE upper(symbol)=%s AND superseded_by IS NULL
                ORDER BY packet_id""",
            (symbol,),
        )
        live_ids = [int(row_id[0]) for row_id in cur.fetchall()]
        if live_ids != [packet_id]:
            errors.append(f"{symbol}: live packet IDs {live_ids} != [{packet_id}]")
        item["live_packet_ids"] = live_ids

    return errors


def run_local(limit: int = DEFAULT_LIMIT) -> dict:
    if os.getenv("WATCH_QUALITY_LOCAL_SCHEDULER_ACK") != ACK_REQUIRED:
        raise RuntimeError(f"WATCH_QUALITY_LOCAL_SCHEDULER_ACK must equal {ACK_REQUIRED}")
    pause = PROJECT_ROOT / "data" / "runtime" / "WATCH_SCHEDULER_PAUSED"
    if pause.exists():
        return {
            "contract": CONTRACT,
            "transaction_contract": TRANSACTION_CONTRACT,
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
            "database_commit_count": 0,
        }

    conn = refresh._conn()
    persisted: list[dict] = []
    prepared: list[dict] = []
    deferred = _DeferredCommitConnection(conn)
    try:
        prepared = _build_all_packets(selected, conn, plan["source_commit"])
        for item in prepared:
            packet = item["packet"]
            packet_id = decision_service.persist(
                packet,
                conn=deferred,
                origin="watch_quality_local_scheduler_v1",
                requested_by="watch_quality_local_scheduler_v1",
                run_id=None,
            )
            persisted.append({
                "symbol": item["symbol"],
                "packet_id": int(packet_id),
                "quality": (packet.get("quality_admission") or {}).get("state"),
                "model_lane_calls": len((packet.get("model_review") or {}).get("lanes_completed") or []),
                "inline_ticket_reviews": sorted(((packet.get("ticket_review") or {}).get("reviews") or {}).keys()),
            })

        verification_errors = _verify_pending_batch(
            conn,
            prepared,
            persisted,
            plan["source_commit"],
        )
        if verification_errors:
            raise RuntimeError("; ".join(verification_errors[:10]))
        if deferred.deferred_commit_calls != len(prepared):
            raise RuntimeError(
                f"canonical persist commit calls {deferred.deferred_commit_calls} != {len(prepared)}"
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
            "prepared_symbols": [item.get("symbol") for item in prepared],
            "attempted_packet_ids": [item.get("packet_id") for item in persisted],
            "persisted": [],
            "database_commit_count": 0,
            "atomic_rollback": True,
            "error": f"{type(exc).__name__}: {str(exc)[:500]}",
        }
    finally:
        _close_quietly(conn)

    return {
        **plan,
        "dry_run": False,
        "status": "PASS_LOCAL_SCHEDULER_COMPLETED",
        "transaction_contract": TRANSACTION_CONTRACT,
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
    report = build_local_plan(args.limit) if args.dry_run else run_local(args.limit)
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    status = report.get("status") or "PASS_LOCAL_SCHEDULER_DRY_RUN"
    print(f"final_status|{status}")
    if str(status).startswith("BLOCKED"):
        raise SystemExit(6)


if __name__ == "__main__":
    main()
