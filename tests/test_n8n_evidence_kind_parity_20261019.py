"""One evidence-kind vocabulary for N8nExpectedOutput@v1 (2026-10-19).

The runtime verdict (scripts/lib/n8n_output_verdict.py) accepted "file" while the FW-M6 checker
(scripts/check_n8n_workflow_framework.py) accepted "file_artifact"; FW-M6 applies both, so no contract could cite a
file as evidence (found fixing PR #1863). The design doc (N8N_CONTRACTS_DESIGN.md FW-M6) names file_artifact.
Receipt `output_evidence` items (e.g. {"kind": "file"} in crontab_snapshot_lane) are a different field and are not
checked against this set."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_n8n_workflow_framework as FW  # noqa: E402
from scripts.lib import n8n_output_verdict as OV  # noqa: E402


def _base_contract() -> dict:
    contracts = json.loads((ROOT / "config/n8n_health_contracts.json").read_text())["contracts"]
    c = next(c for c in contracts if c["id"] == "n8n-comms-intent-consumer")
    assert FW._check_expected_output(c)["status"] == FW.PASS  # the baseline passes FW-M6 as committed
    return copy.deepcopy(c)


def _with_extra_evidence(kind: str) -> dict:
    c = _base_contract()
    c["expected_output"]["evidence"].append({"kind": kind, "ref": "data/runtime/example_latest.json"})
    return c


def test_the_runtime_and_checker_vocabularies_are_the_same_set():
    assert set(OV.EVIDENCE_KINDS) == set(FW.EVIDENCE_KINDS)
    assert "file_artifact" in OV.EVIDENCE_KINDS and "file" not in OV.EVIDENCE_KINDS


def test_a_file_artifact_item_passes_both_validators():
    c = _with_extra_evidence("file_artifact")
    assert OV.validate_expected_output(c["expected_output"]) == []
    assert FW._check_expected_output(c)["status"] == FW.PASS


def test_a_bare_file_item_is_refused_by_both():
    c = _with_extra_evidence("file")
    assert OV.validate_expected_output(c["expected_output"])
    assert FW._check_expected_output(c)["status"] == FW.FAIL


def test_no_committed_contract_cites_the_retired_kind():
    contracts = json.loads((ROOT / "config/n8n_health_contracts.json").read_text())["contracts"]
    kinds = {e.get("kind") for c in contracts for e in ((c.get("expected_output") or {}).get("evidence") or [])}
    assert "file" not in kinds and kinds <= set(OV.EVIDENCE_KINDS)
