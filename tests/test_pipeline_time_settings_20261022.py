"""Pipeline time settings pinned to measured runtimes (2026-10-22).

docs/ops/PIPELINE_TIME_SETTINGS.md is the single place these numbers and their
evidence live. Each assertion below fails if a later change lowers a setting
under the measured runtime it protects, or breaks the arithmetic that keeps the
health tick inside its systemd unit.

Measured (read-only, pipeline_runs + health_tick_history.jsonl, 2026-10-22):
  * trade_ai_orchestrator market-hours runs on 2026-10-21/22 were SIGTERMed at
    1216-1377s by process_reaper's 20m cap; that cap censors them, so 1377s is a
    floor for p100, not p100. Uncensored completions max 1269s (2026-10-15).
  * symbol_enrichment: 224 failed / 1 success in the 36h to 2026-10-22, all
    failures at 29-33s (health_tick orphan_wait_s=30). Uncensored durations
    2026-09-20..10-07 (n=3178): p50 136s, p90 209s, p95 241s, max 419s.
  * Even-hour health ticks: the steps other than pipeline-watchdog took p50
    40s / p95 90s / max 246s (161 undeferred ticks 2026-10-07..10-22).
"""
from __future__ import annotations

import json
import os
import re
import sys
import textwrap
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import process_reaper  # noqa: E402
from scripts import health_tick as ht  # noqa: E402

DOC = ROOT / "docs" / "ops" / "PIPELINE_TIME_SETTINGS.md"
UNIT = ROOT / "config" / "systemd" / "user" / "tradeai-health-tick.service"
STEPS = ROOT / "config" / "health_tick_steps.json"

ORCH_CENSORED_FLOOR_S = 1377      # longest market-hours run seen before the 20m reaper killed it
ORCH_MIN_MARGIN_S = 300           # a true hang must still be caught, but not a slow day
CONTINUOUS_RUNNER_LIMIT_S = 2700  # continuous_runner.run_full_cycle subprocess timeout
ENRICH_P95_S = 241                # uncensored p95, 2026-09-20..10-07
OTHER_STEPS_P95_S = 90            # even-hour tick, non-watchdog steps, p95
OTHER_STEPS_MAX_S = 246           # ... max


def _orch_rule(rules):
    return next(r for r in rules if r["name"] == "trade_ai_orchestrator")


def _unit_timeout_start_s() -> float:
    m = re.search(r"^TimeoutStartSec=(\d+)\s*$", UNIT.read_text(encoding="utf-8"), re.M)
    assert m, "TimeoutStartSec missing from the health-tick unit"
    return float(m.group(1))


@pytest.fixture
def watchdog(monkeypatch):
    monkeypatch.setitem(sys.modules, "psycopg2", types.ModuleType("psycopg2"))
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    sys.modules.pop("pipeline_watchdog", None)
    import pipeline_watchdog
    yield pipeline_watchdog
    sys.modules.pop("pipeline_watchdog", None)


# ── orchestrator reaper cap ─────────────────────────────────────────────────

def test_orchestrator_cap_exceeds_measured_market_hours_runtime_with_margin():
    policy = json.loads((ROOT / "config" / "process_reaper_policy.json").read_text(encoding="utf-8"))
    cap_s = _orch_rule(policy["rules"])["max_runtime_min"] * 60
    assert cap_s >= ORCH_CENSORED_FLOOR_S + ORCH_MIN_MARGIN_S, (
        f"orchestrator reaper cap {cap_s}s is under the measured 1377s market-hours runtime + "
        f"{ORCH_MIN_MARGIN_S}s margin; see docs/ops/PIPELINE_TIME_SETTINGS.md")


def test_orchestrator_fallback_rule_equals_policy():
    policy = json.loads((ROOT / "config" / "process_reaper_policy.json").read_text(encoding="utf-8"))
    assert (_orch_rule(process_reaper.DEFAULT_RULES)["max_runtime_min"]
            == _orch_rule(policy["rules"])["max_runtime_min"])


