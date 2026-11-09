"""A sqlite lock on a flock lane is a retryable failure, not a flock skip.

ANCHOR: N8N_COMMS_INTENT_SQLITE_LOCK_20261109 — flock and the comms-intent consumer
share exit 75. Empty output is a real flock conflict (RUN_SKIPPED_LOCK). Lock text means
the child ran and transient-2 must retry RUN_FAILED exit_75. A non-lock exit 1 stays
terminal. The temp ledger is synthetic. This file never opens the live coordination ledger.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402
from scripts.lib.n8n_retry_policy import (  # noqa: E402
    class_verdict,
    finalize_outcome,
    load_policies,
    next_attempt_at,
)

NOW = "2026-11-09T07:45:00+00:00"
T0 = 1_791_000_000.0


def _policy():
    return load_policies().get("transient-2")


def _runner(code: int, out: str, err: str = ""):
    def run(argv, *, timeout, env, cwd):
        return SimpleNamespace(returncode=code, stdout=out, stderr=err)

    return run


def _spawn(code: int, out: str, err: str = "", *, lock_kind: str = "flock") -> dict:
    return X._spawn(
        {},
        {"lock_kind": lock_kind},
        ["child"],
        _runner(code, out, err),
        60,
        {},
        ROOT,
        None,
        False,
        time.time(),
    )


def _settle(tmp_path: Path, *, attempt: int, state: str, exit_code: int, reason: str, klass: str = "monitor"):
    store = LedgerRunStore(CoordinationLedger(tmp_path / "class.sqlite"))
    store.request(
        run_id="run-1445-0000000001",
        lane_id="n8n-comms-intent-consumer",
        mode="live",
        requested_by="test",
        caller_id="test",
        now=T0,
        slot_key="d:n8n-comms-intent-consumer:live:20261109T0745",
        attempt=attempt,
        klass=klass,
    )
    assert store.claim_next(now=T0) is not None
    row = store.finish(
        "run-1445-0000000001",
        state=state,
        receipt={"exit_code": exit_code, "reason": reason, "duration_s": 0.1, "finished_at": NOW},
        now=T0,
    )
    return finalize_outcome(
        store, row, _policy(), breaker_threshold=99, now=T0, klass=klass, open_breakers=False
    )


def test_lock_text_on_exit_75_is_a_retryable_failure_not_a_flock_skip(tmp_path):
    receipt = _spawn(75, json.dumps({"ok": False, "error": "OperationalError: database is locked"}))
    assert receipt["state"] == "RUN_FAILED"
    assert receipt["reason"] == "exit_75"
    assert receipt["exit_code"] == 75
    assert receipt.get("lock_skipped") is not True
    pol = _policy()
    assert class_verdict(receipt["state"], receipt["exit_code"], receipt["reason"], pol, "monitor") == "retryable"
    assert next_attempt_at(pol, 1, NOW, "monitor") is not None
    out = _settle(tmp_path, attempt=1, state="RUN_FAILED", exit_code=75, reason="exit_75")
    assert out.verdict == "retryable" and out.dead_letter is None


def test_busy_and_sqlite_busy_phrases_are_the_same_retry(tmp_path):
    for text in ("database is busy", "SQLITE_BUSY"):
        receipt = _spawn(75, "", text)
        assert receipt["state"] == "RUN_FAILED" and receipt["reason"] == "exit_75", text
    out = _settle(tmp_path, attempt=1, state="RUN_FAILED", exit_code=75, reason="exit_75")
    assert out.dead_letter is None


def test_empty_exit_75_stays_a_flock_skip():
    receipt = _spawn(75, "", "")
    assert receipt["state"] == "RUN_SKIPPED_LOCK"
    assert receipt["reason"] == "flock_held"
    assert receipt["lock_skipped"] is True
    assert class_verdict("RUN_SKIPPED_LOCK", 75, "flock_held", _policy(), "monitor") == "skipped"


def test_unrelated_exit_75_text_stays_a_flock_skip():
    receipt = _spawn(75, "child exited 75 for another reason", "")
    assert receipt["state"] == "RUN_SKIPPED_LOCK" and receipt["reason"] == "flock_held"


def test_exit_1_fault_stays_terminal_on_attempt_1(tmp_path):
    receipt = _spawn(1, json.dumps({"ok": False, "error": "FileNotFoundError: missing ledger"}))
    assert receipt["state"] == "RUN_FAILED" and receipt["reason"] == "exit_1"
    pol = _policy()
    assert class_verdict("RUN_FAILED", 1, "exit_1", pol, "monitor") == "terminal"
    out = _settle(tmp_path, attempt=1, state="RUN_FAILED", exit_code=1, reason="exit_1")
    assert out.verdict == "terminal" and out.dead_letter is not None


def test_third_lock_attempt_is_the_terminal_dead_letter(tmp_path):
    pol = _policy()
    assert pol.max_attempts == 3
    assert next_attempt_at(pol, 3, NOW, "monitor") is None
    out = _settle(tmp_path, attempt=3, state="RUN_FAILED", exit_code=75, reason="exit_75")
    assert out.verdict == "retryable" and out.dead_letter is not None


def test_send_and_learn_stay_terminal_even_on_exit_75():
    pol = _policy()
    for klass in ("send", "learn"):
        assert class_verdict("RUN_FAILED", 75, "exit_75", pol, klass) == "terminal"


def test_locked_temp_ledger_exits_75_and_the_spawn_retries_it(tmp_path):
    root = tmp_path / "project"
    ledger = root / "data" / "governance" / "ledger.sqlite"
    ledger.parent.mkdir(parents=True)
    holder_py = tmp_path / "hold.py"
    holder_py.write_text(
        "import sqlite3, sys, time\n"
        "c = sqlite3.connect(sys.argv[1], isolation_level=None, timeout=5)\n"
        "c.execute('BEGIN IMMEDIATE')\n"
        "c.execute('CREATE TABLE IF NOT EXISTS _hold(x INTEGER)')\n"
        "print('HELD', flush=True)\n"
        "time.sleep(30)\n"
    )
    holder = subprocess.Popen(
        [sys.executable, str(holder_py), str(ledger)], stdout=subprocess.PIPE, text=True
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "HELD"
        env = {
            "HOME": os.environ["HOME"],
            "PATH": os.environ["PATH"],
            "TMPDIR": str(tmp_path),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(ROOT),
            "TRADE_AI_CI": "1",
            "TRADEAI_STATE_ROOT": str(root),
        }
        started = time.monotonic()
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "n8n_comms_intent_consumer.py"),
                "--apply",
                "--ledger",
                str(ledger),
                "--state-root",
                str(root),
                "--now",
                NOW,
                "--max-intents",
                "1",
            ],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        elapsed = time.monotonic() - started
    finally:
        holder.kill()
        holder.wait(timeout=5)
    assert proc.returncode == 75
    assert elapsed >= 4.0
    assert proc.stderr.strip() == ""
    body = json.loads(proc.stdout)
    assert body["ok"] is False
    assert "database is locked" in str(body.get("error") or "").lower()
    receipt = _spawn(proc.returncode, proc.stdout, proc.stderr)
    assert receipt["state"] == "RUN_FAILED" and receipt["reason"] == "exit_75"
    assert class_verdict(receipt["state"], receipt["exit_code"], receipt["reason"], _policy(), "monitor") == "retryable"
    written = list((root / "data" / "runtime").glob("n8n-comms-intent-consumer_last.json"))
    assert len(written) == 1
