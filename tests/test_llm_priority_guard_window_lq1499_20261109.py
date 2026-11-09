"""ANCHOR: LLM_PRIORITY_GUARD_WINDOW_LQ1499_20261109 — guard-deferred slots are expected.

A cron line wrapped by scripts/llm_priority_guard.sh does not run while that script
defers. The missed-run watchdog and the jobs pages must treat those fires as not
due. The hours come from the script (and a crontab assignment of its variables),
not from a second copy of the clock. Fixture hours below are the fixture's own
defaults. Synthetic lane ids only. No DB, broker, credential, or live crontab.
"""
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.cron_outage_watchdog import bind_components, read_crontab_snapshot
from scripts.lib.cron_outage_watchdog import evaluate
from scripts.lib.jobs_health import _schedule
from scripts.lib.jobs_health import build as health_build
from scripts.lib.jobs_history import lane_history
from scripts.lib.llm_priority_guard import (
    AUTO,
    guard_defers,
    lane_behind_llm_priority_guard,
    load_guard_window,
    parse_guard_window,
)

ET = ZoneInfo("America/New_York")
MATCH = "scripts/synthetic_guarded_lane.py"
DIRECTIVE = "scripts/synthetic_directive.py"
FIXTURE = """
START="${LLM_GUARD_START_HOUR:-9}"
END="${LLM_GUARD_END_HOUR:-11}"
if [ "$DOW" -le 5 ] && [ "$((10#$H))" -ge "$START" ] && [ "$((10#$H))" -lt "$END" ]; then
  exit 1
fi
"""


def et(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=ET)


def fixture_window(**kwargs):
    return parse_guard_window(FIXTURE, **kwargs)


def guarded_lane(**extra):
    lane = {
        "lane_id": "synthetic-guarded-lane",
        "state": "ACTIVE",
        "expected_cadence_hours": 0.25,
        "scheduler": {
            "kind": "cron",
            "expression": "*/15 * * * *",
            "timezone": "America/New_York",
            "match": MATCH,
        },
        "watchdog_llm_priority_guard": True,
        "output_signal": {"kind": "log_line", "path": "logs/synthetic_guarded_lane.log"},
    }
    lane.update(extra)
    return lane


def grade(now, success, *, window, flag=True, trading_day=None, expression=None):
    lane = guarded_lane()
    if not flag:
        lane.pop("watchdog_llm_priority_guard", None)
    if expression:
        lane["scheduler"] = {**lane["scheduler"], "expression": expression}
    successes = {}
    if success is not None:
        successes[lane["lane_id"]] = [{"at": success.isoformat(), "validated_success": True}]
    result = evaluate(
        {"lanes": [lane]}, [], successes, now=now,
        trading_day=trading_day or (lambda at: True), guard_window=window,
    )
    return next(row for row in result["rows"] if row["lane_id"] == lane["lane_id"])


def history(now, evidence, window):
    return lane_history(
        guarded_lane(), now=now, trading_day=lambda at: True, ledger=[], journal=[],
        ledger_since=None, journal_since=None, last_live_success=None, receipt=None,
        output_at=evidence, fixes=[], guard_window=window,
    )


def health_row(now, success, window, *, flag=True):
    lane = guarded_lane()
    if not flag:
        lane.pop("watchdog_llm_priority_guard", None)
    snapshot = {"events": [], "successes": {
        lane["lane_id"]: [{"at": success.isoformat(), "validated_success": True}],
    }}
    report = health_build(
        {"lanes": [lane]}, snapshot, [], {}, now=now, trading_day=lambda at: True, guard_window=window,
    )
    return next(row for row in report["rows"] if row["lane_id"] == lane["lane_id"])


def test_fixture_hours_come_from_the_script_text():
    window = fixture_window()
    assert window is not None
    assert window.start_hour == 9 and window.end_hour == 11 and window.max_isoweekday == 5
    assert guard_defers(et(2026, 11, 9, 9, 30), window)
    assert not guard_defers(et(2026, 11, 9, 6, 20), window)
    assert not guard_defers(et(2026, 11, 9, 11, 0), window)
    assert not guard_defers(et(2026, 11, 7, 9, 30), window)
    assert not guard_defers(datetime(2026, 11, 9, 9, 30), window)


