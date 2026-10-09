"""scripts/n8n_run_executor.py (n8n scheduler-of-record tranche N1, 2026-10-08).

`--once` against a tmp_path ledger and state root, with the REAL scripts/safe_flock.sh wrapper and a fake
runner script in tmp_path: exit 0 -> RUN_DONE, exit 3 -> RUN_FAILED, a live pid file -> RUN_SKIPPED_LOCK,
a sleeper under a 1 s timeout -> RUN_TIMEOUT, a lane missing from the allowlist -> RUN_REFUSED, and a mode
whose argument is null -> RUN_REFUSED. Every row ends with a RunReceipt@v1 on the row, in n8n_runs/<run_id>.json
and in n8n_run_executor_last.json. Never touches the live ledger, crontab or token store."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import n8n_run_executor as X  # noqa: E402
from scripts.lib.n8n_coordination_ledger import CoordinationLedger, LedgerRunStore  # noqa: E402

T0 = 1_791_000_000.0


@pytest.fixture
def bench(tmp_path, monkeypatch):
    """A scratch code root holding the real safe_flock.sh and a fake runner; a scratch state root; a ledger."""
    code = tmp_path / "code"
    (code / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "safe_flock.sh", code / "scripts" / "safe_flock.sh")
    (code / "GIT_SHA").write_text("f" * 40 + "\n")
    runner = code / "scripts" / "fake_lane.py"
    runner.write_text(
        "import os, sys, time, pathlib\n"
        "mode = sys.argv[1] if len(sys.argv) > 1 else 'none'\n"
        "code = int(os.environ.get('FAKE_EXIT', '0'))\n"
        "sleep = float(os.environ.get('FAKE_SLEEP', '0'))\n"
        "sig = os.environ.get('FAKE_SIGNAL')\n"
        "print('fake lane mode=' + mode)\n"
        "if sleep: time.sleep(sleep)\n"
        "if sig and mode == '--apply':\n"
        "    p = pathlib.Path(sig); p.parent.mkdir(parents=True, exist_ok=True); p.write_text('ran\\n')\n"
        "sys.exit(code)\n"
    )
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(state))
    monkeypatch.setenv("SAFE_FLOCK_LOG_DIR", str(tmp_path / "flock-logs"))  # never the repo's logs/
    monkeypatch.setenv("TRADEAI_VENV_PYTHON", sys.executable)
    monkeypatch.delenv("FAKE_EXIT", raising=False)
    monkeypatch.delenv("FAKE_SLEEP", raising=False)
    monkeypatch.setenv("FAKE_SIGNAL", str(state / "data" / "runtime" / "fake_lane_last.json"))
    allow = {
        "schema": "N8nRunAllowlist@v1",
        "lanes": [
            {
                "lane_id": "fake-lane",
                "command": ["$PY", "scripts/fake_lane.py"],
                "lock": str(tmp_path / "locks" / "fake.lock"),
                "timeout_s": 1,
                "dry_run_arg": ["--dry-run"],
                "live_arg": ["--apply"],
                "market_gate": False,
                "output_signal": "data/runtime/fake_lane_last.json",
            },
            {
                "lane_id": "live-only-lane",
                "command": ["$PY", "scripts/fake_lane.py"],
                "lock": str(tmp_path / "locks" / "lo.lock"),
                "timeout_s": 5,
                "dry_run_arg": None,
                "live_arg": ["--apply"],
            },
            {
                "lane_id": "flock-lane",
                "command": ["$PY", "scripts/fake_lane.py"],
                "lock": str(tmp_path / "locks" / "fl.lock"),
                "lock_kind": "flock",
                "timeout_s": 5,
                "dry_run_arg": ["--dry-run"],
                "live_arg": ["--apply"],
            },
        ],
    }
    (tmp_path / "locks").mkdir()
    allow_path = tmp_path / "allow.json"
    allow_path.write_text(json.dumps(allow))
    ledger_path = tmp_path / "ledger.sqlite"
    yield {"code": code, "state": state, "allow": allow_path, "ledger": ledger_path, "locks": tmp_path / "locks"}


def _request(ledger_path: Path, run_id: str, lane: str, mode: str, now: float) -> None:
    ledger = CoordinationLedger(ledger_path)
    LedgerRunStore(ledger).request(
        run_id=run_id, lane_id=lane, mode=mode, requested_by="test", caller_id="n8n-relay", now=now
    )
    ledger.close()


def _once(bench) -> int:
    return X.main(
        [
            "--once",
            "--ledger",
            str(bench["ledger"]),
            "--allowlist",
            str(bench["allow"]),
            "--code-root",
            str(bench["code"]),
            "--state-root",
            str(bench["state"]),
        ]
    )


def _row(bench, run_id: str) -> dict:
    ledger = CoordinationLedger(bench["ledger"])
    try:
        return LedgerRunStore(ledger).get(run_id)
    finally:
        ledger.close()


def test_exit_zero_is_run_done_with_receipt_in_three_places_and_the_output_signal_moved(bench, capsys):
    _request(bench["ledger"], "run-exit0-0000000001", "fake-lane", "live", T0)
    assert _once(bench) == 0
    row = _row(bench, "run-exit0-0000000001")
    assert row["state"] == "RUN_DONE" and row["exit_code"] == 0 and row["duration_s"] is not None and row["started_at"]
    r = row["receipt"]
    assert (
        r["schema"] == "RunReceipt@v1"
        and r["state"] == "RUN_DONE"
        and r["lock_skipped"] is False
        and r["timed_out"] is False
    )
    assert (
        r["code_sha"] == "f" * 40 and r["mode"] == "live" and r["output_signal"] == "data/runtime/fake_lane_last.json"
    )
    assert r["output_signal_mtime_before"] is None and r["output_signal_mtime_after"] is not None  # rail 8: it moved
    assert r["argv"][:3] == ["bash", "scripts/safe_flock.sh", str(bench["locks"] / "fake.lock")]
    assert (
        r["argv"][3:7] == ["timeout", "-k", "30", "1"]
        and r["argv"][-1] == "--apply"
        and "market_day_gate" not in " ".join(r["argv"])
    )
    assert "fake lane mode=--apply" in r["stdout_tail"]
    per_run = json.loads((bench["state"] / "data" / "runtime" / "n8n_runs" / "run-exit0-0000000001.json").read_text())
    last = json.loads((bench["state"] / "data" / "runtime" / "n8n_run_executor_last.json").read_text())
    assert per_run == r == last
    assert "safe_flock_events.jsonl" in os.listdir(os.environ["SAFE_FLOCK_LOG_DIR"])
    out = capsys.readouterr().out
    assert '"state": "RUN_DONE"' in out


def test_dry_run_passes_the_dry_run_argument_and_moves_nothing(bench):
    _request(bench["ledger"], "run-dry00-0000000001", "fake-lane", "dry_run", T0)
    assert _once(bench) == 0
    r = _row(bench, "run-dry00-0000000001")["receipt"]
    assert r["state"] == "RUN_DONE" and r["argv"][-1] == "--dry-run"
    assert r["output_signal_mtime_before"] is None and r["output_signal_mtime_after"] is None


def test_nonzero_exit_is_run_failed(bench, monkeypatch):
    monkeypatch.setenv("FAKE_EXIT", "3")
    _request(bench["ledger"], "run-exit3-0000000001", "fake-lane", "live", T0)
    _once(bench)
    row = _row(bench, "run-exit3-0000000001")
    assert row["state"] == "RUN_FAILED" and row["exit_code"] == 3 and row["receipt"]["reason"] == "exit_3"


def test_a_live_pid_file_on_the_lane_lock_is_run_skipped_lock(bench):
    lock = bench["locks"] / "fake.lock"
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (lock.parent / (lock.name + ".pid")).write_text(f"{sleeper.pid}\n")
        (lock.parent / (lock.name + ".meta")).write_text(f"started_epoch={int(time.time())}\n")
        _request(bench["ledger"], "run-lock0-0000000001", "fake-lane", "live", T0)
        _once(bench)
    finally:
        sleeper.kill()
        sleeper.wait()
    row = _row(bench, "run-lock0-0000000001")
    assert row["state"] == "RUN_SKIPPED_LOCK" and row["exit_code"] == 0
    r = row["receipt"]
    assert (
        r["lock_skipped"] is True
        and r["reason"] == "safe_flock_pid_running"
        and "safe_flock: skipped" in r["stderr_tail"]
    )
    assert r["output_signal_mtime_after"] is None  # exit 0, nothing ran: visible on the receipt


def test_flock_kind_reuses_a_cron_style_lock_and_reports_conflict_as_skipped(bench):
    lock = bench["locks"] / "fl.lock"
    # Hold the real kernel flock directly: acquisition/release are complete
    # before either executor call, including on a CPU-contended test host.
    # Waiting for a killed flock parent did not wait for its sleep child to
    # close the inherited descriptor, causing a false second lock skip.
    with lock.open("a") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        try:
            _request(bench["ledger"], "run-flock-0000000001", "flock-lane", "live", T0)
            _once(bench)
        finally:
            fcntl.flock(holder, fcntl.LOCK_UN)
    row = _row(bench, "run-flock-0000000001")
    assert row["state"] == "RUN_SKIPPED_LOCK" and row["exit_code"] == X.FLOCK_CONFLICT_EXIT
    assert row["receipt"]["argv"][:5] == ["flock", "-n", "-E", "75", str(lock)]
    _request(bench["ledger"], "run-flock-0000000002", "flock-lane", "live", T0 + 1)
    _once(bench)
    assert _row(bench, "run-flock-0000000002")["state"] == "RUN_DONE"


def test_timeout_is_run_timeout(bench, monkeypatch):
    monkeypatch.setenv("FAKE_SLEEP", "5")
    _request(bench["ledger"], "run-tmout-0000000001", "fake-lane", "live", T0)  # timeout_s = 1
    started = time.time()
    _once(bench)
    assert time.time() - started < 20
    row = _row(bench, "run-tmout-0000000001")
    assert row["state"] == "RUN_TIMEOUT" and row["exit_code"] in (124, 137) and row["receipt"]["timed_out"] is True


def test_missing_lane_and_unavailable_mode_are_refused_without_spawning(bench):
    _request(bench["ledger"], "run-refus-0000000001", "not-in-allowlist", "live", T0)
    _request(bench["ledger"], "run-refus-0000000002", "live-only-lane", "dry_run", T0 + 1)
    _request(bench["ledger"], "run-refus-0000000003", "fake-lane", "apply", T0 + 2)
    _once(bench)
    a, b, c = (_row(bench, f"run-refus-000000000{i}") for i in (1, 2, 3))
    assert (
        a["state"] == "RUN_REFUSED"
        and a["receipt"]["reason"] == "lane_not_allowlisted"
        and a["receipt"]["argv"] is None
    )
    assert b["state"] == "RUN_REFUSED" and b["receipt"]["reason"] == "mode_unavailable:dry_run"
    assert c["state"] == "RUN_REFUSED" and c["receipt"]["reason"] == "bad_mode"
    assert all(r["exit_code"] is None for r in (a, b, c))
    assert sorted(p.name for p in (bench["state"] / "data" / "runtime" / "n8n_runs").glob("*.json")) == [
        "run-refus-0000000001.json",
        "run-refus-0000000002.json",
        "run-refus-0000000003.json",
    ]


def test_once_drains_oldest_first_and_an_empty_queue_exits_clean(bench):
    assert _once(bench) == 0
    _request(bench["ledger"], "run-order-0000000002", "fake-lane", "dry_run", T0 + 5)
    _request(bench["ledger"], "run-order-0000000001", "fake-lane", "dry_run", T0)
    _once(bench)
    rows = [_row(bench, f"run-order-000000000{i}") for i in (1, 2)]
    assert all(r["state"] == "RUN_DONE" for r in rows)
    assert rows[0]["started_at"] <= rows[1]["started_at"]


def test_bad_allowlist_is_exit_2_and_malformed_entries_are_dropped(bench, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "Other@v1"}))
    assert (
        X.main(["--once", "--ledger", str(bench["ledger"]), "--allowlist", str(bad), "--code-root", str(bench["code"])])
        == 2
    )
    mixed = tmp_path / "mixed.json"
    mixed.write_text(
        json.dumps(
            {
                "schema": "N8nRunAllowlist@v1",
                "lanes": [
                    {"lane_id": "ok", "command": ["true"], "lock": "/tmp/x.lock", "timeout_s": 5, "live_arg": []},
                    {"lane_id": "no-lock", "command": ["true"], "timeout_s": 5, "live_arg": []},
                    {"lane_id": "relative-lock", "command": ["true"], "lock": "x.lock", "timeout_s": 5, "live_arg": []},
                    {"lane_id": "no-mode", "command": ["true"], "lock": "/tmp/y.lock", "timeout_s": 5},
                    {
                        "lane_id": "bad-timeout",
                        "command": ["true"],
                        "lock": "/tmp/z.lock",
                        "timeout_s": 0,
                        "live_arg": [],
                    },
                    {
                        "lane_id": "abs-signal",
                        "command": ["true"],
                        "lock": "/tmp/w.lock",
                        "timeout_s": 5,
                        "live_arg": [],
                        "output_signal": "/etc/passwd",
                    },
                    {
                        "lane_id": "bad-kind",
                        "command": ["true"],
                        "lock": "/tmp/v.lock",
                        "lock_kind": "none",
                        "timeout_s": 5,
                        "live_arg": [],
                    },
                ],
            }
        )
    )
    assert set(X.load_allowlist(mixed)) == {"ok"}
    assert (
        X.validate_entry(
            {
                "lane_id": "x",
                "command": ["true"],
                "lock": "/tmp/x",
                "timeout_s": 1,
                "dry_run_arg": ["--dry-run"],
                "market_gate": True,
            }
        )
        is None
    )


def test_market_gate_and_tokens_resolve_in_build_argv(tmp_path):
    entry = {
        "lane_id": "g",
        "command": ["$PY", "scripts/x.py", "--root", "$STATE_ROOT/data"],
        "lock": "/tmp/g.lock",
        "timeout_s": 7,
        "dry_run_arg": ["--dry-run"],
        "live_arg": ["--apply"],
        "market_gate": True,
    }
    argv = X.build_argv(
        entry, "live", env={"TRADEAI_VENV_PYTHON": "/venv/bin/python"}, state_root=Path("/state"), code_root=tmp_path
    )
    assert argv == [
        "bash",
        "scripts/safe_flock.sh",
        "/tmp/g.lock",
        "timeout",
        "-k",
        "30",
        "7",
        "bash",
        "scripts/market_day_gate.sh",
        "/venv/bin/python",
        "scripts/x.py",
        "--root",
        "/state/data",
        "--apply",
    ]
    assert X.build_argv(entry, "dry_run", env={}, state_root=Path("/s"), code_root=tmp_path)[-5:] == [
        sys.executable,
        "scripts/x.py",
        "--root",
        "/s/data",
        "--dry-run",
    ]
    assert (
        X.build_argv({**entry, "dry_run_arg": None}, "dry_run", env={}, state_root=Path("/s"), code_root=tmp_path)
        is None
    )


def test_unit_file_runs_the_served_tree_with_the_required_shape():
    unit = (ROOT / "config" / "systemd" / "user" / "tradeai-n8n-run-executor.service").read_text(encoding="utf-8")
    assert "WorkingDirectory=%h/trade-ai-releases/portfolio-server/CURRENT" in unit
    assert "EnvironmentFile=-%t/tradeai/env" in unit
    assert "Environment=TRADEAI_STATE_ROOT=%h/trade-ai-releases/persistent-state" in unit
    assert "Restart=always" in unit and "MemoryMax=1G" in unit and "CPUQuota" not in unit
    assert "%h/trade-ai-releases/portfolio-server/CURRENT/scripts/n8n_run_executor.py" in unit
    assert "proposal only" not in unit.lower() and "not installed" not in unit.lower()
    gateway = (ROOT / "config" / "systemd" / "user" / "tradeai-n8n-coordination-gateway.service").read_text(
        encoding="utf-8"
    )
    assert "proposal" not in gateway.lower()
    expected = json.loads((ROOT / "config" / "expected_services.json").read_text(encoding="utf-8"))
    assert "tradeai-n8n-run-executor.service" in {u["unit"] for u in expected["units"]}
    baseline = (ROOT / "config" / "dev_tree_units_baseline.txt").read_text(encoding="utf-8")
    assert "tradeai-n8n-run-executor.service" not in baseline  # it executes CURRENT, not the dev tree
