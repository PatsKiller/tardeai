"""OPTIONAL (operator decision pending, 2026-10-10): keep trade-ai-scalp-live out of the LLM failure-diagnosis catalogue.

The scalp lane is the live broker-adjacent lane (AGENTS.md §23.3 exception). It was in the catalogue as suggest_only,
so its scrubbed error text and log tail would have gone to an external model. With this change the diagnoser skips it
(`lane_not_in_catalogue`): no evidence pack, no model call. Its failures still become SIEM rows (the bridge is
unaffected) and still reach the operator through the fan-in. Hermetic: repo files only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import n8n_failure_diagnosis as D  # noqa: E402
from scripts.lib import n8n_remediation_catalogue as C  # noqa: E402

SCALP = "trade-ai-scalp-live"
DOC = json.loads((ROOT / "config" / "n8n_remediation_catalogue.json").read_text(encoding="utf-8"))


def test_scalp_is_excluded_and_the_committed_catalogue_agrees():
    assert SCALP in C.DIAGNOSIS_EXCLUDED_LANES and SCALP in C.NEVER_LANES
    lanes = [e["lane_id"] for e in DOC["lanes"]]
    assert SCALP not in lanes
    assert C.validate_catalogue(DOC) == []
    assert DOC["summary"] == C.summarise(DOC["lanes"])


def test_validator_refuses_a_catalogue_that_carries_an_excluded_lane():
    entry = {"lane_id": SCALP, "severity": "Critical", "default_action": C.SUGGEST_ONLY, "actions": []}
    bad = {**DOC, "lanes": [*DOC["lanes"], entry]}
    assert any("excluded from LLM diagnosis" in e for e in C.validate_catalogue(bad))


def test_the_generator_never_targets_an_excluded_lane():
    inv = {"I1": {"source": "n8n", "active": "yes", "job_name": SCALP}, "I2": {"source": "n8n", "active": "yes",
                                                                           "job_name": "storage-watch"}}
    got = C.target_lanes(inv, [SCALP], [])
    assert SCALP not in got and "storage-watch" in got and C.SELFTEST_LANE in got


def test_the_diagnoser_skips_a_scalp_siem_row_without_a_model_call():
    catalogue = C.load_catalogue(ROOT / "config" / "n8n_remediation_catalogue.json")
    row = {"id": 1, "component": f"n8n:{SCALP}", "event_type": "NO_OUTPUT", "severity": "CRITICAL", "message": "x"}
    ok, skipped = D.eligible([row], catalogue, min_severity="WARN", done={})
    assert ok == [] and skipped == [{"id": 1, "lane": SCALP, "reason": "lane_not_in_catalogue"}]
