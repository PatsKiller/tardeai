"""health_tick exit semantics, deadline clamp and orphan reaping (2026-10-09, n8n maturity B3.1).

The 5-minute health tick failed ~265 times in two days. Three causes, each pinned here:
  1. A monitor that correctly FOUND something (system_health_agent: a critical
     component down -> exit 1) failed the unit every 5 minutes, so "the scheduler
     is broken" and "a monitor found a problem" read the same. Steps now declare
     `finding_rc`; a finding is reported in the receipt and the tick exits 0.
  2. portfolio_live_monitor.py is a market-hours daemon; inside the tick it ran
     into its 300 s timeout every firing and pushed every hourly tick past the
     unit's TimeoutStartSec, so systemd killed the tick before the receipt was
     written. It now runs `--once`, and step timeouts are clamped to a tick deadline.
  3. pipeline_watchdog.py leaves fire-and-forget children; systemd SIGTERMed them
     after the tick exited and the unit ended Result=timeout. The tick now reaps
     what a step leaves in its process group and records it.

Hermetic: fake steps, tmp locks/state/logs; the live-monitor test stubs the
loader, the data fetch, the alert writer and Telegram, and forbids sleeping.
"""
from __future__ import annotations

import json
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest

from scripts import health_tick as ht
from scripts.lib.monitor_exit_codes import EXIT_FINDING

REPO = Path(__file__).resolve().parents[1]
LIVE_TABLE = REPO / "config" / "health_tick_steps.json"


def _table(tmp_path: Path, steps: list[dict], **extra) -> Path:
    data = {"schema": "HealthTickSteps@v1", "tick_minutes": 5, "tick_budget_s": 280,
            "max_parallel": 1, "default_timeout_s": 240, "steps": steps}
    data.update(extra)
    p = tmp_path / "steps.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _step(step_id: str, command: list[str], tmp_path: Path, **kw) -> dict:
    row = {"step_id": step_id, "command": command, "cadence_minutes": 5, "minute_offset": 0,
           "hours": None, "weekdays": None, "lock": str(tmp_path / f"{step_id}.lock"),
           "timeout_s": 240, "needs_env": False, "market_day_gate": False,
           "log": f"logs/{step_id}.log", "note": "test"}
    row.update(kw)
    return row


def _run(tmp_path: Path, table: Path) -> tuple[int, dict]:
    state = tmp_path / "state"
    rc = ht.main(["--apply", "--table", str(table), "--project-root", str(tmp_path),
                  "--state-root", str(state), "--now", "2026-10-07T09:20:00"])
    receipt_path = state / "data" / "runtime" / "health_tick_last.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    return rc, receipt


def _rows(receipt: dict) -> dict:
    return {r["step_id"]: r for r in receipt["steps"]}


PY = sys.executable
CLEAN_FINDING = [PY, "-c", "import sys; print('critical component down', file=sys.stderr); sys.exit(3)"]
CRASH = [PY, "-c", "import sys; sys.stderr.write('log line\\n'); raise RuntimeError('boom')"]
FRC = [EXIT_FINDING]   # 3, scripts/lib/monitor_exit_codes.py


# ── 1. finding vs broken ────────────────────────────────────────────────────

def test_declared_finding_is_reported_but_keeps_the_tick_green(tmp_path):
    table = _table(tmp_path, [_step("monitor", CLEAN_FINDING, tmp_path, finding_rc=FRC),
                              _step("ok", ["true"], tmp_path)])
    rc, receipt = _run(tmp_path, table)
    assert rc == ht.EXIT_OK
    assert receipt["status"] == "unhealthy" and receipt["tick_ok"] is True
    assert receipt["findings"] == ["monitor"] and receipt["broken"] == []
    # Back-compat: `ok`/`failed` still mean "everything green".
    assert receipt["ok"] is False and receipt["failed"] == ["monitor"]
    assert _rows(receipt)["monitor"]["outcome"] == "finding"
    assert "exit_semantics" in receipt


