"""LQ-20261107-2148 — the Scheduler late-count lane, per lane (Home v010 Schedulers row).

Registration is not execution (Engineering Constitution v1.5): an n8n lane whose expected slot has no ledger run is
MISSED, never OK; a cron/systemd lane has no per-run ledger, so its late count is NOT_MEASURED (None), never 0; an
unreadable ledger is UNKNOWN, never "no runs".

Every fixture is synthetic (lane ids ``syn-*``, a temp SQLite ledger); nothing reads production.

Fail-before (base f404e0ccd): ``scripts/lib/lane_health.py`` and ``scripts/lane_health_snapshot.py`` do not exist,
so every test below errors at import. The behavioural gap it closes is pinned by
``test_fail_before_jobs_history_reports_no_missed_count_for_a_never_dispatched_lane``: the existing reader
(``jobs_history.lane_history``) gives a registered n8n lane with zero ledger rows ``missed_count`` None — the
Schedulers row had nothing to count — while this lane reports LATE / never_dispatched with every slot missed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib import lane_health as LH  # noqa: E402

UTC = timezone.utc
# 2026-03-04 is a Wednesday in EST (UTC-5). A 2-hourly ET lane has 12 slots in the 24 h before NOW.
NOW = datetime(2026, 3, 4, 12, 59, tzinfo=UTC)
ALWAYS = lambda _d: True  # noqa: E731 -- every day is a trading day for these fixtures
FRAGMENT = ROOT / "config/registration/lane-health-snapshot.json"


def n8n_lane(lane_id="syn-n8n-2h", cron="0 */2 * * *", mode="live", **extra) -> dict:
    return {"lane_id": lane_id, "owner": "platform", "state": "ACTIVE", "value_class": "Operationally Important",
            "scheduler": {"kind": "n8n", "expression": "dispatcher", "match": f"scripts/{lane_id}.py --apply",
                          "cadence": cron, "stage": "canary", "timezone": "America/New_York"},
            "dispatch": {"mode": mode, "cron": [cron], "tz": "America/New_York", "class": "monitor"},
            "expected_cadence_hours": 2.0, "output_signal": {"kind": "none"}, **extra}


def cron_lane(lane_id="syn-cron-hourly") -> dict:
    return {"lane_id": lane_id, "owner": "platform", "state": "ACTIVE",
            "scheduler": {"kind": "cron", "expression": "0 * * * *", "timezone": "America/New_York"},
            "expected_cadence_hours": 1.0, "output_signal": {"kind": "none"}}


def slots_utc(cron_hours=2, n=12, now=NOW):
    """The n newest 2-hourly ET slots before ``now`` (EST: ET even hours = odd UTC hours)."""
    last = datetime(2026, 3, 4, 11, 0, tzinfo=UTC)
    return [last - timedelta(hours=cron_hours * i) for i in reversed(range(n))]


def run(lane_id, at: datetime, *, late_min=0.0, state="RUN_DONE", mode="live", queued_min=None) -> dict:
    started = at + timedelta(minutes=late_min)
    requested = at + timedelta(seconds=10) if queued_min is None else at + timedelta(seconds=10)
    return {"run_id": f"d:{lane_id}:{mode}:{at.isoformat()}", "lane_id": lane_id, "mode": mode, "state": state,
            "requested_at": requested.isoformat(), "started_at": started.isoformat(),
            "finished_at": (started + timedelta(seconds=30)).isoformat(), "exit_code": 0}


def ledger(runs, *, readable=True, covered_from=NOW - timedelta(days=9), gap=None) -> dict:
    return {"readable": readable, "runs": runs, "covered_from": covered_from if readable else None,
            "newest": None, "gap": gap}


def snap(lanes, led, now=NOW, policy=None):
    return LH.build({"lanes": lanes}, ledger=led, now=now, trading_day=ALWAYS, signals={}, policy=policy)


def row(s, lane_id):
    return next(r for r in s["lanes"] if r["lane_id"] == lane_id)


# ── spec tests (HOME-BACKEND-SPEC section LQ-2148) ────────────────────────────────────────────────────────────────

def test_twelve_expected_ten_done_is_two_missed():
    lane = n8n_lane()
    slots = slots_utc()
    runs = [run("syn-n8n-2h", t) for i, t in enumerate(slots) if i not in (3, 7)]
    r = row(snap([lane], ledger(runs)), "syn-n8n-2h")
    assert r["expected_slots_24h"] == 12
    assert r["done_slots_24h"] == 10
    assert r["missed_count_24h"] == 2
    assert r["late_count_24h"] == 0
    assert r["state"] == "LATE" and r["cause_code"] == "missed_slot"
    assert r["missed_slots"] == [slots[3].isoformat(), slots[7].isoformat()]


def test_twenty_minutes_late_with_ten_minute_grace_is_one_late():
    lane = n8n_lane()
    slots = slots_utc()
    runs = [run("syn-n8n-2h", t, late_min=20 if i == 5 else 1) for i, t in enumerate(slots)]
    r = row(snap([lane], ledger(runs), policy={"late_grace_minutes": 10}), "syn-n8n-2h")
    assert (r["expected_slots_24h"], r["done_slots_24h"], r["missed_count_24h"]) == (12, 12, 0)
    assert r["late_count_24h"] == 1
    assert r["late_slots"][0]["slot_at"] == slots[5].isoformat() and r["late_slots"][0]["late_s"] == 1200.0
    assert r["state"] == "LATE" and r["cause_code"] == "late_start"


def test_all_on_time_is_ok():
    lane = n8n_lane()
    runs = [run("syn-n8n-2h", t, late_min=1) for t in slots_utc()]
    s = snap([lane], ledger(runs))
    r = row(s, "syn-n8n-2h")
    assert (r["expected_slots_24h"], r["done_slots_24h"], r["late_count_24h"], r["missed_count_24h"]) == (12, 12, 0, 0)
    assert r["state"] == "OK"
    assert s["schedulers"]["status"] == "OK"


def test_cron_lane_is_not_measured_never_zero():
    s = snap([cron_lane()], ledger([]))
    r = row(s, "syn-cron-hourly")
    assert r["state"] == "NOT_MEASURED" and r["cause_code"] == "no_run_ledger"
    for key in ("expected_slots_24h", "done_slots_24h", "late_count_24h", "missed_count_24h", "failed_count_24h"):
        assert r[key] is None, key  # unknown is not 0
    assert r["source_of_record"].startswith("output signal only")
    # a scheduler made only of unmeasured lanes is UNKNOWN, not OK
    assert s["schedulers"]["status"] == "UNKNOWN"


def test_unreadable_ledger_is_unknown_for_n8n_lanes_and_the_rollup():
    s = snap([n8n_lane(), cron_lane()], ledger([], readable=False, gap="the ledger file is absent"))
    r = row(s, "syn-n8n-2h")
    assert r["state"] == "UNKNOWN" and r["cause_code"] == "ledger_unreadable"
    assert r["missed_count_24h"] is None and r["late_count_24h"] is None
    sch = s["schedulers"]
    assert sch["status"] == "UNKNOWN" and sch["cause_code"] == "ledger_unreadable"
    assert sch["missed_total_24h"] is None and sch["late_total_24h"] is None


def test_read_ledger_window_on_a_missing_file_is_unreadable_not_empty(tmp_path):
    out = LH.read_ledger_window(tmp_path / "absent.sqlite", NOW - timedelta(days=1))
    assert out["readable"] is False and out["gap"] == "the ledger file is absent"
    assert not (tmp_path / "absent.sqlite").exists()  # mode=ro never creates it


def test_dst_spring_forward_slot_follows_the_wall_clock():
    """2026-03-08 02:00 ET springs forward: a 09:00 ET lane fires at 13:00 UTC that day (14:00 UTC the day before)."""
    lane = n8n_lane("syn-daily-9", cron="0 9 * * *")
    now = datetime(2026, 3, 8, 20, 0, tzinfo=UTC)
    on_time = datetime(2026, 3, 8, 13, 1, tzinfo=UTC)
    r = row(snap([lane], ledger([run("syn-daily-9", on_time - timedelta(minutes=1), late_min=1)]), now=now),
            "syn-daily-9")
    assert r["last_expected_at"] == datetime(2026, 3, 8, 13, 0, tzinfo=UTC).isoformat()
    assert (r["expected_slots_24h"], r["done_slots_24h"], r["late_count_24h"]) == (1, 1, 0)
    assert r["state"] == "OK"
    # a run at the pre-DST UTC hour (10:00 EDT wall) is 60 min late, not on time
    late = row(snap([lane], ledger([run("syn-daily-9", datetime(2026, 3, 8, 13, 0, tzinfo=UTC), late_min=60)]),
                    now=now), "syn-daily-9")
    assert late["late_count_24h"] == 1 and late["state"] == "LATE"


# ── registration is not execution ─────────────────────────────────────────────────────────────────────────────────

def test_registered_n8n_lane_with_no_run_is_missed_not_ok():
    s = snap([n8n_lane()], ledger([]))
    r = row(s, "syn-n8n-2h")
    assert r["state"] == "LATE" and r["cause_code"] == "never_dispatched"
    assert r["missed_count_24h"] == 12 and r["done_slots_24h"] == 0
    assert s["schedulers"]["status"] == "WARN"


def test_fail_before_jobs_history_reports_no_missed_count_for_a_never_dispatched_lane():
    """The existing reader cannot count a lane that never ran; the new lane can."""
    from scripts.lib import jobs_history as JH

    lane = n8n_lane()
    old = JH.lane_history(lane, now=NOW, trading_day=ALWAYS, ledger=[], journal=[],
                          ledger_since=NOW - timedelta(days=9), journal_since=None, last_live_success=None,
                          receipt=None, output_at=None, fixes=[])
    assert old.get("missed_count") is None  # before: nothing to count
    new = row(snap([lane], ledger([])), "syn-n8n-2h")
    assert new["missed_count_24h"] == 12  # after: every owed slot is MISSED


def test_queued_run_is_matched_on_requested_at_not_its_late_start():
    """A run requested at the slot but started after the next slot is a LATE run of its slot, not a miss."""
    lane = n8n_lane("syn-n8n-10m", cron="*/10 * * * *")
    lane["expected_cadence_hours"] = 0.1667
    now = datetime(2026, 3, 4, 12, 59, tzinfo=UTC)
    slot = datetime(2026, 3, 4, 12, 0, tzinfo=UTC)
    slots = [slot + timedelta(minutes=10 * i) for i in range(6)]  # 12:00 .. 12:50 UTC
    runs = [run("syn-n8n-10m", t) for t in slots]
    runs[0]["started_at"] = (slot + timedelta(minutes=13)).isoformat()  # queued past the 12:10 slot
    led = ledger(runs, covered_from=slot - timedelta(minutes=2))  # nothing before 12:00 is measured
    r = row(snap([lane], led, now=now), "syn-n8n-10m")
    assert r["missed_count_24h"] == 0, r["missed_slots"]
    assert r["done_slots_24h"] == 6 and r["late_count_24h"] == 1


def test_dry_run_does_not_satisfy_a_live_lane_but_satisfies_a_shadow_lane():
    runs = [run("syn-n8n-2h", t, mode="dry_run") for t in slots_utc()]
    live = row(snap([n8n_lane()], ledger(runs)), "syn-n8n-2h")
    assert live["missed_count_24h"] == 12 and live["state"] == "LATE"
    shadow = row(snap([n8n_lane(mode="dry_run")], ledger(runs)), "syn-n8n-2h")
    assert shadow["done_slots_24h"] == 12 and shadow["state"] == "OK"


def test_lock_skip_is_not_a_run_and_a_failed_last_slot_is_failing():
    slots = slots_utc()
    runs = [run("syn-n8n-2h", t) for t in slots[:-2]]
    runs.append(run("syn-n8n-2h", slots[-2], state="RUN_SKIPPED_LOCK"))
    runs.append(run("syn-n8n-2h", slots[-1], state="RUN_FAILED"))
    r = row(snap([n8n_lane()], ledger(runs)), "syn-n8n-2h")
    assert r["missed_count_24h"] == 1 and r["failed_count_24h"] == 1
    assert r["state"] == "FAILING" and r["cause_code"] == "last_slot_failed"


def test_lane_born_today_owes_no_slot_before_its_first_dispatch():
    slots = slots_utc()
    lane = n8n_lane(state_since="2026-03-04")
    # first dispatch at 06:00 ET (11:00 UTC) on its state_since day: earlier slots that day were not owed
    r = row(snap([lane], ledger([run("syn-n8n-2h", slots[-1])])), "syn-n8n-2h")
    assert r["missed_count_24h"] == 0 and r["state"] == "OK", r
    # ... but a lane registered that day that never ran still owes every slot
    r2 = row(snap([lane], ledger([])), "syn-n8n-2h")
    assert r2["missed_count_24h"] > 0 and r2["cause_code"] == "never_dispatched"


def test_inactive_lane_has_no_row_and_rollup_counts_are_consistent():
    paused = {**n8n_lane("syn-paused"), "state": "PAUSED"}
    s = snap([n8n_lane(), paused, cron_lane()], ledger([]))
    assert {r["lane_id"] for r in s["lanes"]} == {"syn-n8n-2h", "syn-cron-hourly"}
    sch = s["schedulers"]
    assert sum(sch["counts"].values()) == len(s["lanes"]) == sch["lanes_judged"]
    assert sch["missed_total_24h"] == 12 and sch["lanes_n8n"] == 1
    assert s["registry_states"] == {"ACTIVE": 2, "PAUSED": 1}


def test_naive_clock_is_refused():
    with pytest.raises(ValueError):
        LH.build({"lanes": []}, ledger=ledger([]), now=NOW.replace(tzinfo=None), trading_day=ALWAYS, signals={})


# ── the ledger reader against a synthetic SQLite file ─────────────────────────────────────────────────────────────

def test_read_ledger_window_reads_rows_read_only(tmp_path):
    db = tmp_path / "ledger.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE runs (run_id TEXT, lane_id TEXT, mode TEXT, state TEXT, requested_at TEXT, "
                 "started_at TEXT, finished_at TEXT, exit_code INT)")
    old = run("syn-n8n-2h", NOW - timedelta(days=20))
    rows = [old] + [run("syn-n8n-2h", t) for t in slots_utc()]
    conn.executemany("INSERT INTO runs VALUES (:run_id,:lane_id,:mode,:state,:requested_at,:started_at,"
                     ":finished_at,:exit_code)", rows)
    conn.commit()
    conn.close()
    before = db.stat().st_mtime_ns
    since = NOW - timedelta(days=8)
    out = LH.read_ledger_window(db, since)
    assert out["readable"] is True and len(out["runs"]) == 12
    assert out["covered_from"] == since  # an older row exists, so the whole window is covered
    assert db.stat().st_mtime_ns == before
    r = row(snap([n8n_lane()], out), "syn-n8n-2h")
    assert r["done_slots_24h"] == 12 and r["state"] == "OK"


# ── the table write ───────────────────────────────────────────────────────────────────────────────────────────────

class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, params=None):
        if self.conn.fail_on is not None and len(self.conn.executed) == self.conn.fail_on:
            raise RuntimeError("synthetic write failure")
        self.conn.executed.append((sql, params))

    def fetchone(self):
        return (self.conn.regclass,)


class FakeConn:
    def __init__(self, fail_on=None, regclass="lane_health_current"):
        self.executed, self.commits, self.rollbacks = [], 0, 0
        self.fail_on, self.regclass = fail_on, regclass

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def test_write_upserts_every_row_in_one_transaction():
    s = snap([n8n_lane(), cron_lane()], ledger([]))
    conn = FakeConn()
    assert LH.write(conn, s) == 2
    assert conn.commits == 1 and conn.rollbacks == 0
    assert all(sql.startswith("INSERT INTO lane_health_current") and "ON CONFLICT (lane_id)" in sql
               for sql, _ in conn.executed)
    params = dict(zip(LH.COLUMNS, conn.executed[0][1]))
    assert params["run_id"] == "preview" and json.loads(params["detail"])["schema"] == LH.ROW_SCHEMA
    assert not any("DELETE" in sql.upper() or "CREATE" in sql.upper() for sql, _ in conn.executed)


def test_write_rolls_back_on_error():
    s = snap([n8n_lane(), cron_lane()], ledger([]))
    conn = FakeConn(fail_on=1)
    with pytest.raises(RuntimeError):
        LH.write(conn, s)
    assert conn.commits == 0 and conn.rollbacks == 1


def test_table_exists_reads_to_regclass():
    assert LH.table_exists(FakeConn()) is True
    assert LH.table_exists(FakeConn(regclass=None)) is False


def test_migration_matches_the_writer_columns():
    sql = (ROOT / "migrations/2026_11_12_lane_health_current.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS lane_health_current" in sql
    for col in LH.COLUMNS:
        assert f"\n    {col} " in sql, col
    for state in LH.STATES:
        assert f"'{state}'" in sql, state


# ── the CLI ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _cli(*args, env_extra=None, tmp_path=None):
    import os

    env = {k: v for k, v in os.environ.items() if k != "TRADEAI_RUN_ID"}
    env.update(env_extra or {})
    return subprocess.run([sys.executable, str(ROOT / "scripts/lane_health_snapshot.py"), *args],
                          capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=120)


def test_cli_apply_without_run_id_is_refused_before_any_read(tmp_path):
    p = _cli("--apply", "--state-root", str(tmp_path))
    assert p.returncode == 2, p.stderr
    assert json.loads(p.stdout.splitlines()[0])["error"] == "no_run_id"
    assert not (tmp_path / "data/runtime/lane_health_current.json").exists()


def test_cli_dry_run_writes_nothing(tmp_path):
    (tmp_path / "data/runtime").mkdir(parents=True)
    p = _cli("--state-root", str(tmp_path))
    assert p.returncode == 0, p.stderr[-2000:]
    assert "LANE_OUTPUT" in p.stdout + p.stderr
    assert sorted(x.name for x in tmp_path.rglob("*") if x.is_file()) == []  # nothing written
    lines = p.stdout.splitlines()
    lane_output = [x for x in (p.stdout + "\n" + p.stderr).splitlines() if x.startswith("LANE_OUTPUT ")]
    assert len(lane_output) == 1
    emitted = json.loads(lane_output[0].split(" ", 1)[1])
    assert emitted["mode"] == "dry_run" and emitted["produced_count"] == 0
    body = "\n".join(x for x in lines if not x.startswith("LANE_OUTPUT "))
    out = json.loads(body)
    # the synthetic state root has no ledger: the Schedulers row is UNKNOWN, never OK, and totals are unknown
    assert out["schedulers"] == "UNKNOWN" and out["missed_total_24h"] is None
    assert out["run_id"] == "preview"


# ── the registration fragment ─────────────────────────────────────────────────────────────────────────────────────

def _fragment() -> dict:
    return json.loads(FRAGMENT.read_text(encoding="utf-8"))


def test_fragment_rows_agree_with_each_other_and_the_dispatcher():
    f = _fragment()
    reg, allow, fresh, health = (f["lane_registry_row"], f["allowlist_entry"], f["freshness_contract"],
                                 f["health_contract"])
    assert {reg["lane_id"], allow["lane_id"], fresh["lane_id"], health["id"], f["lane_id"]} == {LH.LANE_ID}
    sched, disp = reg["scheduler"], reg["dispatch"]
    assert sched["kind"] == "n8n" and sched["expression"] == "dispatcher"
    assert sched["match"] == " ".join(["scripts/lane_health_snapshot.py", *allow["live_arg"]])
    assert allow["command"] == ["$PY", "scripts/lane_health_snapshot.py"] and allow["dry_run_arg"] == ["--dry-run"]
    assert sched["cadence"] in disp["cron"] and sched["cadence"] == "*/10 * * * *"
    assert sched["stage"] == "shadow" and disp["mode"] == "dry_run"  # shadow first: the dry run writes nothing
    assert reg["output_signal"] == {**reg["output_signal"], "kind": "json_key", "key": "ok_at",
                                    "path": allow["output_signal"]}
    assert allow["output_signal"] == f"data/runtime/{LH.LANE_ID}_last.json"
    assert fresh["signal"] == {"kind": "db_max", "table": LH.TABLE, "column": "measured_at"}
    assert fresh["max_age_hours"] == 0.5 and fresh["severity"] == "P2"
    assert health["schema"] == "N8nHealthContract@v1" and health["workflow_id"] == "tradeai-dispatcher"
    assert health["baseline"]["timeout_s"] == allow["timeout_s"]
    assert (ROOT / "scripts/lane_health_snapshot.py").is_file()
    text = FRAGMENT.read_text()
    assert "/home/" not in text and "place_order" not in text


def test_fragment_row_is_admitted_by_the_dispatcher():
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))
    import lane_dispatch as ld

    f = _fragment()
    ok, reason = ld.r1_class_admission(f["lane_registry_row"], f["allowlist_entry"])
    assert ok is True, reason


def test_fragment_row_is_measured_by_this_lane():
    """The lane judges itself like any other n8n lane: registered with no run is MISSED."""
    reg = dict(_fragment()["lane_registry_row"])
    reg["state_since"] = "2026-03-01"
    r = row(snap([reg], ledger([])), LH.LANE_ID)
    assert r["scheduler_kind"] == "n8n" and r["expected_mode"] == "dry_run"
    assert r["state"] == "LATE" and r["cause_code"] == "never_dispatched" and r["missed_count_24h"] > 100


# ── REVIEW-2171c (cc-opus-1): five mutants survived; each test below pins one honesty rule ───────────────────────

def test_a_due_slot_inside_its_grace_is_pending_not_missed():
    """Mutant 1 (``now < judge_at`` -> False). A slot that fired 2 min ago with no run yet is pending, not MISSED."""
    now = NOW + timedelta(minutes=2)  # 13:01 UTC: the 08:00 ET (13:00 UTC) slot fired 1 min ago, judge_at is 13:15
    runs = [run("syn-n8n-2h", t) for t in slots_utc()]
    r = row(snap([n8n_lane()], ledger(runs), now=now), "syn-n8n-2h")
    assert r["pending_slots"] == 1, r
    assert r["missed_count_24h"] == 0 and r["state"] == "OK", r
    # the same slot past its 15 min grace with still no run is missed
    r2 = row(snap([n8n_lane()], ledger(runs), now=NOW + timedelta(minutes=17)), "syn-n8n-2h")
    assert r2["pending_slots"] == 0 and r2["missed_count_24h"] == 1 and r2["state"] == "LATE", r2


def test_slots_before_the_state_since_day_are_never_owed():
    """Mutant 2 (``_active_day`` ignores state_since). A lane ACTIVE from 2026-03-04 ET that never ran owes only
    that day's slots (00, 02, 04, 06 ET), not the eight 2026-03-03 slots in the 24 h window."""
    lane = n8n_lane(state_since="2026-03-04")
    r = row(snap([lane], ledger([])), "syn-n8n-2h")
    assert r["expected_slots_24h"] == 4 and r["missed_count_24h"] == 4, r
    assert all(s >= "2026-03-04T05:00" for s in r["missed_slots"]), r["missed_slots"]
    assert LH._active_day(lane, datetime(2026, 3, 4, 4, 59, tzinfo=UTC)) is False  # 23:59 ET on 03-03
    assert LH._active_day(lane, datetime(2026, 3, 4, 5, 0, tzinfo=UTC)) is True    # 00:00 ET on 03-04