def test_orchestrator_cap_still_catches_hangs_before_the_runner_limit():
    src = (ROOT / "scripts" / "continuous_runner.py").read_text(encoding="utf-8")
    m = re.search(r"trade_ai_orchestrator\.py.*?subprocess\.run\(cmd, env=os\.environ\.copy\(\), timeout=(\d+)\)",
                  src, re.S)
    assert m and int(m.group(1)) == CONTINUOUS_RUNNER_LIMIT_S
    cap_s = _orch_rule(process_reaper.DEFAULT_RULES)["max_runtime_min"] * 60
    assert cap_s < CONTINUOUS_RUNNER_LIMIT_S


def test_measured_market_hours_run_is_not_reaped_but_a_hang_is():
    rule = _orch_rule(process_reaper.DEFAULT_RULES)
    run = {"pid": 7, "etimes": ORCH_CENSORED_FLOOR_S, "args": "python scripts/trade_ai_orchestrator.py"}
    assert process_reaper._flag(rule, [run]) == ([], [])
    hung = dict(run, etimes=rule["max_runtime_min"] * 60 + 60)
    flagged, _ = process_reaper._flag(rule, [hung])
    assert flagged == [hung]


# ── health tick arithmetic ──────────────────────────────────────────────────

def test_tick_deadline_plus_kill_grace_fits_unit_timeout():
    table = json.loads(STEPS.read_text(encoding="utf-8"))
    deadline = float(table["tick_deadline_s"])
    assert deadline == ht.DEFAULT_TICK_DEADLINE_S
    assert table["tick_budget_s"] <= deadline
    # the last step is clamped to deadline - KILL_GRACE_S, then killed with KILL_GRACE_S;
    # the receipt write needs a few seconds more.
    assert deadline + ht.KILL_GRACE_S + 5 <= _unit_timeout_start_s()


def test_watchdog_enrichment_wait_fits_inside_its_step_and_the_unit(watchdog):
    # SIGTERM grace + SIGKILL reap wait + receipts must fit in the reserve, and the whole
    # supervisor exit path must fit in health_tick's own kill grace (if the tick SIGTERMs it).
    assert watchdog.ENRICHMENT_TERM_GRACE_S + 2 <= watchdog.ENRICHMENT_RESERVE_S
    assert watchdog.ENRICHMENT_TERM_GRACE_S + 2 < ht.KILL_GRACE_S
    # fixed bound covers the measured p95 and fits under the tick deadline
    assert watchdog.ENRICHMENT_BATCH_TIMEOUT_S >= ENRICH_P95_S - 1
    assert (watchdog.ENRICHMENT_BATCH_TIMEOUT_S + watchdog.ENRICHMENT_RESERVE_S
            < float(json.loads(STEPS.read_text(encoding="utf-8"))["tick_deadline_s"]) < _unit_timeout_start_s())


def test_watchdog_batch_is_bounded_by_the_step_budget_health_tick_exports(watchdog, monkeypatch):
    start = watchdog._STEP_STARTED_MONO
    monkeypatch.delenv("HEALTH_TICK_STEP_TIMEOUT_S", raising=False)
    assert watchdog._enrichment_batch_timeout_s(now=start + 5) == watchdog.ENRICHMENT_BATCH_TIMEOUT_S
    monkeypatch.setenv("HEALTH_TICK_STEP_TIMEOUT_S", "200.0")
    assert watchdog._enrichment_batch_timeout_s(now=start + 5) == pytest.approx(200 - 5 - watchdog.ENRICHMENT_RESERVE_S)
    monkeypatch.setenv("HEALTH_TICK_STEP_TIMEOUT_S", "600.0")
    assert watchdog._enrichment_batch_timeout_s(now=start + 5) == watchdog.ENRICHMENT_BATCH_TIMEOUT_S
    monkeypatch.setenv("HEALTH_TICK_STEP_TIMEOUT_S", "10")
    assert watchdog._enrichment_batch_timeout_s(now=start + 5) == 1.0


