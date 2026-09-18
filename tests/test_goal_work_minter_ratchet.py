"""The goal-work minter ratchet must actually execute.

`agent_runtime_live_providers.job_source` built goal `JobRequest`s in-process
and never enqueued them, so they reached neither the intake ON CONFLICT dedup
nor `produce_once`'s `gate_candidate`. That module calls the budget zero times,
so every lap it minted was unbudgeted. It ran at a flat 36 laps an hour: `lap`
reached 85, three distinct dedup keys across 184 rows, 184/184 with
`model_error` and an empty finding, 0/184 closing a need.

It was not hidden. It was simply never counted, because nothing watched for a
NEW path that can create goal work. This test runs the guard inside the only
required context on `main`, so the next one fails the build on the day it is
written instead of after it has run for days.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_goal_work_minters.py"
BASELINE = ROOT / "config" / "goal_work_minter_baseline.json"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECKER), *args],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300)


def test_the_checker_exists_and_is_runnable():
    assert CHECKER.is_file(), "the goal-work minter checker is missing"
    assert BASELINE.is_file(), "the ratchet baseline is missing"


def test_the_ratchet_holds_on_this_tree():
    """Exit code checked for 0 exactly -- not merely 'not a crash'."""
    r = _run()
    assert r.returncode == 0, (
        "goal-work minter ratchet failed:\n"
        f"stdout:\n{r.stdout[-3000:]}\nstderr:\n{r.stderr[-2000:]}")


def test_the_ratchet_reports_its_inventory_or_an_explicit_zero():
    """A silent pass is indistinguishable from a guard that found nothing."""
    r = _run()
    out = (r.stdout + r.stderr).lower()
    assert ("violation" in out) or ("zero undeclared" in out), (
        "the ratchet must state outstanding violations or an explicit clean pass")


def test_the_declared_inventory_names_the_known_minters():
    """Pinned as a set, not a count: a count could be satisfied by the wrong
    modules and would not go RED if the rule started matching something else."""
    declared = set((json.loads(BASELINE.read_text(encoding="utf-8")).get("files") or {}))
    assert "scripts/agent_runtime_live_providers.py" in declared
    assert "scripts/agent_runtime/trigger_sources.py" in declared
    assert "scripts/lib/goal_generation.py" in declared


def test_the_checker_can_go_red(tmp_path):
    """Guard the guard: a NEW undeclared minter must fail the build.

    Without this the ratchet could be vacuous -- passing because it finds
    nothing rather than because nothing new was added.

    The probe is ASSEMBLED FROM FRAGMENTS. The checker scans scripts/ only, so a
    literal here is safe today -- but the telegram chokepoint ratchet learned
    the hard way that a guard widened to the whole tree then flags its own test.
    Plant the pattern without carrying it.
    """
    job_type = "goal_" + "shadow_review"
    probe = (
        "from agent_runtime.agents.dispatcher import JobRequest\n"
        "def source():\n"
        "    return [JobRequest(agent_id='alex', job_type='" + job_type + "',\n"
        "                       input_hash='x', enqueued_at='t',\n"
        "                       dedup_value='goal:probe', trigger_kind='GOAL_DUE',\n"
        "                       payload={'goal_id': 'probe'})]\n"
    )
    planted = ROOT / "scripts" / "_pytest_goal_minter_probe.py"
    planted.write_text(probe, encoding="utf-8")
    try:
        r = _run()
        assert r.returncode != 0, (
            "a new undeclared goal-work minter did NOT fail the ratchet -- "
            f"the guard is vacuous\nstdout:\n{r.stdout[-2000:]}")
        assert "_pytest_goal_minter_probe" in (r.stdout + r.stderr)
    finally:
        planted.unlink(missing_ok=True)


def test_the_scan_still_detects_the_known_minters():
    """Guard the guard's EYES, not just its verdict.

    The ratchet fails on ADDITIONS only. So weakening detection -- dropping a
    name from MINTING_CALLS, say -- would make the scan find fewer minters while
    the ratchet still exited 0 and every other control here stayed green. The
    inventory controls pin the baseline FILE, which such a change never touches.

    `resolved_since_baseline` is the tell: a declared module that the scan no
    longer sees is either genuinely retired (delete it from the baseline
    deliberately) or newly invisible (a bug). Either way it must not pass in
    silence.
    """
    r = _run("--json")
    assert r.returncode == 0, r.stderr[-2000:]
    payload = json.loads(r.stdout)
    assert payload["resolved_since_baseline"] == [], (
        "a declared minter is no longer detected -- detection weakened, or the "
        "module genuinely stopped minting and the baseline was not updated")
    assert payload["current"] == payload["declared"] == 3
