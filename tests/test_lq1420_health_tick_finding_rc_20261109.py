"""ANCHOR: lq1420_health_tick_finding_rc — LQ-20261107-1420.

pipeline-freshness-monitor and pipeline-watchdog exit 3 (EXIT_FINDING) when they
find something. health_tick reads rc 1 as a crash, so each step must declare
finding_rc [3], the same way pipeline-liveness-report already does. Exit 1 stays
a crash.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEPS = json.loads((ROOT / "config" / "health_tick_steps.json").read_text(encoding="utf-8"))["steps"]
BY_ID = {row["step_id"]: row for row in STEPS}


def test_freshness_and_watchdog_declare_finding_rc_3():
    for step_id in ("pipeline-freshness-monitor", "pipeline-watchdog", "pipeline-liveness-report"):
        row = BY_ID[step_id]
        assert row["finding_rc"] == [3], step_id
        assert 1 not in row["finding_rc"]