def test_pipeline_watchdog_runs_last_and_gets_room_for_measured_enrichment():
    table = json.loads(STEPS.read_text(encoding="utf-8"))
    ids = [s["step_id"] for s in table["steps"]]
    assert ids[-1] == "pipeline-watchdog", "the supervising watchdog must not spend the tick of the steps after it"
    budget, deadline = float(table["tick_budget_s"]), float(table["tick_deadline_s"])
    # never deferred at the measured worst case of the other steps ...
    assert OTHER_STEPS_MAX_S < budget
    # ... and at their p95 the watchdog still has the measured enrichment p95 available
    step_window = deadline - OTHER_STEPS_P95_S - ht.KILL_GRACE_S
    assert min(240.0, step_window - 15.0) >= 180.0
    assert step_window - 15.0 > 0


def test_orphan_wait_stays_a_legacy_safety_net():
    table = json.loads(STEPS.read_text(encoding="utf-8"))
    assert table["orphan_wait_s"] == ht.DEFAULT_ORPHAN_WAIT_S == 30


# ── regression: a 45s enrichment child is not killed ────────────────────────

class _FakeClock:
    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.t += max(s, 0.05)


class _FakeChild:
    """A child that runs for `runtime_s` on the fake clock, then exits 0."""

    def __init__(self, clock, runtime_s, pid):
        self.clock, self.end, self.pid = clock, clock.t + runtime_s, pid
        self.returncode = None
        self.signals = []

    def poll(self):
        if self.returncode is None and self.clock.t >= self.end:
            self.returncode = 0
        return self.returncode

    def wait(self, timeout=None):
        return self.poll()


