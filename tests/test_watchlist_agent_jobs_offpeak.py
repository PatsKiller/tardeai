"""Behavioral tests for DeepSeek off-peak watchlist agent-jobs wrapper.

No paid provider calls. No live crontab mutation.
"""
from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WRAPPER = ROOT / "scripts" / "run_watchlist_agent_jobs_offpeak.sh"
HELPER = ROOT / "scripts" / "lib" / "deepseek_offpeak.py"
REPORT = ROOT / "scripts" / "report_agent_jobs_spend_soak.py"
sys.path.insert(0, str(ROOT / "scripts"))

from lib.deepseek_offpeak import (  # noqa: E402
    is_deepseek_peak_utc,
    resolve_overnight_soak_cap,
    should_peak_skip,
)


def utc(h, m=0):
    return datetime(2026, 8, 19, h, m, tzinfo=timezone.utc)


def _isolated_env(tmp_path, **extra):
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path / "home"),
        "PROJ": str(ROOT),
        "PY": sys.executable,
        "TRADEAI_RUN_ENV_PATH": str(tmp_path / "no-run-env"),
        "LANG": "C.UTF-8",
        "HERMES_ALLOW_DEEPSEEK_PEAK": "",
    }
    env.update(extra)
    return env


def _write_operator_env(tmp_path, body: str) -> None:
    op = tmp_path / "home" / ".config" / "tradeai" / "agent-operator.env"
    op.parent.mkdir(parents=True)
    op.write_text(body)


@pytest.fixture
def offpeak_now():
    return "2026-08-19T00:30:00Z"


def test_is_deepseek_peak_utc_windows_deterministic():
    assert is_deepseek_peak_utc(utc(0, 59)) is False
    assert is_deepseek_peak_utc(utc(1, 0)) is True
    assert is_deepseek_peak_utc(utc(3, 59)) is True
    assert is_deepseek_peak_utc(utc(4, 0)) is False
    assert is_deepseek_peak_utc(utc(5, 59)) is False
    assert is_deepseek_peak_utc(utc(6, 0)) is True
    assert is_deepseek_peak_utc(utc(9, 59)) is True
    assert is_deepseek_peak_utc(utc(10, 0)) is False
    edt_peak = datetime.fromisoformat("2026-08-18T21:00:00-04:00")
    assert is_deepseek_peak_utc(edt_peak) is True
    edt_off = datetime.fromisoformat("2026-08-19T00:10:00-04:00")
    assert is_deepseek_peak_utc(edt_off) is False


def test_hermes_peak_override(monkeypatch):
    monkeypatch.setenv("HERMES_ALLOW_DEEPSEEK_PEAK", "1")
    assert should_peak_skip(utc(1, 30)) is False
    monkeypatch.delenv("HERMES_ALLOW_DEEPSEEK_PEAK")
    assert should_peak_skip(utc(1, 30)) is True


def test_soak_cap_resolve():
    assert resolve_overnight_soak_cap(None)["origin"] == "soak"
    assert resolve_overnight_soak_cap("")["cap"] == 2.00
    assert resolve_overnight_soak_cap("0")["origin"] == "soak"
    assert resolve_overnight_soak_cap("-1")["cap"] == 2.00
    kept = resolve_overnight_soak_cap("0.50")
    assert kept["origin"] == "keep"
    assert kept["cap"] == 0.50
    assert resolve_overnight_soak_cap("abc")["ok"] is False
    assert resolve_overnight_soak_cap("nan")["ok"] is False


