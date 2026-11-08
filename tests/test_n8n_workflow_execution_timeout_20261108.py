"""Allowlisted ACTIVE n8n workflows must set settings.executionTimeout.

The bound is the lane allowlist timeout_s plus 30 seconds on a per-lane workflow.
A shared workflow (the dispatcher, the fabric learner) already carries its own
executionTimeout; this test only requires that value to be a positive int.

ANCHOR: N8N_WORKFLOW_EXECUTION_TIMEOUT_20261108
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "docs" / "implementation" / "n8n-parallel" / "workflows" / "generated"
DISPATCHER = ROOT / "docs" / "implementation" / "n8n-maturity" / "workflows" / "tradeai-dispatcher.json"
FABRIC = (
    ROOT / "docs" / "implementation" / "n8n-maturity" / "workflows" / "fabric"
    / "tradeai-fabric-hermes-learning.json"
)
MARGIN_S = 30
NAMED = (
    "n8n-incident-fanin",
    "n8n-pilot-dispatch",
    "n8n-research-intake-consumer",
    "crontab-snapshot-for-health-agent",
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _workflow_by_id() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in GENERATED.glob("*.json"):
        if path.name == "INDEX.json":
            continue
        doc = _load(path)
        wid = doc.get("id")
        if isinstance(wid, str):
            found[wid] = path
    return found


def _source(expression: str, by_id: dict[str, Path]) -> Path | None:
    if expression == "dispatcher":
        return DISPATCHER
    if expression == "tradeai-fabric-hermes-learning":
        return FABRIC
    return by_id.get(expression)


def test_allowlisted_active_workflows_set_execution_timeout():
    registry = _load(ROOT / "config" / "lane_registry.json")
    allow = {
        row["lane_id"]: row
        for row in _load(ROOT / "config" / "n8n_run_allowlist.json")["lanes"]
        if isinstance(row, dict) and row.get("lane_id")
    }
    by_id = _workflow_by_id()
    problems: list[str] = []
    seen: set[str] = set()
    for row in registry["lanes"]:
        if row.get("state") != "ACTIVE" or (row.get("scheduler") or {}).get("kind") != "n8n":
            continue
        lane_id = row["lane_id"]
        entry = allow.get(lane_id)
        if entry is None:
            continue
        expression = str((row.get("scheduler") or {}).get("expression") or "")
        path = _source(expression, by_id)
        if path is None or not path.is_file():
            problems.append(f"{lane_id}: no workflow JSON for expression {expression!r}")
            continue
        seen.add(lane_id)
        doc = _load(path)
        timeout = (doc.get("settings") or {}).get("executionTimeout")
        per_lane = doc.get("name") == lane_id
        if per_lane:
            expect = int(entry["timeout_s"]) + MARGIN_S
            if timeout != expect:
                problems.append(
                    f"{lane_id}: executionTimeout {timeout!r} != allowlist timeout_s "
                    f"{entry['timeout_s']} + {MARGIN_S} ({expect}) in {path.name}"
                )
        elif not isinstance(timeout, int) or timeout < 1:
            problems.append(f"{lane_id}: shared workflow {path.name} lacks executionTimeout ({timeout!r})")
    missing = [lane_id for lane_id in NAMED if lane_id not in seen]
    assert not missing, missing
    assert not problems, "\n".join(problems)
