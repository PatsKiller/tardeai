"""run_with_deepseek_offpeak.sh --scheduled --defer-in-process (2026-10-10).

Problem: AGENTS.md §9.3 puts every paid crontab line behind the wrapper, but on PEAK_SKIP the wrapper exits 0
before the process starts, so the lane writes no receipt. scripts/n8n_failure_diagnosis.py is checked stale
at 45 minutes (3 x its 15-minute cadence), so the wrapped line would raise a P1 every night; the install
packet dropped the wrapper instead. The diagnoser already gates its paid call in process (lib/llm_deferral,
same window as --gate-scheduled) and writes an honest receipt counting the call as ``deferred``.

Fix pinned here: an opt-in flag. With ``--scheduled --defer-in-process`` the wrapper runs the command out of
window with LLM_DEFER_OFFPEAK=1 exported (and says PEAK_DEFER_IN_PROCESS); if lib/llm_deferral cannot load it
falls back to the plain PEAK_SKIP (fail closed). Without the flag nothing changes. Hermetic: subprocess with a
faked clock (TRADEAI_OFFPEAK_NOW_UTC), no DB, no network.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

COVERS = ["scripts/run_with_deepseek_offpeak.sh"]
WRAPPER = ROOT / "scripts" / "run_with_deepseek_offpeak.sh"
OUTSIDE = "2026-09-15T12:30:00Z"  # Tue 08:30 EDT: before the 09:00 window
INSIDE = "2026-09-15T13:05:00Z"  # Tue 09:05 EDT
INSIDE_ALL_GATES = "2026-09-15T14:05:00Z"  # Tue 10:05 EDT: inside --gate (10-21 ET) too
PEAK_SUNDAY = "2026-09-21T02:00:00Z"  # Sun 22:00 EDT = Mon 02:00 UTC, DeepSeek peak
PROBE = ["bash", "-c", 'echo "RAN defer=${LLM_DEFER_OFFPEAK:-unset}"']


def _run(flags: list[str], now_utc: str, *, module: Path | None = None, extra_env: dict | None = None):
    env = dict(os.environ, TRADEAI_OFFPEAK_NOW_UTC=now_utc, PY=sys.executable,
               TRADEAI_OFFPEAK_PY=str(module or ROOT / "scripts" / "lib" / "deepseek_offpeak.py"))
    env.pop("TRADEAI_ALLOW_SCHEDULED_PEAK", None)
    env.pop("LLM_DEFER_OFFPEAK", None)
    env.update(extra_env or {})
    return subprocess.run(["bash", str(WRAPPER), *flags, "--", *PROBE], capture_output=True, text=True,
                          env=env, timeout=60)


# ── default behaviour is unchanged ────────────────────────────────────────────


@pytest.mark.parametrize("flags", [["--scheduled"], ["--official"], []])
def test_without_the_flag_nothing_changes_inside(flags):
    r = _run(flags, INSIDE_ALL_GATES)
    assert r.returncode == 0 and "RAN defer=unset" in r.stdout


def test_without_the_flag_peak_skip_still_drops():
    r = _run(["--scheduled"], OUTSIDE)
    assert r.returncode == 0
    assert "PEAK_SKIP gate=--gate-scheduled" in r.stdout and "RAN" not in r.stdout
    assert "PEAK_DEFER_IN_PROCESS" not in r.stdout


# ── the opt-in mode ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("when", [OUTSIDE, PEAK_SUNDAY])
def test_defer_in_process_runs_out_of_window_armed(when):
    r = _run(["--scheduled", "--defer-in-process"], when)
    assert r.returncode == 0, r.stderr
    assert "PEAK_DEFER_IN_PROCESS gate=--gate-scheduled" in r.stdout
    assert "RAN defer=1" in r.stdout  # the lane runs, and its paid calls are gated in process
    assert "PEAK_SKIP gate=" not in r.stdout  # the gate module itself still prints its verdict


def test_defer_in_process_overrides_a_disarmed_environment():
    r = _run(["--scheduled", "--defer-in-process"], OUTSIDE, extra_env={"LLM_DEFER_OFFPEAK": "0"})
    assert r.returncode == 0 and "RAN defer=1" in r.stdout


def test_defer_in_process_inside_window_runs_armed_without_the_defer_line():
    r = _run(["--scheduled", "--defer-in-process"], INSIDE)
    assert r.returncode == 0 and "RAN defer=1" in r.stdout
    assert "PEAK_DEFER_IN_PROCESS" not in r.stdout


@pytest.mark.parametrize("flags", [["--defer-in-process"], ["--official", "--defer-in-process"],
                                   ["--defer-in-process", "--scheduled"]])
def test_defer_in_process_requires_scheduled(flags):
    r = _run(flags, OUTSIDE)
    assert r.returncode == 2 and "RAN" not in r.stdout
    assert "--defer-in-process requires --scheduled" in r.stderr


def test_falls_back_to_peak_skip_when_in_process_gate_is_missing(tmp_path):
    """No lib/llm_deferral beside the gate module -> fail closed: no run at peak."""
    lib = tmp_path / "scripts" / "lib"
    lib.mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "lib" / "deepseek_offpeak.py", lib / "deepseek_offpeak.py")
    r = _run(["--scheduled", "--defer-in-process"], OUTSIDE, module=lib / "deepseek_offpeak.py")
    assert r.returncode == 0
    assert "PEAK_SKIP gate=--gate-scheduled" in r.stdout and "RAN" not in r.stdout
    assert "in-process deferral unavailable" in r.stderr


# ── the two gates share one window ───────────────────────────────────────────


def test_in_process_gate_uses_the_wrappers_window():
    from lib import deepseek_offpeak, llm_deferral

    assert llm_deferral.is_scheduled_deepseek_window is deepseek_offpeak.is_scheduled_deepseek_window
    assert llm_deferral.ENABLE_ENV == "LLM_DEFER_OFFPEAK"


def test_the_diagnoser_gates_its_paid_call_in_process():
    src = (ROOT / "scripts" / "n8n_failure_diagnosis.py").read_text(encoding="utf-8")
    assert "llm_deferral.evaluate(process_id)" in src
    assert 'reason="deferred_offpeak"' in src
