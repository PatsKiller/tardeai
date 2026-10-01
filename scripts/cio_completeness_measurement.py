#!/usr/bin/env python3
"""Measure CIO source/operator coverage without manufacturing runtime proof."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_operator_evidence import build_operator_evidence  # noqa: E402

PANEL = ROOT / "apps/command-center-v3/src/components/cio/CioOperatorEvidencePanel.tsx"
LINEAGE_PANEL = ROOT / "apps/command-center-v3/src/components/cio/CioDecisionLineagePanel.tsx"
CIO_HUB = ROOT / "apps/command-center-v3/src/pages/CioHub.tsx"


def _ui_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in (PANEL, LINEAGE_PANEL, CIO_HUB) if path.is_file())


def _label(state: str) -> str:
    return {
        "LIVE": "LIVE",
        "PARTIAL": "SOURCE_ONLY",
        "UNWIRED": "UNKNOWN",
        "DARK": "UNKNOWN",
        "UNKNOWN": "UNKNOWN",
    }.get(state, "UNKNOWN")


def build_measurement(*, now: str | None = None) -> dict[str, Any]:
    composed = now or datetime.now(timezone.utc).isoformat()
    evidence = build_operator_evidence(now=composed)
    blocks = evidence.get("blocks") or {}
    ui = _ui_text()

    produced: list[str] = []
    if blocks.get("research", {}).get("artifacts") is not None:
        produced.append("research_provenance")
    if blocks.get("institutional_cognition", {}).get("items") is not None:
        produced.append("institutional_cognition")
    if blocks.get("learning", {}).get("maturity_state") is not None:
        produced.append("learning_cockpit")
    if blocks.get("capability_coverage", {}).get("rows") is not None:
        produced.append("capability_coverage")
    produced.extend(f"capability:{row['capability']}" for row in blocks.get("capability_coverage", {}).get("rows", []))
    produced.append("decision_lineage")

    surfaced: list[str] = []
    if "research-used-group" in ui and "research-retrieved-group" in ui and "research-rejected-group" in ui:
        surfaced.append("research_provenance")
    if "cio-institutional-cognition" in ui and "institutional-cognition" in ui:
        surfaced.append("institutional_cognition")
    if "cio-learning-cockpit" in ui and "learning-cockpit" in ui:
        surfaced.append("learning_cockpit")
    if "cio-capability-coverage" in ui and "capability-coverage" in ui:
        surfaced.append("capability_coverage")
        surfaced.extend(f"capability:{row['capability']}" for row in blocks.get("capability_coverage", {}).get("rows", []))
    if "/api/v3/cio/decision/" in ui and "cio-decision-lineage" in ui:
        surfaced.append("decision_lineage")

    produced_set = set(produced)
    surfaced_set = set(surfaced)
    produced_not_surfaced = sorted(produced_set - surfaced_set)
    unproven: list[dict[str, Any]] = []
    for row in blocks.get("capability_coverage", {}).get("rows", []):
        state = str(row.get("state") or row.get("current_status") or "UNKNOWN")
        if state != "LIVE":
            unproven.append({
                "name": f"capability:{row.get('capability')}",
                "runtime_state": state,
                "ui_label": _label(state),
                "reason": row.get("reason") or "runtime proof unavailable",
            })
    for artifact in blocks.get("research", {}).get("artifacts", []):
        if artifact.get("status") != "USED_IN_JUDGMENT":
            unproven.append({
                "name": f"research:{artifact.get('artifact_id')}",
                "runtime_state": artifact.get("status") or "UNKNOWN",
                "ui_label": "UNKNOWN",
                "reason": "canonical use receipt does not prove judgment use",
            })

    counts = {state: 0 for state in ("LIVE", "PARTIAL", "UNWIRED", "DARK", "UNKNOWN")}
    for row in blocks.get("capability_coverage", {}).get("rows", []):
        state = str(row.get("state") or row.get("current_status") or "UNKNOWN")
        counts[state] = counts.get(state, 0) + 1
    return {
        "schema": "CIOCompletenessMeasurement@v1",
        "authority": "READ_ONLY_ADVISORY",
        "composition_as_of": composed,
        "cio_capabilities_produced": sorted(produced_set),
        "cio_capabilities_operator_visible": sorted(surfaced_set),
        "produced_not_surfaced": produced_not_surfaced,
        "surfaced_not_runtime_proven": unproven,
        "critical_edges_live": counts["LIVE"],
        "critical_edges_partial": counts["PARTIAL"],
        "critical_edges_unwired": counts["UNWIRED"],
        "critical_edges_dark": counts["DARK"],
        "critical_edges_unknown": counts["UNKNOWN"],
        "source_acceptance": {
            "produced_not_surfaced_zero": not produced_not_surfaced,
            "runtime_unproven_items_labelled": all(item.get("ui_label") in {"SHADOW", "PREVIEW", "SOURCE_ONLY", "UNKNOWN", "RETRIEVED", "REJECTED"} for item in unproven),
            "runtime_unproven_count": len(unproven),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = build_measurement()
    print(json.dumps(report, indent=2, sort_keys=True))
    if not args.json:
        print(f"produced_not_surfaced={len(report['produced_not_surfaced'])}")
        print(f"surfaced_not_runtime_proven={len(report['surfaced_not_runtime_proven'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