def test_env_and_crontab_override_the_script_default():
    env = {"LLM_GUARD_START_HOUR": "4", "LLM_GUARD_END_HOUR": "5"}
    window = fixture_window(env=env)
    assert guard_defers(et(2026, 11, 9, 4, 15), window)
    assert not guard_defers(et(2026, 11, 9, 9, 15), window)
    header = "LLM_GUARD_START_HOUR=4\nLLM_GUARD_END_HOUR=5\n# LLM_GUARD_START_HOUR=1\n"
    from_cron = fixture_window(crontab_text=header)
    assert guard_defers(et(2026, 11, 9, 4, 15), from_cron)
    assert not guard_defers(et(2026, 11, 9, 9, 15), from_cron)
    # A local shell name is not the crontab variable the script reads.
    untouched = fixture_window(crontab_text="START=4\nEND=5\n")
    assert untouched.start_hour == 9 and untouched.end_hour == 11
    later = "LLM_GUARD_START_HOUR=4\nLLM_GUARD_START_HOUR=7\nLLM_GUARD_END_HOUR=8\n"
    assert fixture_window(crontab_text=later).start_hour == 7
    beaten = fixture_window(crontab_text=header, env={"LLM_GUARD_START_HOUR": "8", "LLM_GUARD_END_HOUR": "10"})
    assert guard_defers(et(2026, 11, 9, 8, 30), beaten)
    assert not guard_defers(et(2026, 11, 9, 4, 30), beaten)


def test_garbage_does_not_invent_a_window():
    assert parse_guard_window("echo hi") is None
    assert fixture_window(env={"LLM_GUARD_START_HOUR": "nope"}) is None
    assert load_guard_window(path=Path("/no/such/llm_priority_guard.sh")) is None


def test_the_shipped_guard_is_the_source_of_the_hours():
    text = (Path(__file__).resolve().parents[1] / "scripts/llm_priority_guard.sh").read_text(encoding="utf-8")
    window = load_guard_window()
    assert window is not None
    assert f":-{window.start_hour}}}" in text
    assert f":-{window.end_hour}}}" in text
    assert f"-le {window.max_isoweekday}" in text
    assert window.start_env == "LLM_GUARD_START_HOUR"
    assert window.end_env == "LLM_GUARD_END_HOUR"
    assert window.start_hour < window.end_hour


def test_a_crontab_assignment_on_the_shipped_script_replaces_its_default():
    shipped = load_guard_window()
    header = f"{shipped.start_env}=4\n{shipped.end_env}=5\n"
    over = load_guard_window(crontab_text=header)
    assert over.start_hour == 4 and over.end_hour == 5
    assert grade(et(2026, 11, 9, 4, 20), et(2026, 11, 9, 3, 45), window=over)["status"] == "OK"
    later = et(2026, 11, 9, over.start_hour + 5, 20)
    assert grade(later, et(2026, 11, 9, 3, 45), window=over)["status"] == "MISSED_RUNS"
    env = {shipped.start_env: "8", shipped.end_env: "10"}
    beaten = load_guard_window(crontab_text=header, env=env)
    assert guard_defers(et(2026, 11, 9, 8, 30), beaten)
    assert not guard_defers(et(2026, 11, 9, 4, 30), beaten)
    assert load_guard_window(env={shipped.start_env: "nope"}) is None
    assert load_guard_window(crontab_text=f"{shipped.end_env}=1\n") is None


def test_inside_the_derived_window_is_not_a_miss_and_outside_still_is():
    window = fixture_window()
    inside = grade(et(2026, 11, 9, 9, 20), et(2026, 11, 9, 8, 45), window=window)
    assert inside["status"] == "OK" and inside["missed_fires"] == 0
    unguarded = grade(et(2026, 11, 9, 9, 20), et(2026, 11, 9, 8, 45), window=window, flag=False)
    assert unguarded["status"] == "MISSED_RUNS"
    before = grade(et(2026, 11, 9, 8, 20), et(2026, 11, 9, 7, 0), window=window)
    assert before["status"] == "MISSED_RUNS"
    ended = grade(et(2026, 11, 9, 11, 20), et(2026, 11, 9, 8, 45), window=window)
    assert ended["status"] == "MISSED_RUNS"
    closed = grade(et(2026, 11, 9, 9, 20), et(2026, 11, 9, 8, 45), window=None)
    assert closed["status"] == "MISSED_RUNS"
    # AUTO on a flagged lane reads the shipped script. Explicit None does not reload it.
    shipped = load_guard_window()
    monday = datetime(2026, 11, 9, tzinfo=ET)
    now = monday.replace(hour=shipped.start_hour, minute=20)
    success = monday.replace(hour=shipped.start_hour, minute=0) - timedelta(minutes=15)
    assert grade(now, success, window=AUTO)["status"] == "OK"
    assert grade(now, success, window=None)["status"] == "MISSED_RUNS"
    after = monday.replace(hour=shipped.end_hour, minute=20)
    assert grade(after, success, window=shipped)["status"] == "MISSED_RUNS"
    one = grade(monday.replace(hour=shipped.end_hour, minute=5), success, window=shipped)
    assert one["status"] == "OK" and one["missed_fires"] == 1


