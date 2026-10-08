"""Incident fan-in `runs` source (n8n scheduler-of-record program, stream G, 2026-10-08): a failed
or timed-out run on an n8n-scheduled lane opens a P2; a stalled executor opens a P1; a later
RUN_DONE makes the finding disappear so the existing recovery path closes it; the env opt-out keeps
fixtures without a ledger stable."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_incident_fanin as fanin  # noqa: E402
from scripts.lib import lane_registry as LR  # noqa: E402

NOW = datetime(2026, 10, 8, 13, 0, tzinfo=timezone.utc)
DDL = ("CREATE TABLE runs(run_id TEXT PRIMARY KEY, lane_id TEXT, mode TEXT, state TEXT, requested_by TEXT, caller_id TEXT, "
       "requested_at TEXT, started_at TEXT, finished_at TEXT, exit_code INTEGER, duration_s REAL, receipt_json TEXT)")


def _ledger(path: Path, rows: list[tuple]) -> Path:
    conn = sqlite3.connect(path)
    conn.execute(DDL)
    conn.executemany("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit(); conn.close()
    return path


def _row(run_id, lane, state, finished, exit_code=0):
    return (run_id, lane, "live", state, "n8n-relay", "n8n-relay", finished, finished, finished, exit_code, 2.0, "{}")


def _wire(monkeypatch, tmp_path, rows, *, n8n_cadence=1.0, executor_finished=None):
    reg = {"schema": "LaneRegistry@v1", "lanes": [
        {"lane_id": "n8n-lab-watchdog", "state": "ACTIVE", "expected_cadence_hours": n8n_cadence, "scheduler": {"kind": "n8n", "expression": "wf-1"}},
        {"lane_id": "premarket-data-pipeline", "state": "ACTIVE", "expected_cadence_hours": 24.0, "scheduler": {"kind": "cron", "expression": "x"}},
    ]}
    monkeypatch.setattr(LR, "load_registry", lambda path=None: reg)
    monkeypatch.setenv("TRADEAI_FANIN_LANE_REGISTRY", "0")
    monkeypatch.delenv("TRADEAI_FANIN_RUNS", raising=False)
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(_ledger(tmp_path / "l.sqlite", rows)))
    if executor_finished:
        p = tmp_path / "data/runtime/n8n_runs/n8n_run_executor_last.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"schema": "RunReceipt@v1", "finished_at": executor_finished}))


def _runs(found):
    return [f for f in found if f["source"] == "runs"]


def test_a_failed_run_on_an_n8n_lane_opens_a_p2_with_the_receipt_as_evidence(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, [
        _row("r1", "n8n-lab-watchdog", "RUN_DONE", "2026-10-08T11:00:00+00:00"),
        _row("r2", "n8n-lab-watchdog", "RUN_TIMEOUT", "2026-10-08T12:30:00+00:00", exit_code=124),
        _row("r3", "premarket-data-pipeline", "RUN_FAILED", "2026-10-08T12:40:00+00:00", exit_code=2),   # cron lane: not n8n's incident
    ], executor_finished="2026-10-08T12:30:00+00:00")
    found = _runs(fanin.collect(tmp_path, NOW))
    assert [(f["item"], f["severity"]) for f in found] == [("n8n-lab-watchdog:RUN_TIMEOUT", "P2")]
    assert found[0]["artifact_rel"] == "data/runtime/n8n_runs/r2.json" and found[0]["store"] == "data/runtime"
    assert found[0]["detected_at"] == "2026-10-08T12:30:00+00:00" and "exit=124" in found[0]["detail"]
    assert fanin.NOTES["runs_source"].startswith("ok:1:n8n_lanes=1:executor_receipt=yes")
    day = NOW.strftime("%Y-%m-%d")
    ev = fanin.build_event(found[0], day=day, now=NOW, sha="a" * 40)
    assert ev["idempotency_key"] == fanin.idem_key(found[0], day) and ev["subject_key"].startswith("sev=P2;src=runs;item=n8n-lab-watchdog:RUN_TIMEOUT")


def test_the_next_run_done_clears_the_finding_so_the_recovery_path_closes_it(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, [
        _row("r2", "n8n-lab-watchdog", "RUN_FAILED", "2026-10-08T12:30:00+00:00", exit_code=2),
        _row("r4", "n8n-lab-watchdog", "RUN_DONE", "2026-10-08T12:45:00+00:00"),
    ], executor_finished="2026-10-08T12:45:00+00:00")
    assert _runs(fanin.collect(tmp_path, NOW)) == [] and fanin.NOTES["runs_source"].startswith("ok:0")
    # end to end: a previously open runs incident is in `recovered` on the next apply
    monkeypatch.setattr(fanin, "state_root", lambda: tmp_path)
    monkeypatch.setattr(fanin, "served_sha", lambda: "b" * 40)
    monkeypatch.setattr(fanin, "_outbox_findings", lambda now: [])
    key = fanin.idem_key({"source": "runs", "item": "n8n-lab-watchdog:RUN_FAILED"}, NOW.strftime("%Y-%m-%d"))
    receipt = tmp_path / "data/runtime/n8n_incident_fanin_last.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps({"incidents": [{"idempotency_key": key, "state": "ARTIFACT_WRITTEN"}]}))

    class Client:
        url, has_key = "http://127.0.0.1:0", False
        def __init__(self, caller_id): pass
        def healthz(self): return {"ok": True}
        def status(self, k): return {"state": "REFUSED", "reason": "unknown_event"}
        def accept_event(self, ev): return {"state": "REFUSED", "reason": "unknown_lane"}
        def transition(self, op, k, **kw): return {"state": "CONSUMED", "reason": None}
    monkeypatch.setattr(fanin, "GatewayClient", Client)
    monkeypatch.setattr(fanin, "collect", lambda root, now: [])
    rc = fanin.main(["--apply", "--receipt", str(receipt)])
    doc = json.loads(receipt.read_text())
    assert rc == 0 and doc["recovered"] == [{"idempotency_key": key, "ops": [{"op": "consumer_ack", "state": "CONSUMED", "reason": None}], "state": "CONSUMED"}]
    assert doc["source_notes"]["runs_source"].startswith("ok:0")


def test_a_stalled_executor_is_a_p1_against_the_shortest_n8n_cadence(monkeypatch, tmp_path):
    _wire(monkeypatch, tmp_path, [_row("r1", "n8n-lab-watchdog", "RUN_DONE", "2026-10-08T10:00:00+00:00")],
          n8n_cadence=0.5, executor_finished="2026-10-08T11:30:00+00:00")   # 1.5 h old > 2 x 0.5 h
    found = _runs(fanin.collect(tmp_path, NOW))
    assert [(f["item"], f["severity"]) for f in found] == [("executor:stalled", "P1")]
    assert found[0]["artifact_rel"] == "data/runtime/n8n_runs/n8n_run_executor_last.json" and found[0]["detected_at"] == "2026-10-08T00:00:00+00:00"
    assert "age_h=1.5" in found[0]["detail"]
    # fresh executor: nothing
    (tmp_path / "data/runtime/n8n_runs/n8n_run_executor_last.json").write_text(json.dumps({"finished_at": "2026-10-08T12:30:00+00:00"}))
    assert _runs(fanin.collect(tmp_path, NOW)) == []


def test_no_n8n_lanes_no_ledger_or_env_opt_out_yield_nothing_and_a_note(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADEAI_FANIN_LANE_REGISTRY", "0")
    monkeypatch.setattr(LR, "load_registry", lambda path=None: {"lanes": [{"lane_id": "x", "state": "ACTIVE", "scheduler": {"kind": "cron"}}]})
    monkeypatch.delenv("TRADEAI_FANIN_RUNS", raising=False)
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(tmp_path / "absent.sqlite"))
    assert _runs(fanin.collect(tmp_path, NOW)) == [] and fanin.NOTES["runs_source"] == "ok:no_n8n_lanes"
    _wire(monkeypatch, tmp_path, [])
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(tmp_path / "absent.sqlite"))
    assert _runs(fanin.collect(tmp_path, NOW)) == [] and fanin.NOTES["runs_source"].startswith("unavailable:RuntimeError:NO_LEDGER")
    monkeypatch.setenv("TRADEAI_FANIN_RUNS", "0")
    assert _runs(fanin.collect(tmp_path, NOW)) == [] and fanin.NOTES["runs_source"] == "unavailable:RuntimeError:disabled_by_env"
