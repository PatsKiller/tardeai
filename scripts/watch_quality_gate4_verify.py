#!/usr/bin/env python3
"""Gate 4: read-only after-census and card-contract verification.

Consumes a successful Gate 3 evidence file, verifies the five latest live packet
hashes and quality states, checks the persisted one-decision presentation, and
reruns the top-ranked Watch census in a forced PostgreSQL read-only session.
It never rebuilds, refreshes, reviews, deploys, schedules or mutates state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(1, str(PROJECT_ROOT / "scripts" / "lib"))

import watch_packet_quality as packet_quality  # noqa: E402
import watch_quality_audit as quality_audit  # noqa: E402

CONTRACT = "watch-quality-gate4-readonly-verification-v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(payload: Any) -> str | None:
    if payload is None:
        return None
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def _load_gate3(path: Path) -> dict:
    evidence = json.loads(path.read_text())
    if evidence.get("contract") != "watch-quality-gate3-sample-rebuild-v1":
        raise RuntimeError("Gate 3 evidence contract mismatch")
    if evidence.get("status") != "PASS_GATE3_BOUNDED_LOCAL_REBUILD":
        raise RuntimeError("Gate 3 evidence is not PASS_GATE3_BOUNDED_LOCAL_REBUILD")
    sample = evidence.get("sample") or {}
    expected = {"admitted", "research_only", "quarantined", "management_only", "contradiction"}
    if set(sample) != expected:
        raise RuntimeError("Gate 3 evidence does not contain the exact five required roles")
    return evidence


def _prepare_readonly(conn) -> None:
    try:
        conn.rollback()
    except Exception:
        pass
    conn.set_session(readonly=True, autocommit=False)
    cur = conn.cursor()
    cur.execute("SHOW transaction_read_only")
    if str(cur.fetchone()[0]).lower() != "on":
        raise RuntimeError("database session is not read-only")


def _latest_packet(cur, symbol: str) -> dict:
    cur.execute(
        """SELECT packet_id, generated_at, packet
             FROM decision_packets
            WHERE upper(symbol)=%s AND superseded_by IS NULL
            ORDER BY generated_at DESC LIMIT 1""",
        (symbol,),
    )
    row = cur.fetchone()
    if not row:
        return {"packet_id": None, "generated_at": None, "packet": None, "packet_hash": None}
    packet = row[2] or {}
    return {
        "packet_id": row[0],
        "generated_at": row[1].isoformat() if row[1] else None,
        "packet": packet,
        "packet_hash": _stable_hash(packet),
    }


def verify(gate3_path: Path, limit: int = 200, sample_limit: int = 25) -> dict:
    gate3 = _load_gate3(gate3_path)
    conn = quality_audit._conn()
    _prepare_readonly(conn)
    cur = conn.cursor()
    roles: dict[str, dict] = {}
    errors: list[str] = []

    for role, expected in sorted((gate3.get("sample") or {}).items()):
        symbol = str(expected.get("symbol") or "").upper()
        live = _latest_packet(cur, symbol)
        packet = live.get("packet") or {}
        gate = packet_quality.packet_gate(packet)
        conflicts = packet_quality.presentation_conflicts(packet)
        presentation = packet.get("operator_presentation") or {}
        expected_hash = expected.get("after_packet_hash")
        expected_quality = str(expected.get("projected_quality") or "UNASSESSED").upper()
        role_errors: list[str] = []

        if live.get("packet_id") != expected.get("after_packet_id"):
            role_errors.append("latest packet id differs from Gate 3 readback")
        if live.get("packet_hash") != expected_hash:
            role_errors.append("latest packet hash differs from Gate 3 readback")
        if str(gate.get("quality") or "UNASSESSED").upper() != expected_quality:
            role_errors.append("live packet quality differs from projected Gate 3 role")
        if gate.get("validation_source") is None:
            role_errors.append("live packet has no canonical validation source")
        if presentation.get("contract") != packet_quality.PRESENTATION_CONTRACT:
            role_errors.append("live packet lacks watch-quality-governance-v1 presentation")
        if presentation.get("one_sovereign_decision") is not True:
            role_errors.append("live packet does not assert one sovereign decision")
        if conflicts:
            role_errors.extend(f"presentation conflict: {item}" for item in conflicts)
        if role == "management_only":
            if not gate.get("held"):
                role_errors.append("management-only sample is not held")
            if gate.get("new_entry_allowed") is not False:
                role_errors.append("management-only sample permits a new entry")

        roles[role] = {
            "symbol": symbol,
            "packet_id": live.get("packet_id"),
            "packet_hash": live.get("packet_hash"),
            "generated_at": live.get("generated_at"),
            "quality": gate.get("quality"),
            "deterministic": gate.get("deterministic"),
            "new_entry_allowed": gate.get("new_entry_allowed"),
            "held": gate.get("held"),
            "validation_source": gate.get("validation_source"),
            "ticket_hash": gate.get("ticket_hash"),
            "operator_presentation": {
                "contract": presentation.get("contract"),
                "header_state": presentation.get("header_state"),
                "primary_family": presentation.get("primary_family"),
                "family_display_states": presentation.get("family_display_states"),
                "one_sovereign_decision": presentation.get("one_sovereign_decision"),
            },
            "presentation_conflicts": conflicts,
            "errors": role_errors,
        }
        errors.extend(f"{role}:{error}" for error in role_errors)

    conn.rollback()
    census = quality_audit.build_report(conn, limit=limit, sample_limit=sample_limit)
    if census.get("read_only") is not True:
        errors.append("census did not prove read-only mode")

    report = {
        "contract": CONTRACT,
        "generated_at": _now(),
        "gate3_evidence": str(gate3_path),
        "read_only": True,
        "roles": roles,
        "census": {key: value for key, value in census.items() if key != "all_rows"},
        "errors": errors,
        "authority": {
            "database_write": False,
            "packet_rebuild": False,
            "model_provider_call": False,
            "oauth_lane_call": False,
            "paid_lane_call": False,
            "schedule_change": False,
            "service_restart": False,
            "ui_deployment": False,
            "proposal_or_execution_action": False,
        },
        "status": "PASS_GATE4_READONLY_VERIFICATION" if not errors else "BLOCKED_GATE4_VERIFICATION",
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate3-json", required=True)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--sample-limit", type=int, default=25)
    parser.add_argument("--evidence-json", required=True)
    args = parser.parse_args()
    if args.limit < 1 or args.limit > 1000:
        raise SystemExit("--limit must be between 1 and 1000")
    report = verify(Path(args.gate3_json).expanduser().resolve(), args.limit, args.sample_limit)
    output = Path(args.evidence_json).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    output.chmod(0o600)
    public = {**report, "census": report.get("census"), "evidence_json": str(output)}
    print(json.dumps(public, indent=2, sort_keys=True, default=str))
    print(f"final_status|{report.get('status')}")
    if report.get("status") != "PASS_GATE4_READONLY_VERIFICATION":
        raise SystemExit(4)


if __name__ == "__main__":
    main()
