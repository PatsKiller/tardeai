"""Zombie pipeline_runs rows (2026-10-21).

Measured live (read-only) over 30 h: symbol_enrichment 209 failed, finviz_screener_runner
23 failed + 16 'running', process_watchlist_agent_jobs 9, trade_ai_orchestrator 37 + 3
'running'. Every one was a row left status='running' and later flipped by
remediate_pipeline_failures to failed/{"errors": [], "note": "zombie run cleared"} -> the
alert dispatcher paged "Pipeline FAILED ... Error: []".

Root cause (one, shared): the process was KILLED before PipelineRun.__exit__ ran.
  * symbol_enrichment: pipeline_watchdog Popen()s 15 detached enrichments every 2 h;
    health_tick's orphan cleanup SIGTERMs them 30 s later (135 ticks with
    orphans_terminated=["pipeline-watchdog"]).
  * trade_ai_orchestrator: process_reaper SIGTERMs pile-up duplicates and >20 min runs.
  * finviz_screener_runner: the momentum-scalp lane's subprocess.run(timeout=) SIGKILLs the
    per-screener call ("timeout after 51s", "timeout after 1s" in its 07:20 receipt).
  * process_watchlist_agent_jobs: wrapper `timeout` SIGTERM.
Python's default SIGTERM disposition exits without unwinding, and SIGKILL cannot be caught.

Fix under test: PipelineRun turns SIGTERM/SIGHUP into an unwinding exit and closes the row as
"terminated by SIGTERM"; finviz_screener_runner does the same; the lane runner sends SIGTERM
before SIGKILL and does not spawn a call the outer deadline has already exhausted.
Hermetic: no DB (registry writers are stubbed to a JSONL file), no network, no cron.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

_STUBS = textwrap.dedent("""
    import json, sys, time
    sys.path.insert(0, {scripts!r})
    import pipeline_registry as pr
    LOG = {log!r}
    def _w(**k):
        with open(LOG, "a") as f:
            f.write(json.dumps(k) + "\\n")
    pr.run_start = lambda *a, **k: (_w(ev="start"), 4242)[1]
    pr.run_complete = lambda rid, rows=None: _w(ev="complete", rid=rid)
    pr.run_fail = lambda rid, msg="": _w(ev="fail", rid=rid, msg=str(msg))
    pr.run_terminated = lambda rid, signum: _w(ev="terminated", rid=rid, signum=signum)
""")


def _events(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(x) for x in log.read_text().splitlines() if x.strip()]


def _wait_for(pred, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def _spawn(tmp_path: Path, body: str) -> tuple[subprocess.Popen, Path]:
    log = tmp_path / "runs.jsonl"
    script = tmp_path / "child.py"
    script.write_text(_STUBS.format(scripts=str(SCRIPTS), log=str(log)) + textwrap.dedent(body))
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DB_", "PG"))}
    p = subprocess.Popen([sys.executable, str(script)], cwd=str(ROOT), env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p, log


def test_sigterm_inside_pipelinerun_closes_the_row(tmp_path):
    """The symbol_enrichment / orchestrator / watchlist path: a SIGTERM'd run must close."""
    p, log = _spawn(tmp_path, """
        with pr.PipelineRun("symbol_enrichment", triggered_by="cron"):
            _w(ev="working")
            time.sleep(30)
    """)
    try:
        assert _wait_for(lambda: any(e["ev"] == "working" for e in _events(log))), p.stderr.read()
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=10)
    finally:
        if p.poll() is None:
            p.kill()
    evs = [e["ev"] for e in _events(log)]
    assert evs[0] == "start"
    closing = [e for e in _events(log) if e["ev"] in ("complete", "fail", "terminated")]
    assert closing, f"run left 'running' after SIGTERM (zombie): events={evs}"
    assert closing[0]["ev"] == "terminated" and closing[0]["signum"] == signal.SIGTERM
    assert p.returncode != 0, "a killed run must not exit 0"


def test_terminated_row_is_legible_not_an_empty_error():
    import pipeline_registry as pr
    src = (SCRIPTS / "pipeline_registry.py").read_text()
    assert "def run_terminated" in src
    assert "terminated by" in src and "status='running'" in src
    assert issubclass(pr.PipelineRunTerminated, SystemExit)
    assert pr.PipelineRunTerminated(15).code == 143


