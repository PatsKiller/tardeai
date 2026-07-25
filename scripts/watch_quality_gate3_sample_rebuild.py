#!/usr/bin/env python3
"""Gate 3: bounded LOCAL_QUANT sample rebuild for Watch quality governance.

This is an intentionally narrow production-data write. It rebuilds exactly five
representative decision packets after first evaluating every candidate in
memory. No model lane is enabled. No scheduler, service, UI bundle, proposal,
approval or execution surface is changed.

The five roles are selected from a preserved watch-quality-projection-v2 JSON:
  * projected ADMITTED;
  * projected RESEARCH_ONLY;
  * projected QUARANTINED;
  * held management-only;
  * a previously contradictory WAIT/secondary-READY card (FATN preferred).
"""
from __future__ import annotations

import argparse
import hashlib
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

import shadow_decision_service as decision_service  # noqa: E402
import watch_decision_refresh as refresh  # noqa: E402
import watch_packet_quality as packet_quality  # noqa: E402
import watch_quality_governed_builder as governed_builder  # noqa: E402

CONTRACT = "watch-quality-gate3-sample-rebuild-v1"
ACK_REQUIRED = "BOUNDED_LOCAL_QUANT_SAMPLE"
ROLE_ORDER = ("admitted", "research_only", "quarantined", "management_only", "contradiction")
CONTRADICTION_SYMBOLS = ("FATN", "CECO")
MAX_PROJECTION_AGE_HOURS = 6.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(payload: Any) -> str | None:
    if payload is None:
        return None
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def _source_commit() -> str:
    value = str(os.getenv("WATCH_QUALITY_SOURCE_COMMIT") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise RuntimeError("WATCH_QUALITY_SOURCE_COMMIT must be an exact 40-character commit SHA")
    return value


def _load_projection(path: Path) -> dict:
    report = json.loads(path.read_text())
    if report.get("contract") != "watch-quality-projection-v2":
        raise RuntimeError("projection contract must be watch-quality-projection-v2")
    if report.get("read_only") is not True:
        raise RuntimeError("projection evidence is not marked read_only=true")
    authority = report.get("authority") or {}
    if any(bool(value) for value in authority.values()):
        raise RuntimeError("projection evidence contains non-read-only authority")
    generated = str(report.get("generated_at") or "")
    try:
        parsed = datetime.fromisoformat(generated.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 3600
    except Exception as exc:
        raise RuntimeError(f"projection generated_at is invalid: {type(exc).__name__}") from exc
    if age_hours < -0.25 or age_hours > MAX_PROJECTION_AGE_HOURS:
        raise RuntimeError(
            f"projection evidence age {age_hours:.2f}h exceeds the {MAX_PROJECTION_AGE_HOURS:.0f}h Gate 3 limit"
        )
    rows = report.get("all_rows") or []
    if len(rows) < 5:
        raise RuntimeError("projection evidence has fewer than five rows")
    for row in rows:
        if isinstance(row, dict):
            row["projection_generated_at"] = generated
    report["projection_age_hours"] = round(age_hours, 3)
    return report


def _score(row: dict, *, prefer_packet: bool = True) -> tuple:
    observed = ((row.get("provenance") or {}).get("observed_fields") or [])
    return (
        0 if (not prefer_packet or row.get("packet_present")) else 1,
        0 if str(row.get("technical_freshness") or "").upper() == "CURRENT" else 1,
        0 if row.get("new_entry_allowed") is not None else 1,
        -len(observed),
        int(row.get("rank") or 999999),
        str(row.get("symbol") or ""),
    )


def _choose(rows: list[dict], predicate, used: set[str], *, prefer_packet: bool = True) -> dict:
    candidates = [row for row in rows if predicate(row) and str(row.get("symbol") or "").upper() not in used]
    if not candidates:
        raise RuntimeError("projection cannot supply a distinct required sample role")
    selected = sorted(candidates, key=lambda row: _score(row, prefer_packet=prefer_packet))[0]
    used.add(str(selected.get("symbol") or "").upper())
    return selected


def select_sample(report: dict) -> dict[str, dict]:
    rows = list(report.get("all_rows") or [])
    used: set[str] = set()
    sample: dict[str, dict] = {}
    sample["admitted"] = _choose(
        rows, lambda row: row.get("projected_quality") == "ADMITTED", used)
    sample["research_only"] = _choose(
        rows,
        lambda row: row.get("projected_quality") == "RESEARCH_ONLY"
        and not row.get("management_only"),
        used,
    )
    sample["quarantined"] = _choose(
        rows,
        lambda row: row.get("projected_quality") == "QUARANTINED"
        and not row.get("management_only")
        and str(row.get("symbol") or "").upper() not in CONTRADICTION_SYMBOLS,
        used,
    )
    sample["management_only"] = _choose(
        rows, lambda row: row.get("management_only") is True, used, prefer_packet=False)

    contradiction = next(
        (
            row for symbol in CONTRADICTION_SYMBOLS
            for row in rows
            if str(row.get("symbol") or "").upper() == symbol and symbol not in used
        ),
        None,
    )
    if contradiction is None:
        contradiction = _choose(
            rows,
            lambda row: row.get("packet_present")
            and bool(row.get("presentation_conflicts")),
            used,
        )
    else:
        used.add(str(contradiction.get("symbol") or "").upper())
    sample["contradiction"] = contradiction
    return sample


def _latest_packet(conn, symbol: str) -> dict:
    cur = conn.cursor()
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


def _model_lane_count(packet: dict) -> int:
    review = packet.get("model_review") or {}
    lanes = review.get("lanes_completed") or packet.get("model_lanes_completed") or 0
    if isinstance(lanes, (list, tuple, set)):
        return len(lanes)
    try:
        return int(lanes)
    except (TypeError, ValueError):
        return 0


def _candidate_evidence(role: str, projected: dict, packet: dict, source_commit: str) -> dict:
    packet_quality.apply_operator_presentation(packet)
    gate = packet_quality.packet_gate(packet)
    conflicts = packet_quality.presentation_conflicts(packet)
    expected_quality = str(projected.get("projected_quality") or "UNASSESSED").upper()
    observed_quality = str(gate.get("quality") or "UNASSESSED").upper()
    root_quality = packet.get("quality_admission") or {}
    reviews = (packet.get("ticket_review") or {}).get("reviews") or {}
    errors: list[str] = []

    if observed_quality != expected_quality:
        errors.append(f"projected quality {expected_quality} != rebuilt quality {observed_quality}")
    if role == "management_only":
        if not gate.get("held"):
            errors.append("management-only sample is not held in rebuilt packet")
        if gate.get("new_entry_allowed") is not False:
            errors.append("management-only sample unexpectedly authorizes a new entry")
    if role == "contradiction" and conflicts:
        errors.append("operator presentation still contains contradictory READY state")
    if packet.get("governance_source_commit") != source_commit:
        errors.append("packet does not carry the exact reviewed source commit")

    lane_calls = _model_lane_count(packet)
    if lane_calls:
        errors.append(f"LOCAL_QUANT candidate recorded {lane_calls} model lane calls")
    if reviews:
        errors.append("LOCAL_QUANT candidate recorded an inline ticket critic review")

    return {
        "role": role,
        "symbol": str(projected.get("symbol") or "").upper(),
        "projected_quality": expected_quality,
        "projected_management_only": bool(projected.get("management_only")),
        "projected_primary_reason": projected.get("primary_reason"),
        "projected_facts_used": projected.get("facts_used") or {},
        "rebuilt_quality": observed_quality,
        "rebuilt_quality_reasons": root_quality.get("reasons") or [],
        "rebuilt_quality_facts_used": root_quality.get("facts_used") or {},
        "rebuilt_deterministic": gate.get("deterministic"),
        "rebuilt_new_entry_allowed": gate.get("new_entry_allowed"),
        "rebuilt_held": gate.get("held"),
        "validation_source": gate.get("validation_source"),
        "ticket_hash": gate.get("ticket_hash"),
        "governance_source_commit": packet.get("governance_source_commit"),
        "governed_builder_contract": (packet.get("governance_contracts") or {}).get("builder"),
        "presentation_contract": (packet.get("operator_presentation") or {}).get("contract"),
        "presentation_conflicts": conflicts,
        "model_lane_calls": lane_calls,
        "inline_ticket_reviews": sorted(reviews),
        "candidate_packet_hash": _stable_hash(packet),
        "errors": errors,
    }


def execute(projection_path: Path, evidence_path: Path) -> dict:
    if os.getenv("WATCH_GATE3_ACK") != ACK_REQUIRED:
        raise RuntimeError(f"WATCH_GATE3_ACK must equal {ACK_REQUIRED}")
    source_commit = _source_commit()

    projection = _load_projection(projection_path)
    sample = select_sample(projection)
    conn = refresh._conn()
    before = {role: _latest_packet(conn, str(row["symbol"]).upper()) for role, row in sample.items()}

    candidates: dict[str, dict] = {}
    checks: dict[str, dict] = {}
    for role in ROLE_ORDER:
        row = sample[role]
        symbol = str(row.get("symbol") or "").upper()
        packet = governed_builder.build_packet(
            symbol,
            conn,
            row,
            source_commit=source_commit,
            origin="watch_quality_gate3",
            requested_by="watch_quality_gate3_bounded_local",
        )
        candidates[role] = packet
        checks[role] = _candidate_evidence(role, row, packet, source_commit)

    prewrite_errors = [
        f"{role}:{error}"
        for role, check in checks.items()
        for error in check.get("errors") or []
    ]
    report: dict[str, Any] = {
        "contract": CONTRACT,
        "source_commit": source_commit,
        "generated_at": _now(),
        "projection_contract": projection.get("contract"),
        "projection_generated_at": projection.get("generated_at"),
        "projection_age_hours": projection.get("projection_age_hours"),
        "projection_source": str(projection_path),
        "sample": {
            role: {
                "symbol": str(row.get("symbol") or "").upper(),
                "projected_quality": row.get("projected_quality"),
                "projected_management_only": row.get("management_only"),
                "projected_primary_reason": row.get("primary_reason"),
                "before_packet_id": before[role]["packet_id"],
                "before_packet_hash": before[role]["packet_hash"],
                "candidate": checks[role],
            }
            for role, row in sample.items()
        },
        "prewrite_errors": prewrite_errors,
        "authority": {
            "analysis_tier": "LOCAL_QUANT",
            "model_provider_call": False,
            "oauth_lane_call": False,
            "paid_lane_call": False,
            "schedule_change": False,
            "service_restart": False,
            "ui_deployment": False,
            "proposal_or_execution_action": False,
            "database_scope": "bounded decision-packet persistence for five symbols",
            "market_data_reads_may_occur": True,
        },
    }

    if prewrite_errors:
        report["status"] = "BLOCKED_GATE3_PREWRITE_MISMATCH"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
        evidence_path.chmod(0o600)
        return report

    persisted: list[str] = []
    try:
        for role in ROLE_ORDER:
            packet_id = decision_service.persist(
                candidates[role], origin="watch_quality_gate3", run_id=None)
            report["sample"][role]["after_packet_id"] = packet_id
            persisted.append(role)

        readback_conn = refresh._conn()
        for role in ROLE_ORDER:
            symbol = report["sample"][role]["symbol"]
            after = _latest_packet(readback_conn, symbol)
            report["sample"][role]["after_packet_hash"] = after["packet_hash"]
            report["sample"][role]["after_generated_at"] = after["generated_at"]
            if after["packet_id"] != report["sample"][role]["after_packet_id"]:
                raise RuntimeError(f"{symbol} readback packet id mismatch")
            if after["packet_hash"] != checks[role]["candidate_packet_hash"]:
                raise RuntimeError(f"{symbol} readback packet hash mismatch")
            if (after.get("packet") or {}).get("governance_source_commit") != source_commit:
                raise RuntimeError(f"{symbol} readback source commit mismatch")
            gate = packet_quality.packet_gate(after["packet"] or {})
            conflicts = packet_quality.presentation_conflicts(after["packet"] or {})
            report["sample"][role]["after_gate"] = gate
            report["sample"][role]["after_presentation_conflicts"] = conflicts
            if conflicts:
                raise RuntimeError(f"{symbol} readback presentation conflict: {conflicts[0]}")

        report["status"] = "PASS_GATE3_BOUNDED_LOCAL_REBUILD"
    except BaseException as exc:
        report["status"] = "BLOCKED_GATE3_PARTIAL_WRITE"
        report["persisted_roles_before_failure"] = persisted
        report["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"

    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    evidence_path.chmod(0o600)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projection-json", required=True)
    parser.add_argument("--evidence-json", required=True)
    args = parser.parse_args()
    report = execute(
        Path(args.projection_json).expanduser().resolve(),
        Path(args.evidence_json).expanduser().resolve(),
    )
    public = {
        "contract": report.get("contract"),
        "source_commit": report.get("source_commit"),
        "generated_at": report.get("generated_at"),
        "status": report.get("status"),
        "sample": {
            role: {
                "symbol": item.get("symbol"),
                "projected_quality": item.get("projected_quality"),
                "candidate": item.get("candidate"),
                "after_packet_id": item.get("after_packet_id"),
                "after_packet_hash": item.get("after_packet_hash"),
                "after_gate": item.get("after_gate"),
                "after_presentation_conflicts": item.get("after_presentation_conflicts"),
            }
            for role, item in (report.get("sample") or {}).items()
        },
        "prewrite_errors": report.get("prewrite_errors"),
        "authority": report.get("authority"),
        "evidence_json": str(Path(args.evidence_json).expanduser().resolve()),
    }
    print(json.dumps(public, indent=2, sort_keys=True, default=str))
    print(f"final_status|{report.get('status')}")
    if report.get("status") != "PASS_GATE3_BOUNDED_LOCAL_REBUILD":
        raise SystemExit(3)


if __name__ == "__main__":
    main()
