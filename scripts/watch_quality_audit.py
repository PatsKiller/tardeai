#!/usr/bin/env python3
"""Read-only quality census for the governed Watch decision population.

This script never rebuilds packets, calls a model, refreshes data, changes a
schedule, or writes application state. It reads the ranked Watch population and
latest unsuperseded decision packets, then reports deterministic quality,
validation, freshness and presentation-conflict counts.

Examples:
    python scripts/watch_quality_audit.py --limit 200
    python scripts/watch_quality_audit.py --limit 200 --json-output /tmp/watch-quality.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(1, str(PROJECT_ROOT / "scripts" / "lib"))

import watch_packet_quality as packet_quality


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn():
    from env_bootstrap import load_env
    load_env()
    from db_adapter import _get_conn
    return _get_conn()


def _ranked_population(cur, limit: int) -> list[tuple[str, int | None]]:
    cur.execute("""SELECT upper(symbol) AS symbol, min(hermes_rank) AS rank
                   FROM watchlist_items
                   WHERE symbol IS NOT NULL
                     AND coalesce(status, 'active') IN ('active', 'researched')
                   GROUP BY upper(symbol)
                   ORDER BY min(hermes_rank) NULLS LAST, upper(symbol)
                   LIMIT %s""", (limit,))
    return [(str(symbol), int(rank) if rank is not None else None)
            for symbol, rank in cur.fetchall()]


def _latest_packets(cur, symbols: list[str]) -> dict[str, dict]:
    if not symbols:
        return {}
    cur.execute("""SELECT DISTINCT ON (upper(symbol)) upper(symbol), generated_at, packet
                   FROM decision_packets
                   WHERE superseded_by IS NULL AND upper(symbol) = ANY(%s)
                   ORDER BY upper(symbol), generated_at DESC""", (symbols,))
    return {
        str(symbol): {
            "generated_at": generated_at.isoformat() if generated_at else None,
            "packet": packet or {},
        }
        for symbol, generated_at, packet in cur.fetchall()
    }


def _freshness(packet: dict) -> str:
    freshness = packet.get("freshness") or {}
    validity = packet.get("current_validity") or {}
    return str(
        freshness.get("overall_state")
        or validity.get("state")
        or packet.get("freshness_state")
        or "UNKNOWN"
    ).upper()


def build_report(conn, limit: int = 200, sample_limit: int = 25) -> dict:
    cur = conn.cursor()
    cur.execute("BEGIN READ ONLY")
    population = _ranked_population(cur, limit)
    symbols = [symbol for symbol, _ in population]
    packets = _latest_packets(cur, symbols)

    quality_counts: Counter[str] = Counter()
    deterministic_counts: Counter[str] = Counter()
    freshness_counts: Counter[str] = Counter()
    validation_sources: Counter[str] = Counter()
    conflict_counts: Counter[str] = Counter()
    held_management = 0
    no_packet = 0
    rows: list[dict] = []

    for symbol, rank in population:
        packet_record = packets.get(symbol)
        packet = (packet_record or {}).get("packet") or {}
        if not packet_record:
            no_packet += 1
        gate = packet_quality.packet_gate(packet)
        conflicts = packet_quality.presentation_conflicts(packet)
        quality = gate.get("quality") or "UNASSESSED"
        deterministic = gate.get("deterministic") or "NOT_RUN"
        fresh = _freshness(packet) if packet else "PACKET_ABSENT"
        source = gate.get("validation_source") or "NONE"
        quality_counts[quality] += 1
        deterministic_counts[deterministic] += 1
        freshness_counts[fresh] += 1
        validation_sources[source] += 1
        if gate.get("held") and quality != "ADMITTED":
            held_management += 1
        for conflict in conflicts:
            conflict_counts[conflict.split(";")[0]] += 1

        reasons = gate.get("quality_reasons") or gate.get("hard_failures") or gate.get("warnings") or []
        row = {
            "symbol": symbol,
            "rank": rank,
            "packet_generated_at": (packet_record or {}).get("generated_at"),
            "quality": quality,
            "deterministic": deterministic,
            "freshness": fresh,
            "held": bool(gate.get("held")),
            "new_entry_allowed": gate.get("new_entry_allowed"),
            "validation_source": source,
            "primary_reason": str(reasons[0])[:180] if reasons else None,
            "presentation_conflicts": conflicts,
        }
        rows.append(row)

    conn.rollback()
    attention = [
        row for row in rows
        if row["quality"] != "ADMITTED"
        or row["deterministic"] != "PASS"
        or row["freshness"] not in {"CURRENT", "DUE_SOON"}
        or row["presentation_conflicts"]
    ]
    return {
        "contract": "watch-quality-audit-v1",
        "generated_at": _now(),
        "read_only": True,
        "limit": limit,
        "population": len(population),
        "packets_found": len(packets),
        "packets_absent": no_packet,
        "quality_counts": dict(sorted(quality_counts.items())),
        "deterministic_counts": dict(sorted(deterministic_counts.items())),
        "freshness_counts": dict(sorted(freshness_counts.items())),
        "validation_sources": dict(sorted(validation_sources.items())),
        "held_management_only_count": held_management,
        "presentation_conflict_count": sum(conflict_counts.values()),
        "presentation_conflict_types": dict(sorted(conflict_counts.items())),
        "attention_count": len(attention),
        "attention_sample": attention[:sample_limit],
        "all_rows": rows,
        "authority": {
            "database_write": False,
            "packet_rebuild": False,
            "model_call": False,
            "provider_call": False,
            "schedule_change": False,
            "broker_or_order_action": False,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--sample-limit", type=int, default=25)
    parser.add_argument("--json-output")
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 1000:
        raise SystemExit("--limit must be between 1 and 1000")
    if args.sample_limit < 0 or args.sample_limit > args.limit:
        raise SystemExit("--sample-limit must be between 0 and --limit")

    report = build_report(_conn(), args.limit, args.sample_limit)
    public_report = {key: value for key, value in report.items() if key != "all_rows"}
    print(json.dumps(public_report, indent=2, sort_keys=True, default=str))
    if args.json_output:
        path = Path(args.json_output).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
        path.chmod(0o600)
        print(f"sanitized_json_output|{path}")


if __name__ == "__main__":
    main()
