"""Drive the actual registered retry and component loop with fake child effects."""

import copy
import json
import sqlite3
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib import recovery_validator as RV
from tests.test_system_health_freshness_identity_20261012 import agent, core_health_loop  # noqa: F401

NOW = datetime(2026, 10, 18, 14, tzinfo=timezone.utc)
LANE = "finviz-screener-runner"


@pytest.mark.parametrize(
    "case",
    [
        "empty",
        "stale",
        "dry",
        "other_run",
        "other_attempt",
        "other_lane",
        "future",
        "lock_skip",
        "unmapped",
        "monitor_mapping_only",
        "shared_refusal",
        "good",
        "empty_allowed",
        "disarmed",
        "nonzero",
        "uninitialized",
    ],
)
def test_retry_exit_zero_requires_shared_fresh_business_output(agent, monkeypatch, tmp_path, case):
    comp = copy.deepcopy(next(c for c in agent.MONITORED_COMPONENTS if c.get("receipt_lane_id") == LANE))
    comp.pop("lock_file", None)
    if case == "unmapped":
        comp.pop("receipt_lane_id")
        comp.pop("monitor_lane_ids", None)
    if case == "monitor_mapping_only":
        comp.pop("receipt_lane_id")
    ticks, calls, events, escalations = [NOW], [], [], []

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return ticks[0] if tz else ticks[0].replace(tzinfo=None)

    class Conn:
        closed = 0

        def cursor(self):
            return self

        def execute(self, *_a):
            pass

        def fetchone(self):
            return (0,)

        def commit(self):
            pass

    path = tmp_path / "coordination.sqlite"
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(path))
    monkeypatch.setenv("TRADEAI_HEALTH_AGENT_RETRY", "0" if case == "disarmed" else "1")
    monkeypatch.setattr(agent, "datetime", Clock)
    monkeypatch.setattr(agent, "MONITORED_COMPONENTS", [comp])
    monkeypatch.setattr(agent, "_get_conn", lambda: Conn())
    # Fake authoritative complete history qualifies admission mechanics only, never production readiness.
    journal = tmp_path / "state/data/runtime/health_retry_attempts.jsonl"
    journal.parent.mkdir(parents=True, exist_ok=True)
    journal.write_text("")
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    if case != "uninitialized":
        monkeypatch.setattr(agent, "_health_retry_history", lambda path, now: path.read_text())
    monkeypatch.setattr(agent, "_prev_scheduled_fire", lambda *_a: NOW)
    monkeypatch.setattr(
        agent, "_check_component_freshness", lambda *_a, **_k: {"status": "STALE", "reason": "fixture_stale"}
    )
    monkeypatch.setattr(agent, "_check_lock_contention", lambda *_a: {"status": "FREE"})
    monkeypatch.setattr(agent, "_check_output_validity", lambda *_a: {"valid": False, "reason": "fixture_missing"})
    monkeypatch.setattr(agent, "_component_schedule_intent", lambda *_a: {"installed_schedule": "NOT_MEASURED"})
    monkeypatch.setattr(agent, "_log_event", lambda *a, **k: events.append((a, k)))
    monkeypatch.setattr(agent, "_escalate", lambda *a: escalations.append(a))
    fake_pytz = types.ModuleType("pytz")
    fake_pytz.timezone = lambda _: timezone(timedelta(hours=-4))
    monkeypatch.setitem(sys.modules, "pytz", fake_pytz)

    if case == "shared_refusal":
        monkeypatch.setattr(RV, "validate", lambda *a, **k: (False, "review_refusal"))

    class Child:
        returncode = 2 if case == "nonzero" else 0

        def communicate(self, **_kwargs):
            if case != "empty":
                finished = NOW + timedelta(minutes=1)
                if case == "stale":
                    finished = NOW - timedelta(minutes=1)
                if case == "future":
                    finished = NOW + timedelta(days=30)
                rec = {
                    "schema": "RunReceipt@v2",
                    "lane_id": LANE,
                    "run_id": "fixture-live-run",
                    "attempt": 1,
                    "mode": "live",
                    "state": "RUN_DONE",
                    "exit_code": 0,
                    "finished_at": finished.isoformat(),
                    "output_verdict": {"verdict": "produced", "contract_id": LANE},
                }
                row = {k: rec[k] for k in ("lane_id", "run_id", "attempt", "mode", "state", "exit_code", "finished_at")}
                if case.startswith("other_"):
                    rec[{"other_run": "run_id", "other_attempt": "attempt", "other_lane": "lane_id"}[case]] = (
                        2 if case == "other_attempt" else "wrong-identity"
                    )
                if case == "dry":
                    rec["mode"] = "dry_run"
                if case == "lock_skip":
                    rec["lock_skipped"] = True
                if case == "empty_allowed":
                    rec["output_verdict"]["verdict"] = "empty_allowed"
                with sqlite3.connect(path) as db:
                    db.execute(
                        "CREATE TABLE runs (lane_id TEXT, run_id TEXT, attempt INTEGER, mode TEXT, state TEXT, exit_code INTEGER, finished_at TEXT, receipt_json TEXT)"
                    )
                    db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)", (*row.values(), json.dumps(rec)))
            ticks[0] = NOW + timedelta(minutes=2)
            return "", ""

    def fake_popen(command, **_kwargs):
        expected = comp["retry_cmd"].replace(".venv/bin/python", sys.executable, 1)
        assert command == expected
        calls.append(command)
        return Child()

    monkeypatch.setattr(agent.subprocess, "Popen", fake_popen)
    report = core_health_loop(agent)(dry_run=False)
    check = report["checks"][0]
    recovered = case in ("good", "empty_allowed")
    assert (check["status"] == "RECOVERED") is recovered
    assert any(a[2] == "RECOVERED" for a, _ in events) is recovered
    assert bool(escalations) is not recovered
    assert len(calls) == (0 if case in ("disarmed", "uninitialized") else 1)
    if case == "uninitialized":
        assert report["summary"]["retried"] == 0 and report["summary"]["retry_held"] == 1
        assert check["action_taken"] == "retry_held_escalated"
        assert check["recovery_reason"] == "retry_budget_uninitialized"
        assert journal.read_text() == ""
    if not recovered:
        assert check["recovery_reason"], "attempt completion must leave a useful refusal reason"