def test_uncaught_traceback_is_a_crash_even_with_a_finding_rc(tmp_path):
    table = _table(tmp_path, [_step("monitor", CRASH, tmp_path, finding_rc=FRC)])
    rc, receipt = _run(tmp_path, table)
    assert rc == ht.EXIT_TICK_BROKEN
    assert receipt["status"] == "broken" and receipt["broken"] == ["monitor"]
    assert _rows(receipt)["monitor"]["outcome"] == "crashed"


def test_undeclared_nonzero_rc_is_still_broken(tmp_path):
    table = _table(tmp_path, [_step("monitor", CLEAN_FINDING, tmp_path)])   # no finding_rc
    rc, receipt = _run(tmp_path, table)
    assert rc == ht.EXIT_TICK_BROKEN and receipt["broken"] == ["monitor"]


def test_finding_and_breakage_together_exit_broken(tmp_path):
    table = _table(tmp_path, [_step("monitor", CLEAN_FINDING, tmp_path, finding_rc=FRC),
                              _step("bad", ["false"], tmp_path)])
    rc, receipt = _run(tmp_path, table)
    assert rc == ht.EXIT_TICK_BROKEN
    assert receipt["findings"] == ["monitor"] and receipt["broken"] == ["bad"]


def test_all_green_is_healthy(tmp_path):
    rc, receipt = _run(tmp_path, _table(tmp_path, [_step("ok", ["true"], tmp_path)]))
    assert rc == 0 and receipt["status"] == "healthy" and receipt["ok"] is True


@pytest.mark.parametrize("stderr,expected", [
    (b"Traceback (most recent call last):\n  File \"x\", line 1\nValueError: nope\n", True),
    (b"Traceback (most recent call last):\n  File \"x\"\nmod.CustomError: x\n\n", True),
    (b"WARNING handled:\nTraceback (most recent call last):\n  File \"x\"\nKeyError: 'k'\n"
     b"2026-10-09 [agent] carried on after logging it\n", True),
    (b"Traceback (most recent call last):\n  File \"x\"\npsycopg2.OperationalError: connection "
     b"to server failed: Connection refused\n\tIs the server running on that host?\n", True),
    (b"Traceback (most recent call last):\n  File \"x\"\nStopIteration\n", True),
    (b"plain failure line\n", False),
    (b"", False),
])
def test_has_traceback(stderr, expected):
    assert ht.has_traceback(stderr) is expected


@pytest.mark.parametrize("frc", [[0], [1], [1, 3]])
def test_table_rejects_bad_finding_rc(tmp_path, frc):
    """0 is success and 1 is Python's uncaught-exception exit: neither can mean "finding"."""
    bad = _table(tmp_path, [_step("a", ["true"], tmp_path, finding_rc=frc)])
    assert ht.main(["--dry-run", "--table", str(bad)]) == ht.EXIT_CANNOT_RUN


# Each of these crashed a finding_rc step in a way the old last-stderr-line parse
# recorded as `finding` (review of PR #1600, 2026-10-09). With finding_rc [3] they
# are all `crashed`, and the tick is broken.
_OPERATIONAL = ("import sys\nclass OperationalError(Exception): pass\n"
                "raise OperationalError('connection to server at \"127.0.0.1\", port 5432 failed: "
                "Connection refused\\n\\tIs the server running on that host and accepting TCP/IP connections?')")
_READ_TIMEOUT = "class ReadTimeout(OSError): pass\nraise ReadTimeout('read timed out')"
_STOP = "raise StopIteration"
_TB_THEN_MORE = ("import atexit, sys\natexit.register(lambda: sys.stderr.write('[cleanup] closing pool\\n'))\n"
                 "raise KeyError('k')")
_SYS_EXIT_STR = "import sys; sys.exit('fatal: DB_HOST not set')"
_ZERO_WITH_TB = ("import sys, traceback\ntry:\n    1/0\nexcept Exception:\n    traceback.print_exc()\n"
                 "sys.exit(0)")
