"""health_tick: cron-equivalent due computation, lock skip, timeout, receipt, dry-run.

Hermetic: a fake step table with `true` / `sleep` / `false` commands, a tmp
project root, tmp lock paths and a tmp state root. Nothing here touches /tmp
locks the live crontab uses, the live receipt, or any monitor script.
"""
from __future__ import annotations

import fcntl
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

from scripts import health_tick as ht

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


def _run(argv: list[str], tmp_path: Path, table: Path) -> tuple[int, dict]:
    state = tmp_path / "state"
    rc = ht.main(argv + ["--table", str(table), "--project-root", str(tmp_path),
                         "--state-root", str(state), "--now", "2026-10-07T09:20:00"])
    receipt_path = state / "data" / "runtime" / "health_tick_last.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    return rc, receipt


# ── due computation ─────────────────────────────────────────────────────────

def _due(step: dict, when: str, tick_minutes: int = 5) -> bool:
    return ht.step_is_due(step, ht.snap_to_tick(datetime.fromisoformat(when), tick_minutes), tick_minutes)


def test_sub_hour_cadences_follow_cron_star_slash():
    s = {"cadence_minutes": 20, "minute_offset": 0, "hours": None, "weekdays": None}
    assert [m for m in range(0, 60, 5) if _due(s, f"2026-10-07T10:{m:02d}:00")] == [0, 20, 40]
    s15 = {"cadence_minutes": 15, "minute_offset": 0, "hours": None, "weekdays": None}
    assert [m for m in range(0, 60, 5) if _due(s15, f"2026-10-07T10:{m:02d}:00")] == [0, 15, 30, 45]
    s30 = {"cadence_minutes": 30, "minute_offset": 0, "hours": None, "weekdays": None}
    assert [m for m in range(0, 60, 5) if _due(s30, f"2026-10-07T10:{m:02d}:00")] == [0, 30]


def test_hourly_phase_and_off_grid_snap():
    s20 = {"cadence_minutes": 60, "minute_offset": 20, "hours": None, "weekdays": None}
    assert [m for m in range(0, 60, 5) if _due(s20, f"2026-10-07T03:{m:02d}:00")] == [20]
    s27 = {"cadence_minutes": 60, "minute_offset": 27, "hours": None, "weekdays": None}
    assert [m for m in range(0, 60, 5) if _due(s27, f"2026-10-07T03:{m:02d}:00")] == [25]


def test_multi_hour_cadences_match_cron_star_slash_hours():
    every2 = {"cadence_minutes": 120, "minute_offset": 0, "hours": None, "weekdays": None}
    assert [h for h in range(24) if _due(every2, f"2026-10-07T{h:02d}:00:00")] == list(range(0, 24, 2))
    assert not _due(every2, "2026-10-07T02:05:00")
    every4_20 = {"cadence_minutes": 240, "minute_offset": 20, "hours": None, "weekdays": None}
    assert [h for h in range(24) if _due(every4_20, f"2026-10-07T{h:02d}:20:00")] == [0, 4, 8, 12, 16, 20]
    assert not _due(every4_20, "2026-10-07T04:00:00")


def test_hour_and_weekday_windows():
    slo = {"cadence_minutes": 120, "minute_offset": 15, "hours": [7, 9, 11, 13, 15, 17], "weekdays": [1, 2, 3, 4, 5]}
    assert [h for h in range(24) if _due(slo, f"2026-10-07T{h:02d}:15:00")] == [7, 9, 11, 13, 15, 17]  # Wed
    assert not _due(slo, "2026-10-10T09:15:00")   # Saturday
    assert not _due(slo, "2026-10-11T09:15:00")   # Sunday
    mkt = {"cadence_minutes": 5, "minute_offset": 0, "hours": list(range(9, 21)), "weekdays": [1, 2, 3, 4, 5]}
    assert _due(mkt, "2026-10-07T09:00:00") and _due(mkt, "2026-10-07T20:55:00")
    assert not _due(mkt, "2026-10-07T08:55:00") and not _due(mkt, "2026-10-07T21:00:00")
    assert not _due(mkt, "2026-10-10T12:00:00")
    twice = {"cadence_minutes": 60, "minute_offset": 10, "hours": [12, 15], "weekdays": [1, 2, 3, 4, 5]}
    assert [h for h in range(24) if _due(twice, f"2026-10-07T{h:02d}:10:00")] == [12, 15]
    assert not _due(twice, "2026-10-07T12:15:00")


def test_snap_floors_a_late_timer_fire_onto_the_grid():
    late = datetime.fromisoformat("2026-10-07T09:21:40")
    assert ht.snap_to_tick(late, 5).isoformat() == "2026-10-07T09:20:00"


