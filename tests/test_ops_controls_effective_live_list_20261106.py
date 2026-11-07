"""ANCHOR: OPS_CONTROLS_EFFECTIVE_LIVE_LIST_20261106. The Ops Controls n8n tab shows the list the relay USES.

Ops audit 2026-11-06 P0-2: the tab rendered TRADEAI_N8N_RELAY_LIVE_LANES from the host file as "the live list". Since
2026-10-31 (config/n8n_relay_live_source.json) the relay's base is the release's registry render minus pauses
(scripts/lib/n8n_relay_live_lanes.resolve), so the tab showed refused lanes as live and live lanes as dry. Each row now
carries on_live_list from the effective list and a live_exclusion reason.

Hermetic: tmp code root, tmp state root, tmp host file; never the live release, ~/.config or persistent-state.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_relay_live_lanes as RLL  # noqa: E402
from tests.test_ops_controls_20261022 import env, get  # noqa: E402,F401  (fixture re-used)


def _native(lane: str, stage=None) -> dict:
    sched = {"kind": "n8n", "expression": "wf" + lane[-3:], "match": f"scripts/{lane.replace('-', '_')}.py",
             "cadence": "*/15 * * * *"}
    if stage:
        sched["stage"] = stage
    return {"lane_id": lane, "state": "ACTIVE", "scheduler": sched}


def _setup(env, *, pause=None):
    code = Path(env.hosts.code_root)
    reg = {"lanes": [_native("nat-live", "canary"), _native("nat-nostage"), _native("nat-shadow", "shadow")]}
    (code / RLL.REGISTRY_REL).write_text(json.dumps(reg), encoding="utf-8")
    al = {"lanes": [{"lane_id": x, "live_arg": ["--apply"]} for x in ("nat-live", "nat-nostage", "nat-shadow")]}
    (code / RLL.ALLOWLIST_REL).write_text(json.dumps(al), encoding="utf-8")
    (code / RLL.SOURCE_REL).write_text(json.dumps({"schema": RLL.SOURCE_SCHEMA, "source": RLL.PINNED_SOURCE}),
                                       encoding="utf-8")
    assert RLL.render(code)["ok"] is True
    state = env.tmp / "state"
    (state / "data" / "governance").mkdir(parents=True)
    if pause:
        (state / RLL.OVERRIDE_REL).write_text(json.dumps(
            {"schema": RLL.OVERRIDE_SCHEMA, "paused": {pause: {"by": "t", "at": "t", "reason": "t"}}}), encoding="utf-8")
    env.cfg["live_list"]["state_root"] = str(state)
    # The host file still names the lane the render drops plus one the registry never made live.
    env.live.write_text("TRADEAI_N8N_RELAY_LIVE_LANES=nat-nostage legacy-only\n", encoding="utf-8")


def test_tab_shows_the_render_not_the_host_file(env):
    _setup(env)
    st, s = get(env, "/state")
    assert st == 200
    n = s["n8n"]
    assert n["state"] == "OK" and n["live_source"] == "registry_render"
    assert n["live_lanes"] == ["nat-live"]
    assert n["host_env_lanes"] == ["legacy-only", "nat-nostage"]
    assert n["host_env_ignored"] == ["legacy-only", "nat-nostage"]
    rows = {r["lane_id"]: r for r in n["rows"]}
    assert rows["nat-live"]["on_live_list"] is True and rows["nat-live"]["live_exclusion"] is None
    assert rows["nat-nostage"]["on_live_list"] is False
    assert rows["nat-nostage"]["live_exclusion"] == "native_n8n_no_stage"
    assert "scheduler.stage" in rows["nat-nostage"]["live_exclusion_text"]
    assert rows["nat-shadow"]["live_exclusion"] == "stage_shadow"
    assert "paper" not in json.dumps(n).lower()


def test_ops_pause_removes_a_rendered_lane_with_its_reason(env):
    _setup(env, pause="nat-live")
    _st, s = get(env, "/state")
    n = s["n8n"]
    assert n["live_lanes"] == [] and n["paused"] == ["nat-live"]
    row = {r["lane_id"]: r for r in n["rows"]}["nat-live"]
    assert row["on_live_list"] is False and row["live_exclusion"] == "paused_ops_controls"


def test_missing_render_says_fallback_and_uses_the_host_list(env):
    _setup(env)
    (Path(env.hosts.code_root) / RLL.RENDER_NAME).unlink()
    _st, s = get(env, "/state")
    n = s["n8n"]
    assert n["live_source"] == "host_env_fallback" and n["live_source_detail"] == "render_missing"
    assert n["live_lanes"] == ["legacy-only", "nat-nostage"]
    row = {r["lane_id"]: r for r in n["rows"]}["nat-live"]
    assert row["on_live_list"] is False and row["live_exclusion"] == "not_on_host_list"
