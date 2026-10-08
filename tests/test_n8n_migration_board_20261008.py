"""Migration board (n8n scheduler-of-record program, stream G, 2026-10-08): phases, risks, rollback
readiness and the operator renderer from fixture receipts under tmp_path. No host path, no crontab."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_migration_board as B  # noqa: E402
from scripts.lib import lane_registry as LR  # noqa: E402

NOW = datetime(2026, 10, 8, 13, 0, tzinfo=timezone.utc)
DDL = ("CREATE TABLE runs(run_id TEXT PRIMARY KEY, lane_id TEXT, mode TEXT, state TEXT, requested_by TEXT, caller_id TEXT, "
       "requested_at TEXT, started_at TEXT, finished_at TEXT, exit_code INTEGER, duration_s REAL, receipt_json TEXT)")


def _lane(lane_id, kind, cadence=1.0, expression=None, match=None, signal=None):
    return {"lane_id": lane_id, "owner": "platform", "state": "ACTIVE", "expected_cadence_hours": cadence,
            "scheduler": {"kind": kind, "expression": expression or f"0 * * * * python3 scripts/{lane_id}.py", "match": match or f"scripts/{lane_id}.py"},
            "output_signal": signal or {"kind": "file_mtime", "path": f"data/runtime/{lane_id}_last.json"}}


def _write(p: Path, doc: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")


def _fixture(tmp_path):
    root = tmp_path / "state"
    ledger = root / "data" / "governance" / "l.sqlite"
    ledger.parent.mkdir(parents=True)
    conn = sqlite3.connect(ledger)
    conn.execute(DDL)
    conn.executemany("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("r-shadow", "lane-shadow", "dry_run", "RUN_DONE", "n8n-relay", "n8n-relay", "2026-10-08T10:00:00+00:00", None, "2026-10-08T10:00:03+00:00", 0, 3.0, "{}"),
        ("r-canary-1", "lane-canary", "dry_run", "RUN_DONE", "n8n-relay", "n8n-relay", "2026-10-08T09:00:00+00:00", None, "2026-10-08T09:00:03+00:00", 0, 3.0, "{}"),
        ("r-canary-2", "lane-canary", "live", "RUN_DONE", "n8n-relay", "n8n-relay", "2026-10-08T11:00:00+00:00", None, "2026-10-08T11:00:04+00:00", 0, 4.0, "{}"),
        ("r-cut-fail", "lane-cut", "live", "RUN_FAILED", "n8n-relay", "n8n-relay", "2026-10-08T12:00:00+00:00", None, "2026-10-08T12:00:09+00:00", 2, 9.0, "{}"),
    ])
    conn.commit(); conn.close()
    # a receipt file only (no ledger row) still counts, and a receipt enriches a ledger row
    _write(root / "data/runtime/n8n_runs/r-rb.json", {"schema": "RunReceipt@v1", "run_id": "r-rb", "lane_id": "lane-rolled", "mode": "live",
                                                       "exit_code": 0, "duration_s": 1.0, "state": "RUN_DONE", "finished_at": "2026-10-07T12:00:00+00:00"})
    _write(root / "data/runtime/n8n_runs/r-cut-fail.json", {"schema": "RunReceipt@v1", "run_id": "r-cut-fail", "lane_id": "lane-cut", "mode": "live",
                                                             "exit_code": 2, "duration_s": 9.0, "state": "RUN_FAILED", "code_sha": "a" * 40})
    # the executor heartbeat is judged against the real clock (the board is not given now= here, so file mtimes
    # and this age agree); one hour ago is inside the 2x cadence window whenever the test runs
    _write(root / "data/runtime/n8n_run_executor_last.json",
           {"schema": "RunReceipt@v1", "finished_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()})
    _write(root / "data/runtime/n8n_cutover/lane-cut-20261008T0800Z.json", {"schema": "CutoverReceipt@v1", "lane_id": "lane-cut", "action": "cutover",
                                                                            "scheduler_before": "cron", "scheduler_after": "n8n", "applied": True,
                                                                            "at": "2026-10-08T08:00:00+00:00", "crontab_backup": "backups/crontab-x.txt"})
    _write(root / "data/runtime/n8n_cutover/lane-rolled-20261007T0800Z.json", {"schema": "CutoverReceipt@v1", "lane_id": "lane-rolled", "action": "cutover",
                                                                               "applied": True, "at": "2026-10-07T08:00:00+00:00"})
    _write(root / "data/runtime/n8n_cutover/lane-rolled-20261007T0900Z.json", {"schema": "CutoverReceipt@v1", "lane_id": "lane-rolled", "action": "rollback",
                                                                               "scheduler_before": "n8n", "scheduler_after": "cron", "applied": True,
                                                                               "at": "2026-10-07T09:00:00+00:00", "crontab_backup": "backups/crontab-y.txt"})
    _write(root / "data/runtime/n8n_lane_readiness_last.json", {"schema": "N8nLaneReadiness@v1", "lanes": {
        "lane-cut": {"verdict": "GO", "reasons": []}, "lane-canary": {"verdict": "GO_WITH_NOTES", "reasons": ["weekly: one manual fire"]}}})
    # output signals: fresh for canary, stale (3 days at a 24 h cadence) for lane-stale
    (root / "data/runtime").mkdir(parents=True, exist_ok=True)
    (root / "data/runtime/lane-canary_last.json").write_text("{}")
    import os, time
    stale = root / "data/runtime/lane-stale_last.json"
    stale.write_text("{}")
    os.utime(stale, (time.time() - 3 * 86400, time.time() - 3 * 86400))
    registry = {"schema": "LaneRegistry@v1", "lanes": [
        _lane("lane-shadow", "cron"), _lane("lane-canary", "cron", cadence=168.0),
        _lane("lane-cut", "n8n", cadence=1.0, expression="wf-123", match="scripts/lane-cut.py"),
        _lane("lane-rolled", "cron"), _lane("lane-stale", "cron", cadence=24.0),
    ]}
    tranches = {"schema": "N8nMigrationTranches@v1", "tranches": {
        "N1": {"lanes": [{"lane_id": "lane-shadow"}, {"lane_id": "lane-canary"}, {"lane_id": "lane-cut"}]},
        "N2": {"lanes": [{"lane_id": "lane-rolled"}, {"lane_id": "lane-stale"}, {"lane_id": "lane-unregistered", "match": "scripts/x.py"}]}}}
    return root, ledger, registry, tranches


def test_phases_risks_rollback_and_readiness_from_fixture_receipts(tmp_path, monkeypatch):
    root, ledger, registry, tranches = _fixture(tmp_path)
    monkeypatch.setattr(B, "served_sha", lambda: "e" * 40)
    # the stale-signal clock: observe_signal reads real mtimes, so the board clock must be "now"
    board = B.build_board(root=root, registry=registry, tranches=tranches, ledger=ledger,
                          cron_text="0 * * * * python3 scripts/lane-cut.py --apply\n# 0 * * * * python3 scripts/lane-rolled.py\n",
                          units=["tradeai-other.timer"])
    by = {r["lane_id"]: r for r in board["lanes"]}
    assert board["schema"] == "N8nMigrationBoard@v1" and board["lane_count"] == 6 and board["status"] == "OK"
    assert by["lane-shadow"]["phase"] == "SHADOW" and by["lane-shadow"]["last_run"]["mode"] == "dry_run"
    assert by["lane-canary"]["phase"] == "CANARY" and by["lane-canary"]["last_run"]["run_id"] == "r-canary-2" and by["lane-canary"]["run_count"] == 2
    assert by["lane-canary"]["readiness"] == "GO_WITH_NOTES" and by["lane-canary"]["readiness_reasons"] == ["weekly: one manual fire"]
    assert by["lane-canary"]["output_signal_age_h"] is not None and by["lane-canary"]["output_signal_age_h"] < 1
    cut = by["lane-cut"]
    assert cut["phase"] == "CUT_OVER" and cut["scheduler_of_record"] == "n8n" and cut["scheduler_expression"] == "wf-123"
    assert cut["rollback_ready"] is True and cut["readiness"] == "GO" and cut["last_run"]["state"] == "RUN_FAILED"
    assert set(cut["risk_flags"]) == {"RUN_FAILED_AFTER_CUTOVER", "DOUBLE_SCHEDULER"} and cut["double_scheduler"] is True
    assert by["lane-rolled"]["phase"] == "ROLLED_BACK" and by["lane-rolled"]["rollback_ready"] is True and by["lane-rolled"]["cutover"]["action"] == "rollback"
    assert by["lane-stale"]["phase"] == "NOT_STARTED" and by["lane-stale"]["risk_flags"] == ["OUTPUT_SIGNAL_STALE"] and by["lane-stale"]["output_signal_age_h"] > 48
    un = by["lane-unregistered"]
    assert un["registry_row"] is False and un["scheduler_of_record"] == "unregistered" and un["risk_flags"] == ["NO_REGISTRY_ROW"] and un["phase"] == "NOT_STARTED"
    s = board["summary"]
    assert s["by_phase"] == {"NOT_STARTED": 2, "SHADOW": 1, "CANARY": 1, "CUT_OVER": 1, "ROLLED_BACK": 1}
    assert s["per_tranche"]["N1"]["by_phase"]["CUT_OVER"] == 1 and s["per_tranche"]["N2"]["no_registry_row"] == 1
    assert sorted(f["flag"] for f in s["open_risks"]) == ["DOUBLE_SCHEDULER", "OUTPUT_SIGNAL_STALE", "RUN_FAILED_AFTER_CUTOVER"]
    assert s["open_risk_count"] == 3 and s["no_registry_row"] == 1
    assert board["sources"]["ledger_rows"] == 4 and board["sources"]["receipt_files"] == 2 and board["sources"]["cutover_receipts"] == 2
    assert board["sources"]["executor_stalled"] is False and board["sources"]["crontab_read"] is True
    md = B.render_markdown(board)
    assert "| N1 | lane-cut | n8n | CUT_OVER | live RUN_FAILED exit=2" in md and "RUN_FAILED_AFTER_CUTOVER, DOUBLE_SCHEDULER" in md


def test_no_inputs_at_all_is_an_honest_not_started_board(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "served_sha", lambda: None)
    reg = {"schema": "LaneRegistry@v1", "lanes": [_lane("a", "cron")]}
    tr = {"schema": "N8nMigrationTranches@v1", "tranches": {"N1": {"lanes": [{"lane_id": "a"}]}}}
    board = B.build_board(root=tmp_path, registry=reg, tranches=tr, ledger=tmp_path / "none.sqlite", now=NOW)
    assert board["lanes"][0]["phase"] == "NOT_STARTED" and board["lanes"][0]["last_run"] is None
    assert board["sources"]["ledger_status"] == "NO_LEDGER" and board["summary"]["open_risk_count"] == 0
    assert board["sources"]["crontab_read"] is False and board["lanes"][0]["double_scheduler"] is None


def test_executor_stalled_flags_every_cut_over_lane(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "served_sha", lambda: None)
    _write(tmp_path / "data/runtime/n8n_run_executor_last.json", {"finished_at": "2026-10-08T09:00:00+00:00"})
    reg = {"schema": "LaneRegistry@v1", "lanes": [_lane("a", "n8n", cadence=1.0, expression="wf-1"), _lane("b", "cron")]}
    tr = {"schema": "N8nMigrationTranches@v1", "tranches": {"N1": {"lanes": [{"lane_id": "a"}, {"lane_id": "b"}]}}}
    board = B.build_board(root=tmp_path, registry=reg, tranches=tr, ledger=tmp_path / "none.sqlite", now=NOW, cron_text="", units=[])
    assert board["sources"]["executor_stalled"] is True and board["sources"]["executor_last_age_h"] == 4.0
    by = {r["lane_id"]: r for r in board["lanes"]}
    assert "EXECUTOR_STALLED" in by["a"]["risk_flags"] and by["a"]["double_scheduler"] is False and by["b"]["risk_flags"] == []


def test_write_cli_produces_the_receipt_the_route_serves(tmp_path, monkeypatch, capsys):
    root, ledger, registry, tranches = _fixture(tmp_path)
    monkeypatch.setattr(B, "state_root", lambda: root)
    monkeypatch.setattr(B, "served_sha", lambda: None)
    monkeypatch.setattr(B, "load_tranches", lambda path=None: tranches)
    monkeypatch.setattr(LR, "load_registry", lambda path=None: registry)
    rc = B.main(["--write", "--no-host", "--ledger", str(ledger)])
    assert rc == 0
    out = json.loads((root / B.BOARD_REL).read_text())
    assert out["schema"] == "N8nMigrationBoard@v1" and out["lane_count"] == 6 and "written" not in out
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["lanes"] == 6 and line["written"].endswith("n8n_migration_board_last.json")
    rc = B.main(["--markdown", "--no-host", "--ledger", str(ledger)])
    assert rc == 0 and "# n8n migration board" in capsys.readouterr().out


def test_program_config_lists_71_unique_lanes_and_registered_ones_exist():
    tr = B.load_tranches()
    ids = [l["lane_id"] for t in tr["tranches"].values() for l in t["lanes"]]
    assert len(ids) == 71 == tr["lane_count"] and len(set(ids)) == 71
    assert list(tr["tranches"]) == ["N1", "N2", "N3", "N4", "N5", "N6"]
    assert [len(t["lanes"]) for t in tr["tranches"].values()] == [9, 17, 12, 20, 7, 6]
    reg = {r["lane_id"] for r in LR.load_registry()["lanes"]}
    unregistered = [l for t in tr["tranches"].values() for l in t["lanes"] if l["lane_id"] not in reg]
    # every lane without a registry row names what the doc named (a script or a workflow) or says why
    assert all(l.get("match") or l.get("note") for l in unregistered), unregistered
    assert "scripts/n8n_migration_board.py" in B.NO_CONSUMER_REASON or "migration-board" in B.NO_CONSUMER_REASON


def test_board_and_fanin_read_the_heartbeat_where_the_executor_writes_it():
    """Regression for the 2026-10-08 defect: both readers looked inside n8n_runs/ while the executor writes beside it,
    so executor_last_age_h was always None and executor:stalled could never fire. The three paths must agree."""
    from scripts import n8n_incident_fanin as F
    from scripts import n8n_run_executor as X
    executor_rel = X.LAST_REL.as_posix()
    assert B.EXECUTOR_LAST_REL == executor_rel
    assert F.EXECUTOR_LAST_REL == executor_rel
    assert Path(executor_rel).parent != Path(B.RUNS_RECEIPT_DIR)  # the heartbeat is not a run receipt