def test_handlers_are_restored_and_a_scripts_own_handler_is_left_alone(tmp_path):
    p, log = _spawn(tmp_path, """
        import signal
        own = lambda s, f: None
        signal.signal(signal.SIGHUP, own)
        with pr.PipelineRun("x"):
            _w(ev="inside", hup_own=signal.getsignal(signal.SIGHUP) is own,
               term_dfl=signal.getsignal(signal.SIGTERM) is signal.SIG_DFL)
        _w(ev="after", term_dfl=signal.getsignal(signal.SIGTERM) is signal.SIG_DFL)
    """)
    p.wait(timeout=20)
    assert p.returncode == 0, p.stderr.read()
    ev = {e["ev"]: e for e in _events(log)}
    assert ev["inside"]["hup_own"] is True
    assert ev["inside"]["term_dfl"] is False, "SIGTERM must be handled while a run is open"
    assert ev["after"]["term_dfl"] is True, "default disposition restored after the run"
    assert "complete" in ev


def test_a_clean_run_still_completes_and_a_real_failure_still_fails(tmp_path):
    p, log = _spawn(tmp_path, """
        with pr.PipelineRun("a"):
            pass
        try:
            with pr.PipelineRun("b"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
    """)
    p.wait(timeout=20)
    assert p.returncode == 0, p.stderr.read()
    evs = [(e["ev"], e.get("msg")) for e in _events(log) if e["ev"] != "start"]
    assert evs == [("complete", None), ("fail", "boom")]


def test_finviz_screener_runner_closes_its_row_on_sigterm(tmp_path):
    p, log = _spawn(tmp_path, """
        import finviz_screener_runner as fsr
        import lib.lane_last_receipt as llr
        llr.write_lane_receipt = lambda *a, **k: _w(ev="receipt", ok=k.get("ok"))
        def _slow(**k):
            _w(ev="working")
            time.sleep(30)
        fsr.run_screener = _slow
        raise SystemExit(fsr.main(["--screener", "prime_setups"]))
    """)
    try:
        assert _wait_for(lambda: any(e["ev"] == "working" for e in _events(log)), 20), p.stderr.read()
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=10)
    finally:
        if p.poll() is None:
            p.kill()
    evs = [e["ev"] for e in _events(log)]
    assert "terminated" in evs, f"finviz run left 'running' after SIGTERM: {evs}"


def test_lane_runner_timeout_sends_sigterm_before_sigkill(tmp_path):
    import momentum_scalp_early_lane_runner as lane
    marker = tmp_path / "got_term"
    child = tmp_path / "slow.py"
    child.write_text(textwrap.dedent(f"""
        import signal, sys, time
        def h(s, f):
            open({str(marker)!r}, "w").write("term")
            sys.exit(143)
        signal.signal(signal.SIGTERM, h)
        time.sleep(60)
    """))
    r = lane._run([sys.executable, str(child)], timeout=1)
    assert r["rc"] == 124
    assert marker.exists(), "child was SIGKILLed without a SIGTERM: it could not close its run"


def test_lane_runner_does_not_spawn_a_call_the_deadline_already_exhausted(monkeypatch):
    import momentum_scalp_early_lane_runner as lane
    spawned = []
    monkeypatch.setattr(lane, "_run", lambda cmd, timeout=0: spawned.append(timeout) or
                        {"rc": 0, "latency_ms": 1, "stdout_tail": "", "stderr_tail": ""})
    monkeypatch.setattr(lane, "write_refresh_receipt", lambda *a, **k: None)
    # 20 s deadline, 15 s headroom, already 4 s in -> 1 s left: the 10-21 07:20 "timeout after 1s".
    s = lane.stage_finviz_scan(False, deadline_s=20, started_monotonic=time.monotonic() - 4,
                               screener_ids=["pm_volume_continuation"])
    assert spawned == [], f"spawned a call with {spawned}s left -> guaranteed zombie row"
    assert s["ok"] is False and s["calls"][0]["skipped"] == "outer_deadline_exhausted"


def test_orchestrator_does_not_rewrap_a_termination():
    src = (SCRIPTS / "trade_ai_orchestrator.py").read_text()
    main_block = src[src.index('if __name__ == "__main__":'):]
    assert "PipelineRunTerminated" in main_block, (
        "orchestrator __main__ re-wraps every SystemExit; a termination must pass through")
