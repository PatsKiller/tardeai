"""LQ-20261107-114: a shadow lane is never n8n-live, even when its registry row is an ACTIVE n8n-kind row.

The config page counted jsonl-archive-rotate as "n8n live". Its registry row is scheduler.kind n8n, state ACTIVE,
scheduler.stage shadow, dispatch.mode dry_run, and it is not on the relay live list. report_n8n_cutover_outcomes
defined native as kind == n8n and state == ACTIVE, ignoring stage and dispatch mode, so the shadow row counted as live.
The relay-list module (scripts/lib/n8n_relay_live_lanes.py) already requires stage None for a native row.

Fixture-only: no crontab, no ledger, no DB, no gh.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import report_n8n_cutover_outcomes as R  # noqa: E402


def _states(reg_row: dict, live: list[str]) -> dict:
    reg = {"jsonl-archive-rotate": reg_row}
    cron = {"active": [], "commented": []}
    return R.lane_states(registry_rows=reg, live_lanes=live, cron=cron, families={}, dispositions={}, holds={},
                         outcomes={}, effect_events={})["jsonl-archive-rotate"]


def _shadow_row() -> dict:
    # the registry row as it stands in config/lane_registry.json (2026-11-07)
    return {"scheduler": {"kind": "n8n", "expression": "dispatcher", "match": "scripts/ops/jsonl_archive_rotate.py",
                          "stage": "shadow", "wave": "W4"},
            "dispatch": {"mode": "dry_run", "class": "hygiene", "priority": 3},
            "state": "ACTIVE"}


def test_shadow_active_n8n_row_is_not_n8n_live():
    st = _states(_shadow_row(), live=[])
    assert st["relay_live"] is False
    assert st["measure_combo"] == ""  # not an n8n-live lane, so it has no S/E/U measure
    assert st["status"] != "N8N_NATIVE"
    assert st["sched_evidence"] != "n8n_native_row"


def test_native_row_without_stage_still_counts_as_n8n_native():
    row = {"scheduler": {"kind": "n8n", "expression": "dispatcher", "match": "x"}, "state": "ACTIVE"}
    st = _states(row, live=[])
    # control: a native n8n row with no stage keeps its existing n8n-live meaning
    assert st["measure_combo"] != ""
    assert st["sched_evidence"] == "n8n_native_row"


def test_canary_on_paper_is_not_n8n_live():
    # canary stage, dispatch dry_run, not on the relay list: n8n posts a dry run, so it is not live
    row = {"scheduler": {"kind": "n8n", "expression": "dispatcher", "stage": "canary"},
           "dispatch": {"mode": "dry_run"}, "state": "ACTIVE"}
    st = _states(row, live=[])
    assert st["measure_combo"] == ""
    assert st["status"] != "N8N_NATIVE"


def test_relay_listed_shadow_lane_still_counts_as_relay_live():
    # the relay list is the operator's promotion switch; a listed lane keeps its existing live meaning
    st = _states(_shadow_row(), live=["jsonl-archive-rotate"])
    assert st["relay_live"] is True
    assert st["measure_combo"] != ""