def test_45s_enrichment_child_is_not_killed_under_health_tick(watchdog, monkeypatch):
    clock = _FakeClock()
    child = _FakeChild(clock, 45.0, pid=424242)
    monkeypatch.setattr(watchdog.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(watchdog.time, "sleep", clock.sleep)
    monkeypatch.setattr(watchdog, "_STEP_STARTED_MONO", clock.t)
    # the budget health_tick gives the watchdog when it runs last at the p95 tick
    monkeypatch.setenv("HEALTH_TICK_STEP_TIMEOUT_S", str(300.0 - OTHER_STEPS_P95_S - ht.KILL_GRACE_S))
    monkeypatch.setattr(watchdog, "_process_group_alive", lambda pgid: child.poll() is None)
    killed = []
    monkeypatch.setattr(watchdog.os, "killpg", lambda pgid, sig: killed.append((pgid, sig)))
    outcomes = {}
    with watchdog._supervise_enrichment_batch([("ABC", child)], outcomes=outcomes):
        pass
    assert child.returncode == 0
    assert clock.t - 1000.0 >= 45.0
    assert outcomes == {}
    assert [k for k in killed if k[1] != 0] == []


def test_supervised_child_outlives_orphan_wait_inside_a_real_health_tick_step(tmp_path):
    """End to end, time-scaled: orphan_wait_s=0.2 stands in for the live 30s, and a
    1.5s child stands in for a 45s enrichment. The step waits for it, so it completes."""
    marker = tmp_path / "child.done"
    step_script = tmp_path / "step.py"
    step_script.write_text(textwrap.dedent(f"""
        import subprocess, sys, types
        sys.modules['psycopg2'] = types.ModuleType('psycopg2')
        sys.path.insert(0, {str(ROOT / 'scripts')!r})
        import pipeline_watchdog as w
        child = subprocess.Popen([sys.executable, '-c',
            'import time, pathlib; time.sleep(1.5); pathlib.Path({json.dumps(str(marker))}).write_text(\"ok\")'],
            start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with w._supervise_enrichment_batch([('ABC', child)]):
            pass
        sys.exit(0 if child.returncode == 0 else 3)
    """), encoding="utf-8")
    step = {"step_id": "pipeline-watchdog", "command": ["$PY", str(step_script)], "timeout_s": 30}
    env = {"TRADEAI_DEV_ROOT": str(tmp_path)}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        row = ht.run_step(step, py=sys.executable, project_root=tmp_path, default_timeout_s=30,
                          time_left_s=60, orphan_wait_s=0.2)
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    assert row["outcome"] == "ok", row
    assert row["orphans"] is None
    assert marker.read_text() == "ok"


def test_legacy_fire_and_forget_child_is_what_orphan_wait_kills(tmp_path):
    """Control for the test above: the pre-fix shape (child left in the step's group,
    not waited for) is killed by the same 0.2s orphan wait, so the test discriminates."""
    marker = tmp_path / "child.done"
    step_script = tmp_path / "legacy.py"
    step_script.write_text(textwrap.dedent(f"""
        import subprocess, sys
        subprocess.Popen([sys.executable, '-c',
            'import time, pathlib; time.sleep(1.5); pathlib.Path({json.dumps(str(marker))}).write_text(\"ok\")'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    """), encoding="utf-8")
    step = {"step_id": "legacy", "command": ["$PY", str(step_script)], "timeout_s": 30}
    row = ht.run_step(step, py=sys.executable, project_root=tmp_path, default_timeout_s=30,
                      time_left_s=60, orphan_wait_s=0.2)
    assert row["orphans"] and row["orphans"]["killed"] is True
    assert not marker.exists()


def test_health_tick_exports_the_effective_step_timeout(tmp_path):
    out = tmp_path / "env.txt"
    script = tmp_path / "env_step.py"
    script.write_text(f"import os, pathlib; pathlib.Path({str(out)!r}).write_text(os.environ.get('HEALTH_TICK_STEP_TIMEOUT_S', ''))\n",
                      encoding="utf-8")
    step = {"step_id": "env", "command": ["$PY", str(script)], "timeout_s": 600}
    row = ht.run_step(step, py=sys.executable, project_root=tmp_path, default_timeout_s=240,
                      time_left_s=150, orphan_wait_s=0)
    assert row["outcome"] == "ok", row
    assert float(out.read_text()) == pytest.approx(150 - ht.KILL_GRACE_S)


def test_time_settings_doc_exists_and_names_every_setting():
    text = DOC.read_text(encoding="utf-8")
    for needle in ("max_runtime_min", "orphan_wait_s", "ENRICHMENT_BATCH_TIMEOUT_S", "HEALTH_TICK_STEP_TIMEOUT_S",
                   "TimeoutStartSec", "tick_deadline_s", "1377", "224", "2700"):
        assert needle in text, needle


# ── the "Error: []" alert ───────────────────────────────────────────────────

def test_zombie_clear_alert_names_the_clearer_not_an_empty_list(monkeypatch):
    """remediate_pipeline_failures settles zombies with summary errors=[]; the critical
    alert rendered that as "Error: []". The query now falls through to note + cleared_by."""
    import alert_dispatcher_unified as adu

    seen = []

    class Cur:
        def execute(self, sql, params=None):
            seen.append(sql)

        def fetchall(self):
            if len(seen) == 1:
                return [("trade_ai_orchestrator", "zombie run cleared by remediate_pipeline_failures", 2,
                         "2026-10-22 11:01", "2026-10-22 14:11")]
            return []

    class Conn:
        def cursor(self):
            return Cur()

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "db_adapter", types.SimpleNamespace(get_connection=lambda: Conn()))
    alerts = adu.check_pipeline_critical()
    sql = seen[0]
    assert "NULLIF(NULLIF(summary->>'errors', '[]'), '')" in sql
    assert "summary->>'cleared_by'" in sql and "summary->>'note'" in sql
    assert "GROUP BY 1, 2" in sql
    msg = next(a["message"] for a in alerts if a["type"] == "pipeline_critical")
    assert "Error: []" not in msg
    assert msg.endswith("Error: zombie run cleared by remediate_pipeline_failures")
