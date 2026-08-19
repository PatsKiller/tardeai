"""Regression tests for the process_watchlist_agent_jobs cron command form.

Guards two defects at once:

  1. The malformed form that put AGENT_JOBS_LOCK_HELD_EXTERNALLY=1 in the flock
     executable slot (flock: failed to execute ...).

  2. The older form that omitted the env var and silently self-deadlocked
     (outer flock + inner acquire_jobs_lock => OverlapError/exit 99 every run).

No provider, DB, or network access is required.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from lib.agent_jobs_cron import (  # noqa: E402
    CORRECT_FRAGMENT,
    EXTERNAL_ENV,
    LOCK_PATH,
    MALFORMED_FRAGMENT,
    SCRIPT_TOKEN,
    fix_agent_jobs_cron_line,
    transform_crontab,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CANONICAL = PROJECT_ROOT / "crontab_backup.txt"

MALFORMED_LINE = (
    f"*/10 * * * 0,6 cd $PROJ && flock -n -E 99 {LOCK_PATH} {EXTERNAL_ENV} "
    f"/usr/bin/timeout 20m $PY scripts/{SCRIPT_TOKEN} --limit 15 "
    ">> logs/watchlist_agent_jobs.log 2>&1"
)
OLD_LINE = (
    f"*/15 6-19 * * 1-5 cd $PROJ && flock -n -E 99 {LOCK_PATH} timeout 20m "
    f"$PY scripts/{SCRIPT_TOKEN} --limit 10 >> logs/watchlist_agent_jobs.log 2>&1"
)
UNRELATED_LINE = (
    "*/5 * * * * cd $PROJ && $PY scripts/some_other_job.py >> logs/other.log 2>&1"
)


def _agent_jobs_active_lines(text: str) -> list[str]:
    return [
        ln for ln in text.splitlines()
        if SCRIPT_TOKEN in ln and not ln.lstrip().startswith("#")
    ]


def test_fix_malformed_env_placement():
    out = fix_agent_jobs_cron_line(MALFORMED_LINE)
    assert out is not None
    assert f"{LOCK_PATH} env {EXTERNAL_ENV} " in out
    assert f"{LOCK_PATH} {EXTERNAL_ENV} " not in out  # no longer in executable slot
    assert "--limit 15" in out          # schedule/args preserved
    assert ">> logs/watchlist_agent_jobs.log" in out  # logging preserved


def test_fix_old_missing_env_self_deadlock():
    out = fix_agent_jobs_cron_line(OLD_LINE)
    assert out is not None
    assert CORRECT_FRAGMENT in out
    assert "--limit 10" in out


def test_unrelated_line_returns_none_and_is_preserved():
    assert fix_agent_jobs_cron_line(UNRELATED_LINE) is None
    text = MALFORMED_LINE + "\n" + UNRELATED_LINE + "\n"
    out = transform_crontab(text)
    assert UNRELATED_LINE in out          # unrelated content preserved
    assert MALFORMED_LINE not in out      # malformed line fixed
    assert out.count(SCRIPT_TOKEN) == 1


def test_idempotent():
    once = fix_agent_jobs_cron_line(MALFORMED_LINE)
    twice = fix_agent_jobs_cron_line(once)
    assert twice == once


def test_transform_preserves_trailing_newline_and_other_lines():
    text = "FOO=bar\n" + UNRELATED_LINE + "\n" + MALFORMED_LINE + "\n"
    out = transform_crontab(text)
    assert out.endswith("\n")
    assert "FOO=bar" in out
    assert UNRELATED_LINE in out


def test_canonical_snapshot_is_well_formed():
    text = CANONICAL.read_text()
    lines = _agent_jobs_active_lines(text)
    assert len(lines) == 4, f"expected 4 active agent-jobs lines, got {len(lines)}"
    for ln in lines:
        cmd = re.match(r"^\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+(.*)$", ln)
        assert cmd, f"unparseable cron line: {ln[:60]}"
        body = cmd.group(1)
        assert f"flock -n -E 99 {LOCK_PATH} env {EXTERNAL_ENV} " in body, \
            f"missing correct env placement: {body[:100]}"
        assert f"{LOCK_PATH} {EXTERNAL_ENV} " not in body, \
            f"env var in flock executable slot: {body[:100]}"
        assert re.search(r"--limit\s+\d+", body)
        assert ">> logs/watchlist_agent_jobs.log" in body


def test_env_reaches_child_via_flock():
    """flock -> env -> child: the env assignment must reach the child process."""
    child = (
        "import os;"
        "print('seen=' + os.environ.get('AGENT_JOBS_LOCK_HELD_EXTERNALLY','UNSET'))"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(child)
        child_path = f.name
    try:
        r = subprocess.run(
            ["flock", "-n", "-E", "99", LOCK_PATH, "env", EXTERNAL_ENV,
             sys.executable, child_path],
            capture_output=True, text=True, timeout=30,
        )
        assert "seen=1" in r.stdout, (r.stdout, r.stderr)
    finally:
        os.unlink(child_path)


def test_env_is_not_interpreted_as_executable():
    """The malformed form must be detectable: flock fails to exec the assignment."""
    r = subprocess.run(
        ["flock", "-n", "-E", "99", LOCK_PATH, EXTERNAL_ENV,
         sys.executable, "-c", "pass"],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode != 0
    assert "failed to execute" in (r.stdout + r.stderr)


def test_lock_contract_env_skips_reacquire():
    """scripts/lib/agent_jobs_lock.py skips internal flock when env var is set."""
    from lib.agent_jobs_lock import acquire_jobs_lock

    prev = os.environ.get("AGENT_JOBS_LOCK_HELD_EXTERNALLY")
    os.environ["AGENT_JOBS_LOCK_HELD_EXTERNALLY"] = "1"
    try:
        with acquire_jobs_lock(blocking=False) as fd:
            assert fd == -1  # external holder => skip internal re-acquire
    finally:
        if prev is None:
            os.environ.pop("AGENT_JOBS_LOCK_HELD_EXTERNALLY", None)
        else:
            os.environ["AGENT_JOBS_LOCK_HELD_EXTERNALLY"] = prev
