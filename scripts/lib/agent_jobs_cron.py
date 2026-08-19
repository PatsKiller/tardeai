"""Canonical command form + fixer for the process_watchlist_agent_jobs cron lane.

Single source of truth for the correct `flock` → `env` → worker shell structure
used by the live crontab. Two distinct bugs are guarded here:

  1. The live defect where `AGENT_JOBS_LOCK_HELD_EXTERNALLY=1` was placed in the
     flock EXECUTABLE slot, producing
     `flock: failed to execute AGENT_JOBS_LOCK_HELD_EXTERNALLY=1`.

  2. The older form that omitted the env var entirely, which silently
     self-deadlocks: the outer `flock` holds /tmp/tradeai_watchlist_agent_jobs.lock,
     then the worker's internal `acquire_jobs_lock()` re-opens the same path and
     hits OverlapError (exit 99) on every run.

The correct form runs `env` as flock's executable with the env assignment as its
argument, so the worker child inherits the flag and skips its internal re-acquire
(see scripts/lib/agent_jobs_lock.py).
"""
from __future__ import annotations

LOCK_PATH = "/tmp/tradeai_watchlist_agent_jobs.lock"
EXTERNAL_ENV = "AGENT_JOBS_LOCK_HELD_EXTERNALLY=1"
SCRIPT_TOKEN = "process_watchlist_agent_jobs.py"

# `flock <lock> env AGENT_JOBS_LOCK_HELD_EXTERNALLY=1 <executable> ...`
CORRECT_FRAGMENT = f"{LOCK_PATH} env {EXTERNAL_ENV} "
# Malformed: env assignment sits where flock expects the executable.
MALFORMED_FRAGMENT = f"{LOCK_PATH} {EXTERNAL_ENV} "


def fix_agent_jobs_cron_line(line: str) -> str | None:
    """Return a corrected line for process_watchlist_agent_jobs, or None if unrelated.

    Only rewrites the flock/env syntax. Schedule, working dir, python path, script
    path, --limit, log redirect and the trailing rc/logging block are preserved
    byte-for-byte. Returns None for any line that is not an agent-jobs cron entry
    (callers keep those unchanged), and returns the line unchanged when already
    correct (idempotent).
    """
    if SCRIPT_TOKEN not in line:
        return None
    if CORRECT_FRAGMENT in line:
        return line  # already correct
    if MALFORMED_FRAGMENT in line:
        return line.replace(MALFORMED_FRAGMENT, CORRECT_FRAGMENT, 1)
    # Older form: env var missing entirely (self-deadlock). Insert it correctly.
    if f"{LOCK_PATH} timeout" in line or f"{LOCK_PATH} /usr/bin/timeout" in line:
        return line.replace(f"{LOCK_PATH} ", CORRECT_FRAGMENT, 1)
    # Unknown shape — do not guess; leave as-is.
    return line


def transform_crontab(text: str) -> str:
    """Apply fix_agent_jobs_cron_line to every line, preserving unrelated content."""
    fixed = [fix_agent_jobs_cron_line(ln) or ln for ln in text.splitlines()]
    return "\n".join(fixed) + ("\n" if text.endswith("\n") else "")
