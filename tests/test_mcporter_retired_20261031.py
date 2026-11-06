"""Operator 2026-10-31: "turn off the mcporter job, we don't need it" — the lane is RETIRED and hand-curated.

The other two drift rows from the 2026-10-31 stuck sweep stay unruled on purpose: retiring the iris-taxonomy timer
is open operator decision O-4, and db-retention is data-retention policy (AGENTS §17). Both remain ACTIVE +
DISABLED_UNRULED + operator_decision_pending, so their silence stays a finding.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts import reconcile_lane_registry as R

ROOT = Path(__file__).resolve().parents[1]


def _lanes():
    return {r["lane_id"]: r for r in json.loads((ROOT / "config" / "lane_registry.json").read_text())["lanes"]}


def test_mcporter_is_retired_by_the_operator_and_hand_curated():
    row = _lanes()["mcporter-token-refresh"]
    assert row["state"] == "RETIRED" and row.get("generated_by") != R.GENERATOR_VERSION
    assert "turn off the mcporter job, we don't need it" in row["state_reason"]
    assert row["scheduler"]["expression"] == "mcporter-token-refresh.timer"


def test_unruled_drift_rows_stay_unruled():
    lanes = _lanes()
    for lid in ("tradeai-iris-taxonomy", "db-retention-timer"):
        assert lanes[lid]["state"] == "ACTIVE" and lanes[lid]["status"] == "DISABLED_UNRULED", lid
        assert lanes[lid]["operator_decision_pending"] is True, lid
