#!/usr/bin/env python3
"""Audit source-declared contract baselines. No runtime, network, credentials or DB.

The correction helper returns a copy for review; the CLI only prints an audit.
It preserves numeric baselines and never grants review or scheduling authority.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_n8n_health_contracts import baseline  # noqa: E402
from scripts.lib.cron_schedule import parse as parse_cron  # noqa: E402
from scripts.lib.n8n_momentum_lifecycle import contract_body_digest  # noqa: E402

NO_CONSUMER_REASON = "Operator-run read-only source baseline audit; its printed coverage is reviewed by the operator, never a scheduler or authority writer."
FIELDS = ("timeout_s", "freshness_degraded_after_h", "freshness_failed_after_h")
AUDIT_REL = "docs/implementation/n8n-maturity/reconciliation-20261012/N8N_CONTRACT_BASELINE_CORRECTION_20261012.json"


def positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def baseline_errors(contract: Mapping) -> list[str]:
    """Every current catalogue row has bounded work and recurring health observation."""
    base = contract.get("baseline") or {}
    errors = [
        f"baseline.{field} must be finite and positive" for field in FIELDS if not positive_number(base.get(field))
    ]
    degraded, failed = base.get(FIELDS[1]), base.get(FIELDS[2])
    if positive_number(degraded) and positive_number(failed) and failed <= degraded:
        errors.append("baseline.freshness_failed_after_h must exceed freshness_degraded_after_h")
    return errors


def minute_cadence(expression: Any) -> float | None:
    """Exact regular minute cadence within the source calendar, never an overnight SLO."""
    if not isinstance(expression, str):
        return None
    fields = expression.split()
    if len(fields) != 5:
        return None
    try:
        parse_cron(expression)
    except ValueError:
        return None
    if fields[0] == "*":
        return 1 / 60
    match = re.fullmatch(r"\*/([1-9][0-9]?)", fields[0])
    if match and 60 % int(match[1]) == 0:
        return int(match[1]) / 60
    return None


def source_values(contract: Mapping, registry: Mapping, allowlist: Mapping, workflows: Mapping) -> dict:
    cid = str(contract.get("id") or "")
    row, entry = registry.get(cid, {}), allowlist.get(cid, {})
    sources: dict[str, Any] = {}
    timeout = entry.get("timeout_s")
    if positive_number(timeout):
        sources["timeout_s"] = {
            "value": timeout,
            "path": "config/n8n_run_allowlist.json",
            "pointer": f"lanes.{cid}.timeout_s",
        }
    elif contract.get("kind") == "host_monitor":
        # These fixed public source install-line declarations already impose GNU timeout.
        line = row.get("scheduler", {}).get("install_line", "")
        values = re.findall(r"\btimeout\s+(?:-k\s+[0-9]+\s+)?([0-9]+)\s", line)
        if len(values) == 1 and int(values[0]) > 0:
            sources["timeout_s"] = {
                "value": int(values[0]),
                "path": "config/lane_registry.json",
                "pointer": f"lanes[{cid}].scheduler.install_line:timeout",
            }

    if contract.get("kind") == "generic_workflow":
        workflow = workflows.get(cid, {})
        timeout = workflow.get("settings", {}).get("executionTimeout")
        if positive_number(timeout):
            sources["timeout_s"] = {
                "value": timeout,
                "path": f"docs/implementation/n8n-maturity/workflows/{cid}.json",
                "pointer": "settings.executionTimeout",
            }
        expressions = [
            interval.get("expression")
            for node in workflow.get("nodes", [])
            if node.get("type") == "n8n-nodes-base.scheduleTrigger"
            for interval in node.get("parameters", {}).get("rule", {}).get("interval", [])
            if interval.get("field") == "cronExpression"
        ]
        cadences = [minute_cadence(expression) for expression in expressions]
        if len(cadences) == 1 and positive_number(cadences[0]):
            sources["cadence_h"] = {
                "value": cadences[0],
                "expression": expressions[0],
                "path": f"docs/implementation/n8n-maturity/workflows/{cid}.json",
                "pointer": "nodes[scheduleTrigger].parameters.rule.interval",
            }
    else:
        exact_cadence = minute_cadence(row.get("scheduler", {}).get("expression"))
        cadence = exact_cadence or row.get("expected_cadence_hours")
        if positive_number(cadence):
            sources["cadence_h"] = {
                "value": cadence,
                "path": "config/lane_registry.json",
                "pointer": f"lanes[{cid}]." + ("scheduler.expression" if exact_cadence else "expected_cadence_hours"),
            }
    return sources


def correct_catalogue(
    catalogue: Mapping, registry: Mapping, allowlist: Mapping, workflows: Mapping, *, as_of: date
) -> tuple[dict, dict]:
    """Correct only incomplete bodies from fixed sources, keeping actual review pending."""
    corrected = copy.deepcopy(catalogue)
    records = []
    for contract in corrected.get("contracts", []):
        original = copy.deepcopy(contract)
        base = contract.setdefault("baseline", {})
        before_errors = baseline_errors(original)
        sources = source_values(contract, registry, allowlist, workflows)
        changed = []
        if before_errors:
            defaults = baseline(
                [],
                cadence_h=sources.get("cadence_h", {}).get("value"),
                timeout_s=sources.get("timeout_s", {}).get("value"),
                cls=str(base.get("class") or contract.get("kind")),
                as_of=as_of,
            )
            for field in FIELDS:
                if not positive_number(base.get(field)) and positive_number(defaults.get(field)):
                    base[field] = defaults[field]
                    changed.append(field)
            if (
                contract.get("kind") == "generic_workflow"
                and positive_number(defaults.get(FIELDS[2]))
                and base.get(FIELDS[2]) != defaults[FIELDS[2]]
            ):
                base[FIELDS[2]] = defaults[FIELDS[2]]
                changed.append(FIELDS[2])
            # The six shared generic templates copied a five-minute failed threshold,
            # even for five-minute ticks. Revise the conflict only in a held DRAFT body.
            if (
                positive_number(base.get(FIELDS[1]))
                and positive_number(base.get(FIELDS[2]))
                and base[FIELDS[2]] <= base[FIELDS[1]]
                and positive_number(defaults.get(FIELDS[2]))
            ):
                base[FIELDS[2]] = defaults[FIELDS[2]]
                changed.append(FIELDS[2])
            if changed:
                base["source_derived_correction"] = {
                    "as_of": as_of.isoformat(),
                    "evidence": AUDIT_REL,
                    "basis": "SOURCE_DECLARATION_ONLY; existing builder 2x/3x cadence policy, round(., 3)",
                    "calendar": "Cadence thresholds apply within the existing source calendar; off-session and market-day requirements remain unchanged.",
                    "runtime_and_business_baseline": "NOT_MEASURED; no ledger, expected-fire or output observations collected by this audit",
                }
            if changed or original.get("status") == "REVIEWED":
                old_review = copy.deepcopy(original.get("review"))
                review = copy.deepcopy(old_review) if isinstance(old_review, dict) else {}
                if original.get("status") == "REVIEWED":
                    contract["status"] = "DRAFT"
                    review = {
                        "status": "PENDING_BODY_REVIEW",
                        "reviewed_by": None,
                        "decision_ref": None,
                        "contract_body_sha256": None,
                        "previous_review": {
                            "status": "REVIEWED",
                            "body_sha256": contract_body_digest(original),
                            "metadata": old_review,
                        },
                    }
                review["baseline_correction_requires_review"] = True
                review["baseline_correction_changed_fields"] = changed
                review["proposed_contract_body_sha256"] = contract_body_digest(contract)
                contract["review"] = review
        after_errors = baseline_errors(contract)
        records.append(
            {
                "id": contract.get("id"),
                "kind": contract.get("kind"),
                "status_before": original.get("status"),
                "status_after": contract.get("status"),
                "applicability": {
                    field: "REQUIRED: bounded work and recurring health observation in current catalogue"
                    for field in FIELDS
                },
                "before": {field: original.get("baseline", {}).get(field) for field in FIELDS},
                "after": {field: contract.get("baseline", {}).get(field) for field in FIELDS},
                "prior_baseline": original.get("baseline") if changed else None,
                "source_values": sources if before_errors else {},
                "changed_fields": changed,
                "body_sha256_before": contract_body_digest(original),
                "body_sha256_after": contract_body_digest(contract),
                "errors_before": before_errors,
                "errors_after": after_errors,
                "collection_action": "Collect exact bounded timeout and calendar/cadence from owner-approved source; keep DRAFT until resolved"
                if after_errors
                else None,
                "review_action": "Fresh independent substantive-body review required; historical review is preserved, no decision is fabricated"
                if before_errors
                else None,
            }
        )
    counts = {
        field: {
            "required": len(records),
            "present_before": sum(positive_number(row["before"][field]) for row in records),
            "present_after": sum(positive_number(row["after"][field]) for row in records),
            "fixed": sum(field in row["changed_fields"] for row in records),
            "missing_filled": sum(
                field in row["changed_fields"] and not positive_number(row["before"][field]) for row in records
            ),
            "existing_value_revised": sum(
                field in row["changed_fields"] and positive_number(row["before"][field]) for row in records
            ),
            "unresolved": sum(not positive_number(row["after"][field]) for row in records),
            "not_applicable": 0,
        }
        for field in FIELDS
    }
    audit = {
        "schema": "N8nContractBaselineCorrection@v1",
        "as_of": as_of.isoformat(),
        "authority": "SOURCE_ONLY_PROPOSED_BODY_CORRECTION; no runtime, review, owner or admission authority",
        "contracts_total": len(records),
        "fields": counts,
        "contracts_changed": sum(bool(row["changed_fields"]) for row in records),
        "changed_reviewed_bodies_held_draft": sum(
            bool(row["changed_fields"]) and row["status_before"] == "REVIEWED" for row in records
        ),
        "contracts_with_unresolved_baselines": sum(bool(row["errors_after"]) for row in records),
        "not_applicable_reasons": [],
        "records": records,
    }
    return corrected, audit


def load_sources(root: Path) -> tuple[dict, dict, dict, dict]:
    def read(relative: str) -> dict:
        return json.loads((root / relative).read_text(encoding="utf-8"))

    catalogue = read("config/n8n_health_contracts.json")
    registry = {row["lane_id"]: row for row in read("config/lane_registry.json")["lanes"]}
    allow = read("config/n8n_run_allowlist.json")["lanes"]
    allow = allow if isinstance(allow, dict) else {row["lane_id"]: row for row in allow}
    workflows = {}
    for index_rel in (
        "docs/implementation/n8n-maturity/workflows/INDEX.json",
        "docs/implementation/n8n-maturity/observers/INDEX.json",
    ):
        for row in read(index_rel).get("workflows", []):
            filename = row.get("file", "")
            if not re.fullmatch(r"[a-z0-9-]+\.json", filename):
                raise ValueError("invalid public workflow source filename")
            workflows[row["id"]] = read("docs/implementation/n8n-maturity/workflows/" + filename)
    return catalogue, registry, allow, workflows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    catalogue, registry, allowlist, workflows = load_sources(args.root)
    _, audit = correct_catalogue(catalogue, registry, allowlist, workflows, as_of=date.today())
    # Report current acceptance, not the uncommitted result returned by the helper.
    current_errors = {row["id"]: baseline_errors(row) for row in catalogue["contracts"] if baseline_errors(row)}
    print(json.dumps({"current_errors": current_errors, "proposed_correction_audit": audit}, indent=2, sort_keys=True))
    return 1 if current_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