def test_wrapper_exists_contract():
    assert WRAPPER.is_file()
    mode = WRAPPER.stat().st_mode
    WRAPPER.chmod(mode | stat.S_IXUSR)
    text = WRAPPER.read_text()
    assert "set -euo pipefail" in text
    assert "--limit 8" in text
    command_lines = "\n".join(
        ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")
    )
    assert "--scheduled-canary" not in command_lines
    assert 'TRADEAI_OFFPEAK_TIMEOUT_SEC:-20m' in text
    assert 'timeout "$TIMEOUT_SPEC"' in text
    assert "AGENT_JOBS_LOCK_HELD_EXTERNALLY=1" in text
    assert "/tmp/tradeai_watchlist_agent_jobs.lock" in text
    assert "PEAK_SKIP" in text
    assert "SOAK_CAP=2.00 (not measured; overnight lane only)" in text
    assert "TRADEAI_OFFPEAK_DRY_RUN" in text
    assert "HERMES_ALLOW_DEEPSEEK_PEAK" in HELPER.read_text()
    # env assignment must not be flock's executable (#399 form)
    flock_lines = [ln for ln in text.splitlines() if "flock" in ln and not ln.strip().startswith("#")]
    for ln in flock_lines:
        assert not re.search(r"\bflock\b.*\benv\b", ln), ln
        assert "LLM_GLOBAL_DAILY_USD_CAP=" not in ln.split("flock", 1)[-1]
    assert "export AGENT_JOBS_LOCK_HELD_EXTERNALLY=1" in text
    # never unlink a held lock
    assert 'rm -f "$LOCK"' not in command_lines
    assert "rm -f ${LOCK}" not in command_lines
    assert "unlink " not in command_lines
    # documented cron: no unescaped %
    cron_comments = [ln for ln in text.splitlines() if "run_watchlist_agent_jobs_offpeak.sh" in ln and ln.strip().startswith("#")]
    assert any("*/15 0-1 * * 1-6" in ln for ln in cron_comments)
    for ln in cron_comments:
        assert "%" not in ln
        assert "*/5 0-5" not in ln
    assert "*/15 0-1 * * 0" in text