_FINDING_WITH_TB = ("import sys, traceback\ntry:\n    1/0\nexcept Exception:\n    traceback.print_exc()\n"
                    "sys.exit(3)")


@pytest.mark.parametrize("name,code", [
    ("multiline_operational_error", _OPERATIONAL),
    ("read_timeout", _READ_TIMEOUT),
    ("stop_iteration", _STOP),
    ("traceback_then_more_stderr", _TB_THEN_MORE),
    ("sys_exit_string", _SYS_EXIT_STR),
    ("rc0_with_traceback", _ZERO_WITH_TB),
    ("finding_rc_with_traceback", _FINDING_WITH_TB),
])
def test_crash_shapes_on_a_finding_step_are_crashes(tmp_path, name, code):
    table = _table(tmp_path, [_step("monitor", [PY, "-c", code], tmp_path, finding_rc=FRC)])
    rc, receipt = _run(tmp_path, table)
    row = _rows(receipt)["monitor"]
    assert row["outcome"] == "crashed", (name, row)
    assert rc == ht.EXIT_TICK_BROKEN and receipt["broken"] == ["monitor"], name


def test_rc1_is_a_crash_even_without_any_stderr(tmp_path):
    table = _table(tmp_path, [_step("monitor", [PY, "-c", "import sys; sys.exit(1)"], tmp_path,
                                    finding_rc=FRC)])
    rc, receipt = _run(tmp_path, table)
    assert _rows(receipt)["monitor"]["outcome"] == "crashed" and rc == ht.EXIT_TICK_BROKEN


def test_classify_never_reads_rc1_as_a_finding():
    row = {"ran": True, "rc": 1}
    assert ht.classify(row, [1, 3], crashed=False) == "crashed"
    assert ht.classify({"ran": True, "rc": 3}, [3], crashed=False) == "finding"
    assert ht.classify({"ran": True, "rc": 0}, [3], crashed=True) == "crashed"


# ── 2. deadline clamp ───────────────────────────────────────────────────────

def test_step_timeout_is_clamped_to_the_tick_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(ht, "KILL_GRACE_S", 1.0)
    table = _table(tmp_path, [_step("slow", ["sleep", "30"], tmp_path, timeout_s=240),
                              _step("after", ["true"], tmp_path)],
                   tick_budget_s=1, tick_deadline_s=7)
    rc, receipt = _run(tmp_path, table)
    rows = _rows(receipt)
    assert rows["slow"]["timeout"] is True and rows["slow"]["outcome"] == "timeout"
    assert rows["slow"]["effective_timeout_s"] <= 6.0
    assert "clamped from 240s" in rows["slow"]["error"]
    assert receipt["duration_s"] < 30          # generous: a loaded host slows spawn, not the clamp
    assert rows["after"]["outcome"] == "deferred" and receipt["deferred"] == ["after"]
    assert rc == ht.EXIT_TICK_BROKEN and set(receipt["broken"]) == {"slow", "after"}


# ── 3. orphan reaping ───────────────────────────────────────────────────────

_SPAWN = ("import subprocess, sys; subprocess.Popen(['sleep', '{n}'], stdout=subprocess.DEVNULL, "
          "stderr=subprocess.DEVNULL); sys.exit(0)")


def test_leftover_children_are_terminated_and_recorded(tmp_path):
    table = _table(tmp_path, [_step("spawner", [PY, "-c", _SPAWN.format(n=60)], tmp_path)],
                   orphan_wait_s=0.3)
    rc, receipt = _run(tmp_path, table)
    row = _rows(receipt)["spawner"]
    assert rc == ht.EXIT_OK and row["outcome"] == "ok"
    assert row["orphans"]["killed"] is True and receipt["orphans_terminated"] == ["spawner"]
    assert row["duration_s"] < 30
    assert "left processes in its group" in (tmp_path / "logs" / "spawner.log").read_text()


