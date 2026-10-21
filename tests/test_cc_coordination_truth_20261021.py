"""Command Center /v3/coordination truth (audit 2026-10-21).

1. n8n dispatcher lanes (scheduler.expression "dispatcher") resolve to the active `tradeai-dispatcher`
   workflow and take their state from run evidence (RunReceipt@v3 included), not a false ORPHANED.
   Infrastructure workflows (dispatcher, routers, heartbeat, digest, fabric-*) are INFRASTRUCTURE and a
   `<lane>-shadow` workflow is attached to its lane; a truly unowned workflow stays ORPHANED.
2. (TS) Problems filter — apps/command-center-v3/src/lib/schedulerOperations.test.ts.
3. The migration board is computed live from the registry (scheduler.stage counts included) instead of
   serving a stale receipt file; the file is only a flagged fallback.

Hermetic: tmp_path state, fixture registry/tranches/ledger; no host, no crontab, no n8n.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_migration_board as B  # noqa: E402
from scripts.lib.scheduler_operations import build_projection, receipt_proves_run  # noqa: E402

NOW = datetime(2026, 10, 21, 13, 0, tzinfo=timezone.utc)


def _dispatch_lane(lane_id="source-attribution-monitor", stage="cutover", expression="dispatcher"):
    return {
        "lane_id": lane_id,
        "owner": "platform",
        "state": "ACTIVE",
        "expected_cadence_hours": 24,
        "scheduler": {"kind": "n8n", "expression": expression, "match": f"scripts/{lane_id}.py",
                      "cadence": "0 6 * * *", "stage": stage},
        "output_signal": {"kind": "file_mtime", "path": f"data/runtime/{lane_id}.json"},
    }


def _obs(workflows):
    at = NOW.isoformat()
    return {
        "cron": {"measured": True, "as_of": at, "entries": []},
        "systemd": {"measured": False, "units": {}},
        "n8n": {"measured": True, "as_of": at, "workflows": workflows},
        "openclaw": {"measured": False, "jobs": []},
    }


def _run(lane_id, state="RUN_DONE", schema="RunReceipt@v3", mode="live", exit_code=0, at=None):
    at = at or (NOW - timedelta(hours=3)).isoformat()
    run_id = f"d:{lane_id}:{mode}:{at}"
    receipt = {"schema": schema, "run_id": run_id, "lane_id": lane_id, "mode": mode, "state": state,
               "exit_code": exit_code, "lock_skipped": False, "timed_out": False, "finished_at": at}
    return {"run_id": run_id, "lane_id": lane_id, "mode": mode, "state": state, "exit_code": exit_code,
            "requested_at": at, "started_at": at, "finished_at": at, "duration_s": 0.3, "receipt": receipt}


def _fresh_output(tmp_path, lane_id):
    p = tmp_path / "data" / "runtime" / f"{lane_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}")
    import os

    t = (NOW - timedelta(hours=3)).timestamp()
    os.utime(p, (t, t))


WORKFLOWS = [
    {"id": "tradeai-dispatcher", "name": "tradeai-dispatcher", "active": True},
    {"id": "tradeai-event-router", "name": "tradeai-event-router", "active": True},
    {"id": "tradeai-incident-router", "name": "tradeai-incident-router", "active": True},
    {"id": "tradeai-heartbeat-watcher", "name": "tradeai-heartbeat-watcher", "active": True},
    {"id": "tradeai-digest-scheduler", "name": "tradeai-digest-scheduler", "active": True},
    {"id": "tradeai-fabric-run-lane", "name": "tradeai-fabric-run-lane", "active": True},
    {"id": "tradeai-fabric-error", "name": "tradeai-fabric-error", "active": True},
    {"id": "498d749165a93ff9", "name": "source-attribution-monitor-shadow", "active": True},
    {"id": "wf-unknown", "name": "someone-elses-job", "active": True},
]


def _project(tmp_path, lanes, runs, workflows=WORKFLOWS):
    return build_projection({"lanes": lanes}, _obs(workflows), root=tmp_path, now=NOW, runs=runs, runs_measured=True)


# --- 1. scheduler operations ---------------------------------------------------------------------------


def test_run_receipt_v3_proves_a_run():
    assert receipt_proves_run(_run("x", schema="RunReceipt@v3"), NOW) is True
    assert receipt_proves_run(_run("x", schema="RunReceipt@v9"), NOW) is False


def test_dispatcher_lane_with_recent_live_run_done_is_live_not_orphaned(tmp_path):
    lane = _dispatch_lane()
    _fresh_output(tmp_path, lane["lane_id"])
    rows = {r["lane_id"]: r for r in _project(tmp_path, [lane], [_run(lane["lane_id"])])["rows"]}
    row = rows[lane["lane_id"]]
    assert row["runtime_state"] == "LIVE", row
    assert row["scheduler_drift"] is False
    assert row["scheduler_observations"][0]["id"] == "tradeai-dispatcher"
    # the lane keeps its own cadence; the dispatcher's every-minute trigger is not the lane's schedule
    assert row["schedule"] == "0 6 * * *"


def test_dispatcher_lane_with_recent_live_run_failed_is_run_failed(tmp_path):
    lane = _dispatch_lane("registry-runtime-truth")
    _fresh_output(tmp_path, lane["lane_id"])
    row = next(r for r in _project(tmp_path, [lane], [_run(lane["lane_id"], state="RUN_FAILED")])["rows"]
               if r["lane_id"] == lane["lane_id"])
    assert row["runtime_state"] == "RUN_FAILED"


def test_dispatcher_lane_is_orphaned_only_when_the_dispatcher_workflow_is_inactive(tmp_path):
    lane = _dispatch_lane()
    wfs = [dict(w, active=False) if w["id"] == "tradeai-dispatcher" else w for w in WORKFLOWS]
    row = next(r for r in _project(tmp_path, [lane], [], wfs)["rows"] if r["lane_id"] == lane["lane_id"])
    assert row["runtime_state"] == "ORPHANED"


def test_infrastructure_workflows_are_not_orphaned(tmp_path):
    # the dispatcher keeps its own INFRASTRUCTURE row even while dispatcher lanes claim it
    rows = _project(tmp_path, [_dispatch_lane()], [])["rows"]
    infra = {r["scheduler_observations"][0]["name"]: r for r in rows if r.get("infrastructure")}
    assert set(infra) == {
        "tradeai-dispatcher", "tradeai-event-router", "tradeai-incident-router", "tradeai-heartbeat-watcher",
        "tradeai-digest-scheduler", "tradeai-fabric-run-lane", "tradeai-fabric-error",
    }
    assert all(r["runtime_state"] == "INFRASTRUCTURE" and r["scheduler_drift"] is False for r in infra.values())
    # a workflow nobody owns is still a true orphan
    orphans = [r for r in rows if r["runtime_state"] == "ORPHANED"]
    assert [r["scheduler_observations"][0]["name"] for r in orphans] == ["someone-elses-job"]


def test_lane_shadow_workflow_attaches_to_its_lane(tmp_path):
    lane = _dispatch_lane()
    rows = _project(tmp_path, [lane], [])["rows"]
    assert not any(r["lane_id"].startswith("unregistered-n8n-498d") for r in rows)
    row = next(r for r in rows if r["lane_id"] == lane["lane_id"])
    shadow = [o for o in row["scheduler_observations"] if o.get("kind") == "n8n-shadow"]
    assert shadow and shadow[0]["name"] == "source-attribution-monitor-shadow" and shadow[0]["active"] is True


# --- 3. migration board ----------------------------------------------------------------------------------


def _board_fixture(tmp_path):
    root = tmp_path / "state"
    stale = {"schema": "N8nMigrationBoard@v1", "status": "OK", "as_of": "2026-10-08T16:16:52+00:00",
             "lanes": [], "summary": {"by_phase": {"NOT_STARTED": 70, "SHADOW": 1}}}
    (root / "data" / "runtime").mkdir(parents=True)
    (root / B.BOARD_REL).write_text(json.dumps(stale))
    ledger = root / "data" / "governance" / "l.sqlite"
    ledger.parent.mkdir(parents=True)
    sqlite3.connect(ledger).execute(
        "CREATE TABLE runs(run_id TEXT PRIMARY KEY, lane_id TEXT, mode TEXT, state TEXT, requested_by TEXT, "
        "caller_id TEXT, requested_at TEXT, started_at TEXT, finished_at TEXT, exit_code INTEGER, duration_s REAL, "
        "receipt_json TEXT)"
    ).connection.close()
    lanes = [_dispatch_lane(f"cut-{i}", "cutover") for i in range(2)]
    lanes += [_dispatch_lane(f"can-{i}", "canary") for i in range(3)]
    lanes += [dict(_dispatch_lane(f"sh-{i}", "shadow"), scheduler={"kind": "cron", "expression": "0 6 * * *",
                                                                    "match": f"scripts/sh-{i}.py", "stage": "shadow"})
              for i in range(4)]
    lanes.append(dict(_dispatch_lane("plain"), scheduler={"kind": "cron", "expression": "0 6 * * *", "match": "x"}))
    tranches = {"schema": B.TRANCHES_SCHEMA, "tranches": {"N1": {"lanes": [{"lane_id": "cut-0"}, {"lane_id": "sh-0"}]}}}
    return root, {"lanes": lanes}, tranches, ledger


def test_dispatch_stage_summary_counts_registry_stages():
    reg = {"lanes": [{"lane_id": "a", "scheduler": {"kind": "n8n", "stage": "cutover"}},
                     {"lane_id": "b", "scheduler": {"kind": "cron", "stage": "canary"}},
                     {"lane_id": "c", "scheduler": {"kind": "cron", "stage": "shadow"}},
                     {"lane_id": "d", "scheduler": {"kind": "cron"}}]}
    s = B.dispatch_stage_summary(reg)
    assert s["by_stage"] == {"shadow": 1, "canary": 1, "cutover": 1}
    assert [r["lane_id"] for r in s["lanes"]] == ["a", "b", "c"]


def test_served_board_is_computed_live_not_the_stale_file(tmp_path):
    root, reg, tranches, ledger = _board_fixture(tmp_path)
    board = B.served_board(root=root, now=NOW, registry=reg, tranches=tranches, ledger=ledger, host=False, cache=False)
    assert board["computed"] == "LIVE"
    assert board["as_of"].startswith("2026-10-21")
    assert board["stale"] is False
    assert board["dispatch_stages"]["by_stage"] == {"shadow": 4, "canary": 3, "cutover": 2}
    assert board["summary"]["by_phase"]["CUT_OVER"] == 1


def test_served_board_falls_back_to_the_file_flagged_stale(tmp_path, monkeypatch):
    root, reg, tranches, ledger = _board_fixture(tmp_path)

    def boom(**_kw):
        raise RuntimeError("private-detail")

    monkeypatch.setattr(B, "build_board", boom)
    board = B.served_board(root=root, now=NOW, registry=reg, tranches=tranches, ledger=ledger, host=False, cache=False)
    assert board["computed"] == "FILE_FALLBACK" and board["fallback_reason"] == "RuntimeError"
    assert board["stale"] is True and board["age_h"] > 24
    assert "private-detail" not in json.dumps(board)


def test_api_route_serves_the_live_board(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path))
    live = {"schema": "N8nMigrationBoard@v1", "status": "OK", "computed": "LIVE", "as_of": NOW.isoformat()}
    monkeypatch.setattr(B, "served_board", lambda **_kw: live)
    source = (ROOT / "scripts/api_v2.py").read_text()
    start = source.index('    if base_path == "/api/v2/coordination/migration-board":')
    end = source.index("    # What n8n did today", start)
    scope = {"base_path": "/api/v2/coordination/migration-board", "method": "GET", "json": json}
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        exec("def route():\n" + source[start:end], scope)
        assert scope["route"]() == (200, {"ok": True, "data": live})
        scope["method"] = "POST"
        assert scope["route"]()[0] == 405
    finally:
        sys.path.remove(str(ROOT / "scripts"))
