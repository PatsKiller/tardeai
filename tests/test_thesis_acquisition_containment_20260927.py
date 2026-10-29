"""Symbol-thesis acquisition runs after the operator clears containment (2026-09-27).

The 09-15 "agents clear" archived the P0 containment flag and left a tripwire.
The wrapper required the flag to exist (it was built to run DESPITE containment),
so it exited 78 every day from 09-16 and no symbol thesis was acquired.
Hermetic: dry-run mode only, isolated HOME, no provider call.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "run_governed_symbol_thesis_acquisition.sh"


def _run(tmp_path, *, flag=False, tripwire=False):
    home = tmp_path / "home"
    state = home / ".local/state/tradeai"
    (state / "archive").mkdir(parents=True)
    if flag:
        (state / "AGENT_JOBS_P0_CONTAINED").write_text("active reason=test\n")
    if tripwire:
        (state / "archive" / "AGENT_JOBS_P0_CONTAINED.TRIPWIRE.md").write_text("# ARCHIVED -- operator clear\n")
    log = tmp_path / "acq.log"
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "TRADEAI_PROJ": str(ROOT),
        "PY": sys.executable,
        "TRADEAI_RUN_ENV_PATH": str(tmp_path / "no-run-env"),
        "TRADEAI_GOVERNED_THESIS_LOG": str(log),
        "TRADEAI_GOVERNED_THESIS_DRY_RUN": "1",
        "TRADEAI_THESIS_LOCK_PATH": str(tmp_path / "acq.lock"),
        "deepseek_tradeai": "test-key-not-used",
        "LLM_GLOBAL_DAILY_USD_CAP": "1.0",
        "LANG": "C.UTF-8",
    }
    proc = subprocess.run(["bash", str(WRAPPER)], env=env, capture_output=True, text=True, timeout=60)
    return proc.returncode, (log.read_text() if log.exists() else "")


def test_missing_flag_without_operator_clear_still_fails_closed(tmp_path):
    rc, body = _run(tmp_path)
    assert rc == 78
    assert "containment_state=missing" in body and "exit=78" in body


def test_operator_cleared_containment_runs(tmp_path):
    rc, body = _run(tmp_path, tripwire=True)
    assert rc == 0, body
    assert "containment_state=cleared" in body
    assert "success: dry_run complete" in body


def test_active_containment_still_runs_with_process_override(tmp_path):
    rc, body = _run(tmp_path, flag=True)
    assert rc == 0, body
    assert "containment_state=active" in body
    assert "containment_override=process-scoped" in body


def test_wrapper_never_touches_the_host_flag():
    text = WRAPPER.read_text()
    assert 'rm -f "$FLAG_HOST"' not in text and "mv " not in text


def test_autonomous_path_passes_enqueue_refresh(tmp_path):
    """A blocked symbol must enqueue its evidence refresh so the next run can clear it.

    Regression (2026-10-29): the governed wrapper ran the acquisition with --apply but never
    --enqueue-refresh, so a symbol BLOCKED on an evidence gap never enqueued the Hermes refresh
    that would change the evidence — and blocked_backoff kept skipping it on unchanged evidence
    forever. This drives the wrapper's autonomous path with a fake runner and asserts the argv.
    """
    home = tmp_path / "home"
    state = home / ".local/state/tradeai"
    state.mkdir(parents=True)
    (state / "AGENT_JOBS_P0_CONTAINED").write_text("active reason=test\n")
    src = tmp_path / "src"
    (src / "scripts").mkdir(parents=True)
    (src / "scripts" / "run_symbol_thesis_acquisition.py").write_text("")
    argv_file = tmp_path / "argv.txt"
    fake_py = tmp_path / "fake_py.sh"
    fake_py.write_text(f'#!/bin/bash\nprintf "%s\\n" "$@" > "{argv_file}"\nexit 0\n')
    fake_py.chmod(0o755)
    log = tmp_path / "acq.log"
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "TRADEAI_SRC": str(src),
        "TRADEAI_PROJ": str(src),
        "PY": str(fake_py),
        "TRADEAI_RUN_ENV_PATH": str(tmp_path / "no-run-env"),
        "TRADEAI_GOVERNED_THESIS_LOG": str(log),
        "TRADEAI_GOVERNED_THESIS_DRY_RUN": "0",
        "TRADEAI_THESIS_LOCK_PATH": str(tmp_path / "acq.lock"),
        "TRADEAI_GOVERNED_THESIS_TIMEOUT_SEC": "30",
        "deepseek_tradeai": "test-key-not-used",
        "LLM_GLOBAL_DAILY_USD_CAP": "1.0",
        "LANG": "C.UTF-8",
    }
    proc = subprocess.run(["bash", str(WRAPPER)], env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    argv = argv_file.read_text().splitlines() if argv_file.exists() else []
    assert "--apply" in argv, argv
    assert "--enqueue-refresh" in argv, argv
