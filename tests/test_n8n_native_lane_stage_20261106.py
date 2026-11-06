"""ANCHOR: N8N_NATIVE_LANE_STAGE_20261106. n8n program 0.4b-fix: the four native n8n lanes are on the relay live list.

Since 2026-10-30/31 the relay builds its live list from the registry render. n8n-incident-fanin, n8n-pilot-dispatch,
n8n-research-intake-consumer and crontab-snapshot-for-health-agent had no scheduler.stage, so the render dropped them
(native_n8n_no_stage) and the relay refused every fire with relay_live_not_enabled (HTTP 403), every 5-20 minutes,
for a week. Their rows now say stage canary, like the other native n8n rows. Reads the committed registry and
allowlist; no host file, no relay, no n8n.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_relay_live_lanes as R  # noqa: E402
from tests.support.n8n_native_lane_stage import WORKFLOWS as FOUR  # noqa: E402


def _load(name: str) -> dict:
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


def _rows() -> dict:
    return {r["lane_id"]: r for r in _load("lane_registry.json")["lanes"]}


def test_the_four_rows_name_their_workflow_and_a_live_stage():
    rows = _rows()
    for lane, wid in FOUR.items():
        sched = rows[lane]["scheduler"]
        assert sched["kind"] == "n8n" and sched["expression"] == wid
        assert sched.get("stage") == "canary", lane
        assert rows[lane]["state"] == "ACTIVE"


def test_the_committed_render_lists_the_four_and_drops_none_for_a_missing_stage():
    lanes, excluded = R.registry_live_lanes(_load("lane_registry.json"), _load("n8n_run_allowlist.json"))
    assert set(FOUR) <= set(lanes)
    assert not [k for k, why in excluded.items() if why == "native_n8n_no_stage"]


def test_this_file_is_registered_in_a_ci_gate():
    from scripts.lib import ci_gates  # noqa: PLC0415 -- needs ROOT on sys.path first

    assert "tests/test_n8n_native_lane_stage_20261106.py" in ci_gates.registry_text(ROOT)
