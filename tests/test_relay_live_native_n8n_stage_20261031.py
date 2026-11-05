"""ANCHOR: RELAY_LIVE_NATIVE_N8N_STAGE_20261031. A native n8n lane with no scheduler.stage is named, never dropped silently.

2026-10-31 13:20 ET: release 04f739254 carried an ACTIVE AGENTS.md header, so the relay switched from the host-file
live list to the registry render. Four ACTIVE native n8n lanes (n8n-incident-fanin, n8n-pilot-dispatch,
n8n-research-intake-consumer, crontab-snapshot-for-health-agent) had an allowlist live_arg but no scheduler.stage;
the render left them off with no trace and the relay refused every fire (relay_live_not_enabled), so the Jobs page
showed them Missed. The render must still not widen, but it must say which lanes it dropped and why.

Hermetic: fixture registry/allowlist dicts and a tmp_path root; never the live release or ~/.config.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_relay_live_lanes as R  # noqa: E402


def _row(lane: str, *, stage=None, state="ACTIVE", kind="n8n") -> dict:
    sched = {"kind": kind, "expression": "abc123", "match": f"scripts/{lane}.py", "cadence": "*/5 * * * *"}
    if stage is not None:
        sched["stage"] = stage
    return {"lane_id": lane, "state": state, "scheduler": sched}


def _allow(*lanes: str, live_arg=("--apply",)) -> dict:
    return {"lanes": [{"lane_id": lane, "live_arg": list(live_arg) if live_arg is not None else None} for lane in lanes]}


def test_native_n8n_lane_without_stage_is_excluded_with_a_reason():
    reg = {"lanes": [_row("fanin"), _row("staged", stage="canary")]}
    lanes, excluded = R.registry_live_lanes(reg, _allow("fanin", "staged"))
    assert lanes == ["staged"]  # never widened
    assert excluded == {"fanin": "native_n8n_no_stage"}


def test_rows_that_never_looked_live_stay_unlisted():
    reg = {"lanes": [_row("retired", state="RETIRED"), _row("no_live_arg"), _row("cronrow", kind="cron"),
                     _row("not_allowlisted")]}
    allow = {"lanes": _allow("retired")["lanes"] + _allow("no_live_arg", live_arg=None)["lanes"]
             + _allow("cronrow")["lanes"]}
    lanes, excluded = R.registry_live_lanes(reg, allow)
    assert lanes == [] and excluded == {}


def test_render_report_and_file_name_the_dropped_lanes(tmp_path):
    (tmp_path / "config").mkdir()
    reg = {"lanes": [_row("n8n-incident-fanin"), _row("heartbeat", stage="cutover")]}
    (tmp_path / R.REGISTRY_REL).write_text(json.dumps(reg), encoding="utf-8")
    (tmp_path / R.ALLOWLIST_REL).write_text(json.dumps(_allow("n8n-incident-fanin", "heartbeat")), encoding="utf-8")
    rep = R.render(tmp_path)
    assert rep["ok"] is True
    assert rep["native_n8n_no_stage"] == ["n8n-incident-fanin"]
    doc = json.loads((tmp_path / R.RENDER_NAME).read_text(encoding="utf-8"))
    assert doc["lanes"] == ["heartbeat"]
    assert doc["excluded"] == {"n8n-incident-fanin": "native_n8n_no_stage"}
