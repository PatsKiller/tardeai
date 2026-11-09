"""ANCHOR: LQ1490_COMMS_INTENT_BUSY_RETRY_20261109. LQ-20261107-1490.

A locked coordination ledger is retried in process. If it stays locked, the
consumer exits 75 and prints ``database is locked``. On this lane's flock
lock, a bare 75 is RUN_SKIPPED_LOCK; the phrase makes it RUN_FAILED exit_75,
which transient-2 retries. A claim this run committed is released back to
QUEUED, so the retry records the incident once. No send.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_comms_intent_consumer as CLI  # noqa: E402
from scripts import n8n_incident_fanin as fanin  # noqa: E402
from scripts.lib import n8n_comms_intent_consumption as C  # noqa: E402
from scripts.lib import n8n_fabric_store as F  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger  # noqa: E402

ROUTES_PATH = ROOT / "config" / "n8n_comms_intent_routes.json"
NOW = datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc)


def _body(wf: str = "tradeai-fabric-error-probe", ex: str = "25953") -> dict:
    return {
        "domain": "fabric",
        "kind": "workflow_error",
        "subject": f"workflow {wf} failed at Fail on purpose",
        "summary": f"{wf}: deliberate failure",
        "workflow_id": wf,
        "execution_id": ex,
        "node": "Fail on purpose",
    }


@pytest.fixture(autouse=True)
def no_send(monkeypatch):
    calls: list[tuple] = []

    def boom(*a, **k):
        calls.append((a, k))
        raise AssertionError("a Telegram chokepoint was called from the comms-intent consumer path")

    fake_alert = types.ModuleType("telegram_alert")
    fake_alert.send_telegram = boom
    fake_alert.record_operator_message = boom
    fake_system = types.ModuleType("scripts.lib.autonomy_watchdog.telegram_system")
    fake_system.send_system = boom
    for name, mod in (
        ("telegram_alert", fake_alert),
        ("scripts.telegram_alert", fake_alert),
        ("scripts.lib.autonomy_watchdog.telegram_system", fake_system),
    ):
        monkeypatch.setitem(sys.modules, name, mod)
    yield calls
    assert calls == []


@pytest.fixture
def env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    (state / "data" / "governance").mkdir(parents=True)
    ledger = state / "data" / "governance" / "n8n_coordination_ledger.sqlite"
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setenv("TRADEAI_N8N_COORDINATION_LEDGER", str(ledger))
    monkeypatch.delenv("TRADEAI_FANIN_COMMS_INTENT", raising=False)
    monkeypatch.setattr(fanin, "HEALTH_CONTRACTS_PATH", tmp_path / "no_contracts.json")
    monkeypatch.setattr(CLI, "_sleep", lambda _s: None)
    led = CoordinationLedger(ledger)
    store = F.CommsIntentStore(led, routes_path=ROUTES_PATH)
    return types.SimpleNamespace(state=state, ledger=ledger, led=led, store=store, tmp=tmp_path)


def _cli(env, *args: str, now: datetime = NOW) -> int:
    return CLI.main([*args, "--ledger", str(env.ledger), "--state-root", str(env.state), "--now", now.isoformat()])


def _q(env, sql: str, params: tuple = ()) -> list[dict]:
    conn = sqlite3.connect(env.ledger)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


def _receipt(env) -> dict:
    return json.loads((env.state / "data" / "runtime" / "n8n-comms-intent-consumer_last.json").read_text())


def test_a_lock_after_claim_is_released_and_the_retry_records_once(env, monkeypatch):
    rec = env.store.accept(_body(), caller_id="n8n-relay", now=(NOW - timedelta(minutes=5)).timestamp())
    real_complete = C.complete
    state = {"complete": 0}

    def complete(conn, intent, mapped, *, token, now, window_s):
        state["complete"] += 1
        if state["complete"] == 1:
            raise sqlite3.OperationalError("database is locked")
        return real_complete(conn, intent, mapped, token=token, now=now, window_s=window_s)

    def fail(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(C, "complete", complete)
    monkeypatch.setattr(C, "fail", fail)
    assert _cli(env, "--apply") == 0
    intent = env.store.get(rec["intent_id"])
    assert intent["state"] == "DONE"
    rows = _q(env, "SELECT state, attempts FROM comms_intent_consumption")
    assert rows == [{"state": "DONE", "attempts": 1}]
    incidents = _q(env, "SELECT count, state FROM comms_intent_incidents")
    assert len(incidents) == 1 and incidents[0]["count"] == 1 and incidents[0]["state"] == "OPEN"
    assert _cli(env, "--apply", now=NOW + timedelta(minutes=5)) == 0
    assert _q(env, "SELECT count FROM comms_intent_incidents")[0]["count"] == 1


def test_a_ledger_that_stays_locked_exits_75_and_prints_the_phrase(env, monkeypatch, capsys):
    env.store.accept(_body(), caller_id="n8n-relay", now=(NOW - timedelta(minutes=5)).timestamp())

    def locked(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(C, "close_expired", locked)
    rc = _cli(env, "--apply")
    assert rc == CLI.EX_TEMPFAIL == 75
    out = capsys.readouterr().out
    assert "database is locked" in out
    assert _receipt(env)["summary"]["busy_attempts"] == CLI._BUSY_ATTEMPTS
    assert _q(env, "SELECT state FROM comms_intents")[0]["state"] == "QUEUED"
    assert _q(env, "SELECT * FROM comms_intent_incidents") == []


def test_a_prior_busy_claim_is_released_on_the_next_run(env):
    rec = env.store.accept(_body(), caller_id="n8n-relay", now=(NOW - timedelta(minutes=5)).timestamp())
    conn = C.connect_rw(env.ledger)
    try:
        it = C.claimable(conn, NOW, 10)[0]
        assert C.claim(conn, it, token="stuck", now=NOW) is True
    finally:
        conn.close()
    path = env.state / "data" / "runtime" / "n8n-comms-intent-consumer_last.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"summary": {"busy_claim_token": "stuck", "error": "OperationalError: database is locked"}}))
    assert _cli(env, "--apply") == 0
    assert env.store.get(rec["intent_id"])["state"] == "DONE"
    assert _q(env, "SELECT count FROM comms_intent_incidents")[0]["count"] == 1
    assert _q(env, "SELECT claim_token FROM comms_intent_consumption")[0]["claim_token"] != "stuck"


def test_exit_75_with_the_lock_phrase_is_retried_and_a_bare_75_is_a_flock_skip(tmp_path):
    """n8n-comms-intent-consumer is lock_kind flock. n8n_run_executor._spawn skips
    exit 75 only when the child did not report a sqlite lock (LQ-1445). This lane
    prints the phrase, so exit 75 is RUN_FAILED exit_75 and transient-2 retries it.
    """
    from scripts import n8n_run_executor as X
    from scripts.lib.n8n_retry_policy import load_policies, verdict

    entry = {
        "lane_id": "n8n-comms-intent-consumer",
        "command": ["python", "scripts/n8n_comms_intent_consumer.py"],
        "lock": "/tmp/tradeai_n8n_comms_intent_consumer.lock",
        "lock_kind": "flock",
        "timeout_s": 60,
        "dry_run_arg": ["--dry-run"],
        "live_arg": ["--apply"],
        "env_allowlist_mode": "report",
        "env_names": [],
    }
    row = {
        "run_id": "d:n8n-comms-intent-consumer:live:20261108T0545",
        "lane_id": "n8n-comms-intent-consumer",
        "mode": "live",
    }
    policy = load_policies().policies["transient-2"]
    phrase = '{"mode": "apply", "ok": false, "error": "OperationalError: database is locked"}'

    def _classify(code: int, *, stdout: str = "", stderr: str = ""):
        def runner(argv, *, timeout, env, cwd):
            return SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)

        receipt = X.execute(
            row, entry, env={}, state_root=tmp_path, code_root=tmp_path, runner=runner,
        )
        return receipt, verdict(receipt["state"], receipt["exit_code"], receipt["reason"], policy)

    busy, busy_verdict = _classify(75, stdout=phrase)
    assert busy["state"] == "RUN_FAILED"
    assert busy["reason"] == "exit_75"
    assert busy["exit_code"] == 75
    assert busy_verdict == "retryable"

    held, held_verdict = _classify(75)
    assert held["state"] == "RUN_SKIPPED_LOCK"
    assert held["reason"] == "flock_held"
    assert held_verdict == "skipped"