def test_live_table_loads_and_reproduces_the_crontab_weekly_count():
    table = ht.load_table(LIVE_TABLE)
    assert len(table["steps"]) == 17
    counts = ht.firings_per_week(table, datetime.fromisoformat("2026-10-05T00:00:00"))
    # Hand-computed from the 17 crontab lines (weekday 1166 + weekend 786 per day).
    assert sum(counts.values()) == 7402
    assert counts["cio-bridge-watchdog"] == 2016 and counts["system-health-alerts"] == 10
    assert counts["symbol-news-curation-monitor"] == 168 and counts["pipeline-freshness-slo"] == 30
    gated = [s for s in table["steps"] if s["market_day_gate"]]
    assert [s["step_id"] for s in gated] == ["system-health-alerts"]
    assert ht.render_command(gated[0], py="PYX", project_root=Path("/p"))[:2] == ["bash", "scripts/market_day_gate.sh"]
    assert all(s["needs_env"] is False for s in table["steps"])
    assert all(s["lock"].startswith("/tmp/") for s in table["steps"])


def test_table_validation_rejects_bad_rows(tmp_path):
    bad = _table(tmp_path, [_step("a", ["true"], tmp_path, cadence_minutes=0)])
    with pytest.raises(ValueError):
        ht.load_table(bad)
    dup = _table(tmp_path, [_step("a", ["true"], tmp_path), _step("a", ["true"], tmp_path)])
    with pytest.raises(ValueError):
        ht.load_table(dup)
    (tmp_path / "wrong.json").write_text(json.dumps({"schema": "Other@v1", "steps": [{}]}))
    with pytest.raises(ValueError):
        ht.load_table(tmp_path / "wrong.json")
    assert ht.main(["--dry-run", "--table", str(tmp_path / "wrong.json")]) == ht.EXIT_CANNOT_RUN


# ── execution ───────────────────────────────────────────────────────────────

def test_apply_runs_due_steps_writes_receipt_and_logs(tmp_path):
    table = _table(tmp_path, [
        _step("ok", ["true"], tmp_path),
        _step("echoer", [sys.executable, "-c", "import sys; print('hello'); print('warn line', file=sys.stderr)"], tmp_path),
        _step("not-due", ["false"], tmp_path, cadence_minutes=60, minute_offset=45),
    ])
    rc, receipt = _run(["--apply"], tmp_path, table)
    assert rc == 0
    assert receipt["schema"] == "HealthTickReceipt@v1"
    assert receipt["ok"] is True and receipt["sends"] is False
    assert receipt["tick"].startswith("2026-10-07T09:20")
    assert {"as_of", "served_sha", "tick", "steps", "ok"} <= set(receipt)
    rows = {r["step_id"]: r for r in receipt["steps"]}
    assert set(rows) == {"ok", "echoer", "not-due"}
    assert rows["ok"]["due"] and rows["ok"]["ran"] and rows["ok"]["rc"] == 0
    assert rows["echoer"]["stderr_first_line"] == "warn line"
    assert rows["not-due"] == {**rows["not-due"], "due": False, "ran": False, "rc": None}
    for key in ("step_id", "due", "ran", "rc", "duration_s", "lock_skipped", "timeout"):
        assert key in rows["ok"]
    log = (tmp_path / "logs" / "echoer.log").read_text()
    assert "hello" in log and "warn line" in log
    history = (tmp_path / "state" / "data" / "runtime" / "health_tick_history.jsonl").read_text().splitlines()
    assert len(history) == 1 and json.loads(history[0])["ok"] is True


def test_failed_step_sets_nonzero_exit(tmp_path):
    table = _table(tmp_path, [_step("ok", ["true"], tmp_path), _step("bad", ["false"], tmp_path)])
    rc, receipt = _run(["--apply"], tmp_path, table)
    assert rc == ht.EXIT_STEP_FAILED
    assert receipt["ok"] is False and receipt["failed"] == ["bad"]
    rows = {r["step_id"]: r for r in receipt["steps"]}
    assert rows["bad"]["rc"] == 1 and rows["ok"]["rc"] == 0


def test_timeout_is_a_failure_and_does_not_hang(tmp_path):
    table = _table(tmp_path, [_step("slow", ["sleep", "30"], tmp_path, timeout_s=1), _step("after", ["true"], tmp_path)])
    rc, receipt = _run(["--apply"], tmp_path, table)
    assert rc == ht.EXIT_STEP_FAILED
    rows = {r["step_id"]: r for r in receipt["steps"]}
    assert rows["slow"]["timeout"] is True and rows["slow"]["ran"] is True
    assert rows["slow"]["rc"] != 0
    assert rows["slow"]["duration_s"] < 15
    assert receipt["timed_out"] == ["slow"] and receipt["failed"] == ["slow"]
    assert rows["after"]["rc"] == 0          # the wedge did not stop the next step
    assert "timeout after 1s" in (tmp_path / "logs" / "slow.log").read_text()


