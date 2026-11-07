"""ANCHOR: LLM_HEALTH_GATE_STALE_CHECKS_20261107 — the preflight refused its own lane.

WORK-QUEUE 2026-11-07, item 15 `trade-close-llm-analyzer-source`. The lane failed every weekly slot
(2026-10-18, 10-25, 11-01, 11-02) with

    [FAIL] disabled_model_routing — qwen3:14b → LOCAL_GENERATIVE_RETIRED, blocked=True
    [FAIL] no_unsafe_jobs — analyzer --apply running (pid …): /bin/bash -c cd $PROJ && bash
           $PROJ/scripts/safe_flock.sh /tmp/llm_backtest_review.lock $PY scripts/trade_close_llm_anal…
    [llm-analyzer] LLM preflight FAILED: health_script_pass
    [llm-analyzer] Refusing to run --apply with failed health checks

Neither failure is a model problem:

* check 5 asserted `resolved == SAFE_MODEL`, but local generative is retired — `local_llm` is a
  facade over DeepSeek Flash and `_resolve_model` answers ("LOCAL_GENERATIVE_RETIRED", True), which
  the old assertion can never accept.
* check 7 excludes pid/ppid/grandparent only. The gate runs *as the preflight* of
  `trade_close_llm_analyzer.py --apply`, and in the cron shape that match sits three levels up
  (cron bash -c → safe_flock bash → python analyzer → python gate), so it flagged the lane's own run.

Hermetic: synthetic `ps` output and real /proc ancestry only; no Ollama, no network, no subprocess.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_local_llm_health as H  # noqa: E402

CRON_LINE = (
    "/bin/bash -c cd $PROJ && bash $PROJ/scripts/safe_flock.sh /tmp/llm_backtest_review.lock "
    "$PY scripts/trade_close_llm_analyzer.py --source backtest --limit 50 --apply"
)


# --- check 7: no unsafe jobs ----------------------------------------------------------------


def test_the_lanes_own_cron_shell_is_an_unsafe_job_when_it_is_not_our_ancestor():
    """The live line. With an empty exclude set it is unsafe — this is what the gate saw."""
    ok, detail = H._unsafe_job(f"  PID ARGS\n 4242 {CRON_LINE}\n", exclude_pids=set())
    assert ok is False
    assert "analyzer --apply running (pid 4242)" in detail


def test_every_ancestor_of_the_gate_is_excluded():
    """Our own cron shell must not be an unsafe job, however many levels up it sits."""
    ancestors = {11, 22, 33, 44}
    ps = "  PID ARGS\n" + "".join(f" {pid} {CRON_LINE}\n" for pid in ancestors)
    ok, detail = H._unsafe_job(ps, exclude_pids=ancestors | {99})
    assert ok is True, detail


def test_a_different_tree_running_apply_still_fails_the_gate():
    """Exclusion is by pid, not by pattern: another checkout's --apply must still block ours."""
    ps = f"  PID ARGS\n 4242 {CRON_LINE}\n 4243 {CRON_LINE}\n"
    ok, detail = H._unsafe_job(ps, exclude_pids={4243})
    assert ok is False
    assert "pid 4242" in detail


def test_a_classifier_apply_is_unsafe_too():
    line = " 5151 python scripts/trade_strategy_classifier.py --apply --limit 10"
    ok, detail = H._unsafe_job(line + "\n", exclude_pids=set())
    assert ok is False
    assert detail.startswith("classifier --apply running (pid 5151)")


def test_a_dry_run_of_the_analyzer_is_not_unsafe():
    line = " 6161 python scripts/trade_close_llm_analyzer.py --source backtest --limit 50"
    assert H._unsafe_job(line + "\n", exclude_pids=set()) == (True, "no unsafe jobs")


def test_the_ancestor_walk_reaches_at_least_the_parent():
    ancestors = H._ancestor_pids(os.getpid())
    assert os.getppid() in ancestors
    assert os.getpid() not in ancestors


def test_the_ancestor_walk_terminates_on_a_missing_pid():
    assert H._ancestor_pids(2_147_483_646) == set()


def test_the_gate_excludes_a_marker_bearing_ancestor_three_levels_up(tmp_path):
    """End-to-end shape of the failure: run the real check from a cron-like chain.

    A marker-bearing `bash -c` (exactly what cron runs) sits three levels above the gate, beyond
    the old pid/ppid/grandparent exclusion. The check must report no unsafe jobs.
    """
    gate = ROOT / "scripts" / "check_local_llm_health.py"
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import json, os, sys\n"
        f"sys.path.insert(0, {str(ROOT / 'scripts')!r})\n"
        "import check_local_llm_health as H\n"
        "ok, detail = H._check_no_unsafe_jobs()\n"
        "print(json.dumps({'ok': ok, 'detail': detail, 'exclude': sorted(H._ancestor_pids(os.getpid()))}))\n"
    )
    # bash -c <marker> -> bash <mid> -> python <probe> -> the ancestor walk. `; true` keeps the
    # marker-bearing shell alive while its child runs, as `cd $PROJ && …` does under cron.
    script = tmp_path / "chain.sh"
    script.write_text(
        "#!/bin/bash\n"
        f"bash -c 'bash {script.with_name('mid.sh')} \"$1\"; true' cron \"$1\" "
        "trade_close_llm_analyzer.py --apply\n"
    )
    script.with_name("mid.sh").write_text(
        "#!/bin/bash\n"
        f"\"${{PYTHON:-{sys.executable}}}\" \"$1\"\n"
    )
    result = subprocess.run(["bash", str(script), str(probe)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    payload = result.stdout.strip().splitlines()[-1]
    import json
    report = json.loads(payload)
    assert report["ok"] is True, report["detail"]
    assert gate.exists()


# --- check 5: disabled model routing --------------------------------------------------------


def test_the_retired_sentinel_satisfies_the_route():
    """After the retirement: _resolve_model answers LOCAL_GENERATIVE_RETIRED, blocked=True."""
    assert H._routing_blocked("LOCAL_GENERATIVE_RETIRED", True,
                              safe_model="gemma3:4b", retired="LOCAL_GENERATIVE_RETIRED") is True


def test_the_safe_model_still_satisfies_the_route():
    """If the facade is ever un-retired, routing to the safe model is still the good answer."""
    assert H._routing_blocked("gemma3:4b", True,
                              safe_model="gemma3:4b", retired="LOCAL_GENERATIVE_RETIRED") is True


@pytest.mark.parametrize("resolved,blocked", [
    ("qwen3:14b", True),   # resolved to the disabled model itself
    ("gemma3:4b", False),  # not reported as blocked
    ("", True),            # no resolution at all
    ("some-other:1b", True),
])
def test_a_bad_route_still_fails(resolved, blocked):
    assert H._routing_blocked(resolved, blocked,
                              safe_model="gemma3:4b", retired="LOCAL_GENERATIVE_RETIRED") is False


def test_the_real_facade_keeps_the_gate_green():
    """Pin the invariant to the shipped facade, not a synthetic string."""
    local_llm = pytest.importorskip("local_llm")
    resolved, was_blocked = local_llm._resolve_model("qwen3:14b")
    assert resolved != "qwen3:14b"
    assert H._routing_blocked(resolved, was_blocked, safe_model=H.SAFE_MODEL,
                              retired=local_llm.OLLAMA_MODEL) is True