def test_weekend_and_a_closed_market_still_follow_the_shell():
    shipped = load_guard_window()
    saturday = datetime(2026, 11, 7, shipped.start_hour, 20, tzinfo=ET)
    friday = datetime(2026, 11, 6, shipped.start_hour, 0, tzinfo=ET)
    assert grade(saturday, friday, window=shipped)["status"] == "MISSED_RUNS"
    window = fixture_window()
    row = grade(
        et(2026, 11, 9, 9, 20), et(2026, 11, 9, 8, 45), window=window, trading_day=lambda at: False,
    )
    assert row["status"] != "MISSED_RUNS"
    buried = grade(et(2026, 11, 9, 9, 20), et(2026, 11, 6, 9, 0), window=window, expression="0 9 * * 1-5")
    assert buried["status"] == "OUTSIDE_WINDOW"


def test_jobs_history_does_not_call_a_deferred_slot_late():
    window = fixture_window()
    inside = history(et(2026, 11, 9, 9, 20), et(2026, 11, 9, 8, 45), window)
    assert inside["status"] != "late"
    assert inside["status"] == "ok_unverified"
    assert "llm_priority_guard" not in inside["cadence"]
    late = history(et(2026, 11, 9, 11, 20), et(2026, 11, 9, 8, 45), window)
    assert late["status"] == "late"


def test_jobs_health_due_slot_is_the_last_fire_the_guard_allowed():
    window = fixture_window()
    now = et(2026, 11, 9, 9, 20)
    due, nxt, issue, _gated, due_today = _schedule(guarded_lane(), now, lambda at: True, window)
    assert issue is None and due_today
    assert due[-1].astimezone(ET) == et(2026, 11, 9, 8, 45)
    assert all(not guard_defers(at, window) for at in due)
    assert nxt.astimezone(ET) == et(2026, 11, 9, 11, 0)
    row = health_row(now, et(2026, 11, 9, 8, 45), window)
    assert row["result"] == "succeeded"
    missed = health_row(et(2026, 11, 9, 11, 20), et(2026, 11, 9, 8, 45), window)
    assert missed["result"] == "missed"
    still = health_row(now, et(2026, 11, 9, 8, 45), window, flag=False)
    assert still["result"] == "missed"


def test_bind_stamps_only_when_every_live_line_is_wrapped():
    wrapped = f"*/15 * * * * bash scripts/llm_priority_guard.sh && python {MATCH}"
    bare = f"*/15 * * * * python {MATCH}"
    commented = f"# {wrapped}"
    lane = {"lane_id": "synthetic-guarded-lane", "scheduler": {"match": MATCH}}
    before = dict(lane["scheduler"])

    def stamped(text, command=""):
        row = {"lane_id": "synthetic-guarded-lane", "scheduler": {"match": MATCH, "command_text": command}}
        bound = bind_components({"lanes": [row]}, {}, crontab_text=text)
        return bound["lanes"][0].get("watchdog_llm_priority_guard") is True

    assert stamped(wrapped)
    assert not stamped(bare)
    assert not stamped(commented)
    assert not stamped("")
    assert not stamped(f"{wrapped}\n{bare}")
    assert stamped("", f"bash scripts/llm_priority_guard.sh && python {MATCH}")
    assert not stamped("", f"python {MATCH}")
    directive = f"*/30 * * * * bash scripts/llm_priority_guard.sh && python {DIRECTIVE}"
    assert lane_behind_llm_priority_guard(DIRECTIVE, f"{directive}\n*/30 * * * * python {DIRECTIVE}") is False
    assert lane_behind_llm_priority_guard("ab.py", wrapped) is False
    assert lane_behind_llm_priority_guard("coordinator_only", wrapped) is False
    bind_components({"lanes": [lane]}, {}, crontab_text=wrapped)
    assert lane["scheduler"] == before
    assert "watchdog_llm_priority_guard" not in lane


def test_missing_crontab_snapshot_is_empty(tmp_path):
    assert read_crontab_snapshot(tmp_path) == ""
    path = tmp_path / "data/runtime"
    path.mkdir(parents=True)
    (path / "crontab_snapshot.txt").write_text("LLM_GUARD_START_HOUR=4\n", encoding="utf-8")
    assert "LLM_GUARD_START_HOUR=4" in read_crontab_snapshot(tmp_path)
