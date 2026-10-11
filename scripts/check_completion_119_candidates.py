#!/usr/bin/env python3
"""Read-only source check for the held 119-lane remediation packets.

These documents never authorize executor configuration or runtime admission.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKETS = ROOT / "docs/implementation/n8n-maturity/completion-119"


def findings(scope: dict, packets: list[dict]) -> list[str]:
    expected = [r["lane_id"] for r in scope["rows"]]
    errors = []
    if len(expected) != 119 or len(set(expected)) != len(expected):
        errors.append("scope must contain 119 distinct lane ids")
    seen = []
    for packet in packets:
        if packet.get("evidence_class") != "SOURCE_ONLY" or packet.get("runtime") != "NOT_MEASURED":
            errors.append("packet must remain SOURCE_ONLY / runtime NOT_MEASURED")
        if packet.get("operational_admission") or packet.get("operational_admissions_added", 0):
            errors.append("packet cannot apply operational admission")
        for row in packet.get("rows", []):
            lane = row["lane_id"]
            seen.append(lane)
            if row.get("evidence_class") != "SOURCE_ONLY":
                errors.append(f"{lane}: source evidence class required")
            if row.get("operational_configuration_changed") or row.get("admission_status", "NOT_APPLIED") != "NOT_APPLIED":
                errors.append(f"{lane}: operational configuration must stay held")
            scheduler = row.get("scheduler_unchanged", row.get("current_scheduler", row.get("scheduler_retained", {})))
            proposed_scheduler = (row.get("registry_candidate") or {}).get("scheduler", {})
            if scheduler.get("kind") == "systemd" and proposed_scheduler.get("kind") == "cron":
                errors.append(f"{lane}: timer admission cannot fabricate a cron identity")
            for field in ("health_contract_candidate", "proposed_candidate"):
                candidate = row.get(field)
                if not candidate:
                    continue
                if candidate.get("status") != "DRAFT" or candidate.get("reviewer") or candidate.get("reviewed_by"):
                    errors.append(f"{lane}: candidate must remain unreviewed DRAFT")
                if candidate.get("admission_enabled") or candidate.get("automatic_promotion"):
                    errors.append(f"{lane}: candidate cannot enable or promote itself")
            candidate = row.get("allowlist_candidate") or row.get("proposed_candidate")
            if candidate and candidate.get("live_arg") is not None:
                errors.append(f"{lane}: candidate cannot authorize live arguments")
    if len(seen) != len(set(seen)):
        errors.append("duplicate lane in candidate packets")
    if set(seen) != set(expected):
        errors.append(f"scope mismatch: missing={sorted(set(expected)-set(seen))} extra={sorted(set(seen)-set(expected))}")
    return errors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--directory", type=Path, default=PACKETS)
    args = parser.parse_args(argv)
    try:
        scope = json.loads((args.directory / "scope-119.json").read_text())
        packets = [json.loads((args.directory / f"candidates-{group}.json").read_text())
                   for group in ("01-03", "04-06", "07-08")]
        errors = findings(scope, packets)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"completion-119 CANNOT_RUN: {type(exc).__name__}")
        return 2
    for error in errors:
        print(error)
    print(f"completion-119 source candidates: {len(scope['rows'])} lanes, {len(errors)} findings; no runtime acceptance")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