def test_lock_held_elsewhere_skips_the_step_without_failing(tmp_path):
    lock = tmp_path / "held.lock"
    fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        table = _table(tmp_path, [_step("held", ["false"], tmp_path, lock=str(lock))])
        rc, receipt = _run(["--apply"], tmp_path, table)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    assert rc == 0
    rows = {r["step_id"]: r for r in receipt["steps"]}
    assert rows["held"]["lock_skipped"] is True and rows["held"]["ran"] is False
    assert receipt["lock_skipped"] == ["held"] and receipt["ok"] is True
    # The lock is released after a run, so a second tick runs it.
    table2 = _table(tmp_path, [_step("held", ["true"], tmp_path, lock=str(lock))])
    rc2, receipt2 = _run(["--apply"], tmp_path, table2)
    assert rc2 == 0 and {r["step_id"]: r for r in receipt2["steps"]}["held"]["ran"] is True


def test_tick_budget_defers_remaining_steps_and_reports_it(tmp_path):
    table = _table(tmp_path, [_step("first", ["sleep", "1"], tmp_path), _step("second", ["true"], tmp_path)],
                   tick_budget_s=0.5)
    rc, receipt = _run(["--apply"], tmp_path, table)
    assert rc == ht.EXIT_STEP_FAILED
    assert receipt["deferred"] == ["second"] and "second" in receipt["failed"]
    rows = {r["step_id"]: r for r in receipt["steps"]}
    assert rows["first"]["rc"] == 0 and rows["second"]["ran"] is False


def test_dry_run_writes_nothing_and_once_runs_one_step(tmp_path, capsys):
    table = _table(tmp_path, [_step("a", ["true"], tmp_path), _step("b", ["false"], tmp_path, cadence_minutes=60, minute_offset=45)])
    rc, receipt = _run(["--dry-run"], tmp_path, table)
    assert rc == 0 and receipt == {}
    assert not (tmp_path / "state").exists() and not (tmp_path / "logs").exists()
    out = capsys.readouterr().out
    assert "mode=dry-run" in out and "PLANNED" in out and "  a " in out and "  b " not in out

    rc, receipt = _run(["--once", "--step", "b"], tmp_path, table)      # not due at 09:20, forced
    assert rc == ht.EXIT_STEP_FAILED and receipt["mode"] == "once"
    rows = {r["step_id"]: r for r in receipt["steps"]}
    assert rows["b"]["ran"] is True and rows["b"]["rc"] == 1 and rows["a"]["ran"] is False
    assert ht.main(["--once", "--table", str(table)]) == ht.EXIT_CANNOT_RUN
    assert ht.main(["--once", "--step", "nope", "--table", str(table), "--project-root", str(tmp_path),
                    "--state-root", str(tmp_path / "s")]) == ht.EXIT_CANNOT_RUN


def test_market_day_gate_wrapper_and_env_rendering(tmp_path):
    gate = tmp_path / "scripts" / "market_day_gate.sh"
    gate.parent.mkdir(parents=True)
    gate.write_text("#!/usr/bin/env bash\necho gated:$*\nexec \"$@\"\n")
    (tmp_path / ".env").write_text("HT_TEST_VAR=from_env\n")
    probe = [sys.executable, "-c", "import os,sys; print(os.environ.get('HT_TEST_VAR','unset')); sys.exit(0)"]
    table = _table(tmp_path, [
        _step("gated", ["$PY", "-c", "print('ran-under-gate')"], tmp_path, market_day_gate=True),
        _step("env-on", probe, tmp_path, needs_env=True),
        _step("env-off", probe, tmp_path, needs_env=False),
    ])
    rc, receipt = _run(["--apply", "--py", sys.executable], tmp_path, table)
    assert rc == 0
    rows = {r["step_id"]: r for r in receipt["steps"]}
    assert rows["gated"]["command"][:3] == ["bash", "scripts/market_day_gate.sh", sys.executable]
    gated_log = (tmp_path / "logs" / "gated.log").read_text()
    assert "gated:" in gated_log and "ran-under-gate" in gated_log
    assert "from_env" in (tmp_path / "logs" / "env-on.log").read_text()
    assert "unset" in (tmp_path / "logs" / "env-off.log").read_text()


def test_stderr_line_is_redacted(tmp_path):
    leak = [sys.executable, "-c", "import sys; print('db postgres://u:p@h/db token=abc', file=sys.stderr); sys.exit(3)"]
    table = _table(tmp_path, [_step("leaky", leak, tmp_path)])
    rc, receipt = _run(["--apply"], tmp_path, table)
    row = receipt["steps"][0]
    assert rc == ht.EXIT_STEP_FAILED and row["rc"] == 3
    assert "postgres://" not in row["stderr_first_line"] and "abc" not in row["stderr_first_line"]
    assert "[redacted]" in row["stderr_first_line"]