def test_peak_window_skipped_exit_0(tmp_path, offpeak_now):
    _write_operator_env(tmp_path, "deepseek_tradeai=test-secret-not-printed\n")
    log = tmp_path / "peak.log"
    env = _isolated_env(
        tmp_path,
        TRADEAI_OFFPEAK_LOG=str(log),
        TRADEAI_OFFPEAK_DRY_RUN="1",
        TRADEAI_OFFPEAK_NOW_UTC="2026-08-19T01:30:00Z",
        AGENT_JOBS_LOCK_PATH=str(tmp_path / "jobs.lock"),
    )
    proc = subprocess.run(["bash", str(WRAPPER)], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, (proc.stdout, proc.stderr, log.read_text() if log.exists() else "")
    body = log.read_text()
    assert "PEAK_SKIP" in body
    assert "exit=0" in body
    assert "test-secret-not-printed" not in body
    assert "mode=offpeak_drain" not in body
    assert "mode=dry_run" not in body


def test_hermes_override_runs_during_peak_dry_run(tmp_path):
    _write_operator_env(tmp_path, "deepseek_tradeai=test-secret-not-printed\n")
    log = tmp_path / "ov.log"
    lock = tmp_path / "jobs.lock"
    env = _isolated_env(
        tmp_path,
        TRADEAI_OFFPEAK_LOG=str(log),
        TRADEAI_OFFPEAK_DRY_RUN="1",
        TRADEAI_OFFPEAK_NOW_UTC="2026-08-19T01:30:00Z",
        HERMES_ALLOW_DEEPSEEK_PEAK="1",
        AGENT_JOBS_LOCK_PATH=str(lock),
    )
    proc = subprocess.run(["bash", str(WRAPPER)], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, (proc.stdout, proc.stderr, log.read_text() if log.exists() else "")
    body = log.read_text()
    assert "PEAK_SKIP" not in body
    assert "mode=dry_run" in body
    assert "lock_ok=" in body


def test_offpeak_proceeds_to_flock_env(tmp_path):
    _write_operator_env(tmp_path, "deepseek_tradeai=test-secret-not-printed\nLLM_GLOBAL_DAILY_USD_CAP=0.75\n")
    log = tmp_path / "off.log"
    lock = tmp_path / "jobs.lock"
    env = _isolated_env(
        tmp_path,
        TRADEAI_OFFPEAK_LOG=str(log),
        TRADEAI_OFFPEAK_DRY_RUN="1",
        TRADEAI_OFFPEAK_NOW_UTC="2026-08-19T00:30:00Z",
        AGENT_JOBS_LOCK_PATH=str(lock),
    )
    proc = subprocess.run(["bash", str(WRAPPER)], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, (proc.stdout, proc.stderr, log.read_text() if log.exists() else "")
    body = log.read_text()
    assert "PEAK_SKIP" not in body
    assert "mode=dry_run" in body
    assert "env_loaded=agent-operator.env" in body
    assert "lock_ok=" in body
    assert "lock_held_externally=1" in body
    assert "LLM_GLOBAL_DAILY_USD_CAP_ok=yes" in body
    assert "SOAK_CAP=2.00" not in body
    assert "test-secret-not-printed" not in body
    assert "success: dry_run complete" in body


def test_missing_cap_gets_soak_2(tmp_path):
    _write_operator_env(tmp_path, "deepseek_tradeai=test-secret-not-printed\n")
    log = tmp_path / "soak.log"
    env = _isolated_env(
        tmp_path,
        TRADEAI_OFFPEAK_LOG=str(log),
        TRADEAI_OFFPEAK_DRY_RUN="1",
        TRADEAI_OFFPEAK_NOW_UTC="2026-08-19T00:30:00Z",
        AGENT_JOBS_LOCK_PATH=str(tmp_path / "jobs.lock"),
    )
    proc = subprocess.run(["bash", str(WRAPPER)], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, log.read_text() if log.exists() else proc.stderr
    body = log.read_text()
    assert "SOAK_CAP=2.00 (not measured; overnight lane only)" in body


def test_malformed_cap_fail_closed(tmp_path):
    _write_operator_env(tmp_path, "deepseek_tradeai=x\nLLM_GLOBAL_DAILY_USD_CAP=not-a-number\n")
    log = tmp_path / "bad.log"
    env = _isolated_env(
        tmp_path,
        TRADEAI_OFFPEAK_LOG=str(log),
        TRADEAI_OFFPEAK_DRY_RUN="1",
        TRADEAI_OFFPEAK_NOW_UTC="2026-08-19T00:30:00Z",
    )
    proc = subprocess.run(["bash", str(WRAPPER)], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 2
    assert "malformed" in log.read_text()


def test_lock_held_exported_to_child_and_limit_8_not_canary(tmp_path):
    _write_operator_env(tmp_path, "deepseek_tradeai=test-secret-not-printed\n")
    log = tmp_path / "child.log"
    dump = tmp_path / "argv.txt"
    stub = tmp_path / "stub_py"
    stub.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "dump = os.environ.get('TRADEAI_OFFPEAK_ARGV_DUMP')\n"
        "if dump:\n"
        "    with open(dump, 'w') as f:\n"
        "        f.write('LOCK_HELD=' + os.environ.get('AGENT_JOBS_LOCK_HELD_EXTERNALLY', '') + '\\n')\n"
        "        f.write('ARGS=' + ' '.join(sys.argv[1:]) + '\\n')\n"
        "sys.exit(0)\n"
    )
    stub.chmod(0o755)
    env = _isolated_env(
        tmp_path,
        PY=str(stub),
        TRADEAI_OFFPEAK_LOG=str(log),
        TRADEAI_OFFPEAK_DRY_RUN="0",
        TRADEAI_OFFPEAK_NOW_UTC="2026-08-19T00:30:00Z",
        TRADEAI_OFFPEAK_TIMEOUT_SEC="5",
        TRADEAI_OFFPEAK_ARGV_DUMP=str(dump),
        AGENT_JOBS_LOCK_PATH=str(tmp_path / "jobs.lock"),
    )
    # Peak/cap helpers need a real interpreter; only the worker is stubbed via PATH? 
    # Wrapper uses $PY for helper AND worker. Stub --resolve-cap/--gate would fail.
    # So run helper with real python by putting a dispatcher stub.
    dispatcher = tmp_path / "dispatch_py"
    dispatcher.write_text(
        "#!/usr/bin/env python3\n"
        "import os, runpy, sys\n"
        "argv = sys.argv[1:]\n"
        "if argv and argv[0].endswith('deepseek_offpeak.py'):\n"
        "    sys.argv = argv\n"
        "    runpy.run_path(argv[0], run_name='__main__')\n"
        "    raise SystemExit(0)\n"
        "if argv and argv[0] == '-c':\n"
        "    exec(argv[1])\n"
        "    raise SystemExit(0)\n"
        "dump = os.environ.get('TRADEAI_OFFPEAK_ARGV_DUMP')\n"
        "if dump:\n"
        "    with open(dump, 'w') as f:\n"
        "        f.write('LOCK_HELD=' + os.environ.get('AGENT_JOBS_LOCK_HELD_EXTERNALLY', '') + '\\n')\n"
        "        f.write('ARGS=' + ' '.join(argv) + '\\n')\n"
        "raise SystemExit(0)\n"
    )
    dispatcher.chmod(0o755)
    env["PY"] = str(dispatcher)
    proc = subprocess.run(["bash", str(WRAPPER)], env=env, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, (proc.stdout, proc.stderr, log.read_text() if log.exists() else "")
    dumped = dump.read_text()
    assert "LOCK_HELD=1" in dumped
    assert "--limit 8" in dumped
    assert "--scheduled-canary" not in dumped
    body = log.read_text()
    assert "mode=offpeak_drain" in body
    assert "success: offpeak drain completed" in body


def test_lock_skip_99(tmp_path):
    _write_operator_env(tmp_path, "deepseek_tradeai=x\n")
    log = tmp_path / "busy.log"
    lock = tmp_path / "jobs.lock"
    env = _isolated_env(
        tmp_path,
        TRADEAI_OFFPEAK_LOG=str(log),
        TRADEAI_OFFPEAK_DRY_RUN="1",
        TRADEAI_OFFPEAK_NOW_UTC="2026-08-19T00:30:00Z",
        AGENT_JOBS_LOCK_PATH=str(lock),
    )
    # Hold lock in a subprocess while wrapper runs
    holder = subprocess.Popen(["flock", "-n", str(lock), "sleep", "20"])
    try:
        proc = subprocess.run(["bash", str(WRAPPER)], env=env, capture_output=True, text=True, timeout=30)
    finally:
        holder.terminate()
        holder.wait(timeout=5)
    assert proc.returncode == 99
    assert "lock-skip" in log.read_text()
    assert lock.exists()  # never unlinked


def test_report_json_with_mocks():
    sys.path.insert(0, str(ROOT / "scripts"))
    import report_agent_jobs_spend_soak as soak

    payload = soak.build_report(
        ledger_paid_usd_today=lambda: 0.42,
        job_counts_fn=lambda: {"queued": 3, "completed": 1},
    )
    assert payload["ledger_paid_usd_today"] == 0.42
    assert payload["watchlist_agent_jobs"]["queued"] == 3
    assert payload["soak_cap_usd"] == 2.00
    text = json.dumps(payload)
    assert "api_key" not in text.lower() or "redacted" in text


def test_report_db_missing_mocked(monkeypatch):
    import report_agent_jobs_spend_soak as soak

    def boom_ledger():
        raise RuntimeError("no db")

    payload = soak.build_report(
        ledger_paid_usd_today=boom_ledger,
        job_counts_fn=lambda: (_ for _ in ()).throw(RuntimeError("missing")),
    )
    assert payload["ledger_paid_usd_today"] is None
    assert payload["watchlist_agent_jobs"] is None
    assert payload["errors"]


def test_report_cli_json(tmp_path, monkeypatch):
    import report_agent_jobs_spend_soak as soak

    monkeypatch.setattr(
        soak,
        "build_report",
        lambda: {
            "ledger_paid_usd_today": 0.0,
            "watchlist_agent_jobs": {},
            "deepseek_tradeai": "should-redact-if-present",
        },
    )
    # CLI uses build_report then dumps; redact happens inside build_report.
    # Call main with a patched build_report that already looks like output.
    monkeypatch.setattr(
        soak,
        "build_report",
        lambda: soak._redact(
            {
                "ledger_paid_usd_today": 1.25,
                "watchlist_agent_jobs": {"queued": 9},
                "api_key": "SECRET",
            }
        ),
    )
    proc_out = []
    monkeypatch.setattr(soak.sys.stdout, "write", lambda s: proc_out.append(s) or len(s))
    rc = soak.main(["--json"])
    assert rc == 0
    blob = "".join(proc_out)
    data = json.loads(blob)
    assert data["ledger_paid_usd_today"] == 1.25
    assert data["api_key"] == "redacted"
    assert "SECRET" not in blob
