#!/usr/bin/env python3
"""Gate 3 verifier with exact-id, semantic JSONB round-trip validation.

The legacy Gate 3 builder/persister remains the authority. This wrapper freezes
all five candidates at the JSON boundary, lets PostgreSQL normalize numeric JSON
representation, then exhaustively verifies every returned packet id. It changes
no model, critic, scheduler, UI, proposal, approval, broker, order, or 2FA path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(1, str(PROJECT_ROOT / "scripts" / "lib"))

import watch_quality_gate3_sample_rebuild as gate3  # noqa: E402

ROUNDTRIP_CONTRACT = "watch-quality-gate3-jsonb-roundtrip-v1"
MAX_DIFFS = 50


def _json_snapshot(payload: Any) -> Any:
    return json.loads(json.dumps(payload, default=str))


def _raw_hash(payload: Any) -> str | None:
    if payload is None:
        return None
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def _number_token(value: int | float) -> str:
    if isinstance(value, bool):
        raise TypeError("bool is not a JSON number")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite JSON number cannot be persisted to JSONB")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid JSON number: {value!r}") from exc
    if not number.is_finite():
        raise ValueError("non-finite JSON number cannot be persisted to JSONB")
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def _semantic_normalize(payload: Any) -> Any:
    if payload is None or isinstance(payload, (bool, str)):
        return payload
    if isinstance(payload, (int, float)):
        return {"__watch_quality_json_number__": _number_token(payload)}
    if isinstance(payload, list):
        return [_semantic_normalize(item) for item in payload]
    if isinstance(payload, dict):
        return {
            str(key): _semantic_normalize(value)
            for key, value in sorted(payload.items(), key=lambda item: str(item[0]))
        }
    raise TypeError(f"non-JSON value after snapshot: {type(payload).__name__}")


def _semantic_hash(payload: Any) -> str | None:
    if payload is None:
        return None
    normalized = _semantic_normalize(_json_snapshot(payload))
    body = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


def _numbers_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return False
    try:
        return _number_token(left) == _number_token(right)
    except ValueError:
        return False


def _semantic_differences(expected: Any, actual: Any, *, path: str = "$",
                          limit: int = MAX_DIFFS) -> list[dict[str, Any]]:
    """Strict structural diff; only equal-valued JSON numbers may differ in type/spelling."""
    differences: list[dict[str, Any]] = []

    def add(reason: str, left: Any, right: Any, location: str) -> None:
        if len(differences) < limit:
            differences.append({
                "path": location,
                "reason": reason,
                "expected": left,
                "actual": right,
            })

    def walk(left: Any, right: Any, location: str) -> None:
        if len(differences) >= limit or _numbers_equal(left, right):
            return
        if isinstance(left, dict) and isinstance(right, dict):
            left_keys, right_keys = set(left), set(right)
            for key in sorted(left_keys - right_keys):
                add("missing_key", left[key], None, f"{location}.{key}")
            for key in sorted(right_keys - left_keys):
                add("unexpected_key", None, right[key], f"{location}.{key}")
            for key in sorted(left_keys & right_keys):
                walk(left[key], right[key], f"{location}.{key}")
            return
        if isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                add("list_length", len(left), len(right), location)
            for index, (left_item, right_item) in enumerate(zip(left, right)):
                walk(left_item, right_item, f"{location}[{index}]")
            return
        if type(left) is not type(right):
            add("type", type(left).__name__, type(right).__name__, location)
        elif left != right:
            add("value", left, right, location)

    walk(_json_snapshot(expected), _json_snapshot(actual), path)
    return differences


def _packet_by_id(conn, packet_id: int) -> dict[str, Any]:
    cur = conn.cursor()
    cur.execute(
        """SELECT packet_id, symbol, generated_at, packet, superseded_by
             FROM decision_packets
            WHERE packet_id=%s""",
        (packet_id,),
    )
    row = cur.fetchone()
    if not row:
        return {"packet_id": None, "packet": None}
    packet = row[3] or {}
    return {
        "packet_id": row[0],
        "symbol": str(row[1] or "").upper(),
        "generated_at": row[2].isoformat() if row[2] else None,
        "packet": packet,
        "raw_hash": _raw_hash(packet),
        "semantic_hash": _semantic_hash(packet),
        "superseded_by": row[4],
    }


def _append(errors: list[str], role: str, message: str) -> None:
    errors.append(f"{role}:{message}")


def _rewrite(report: dict[str, Any], evidence_path: Path) -> dict[str, Any]:
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    evidence_path.chmod(0o600)
    return report


def execute(projection_path: Path, evidence_path: Path) -> dict[str, Any]:
    snapshots: dict[str, Any] = {}
    original_build = gate3.governed_builder.build_packet
    original_hash = gate3._stable_hash

    def frozen_build(symbol: str, *args, **kwargs) -> dict:
        packet = _json_snapshot(original_build(symbol, *args, **kwargs))
        snapshots[str(symbol).upper()] = packet
        return packet

    gate3.governed_builder.build_packet = frozen_build
    gate3._stable_hash = _semantic_hash
    try:
        report = gate3.execute(projection_path, evidence_path)
    finally:
        gate3.governed_builder.build_packet = original_build
        gate3._stable_hash = original_hash

    report["roundtrip_contract"] = ROUNDTRIP_CONTRACT
    legacy_status = report.get("status")
    report["legacy_status"] = legacy_status

    if legacy_status == "BLOCKED_GATE3_PREWRITE_MISMATCH":
        return _rewrite(report, evidence_path)

    sample = report.get("sample") or {}
    packet_ids = {
        role: item.get("after_packet_id")
        for role, item in sample.items()
        if item.get("after_packet_id") is not None
    }
    if len(packet_ids) != len(gate3.ROLE_ORDER):
        report["status"] = "BLOCKED_GATE3_PERSISTENCE_FAILURE"
        report["persisted_roles_before_failure"] = [
            role for role in gate3.ROLE_ORDER if role in packet_ids
        ]
        report["error"] = report.get("error") or "not all five packet ids were returned"
        return _rewrite(report, evidence_path)

    errors: list[str] = []
    representation_mismatches: list[str] = []
    readback_conn = gate3.refresh._conn()

    for role in gate3.ROLE_ORDER:
        item = sample[role]
        symbol = str(item.get("symbol") or "").upper()
        packet_id = int(item["after_packet_id"])
        expected = snapshots.get(symbol)
        if expected is None:
            _append(errors, role, f"{symbol} candidate snapshot missing")
            continue
        try:
            after = _packet_by_id(readback_conn, packet_id)
            packet = after.get("packet") or {}
            item["candidate_representation_hash"] = _raw_hash(expected)
            item["candidate_semantic_hash"] = _semantic_hash(expected)
            item["after_packet_hash"] = after.get("raw_hash")
            item["after_semantic_hash"] = after.get("semantic_hash")
            item["after_generated_at"] = after.get("generated_at")
            item["after_superseded_by"] = after.get("superseded_by")

            if after.get("packet_id") != packet_id:
                _append(errors, role, f"{symbol} exact packet id {packet_id} not found")
                continue
            if after.get("symbol") != symbol:
                _append(errors, role, f"packet {packet_id} symbol mismatch")
            if after.get("superseded_by") is not None:
                _append(errors, role, f"packet {packet_id} unexpectedly superseded")

            if _raw_hash(expected) != after.get("raw_hash"):
                representation_mismatches.append(role)
            differences = _semantic_differences(expected, packet)
            item["after_semantic_differences"] = differences
            if differences:
                _append(errors, role, f"{symbol} JSONB semantic difference at {differences[0]['path']}")
            if _semantic_hash(expected) != after.get("semantic_hash"):
                _append(errors, role, f"{symbol} semantic hash mismatch")
            if packet.get("governance_source_commit") != report.get("source_commit"):
                _append(errors, role, f"{symbol} source commit mismatch")

            gate = gate3.packet_quality.packet_gate(packet)
            conflicts = gate3.packet_quality.presentation_conflicts(packet)
            item["after_gate"] = gate
            item["after_presentation_conflicts"] = conflicts
            if conflicts:
                _append(errors, role, f"{symbol} presentation conflict: {conflicts[0]}")

            candidate = item.get("candidate") or {}
            for field, candidate_field in (
                ("quality", "rebuilt_quality"),
                ("deterministic", "rebuilt_deterministic"),
                ("new_entry_allowed", "rebuilt_new_entry_allowed"),
                ("held", "rebuilt_held"),
                ("validation_source", "validation_source"),
                ("ticket_hash", "ticket_hash"),
            ):
                if gate.get(field) != candidate.get(candidate_field):
                    _append(errors, role, f"{symbol} gate field {field} changed after persistence")

            lane_calls = gate3._model_lane_count(packet)
            reviews = (packet.get("ticket_review") or {}).get("reviews") or {}
            if lane_calls:
                _append(errors, role, f"{symbol} readback recorded {lane_calls} model lane calls")
            if reviews:
                _append(errors, role, f"{symbol} readback recorded inline ticket reviews")
        except BaseException as exc:
            _append(errors, role, f"{symbol} verification raised {type(exc).__name__}: {str(exc)[:300]}")

    report["persisted_roles"] = list(gate3.ROLE_ORDER)
    report["representation_hash_mismatches"] = representation_mismatches
    report["verification_errors"] = errors
    if errors:
        report["status"] = "BLOCKED_GATE3_POSTWRITE_VERIFICATION"
        report["error"] = errors[0]
    else:
        report["status"] = "PASS_GATE3_BOUNDED_LOCAL_REBUILD"
        report.pop("error", None)
        report.pop("persisted_roles_before_failure", None)
    return _rewrite(report, evidence_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projection-json", required=True)
    parser.add_argument("--evidence-json", required=True)
    args = parser.parse_args()
    evidence_path = Path(args.evidence_json).expanduser().resolve()
    report = execute(Path(args.projection_json).expanduser().resolve(), evidence_path)
    public = {
        "contract": report.get("contract"),
        "roundtrip_contract": report.get("roundtrip_contract"),
        "source_commit": report.get("source_commit"),
        "generated_at": report.get("generated_at"),
        "status": report.get("status"),
        "legacy_status": report.get("legacy_status"),
        "sample": {
            role: {
                "symbol": item.get("symbol"),
                "projected_quality": item.get("projected_quality"),
                "candidate": item.get("candidate"),
                "after_packet_id": item.get("after_packet_id"),
                "candidate_representation_hash": item.get("candidate_representation_hash"),
                "candidate_semantic_hash": item.get("candidate_semantic_hash"),
                "after_packet_hash": item.get("after_packet_hash"),
                "after_semantic_hash": item.get("after_semantic_hash"),
                "after_semantic_differences": item.get("after_semantic_differences"),
                "after_gate": item.get("after_gate"),
                "after_presentation_conflicts": item.get("after_presentation_conflicts"),
            }
            for role, item in (report.get("sample") or {}).items()
        },
        "prewrite_errors": report.get("prewrite_errors"),
        "verification_errors": report.get("verification_errors"),
        "representation_hash_mismatches": report.get("representation_hash_mismatches"),
        "persisted_roles_before_failure": report.get("persisted_roles_before_failure"),
        "persisted_roles": report.get("persisted_roles"),
        "error": report.get("error"),
        "authority": report.get("authority"),
        "evidence_json": str(evidence_path),
    }
    print(json.dumps(public, indent=2, sort_keys=True, default=str))
    print(f"final_status|{report.get('status')}")
    if report.get("status") != "PASS_GATE3_BOUNDED_LOCAL_REBUILD":
        raise SystemExit(3)


if __name__ == "__main__":
    main()
