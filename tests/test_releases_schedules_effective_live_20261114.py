"""OPS-C6b finding 1: the Releases/Schedules timeline reports the relay's EFFECTIVE live set, not the host file.

Before this change ``GET /api/v2/ops/releases-schedules`` published ``live_lanes.count`` straight from
``~/.config/tradeai/n8n-live-lanes.env`` and the page rendered that number as "relay live list N lanes". Since
2026-10-31 the relay resolves the release's registry render first (``n8n_relay_live_lanes.resolve``); on the served
release at 2026-11-14T20:45Z that is 134 lanes against the host file's 104, with one lane (``maturity-remeasure``)
listed only in the host file. Two surfaces, two numbers, neither naming a source.

Every fixture here is synthetic and hermetic: the release root, the host env file and the state root are all under
``tmp_path``. No host store, no host override file and no host env file is read.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.lib import n8n_relay_live_lanes as RLL
from scripts.lib import releases_schedules_view as V

NOW = datetime(2026, 11, 14, 20, 45, tzinfo=timezone.utc)
RENDERED_AT = datetime(2026, 11, 14, 16, 39, 57, tzinfo=timezone.utc)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _lane(lane_id: str) -> dict:
    return {"lane_id": lane_id, "state": "ACTIVE",
            "scheduler": {"kind": "n8n", "expression": f"wf-{lane_id}", "cadence": "*/5 * * * *"}}


def _root(tmp_path: Path, *, render_lanes: list[str] | None = ("lane-a", "lane-b"), host: str | None = "lane-a,lane-z"
          ) -> dict[str, Path]:
    """A release root with a registry, an allowlist and (optionally) a matching registry render."""
    root = tmp_path / "release"
    (root / "config").mkdir(parents=True)
    (root / "config" / "lane_registry.json").write_text(
        json.dumps({"lanes": [_lane("lane-a"), _lane("lane-b"), _lane("lane-z")]}))
    (root / "config" / "n8n_run_allowlist.json").write_text(json.dumps({"lanes": {}}))
    (root / "config" / "n8n_relay_live_source.json").write_text(
        json.dumps({"schema": "N8nRelayLiveSource@v1", "source": "registry_render", "one_way": True}))
    if render_lanes is not None:
        (root / RLL.RENDER_NAME).write_text(json.dumps({
            "schema": RLL.RENDER_SCHEMA, "lanes": list(render_lanes), "rendered_at": RENDERED_AT.isoformat(),
            "registry_sha256": _sha(root / "config" / "lane_registry.json"),
            "allowlist_sha256": _sha(root / "config" / "n8n_run_allowlist.json")}))
        os.utime(root / RLL.RENDER_NAME, (RENDERED_AT.timestamp(), RENDERED_AT.timestamp()))
    live = tmp_path / "n8n-live-lanes.env"
    live.write_text(f"OTHER_SECRET=never-read\n{RLL.LIVE_LANES_ENV}=" + (host or "") + "\n")
    return {"registry": root / "config" / "lane_registry.json", "live": live, "state": tmp_path / "state", "root": root}


def _timeline(paths: dict[str, Path], *, name_a: str = "lane-a", name_z: str = "lane-z", state_root=...):
    """The merged lane names in the fixture make the render/registry disagree on purpose; rows are keyed by lane id."""
    reg = json.loads(paths["registry"].read_text())
    reg["lanes"] = [{**r, "lane_id": r["lane_id"]} for r in reg["lanes"]]
    paths["registry"].write_text(json.dumps(reg))
    return V.read_timeline(NOW, registry_path=paths["registry"], live_lanes_path=paths["live"],
                           crontab_reader=lambda: ("", "crontab", None, None),
                           state_root=paths["state"] if state_root is ... else state_root)


def _rows(tl: dict) -> dict[str, dict]:
    v = tl["value"]
    return {r["lane_id"]: r for r in (v["rows"] + v["recurring"]) if r["runner"] == "n8n"}


def test_the_effective_list_is_the_registry_render_not_the_host_file(tmp_path):
    p = _root(tmp_path)
    tl = _timeline(p)
    el = tl["value"]["effective_live"]
    assert el["status"] == "OK" and el["source"] == "registry_render", el
    assert el["count"] == 2, "lane-a + lane-b are the render; the host file is not the live set"
    assert el["only_in_host_file"] == ["lane-z"], "a lane the host file lists that the relay does not run"
    assert el["as_of"] == RENDERED_AT.isoformat(), "the render's own age, not the request clock"
    # the host file is still shown, with its role written out: an input, never called the live list
    assert tl["value"]["live_lanes"]["count"] == 2
    assert "not the relay's live list" in tl["value"]["live_lanes"]["role"]


def test_row_membership_answers_relay_and_host_separately(tmp_path):
    tl = _timeline(_root(tmp_path))
    rows = _rows(tl)
    assert rows["lane-a"]["in_relay_live_list"] is True and rows["lane-a"]["in_host_live_list"] is True
    assert rows["lane-b"]["in_relay_live_list"] is True and rows["lane-b"]["in_host_live_list"] is False, \
        "in the render only: the relay runs it, the host file does not list it"
    assert rows["lane-z"]["in_relay_live_list"] is False and rows["lane-z"]["in_host_live_list"] is True, \
        "the lie this finding is about: host-file membership was reported as relay membership"
    assert rows["lane-z"]["stage"] == "NOT LIVE", "an unlabelled lane takes its stage from the relay, not the file"


def test_a_missing_render_names_the_fallback_it_used(tmp_path):
    tl = _timeline(_root(tmp_path, render_lanes=None))
    el = tl["value"]["effective_live"]
    assert el["status"] == "OK" and el["source"] == "host_env_fallback", el
    assert el["detail"] == "render_missing" and el["count"] == 2 and el["as_of"] is None
    assert _rows(tl)["lane-z"]["in_relay_live_list"] is True, "with no render the host file IS the relay's input"


def test_no_state_root_means_unknown_never_guessed(tmp_path):
    tl = _timeline(_root(tmp_path), state_root=None)
    el = tl["value"]["effective_live"]
    assert el["status"] == "UNAVAILABLE" and el["count"] is None and el["source"] is None
    assert "state root" in el["detail"]
    assert tl["freshness"] == "STALE", "an unresolved live set is not a fresh timeline"
    assert any("effective live list unavailable" in n for n in tl["value"]["notes"])
    assert all(r["in_relay_live_list"] is None for r in _rows(tl).values()), "unknown beats wrong"


def test_the_ops_pause_override_removes_a_rendered_lane(tmp_path):
    p = _root(tmp_path)
    ov = p["state"] / RLL.OVERRIDE_REL
    ov.parent.mkdir(parents=True)
    ov.write_text(json.dumps({"schema": RLL.OVERRIDE_SCHEMA,
                              "paused": {"lane-a": {"reason": "operator hold", "at": NOW.isoformat()}}}))
    tl = _timeline(p)
    el = tl["value"]["effective_live"]
    assert el["count"] == 1 and el["paused_by_override"] == ["lane-a"], el
    assert _rows(tl)["lane-a"]["in_relay_live_list"] is False