def test_children_that_finish_within_the_wait_are_not_killed(tmp_path):
    table = _table(tmp_path, [_step("spawner", [PY, "-c", _SPAWN.format(n=0.2)], tmp_path)],
                   orphan_wait_s=20)
    rc, receipt = _run(tmp_path, table)
    row = _rows(receipt)["spawner"]
    assert rc == ht.EXIT_OK
    assert row["orphans"] is None or row["orphans"]["killed"] is False
    assert receipt["orphans_terminated"] == []


# ── live table ──────────────────────────────────────────────────────────────

def test_live_table_declares_findings_deadline_and_once():
    table = ht.load_table(LIVE_TABLE)
    steps = {s["step_id"]: s for s in table["steps"]}
    for sid in ("system-health-agent", "moomoo-opend-health", "pipeline-liveness-report"):
        assert steps[sid]["finding_rc"] == [EXIT_FINDING], sid
    assert table["tick_budget_s"] <= table["tick_deadline_s"] < 330   # unit TimeoutStartSec
    plm = steps["portfolio-live-monitor"]
    assert "--once" in plm["command"] and plm["timeout_s"] < table["tick_budget_s"]


# ── portfolio_live_monitor --once ───────────────────────────────────────────

@pytest.fixture
def plm(monkeypatch, tmp_path):
    from scripts import portfolio_live_monitor as mod

    sent: list[str] = []

    def _no_sleep(*_a, **_k):
        raise AssertionError("--once must never sleep")

    monkeypatch.setattr(mod.time, "sleep", _no_sleep)
    monkeypatch.setattr(mod, "_send_telegram", lambda msg, root: sent.append(msg) or None)
    monkeypatch.setattr(mod, "_fetch_holdings_data", lambda symbols, root: {})
    monkeypatch.setattr(mod, "_morning_brief", lambda p, m, r: "BRIEF")
    monkeypatch.setattr(mod, "_eod_summary", lambda p, m, a, r: "EOD:" + "|".join(a))
    fired = {"n": 0}

    def _triggers(portfolio, market_data, state):
        fired["n"] += 1
        return [{"msg": "XYZ down", "ticker": "XYZ", "trigger": "DOWN_3PCT"}] if fired["n"] == 1 else []

    monkeypatch.setattr(mod, "check_triggers", _triggers)
    loader = types.ModuleType("portfolio_loader")
    loader.load_all_portfolios = lambda root: {"holdings": [{"symbol": "XYZ", "market_value": 1000}]}
    writer = types.ModuleType("alert_event_writer")
    writer.save_alert_event = lambda **kw: None
    writer.attach_telegram_message_id = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "portfolio_loader", loader)
    monkeypatch.setitem(sys.modules, "alert_event_writer", writer)
    state = tmp_path / "state"
    state.mkdir()
    return mod, sent, state, tmp_path


def test_once_runs_one_cycle_and_dedups_brief_and_eod_across_processes(plm):
    mod, sent, state, root = plm
    assert mod.run_once(root, state, now=datetime(2026, 10, 9, 9, 5)) == "cycled"
    assert sent == ["BRIEF", "XYZ down"]
    assert mod.run_once(root, state, now=datetime(2026, 10, 9, 9, 10)) == "cycled"
    assert sent == ["BRIEF", "XYZ down"]                       # brief not repeated
    assert mod.run_once(root, state, now=datetime(2026, 10, 9, 16, 20)) == "cycled"
    assert mod.run_once(root, state, now=datetime(2026, 10, 9, 16, 25)) == "cycled"
    eods = [m for m in sent if m.startswith("EOD:")]
    assert len(eods) == 1 and "XYZ DOWN_3PCT" in eods[0]     # alerts carried across runs


@pytest.mark.parametrize("now,expected", [
    (datetime(2026, 10, 9, 16, 40), "after_close"),
    (datetime(2026, 10, 10, 10, 0), "weekend"),
    (datetime(2026, 10, 9, 7, 0), "pre_market"),
])
def test_once_outside_the_window_does_nothing(plm, now, expected):
    mod, sent, state, root = plm
    assert mod.run_once(root, state, now=now) == expected and sent == []