def test_business_critical_classes_narrow_the_warn_rollup():
    """Mutant 3 (critical filter removed). With business_critical_value_classes set, a LATE lane outside those
    classes does not turn Home Schedulers WARN; a LATE lane inside them does."""
    late_other = n8n_lane("syn-late-ops")  # value_class "Operationally Important"
    late_crit = n8n_lane("syn-late-crit", value_class="Business Critical")
    policy = {"business_critical_value_classes": ["Business Critical"]}
    s = snap([late_other], ledger([]), policy=policy)
    assert row(s, "syn-late-ops")["state"] == "LATE"
    assert s["schedulers"]["status"] == "OK" and s["schedulers"]["worst"] == [], s["schedulers"]
    s2 = snap([late_other, late_crit], ledger([]), policy=policy)
    assert s2["schedulers"]["status"] == "WARN"
    assert [w["lane_id"] for w in s2["schedulers"]["worst"]] == ["syn-late-crit"]
    # with the list empty (today's config) every LATE lane counts
    assert snap([late_other], ledger([]))["schedulers"]["status"] == "WARN"


def test_a_shadow_lane_with_an_old_output_signal_is_never_stale():
    """Mutant 4 (``stale and live`` -> ``stale``). A dry_run lane writes no output by design; only a live lane
    whose signal is older than its last n expected slots is STALE."""
    old_signal = {"readable": True, "kind": "file", "at": NOW - timedelta(days=3)}
    shadow = n8n_lane("syn-shadow", mode="dry_run")
    live = n8n_lane("syn-live")
    runs = [run("syn-shadow", t, mode="dry_run") for t in slots_utc()] + [run("syn-live", t) for t in slots_utc()]
    s = LH.build({"lanes": [shadow, live]}, ledger=ledger(runs), now=NOW, trading_day=ALWAYS,
                 signals={"syn-shadow": old_signal, "syn-live": old_signal})
    assert row(s, "syn-shadow")["state"] == "OK", row(s, "syn-shadow")
    assert row(s, "syn-live")["state"] == "STALE" and row(s, "syn-live")["cause_code"] == "output_stale"


def test_a_young_ledger_does_not_count_its_pre_history_as_missed(tmp_path):
    """Mutant 5 (covered_from always ``since``). A ledger whose oldest row is younger than the window covers only
    from that row: earlier slots are not_measured, never MISSED."""
    db = tmp_path / "ledger.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE runs (run_id TEXT, lane_id TEXT, mode TEXT, state TEXT, requested_at TEXT, "
                 "started_at TEXT, finished_at TEXT, exit_code INT)")
    slots = slots_utc()
    conn.executemany("INSERT INTO runs VALUES (:run_id,:lane_id,:mode,:state,:requested_at,:started_at,"
                     ":finished_at,:exit_code)", [run("syn-n8n-2h", t) for t in slots[6:]])
    conn.commit()
    conn.close()
    since = NOW - timedelta(days=8)
    out = LH.read_ledger_window(db, since)
    assert out["readable"] is True and len(out["runs"]) == 6
    assert out["covered_from"] == slots[6] + timedelta(seconds=10), out["covered_from"]  # the oldest requested_at
    r = row(snap([n8n_lane()], out), "syn-n8n-2h")
    assert r["missed_count_24h"] == 0 and r["expected_slots_24h"] == 6 and r["state"] == "OK", r
