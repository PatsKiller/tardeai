"""Heartbeat helper, SLA seed and conformance v0 (06 §3–§4, 05 §3) — hermetic."""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))

import supervisor_heartbeat as hb  # noqa: E402
import seed_supervisor_sla as seed  # noqa: E402
import report_platform_conformance as conf  # noqa: E402


class _Cur:
    def __init__(self, regclass):
        self.regclass = regclass; self.executed = []
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None): self.executed.append(sql)
    def fetchone(self): return (self.regclass,)


class _Conn:
    def __init__(self, regclass): self.cur = _Cur(regclass); self.commits = 0
    def cursor(self): return self.cur
    def commit(self): self.commits += 1
    def rollback(self): pass


def test_beat_writes_file_and_keeps_previous_success(tmp_path):
    env = {"TRADEAI_HEARTBEAT_DIR": str(tmp_path / "hb")}
    r1 = hb.beat("lane-a", success=True, output_signal=True, work_done=2, env=env)
    assert r1["pg"] == "skipped" and Path(r1["file"]).exists() and r1["last_success"]
    r2 = hb.beat("lane-a", env=env)
    assert r2["last_success"] == r1["last_success"] and r2["last_output_signal"] == r1["last_output_signal"]
    assert hb.read_all(env=env)[0]["lane_id"] == "lane-a"


def test_beat_pg_absent_and_written_paths(tmp_path):
    env = {"TRADEAI_HEARTBEAT_DIR": str(tmp_path / "hb")}
    assert hb.beat("lane-b", conn=_Conn(None), env=env)["pg"] == "absent"
    c = _Conn("intelligence.heartbeat")
    r = hb.beat("lane-b", conn=c, success=True, env=env)
    assert r["pg"] == "written" and c.commits == 1 and "ON CONFLICT (lane_id, boot_id)" in c.cur.executed[-1]


def test_beat_never_raises_on_pg_error(tmp_path):
    class Bad(_Conn):
        def cursor(self): raise RuntimeError("db down")
    r = hb.beat("lane-c", conn=Bad(None), env={"TRADEAI_HEARTBEAT_DIR": str(tmp_path)})
    assert r["pg"] == "error" and "db down" in r["pg_error"] and Path(r["file"]).exists()


def test_sla_seed_heuristics():
    rows = seed.build({"lanes": [
        {"lane_id": "cio-wake-dispatch", "owner": "platform", "state": "ACTIVE", "expected_cadence_hours": 0.0833, "scheduler": {"kind": "cron"}, "output_signal": {"kind": "file_mtime", "path": "x"}},
        {"lane_id": "health-agent", "owner": "platform", "state": "ACTIVE", "expected_cadence_hours": 1, "scheduler": {"kind": "systemd"}, "output_signal": {"kind": "json_key", "path": "y"}},
        {"lane_id": "misc-job", "owner": "x", "state": "RETIRED", "scheduler": {"kind": "none"}},
    ]})
    by = {r["lane_id"]: r for r in rows}
    assert by["cio-wake-dispatch"]["memory_context_required"] == "fail-closed" and by["cio-wake-dispatch"]["max_silence_s"] == 900
    assert by["cio-wake-dispatch"]["max_run_s"] == 299 and by["cio-wake-dispatch"]["event_to_effect_p95_s"] == 600
    assert by["health-agent"]["memory_context_required"] == "degraded" and by["health-agent"]["max_silence_s"] == 3 * 3600
    assert by["misc-job"]["max_silence_s"] is None and by["misc-job"]["memory_context_required"] == "none"
    assert all(r["ladder_max"] == 3 for r in rows)


def test_conformance_v0_scores_only_what_has_data(tmp_path):
    root = tmp_path
    (root / "config").mkdir(); (root / "data" / "runtime" / "heartbeats").mkdir(parents=True); (root / "data" / "cio").mkdir()
    (root / "config" / "platform_silos.json").write_text(json.dumps({"silos": [
        {"silo_id": "cio-decision", "title": "t", "lane_prefixes": ["cio-"], "owners": []},
        {"silo_id": "desk-bot", "title": "t", "lane_prefixes": ["telegram"], "owners": []}]}))
    (root / "config" / "lane_registry.json").write_text(json.dumps({"lanes": [
        {"lane_id": "cio-wake", "owner": "p", "state": "ACTIVE", "expected_cadence_hours": 1, "output_signal": {"kind": "file_mtime", "path": "a"}},
        {"lane_id": "cio-old", "owner": "p", "state": "RETIRED"},
        {"lane_id": "orphan-lane", "owner": "nobody", "state": "ACTIVE", "expected_cadence_hours": 2, "output_signal": {"kind": "none"}}]}))
    (root / "data" / "runtime" / "supervisor_sla_seed.json").write_text(json.dumps({"rows": [{"lane_id": "cio-wake"}]}))
    (root / "data" / "runtime" / "heartbeats" / "cio-wake.json").write_text(json.dumps({"lane_id": "cio-wake"}))
    now = dt.datetime(2026, 9, 27, 20, 0, tzinfo=dt.timezone.utc)
    ctxp = root / "data" / "cio" / "memory_contexts.jsonl"
    ctxp.write_text("\n".join(json.dumps(r) for r in [
        {"event": "OPENED", "context_id": "c1", "lane_id": "cio-wake", "opened_at": (now - dt.timedelta(hours=1)).isoformat(), "degraded": False},
        {"event": "COMMITTED", "context_id": "c1", "lane_id": "cio-wake", "committed_at": (now - dt.timedelta(hours=1)).isoformat()},
        {"event": "OPENED", "context_id": "c0", "lane_id": "cio-wake", "opened_at": (now - dt.timedelta(days=3)).isoformat(), "degraded": True}]) + "\n")
    (root / "data" / "cio" / "retrieval_receipts.jsonl").write_text(json.dumps(
        {"lane_id": "cio-wake", "created_at": now.isoformat(), "decision": "HIT_FRESH", "generated": True, "ladder": [1]}) + "\n")
    rep = conf.build(root, now=now, env={})
    by = {s["silo_id"]: s for s in rep["silos"]}
    cio = by["cio-decision"]
    assert cio["active_lanes"] == 1 and cio["standards"]["worker"] == 1.0 and cio["standards"]["monitoring"] == 1.0
    assert cio["standards"]["memory"] == 1.0 and cio["standards"]["research"] == 0.5 and cio["standards"]["identity"] is None
    assert cio["unmeasured"] == ["identity"] and cio["state"] in ("DEGRADED", "NON_CONFORMANT", "CONFORMANT")
    assert by["desk-bot"]["state"] == "UNMEASURED" and by["UNASSIGNED"]["lanes"] == 1
    assert rep["unmeasured_standards_total"] >= 1 and rep["inputs"]["memory_contexts_24h"] == 2
    assert any(f["measure"] == "lanes_with_output_signal_and_cadence" for f in by["UNASSIGNED"]["findings"])
