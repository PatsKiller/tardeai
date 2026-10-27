"""Release train Phase 7 prerequisites (2026-10-22; AGENTS.md §25.3, §25.7; arming packet §J.2–J.3).

06:00: ``release_train_drain.ReadOnlyDrainProbe`` replaces the hardcoded ``UnprovenDrain`` on the production path. It
proves quiescence from read-only signals (measured restart impact, market hours, critical-lane schedule, running
pipeline_runs, held flock locks) and refuses whenever any signal is missing.

08:00: the latest activation start is 09:00 minus the worst measured promote + verify + rollback minus the buffer, from
``release_train_timing.DurationHistory`` (train rows + the deploy receipt history), and is refused until each duration
has 3 samples. The macro calendar gate (08:30 release day or stale calendar -> skip) is pinned again here.

Both stay inert behind window enablement: a live train refuses a disabled slot before any window rule runs.

Hermetic: every reader is injected; no DB, no network, no host state, no real clock.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from scripts.lib import exact_release_receipt as ER
from scripts.lib import macro_calendar as MC
from scripts.lib import release_train_controller as T
from scripts.lib import release_train_drain as DR
from scripts.lib import release_train_timing as TM
from tests.test_release_train_controller_20261021 import World, _cal

ROOT = Path(__file__).resolve().parents[1]
ET = ZoneInfo("America/New_York")
UTC = timezone.utc


# ── fixtures ──────────────────────────────────────────────────────────────────────────────────────

def history(tmp_path: Path, rows: list[dict], deploy_rows: list[dict] | None = None) -> TM.DurationHistory:
    train = tmp_path / "train_measurements.jsonl"
    train.write_text("".join(json.dumps(r) + "\n" for r in rows))
    deploy = None
    if deploy_rows is not None:
        deploy = tmp_path / "deploy_receipt_history.jsonl"
        deploy.write_text("".join(json.dumps(r) + "\n" for r in deploy_rows))
    return TM.DurationHistory(train, deploy)


MEASURED = [{"promote_s": 120, "verify_s": 60, "rollback_s": 90}] * 3


def policy(**over) -> dict:
    doc = json.loads((ROOT / "config/release_train_drain_policy.json").read_text())
    doc.update(over)
    return doc


def lane(lane_id, expr, *, value_class="Business Critical", state="ACTIVE", kind="cron", **extra):
    return {"lane_id": lane_id, "state": state, "value_class": value_class,
            "scheduler": {"kind": kind, "expression": expr, **extra}}


QUIET_REGISTRY = {"lanes": [
    lane("positions-sync", "9,24,39,54 9-16 * * 1-5", match="flock -n /tmp/positions_sync.lock python x.py"),
    lane("nightly-report", "30 20 * * 1-5"),
    lane("noisy-but-unimportant", "*/5 * * * *", value_class="Nice to Have"),
    lane("retired-critical", "*/5 * * * *", state="RETIRED"),
    lane("portfolio-server-service", "portfolio-server.service", kind="systemd"),
]}


def probe(tmp_path, *, rows=MEASURED, pol=None, registry=QUIET_REGISTRY, running=(), held=None, now=None):
    h = history(tmp_path, list(rows))
    return DR.ReadOnlyDrainProbe(
        history=h,
        policy_loader=lambda: DR.load_policy(_write(tmp_path / "policy.json", pol or policy())),
        registry_reader=lambda: registry,
        pipeline_reader=lambda statuses, lookback: list(running) if running is not None else None,
        lock_reader=(lambda paths: {p: p in (held or ()) for p in paths}) if held != "UNREADABLE" else (lambda p: None),
        clock=lambda: now or datetime(2026, 10, 22, 5, 0, tzinfo=ET),
    )


def _write(path: Path, doc: dict) -> Path:
    path.write_text(json.dumps(doc))
    return path


def win(day: date, slot="0600", hhmm="0600", duration=60) -> T.TrainWindow:
    start = T.local_start(day, hhmm)
    assert start is not None
    return T.TrainWindow(slot, "requires_drain_or_non_disruptive_path", start, duration, True)


THU = date(2026, 10, 22)


# ── 06:00 drain probe ─────────────────────────────────────────────────────────────────────────────

def test_drain_probe_passes_only_when_every_read_only_signal_is_clear(tmp_path):
    p = probe(tmp_path)
    ok, why = p.check(win(THU))
    assert ok, why
    rep = p.last_report
    assert rep["schema"] == "ReleaseTrainDrain@v1" and rep["ok"] is True
    assert set(rep["checks"]) == {"policy", "impact", "market", "schedule", "running", "locks"}
    assert all(c["ok"] for c in rep["checks"].values())
    # critical = ACTIVE + Business Critical; the daemon has no schedule; the retired/unimportant lanes are ignored
    assert rep["critical_lanes"] == ["positions-sync", "nightly-report", "portfolio-server-service"]
    # span = start - 5 min .. end + (120+60+90) s + 10 min
    assert rep["span"]["start"] == "2026-10-22T05:55:00-04:00"
    assert rep["span"]["end"] == "2026-10-22T07:14:30-04:00"


@pytest.mark.parametrize("rows,needle", [
    ([], "promote_s 0/3"),
    (MEASURED[:2], "verify_s 2/3"),
    ([{"promote_s": 120, "verify_s": 60}] * 3, "rollback_s 0/3"),
])
def test_drain_unproven_without_three_measured_durations_refuses(tmp_path, rows, needle):
    ok, why = probe(tmp_path, rows=rows).check(win(THU))
    assert not ok and why.startswith("impact:") and needle in why


def test_drain_refuses_when_measured_restart_impact_is_too_large(tmp_path):
    ok, why = probe(tmp_path, pol=policy(max_restart_impact_s=200)).check(win(THU))
    assert not ok and "exceeds 200s" in why


def test_drain_refuses_a_critical_lane_due_inside_the_span(tmp_path):
    reg = {"lanes": QUIET_REGISTRY["lanes"] + [lane("options-tick", "7,22,37,52 * * * *")]}
    p = probe(tmp_path, registry=reg)
    ok, why = p.check(win(THU))
    assert not ok and why.startswith("schedule:") and "options-tick@06:07" in why
    assert p.last_report["checks"]["schedule"]["due"][0]["fires"][0] == "2026-10-22T06:07:00-04:00"


def test_restart_tolerant_lane_is_exempt_from_the_due_check_only(tmp_path):
    reg = {"lanes": QUIET_REGISTRY["lanes"] + [lane("options-tick", "7,22,37,52 * * * *")]}
    tol = policy(restart_tolerant={"options-tick": "idempotent; re-fires in 15 min (operator review)"})
    assert probe(tmp_path, registry=reg, pol=tol).check(win(THU))[0]
    ok, why = probe(tmp_path, registry=reg, pol=tol, running=[{"pipeline_key": "options_tick"}]).check(win(THU))
    assert not ok and why.startswith("running:")


def test_unreadable_schedule_for_a_critical_lane_refuses(tmp_path):
    reg = {"lanes": QUIET_REGISTRY["lanes"] + [lane("mystery", "emitted by hooks", kind="event")]}
    ok, why = probe(tmp_path, registry=reg).check(win(THU))
    assert not ok and "schedule not readable" in why and "mystery" in why


def test_n8n_dispatcher_lane_uses_its_cadence(tmp_path):
    reg = {"lanes": QUIET_REGISTRY["lanes"] + [lane("disp", "dispatcher", kind="n8n", cadence="0 6 * * *")]}
    ok, why = probe(tmp_path, registry=reg).check(win(THU))
    assert not ok and "disp@06:00" in why


def test_running_critical_pipeline_refuses_and_db_unreadable_refuses(tmp_path):
    ok, why = probe(tmp_path, running=[{"pipeline_key": "positions_sync", "run_id": "r1", "status": "running"}]
                    ).check(win(THU))
    assert not ok and why.startswith("running:") and "positions_sync" in why
    # a non-critical running pipeline does not block
    assert probe(tmp_path, running=[{"pipeline_key": "finviz_screener_runner"}]).check(win(THU))[0]
    ok, why = probe(tmp_path, running=None).check(win(THU))
    assert not ok and why == "running: pipeline_runs unreadable"


def test_held_critical_lock_refuses_and_unreadable_locks_refuse(tmp_path):
    ok, why = probe(tmp_path, held=("/tmp/positions_sync.lock",)).check(win(THU))
    assert not ok and why.startswith("locks:") and "/tmp/positions_sync.lock" in why
    ok, why = probe(tmp_path, held="UNREADABLE").check(win(THU))
    assert not ok and why.startswith("locks:")


def test_proc_locks_reader_matches_by_inode_and_never_locks(tmp_path):
    held, free = tmp_path / "held.lock", tmp_path / "free.lock"
    held.write_text("")
    free.write_text("")
    st = os.stat(held)
    ident = f"{os.major(st.st_dev):02x}:{os.minor(st.st_dev):02x}:{st.st_ino}"
    locks = tmp_path / "locks"
    locks.write_text(f"1: FLOCK  ADVISORY  WRITE 4242 {ident} 0 EOF\n2: -> FLOCK  ADVISORY  WRITE 4243 {ident} 0 EOF\n")
    out = DR.read_held_locks([str(held), str(free), str(tmp_path / "absent.lock")], proc_locks=locks)
    assert out == {str(held): True, str(free): False, str(tmp_path / "absent.lock"): False}
    assert DR.read_held_locks([str(held)], proc_locks=tmp_path / "nope") is None


def test_lock_paths_come_from_the_lanes_crontab_line():
    sched = {"kind": "cron", "expression": "*/5 * * * * cd x && flock -n -E 75 /tmp/a.lock python y.py",
             "command_text": "flock -n /tmp/b.lock z"}
    assert sorted(DR.lock_paths(sched)) == ["/tmp/a.lock", "/tmp/b.lock"]


@pytest.mark.parametrize("bad", [
    {"schema": "nope"},
    {"max_restart_impact_s": 0},
    {"critical_value_classes": [], "critical_lanes_extra": []},
    {"restart_tolerant": {"x": "short"}},
    {"extra_locks": ["relative.lock"]},
    {"running_statuses": []},
])
def test_bad_policy_refuses(tmp_path, bad):
    ok, why = probe(tmp_path, pol=policy(**bad)).check(win(THU))
    assert not ok and why.startswith("policy:")


def test_missing_policy_file_refuses(tmp_path):
    p = probe(tmp_path)
    p.policy_loader = lambda: DR.load_policy(tmp_path / "absent.json")
    ok, why = p.check(win(THU))
    assert not ok and "drain policy unreadable" in why


def test_declared_extra_lane_missing_from_registry_refuses(tmp_path):
    ok, why = probe(tmp_path, pol=policy(critical_lanes_extra=["ghost-lane"])).check(win(THU))
    assert not ok and "ghost-lane" in why


def test_registry_unreadable_refuses(tmp_path):
    ok, why = probe(tmp_path, registry=None).check(win(THU))
    assert not ok and why == "schedule: lane registry unreadable"


def test_market_guard_refuses_a_span_that_reaches_the_open(tmp_path):
    # a long impact pushes the span end past 08:30 (09:30 open - 60 min guard)
    slow = [{"promote_s": 3000, "verify_s": 600, "rollback_s": 1500}] * 3
    pol = policy(max_restart_impact_s=7200)
    ok, why = probe(tmp_path, rows=slow, pol=pol).check(win(THU))
    assert not ok and why.startswith("market:") and "09:30 open" in why
    # Saturday: no session, the same span passes the market check (and everything else)
    ok, why = probe(tmp_path, rows=slow, pol=pol).check(win(date(2026, 10, 24)))
    assert ok, why


@pytest.mark.parametrize("day,offset", [
    (date(2026, 3, 9), "-04:00"),    # Monday after spring-forward: EDT
    (date(2026, 11, 2), "-05:00"),   # Monday after fall-back: EST
    (date(2026, 11, 1), "-05:00"),   # fall-back Sunday itself (06:00 is after the repeated hour)
])
def test_drain_span_is_dst_safe(tmp_path, day, offset):
    p = probe(tmp_path, registry={"lanes": [lane("at-0710", "10 7 * * *")]})
    ok, why = p.check(win(day))
    assert not ok and "at-0710@07:10" in why  # 07:10 local, whatever the offset
    assert p.last_report["span"]["start"].endswith(offset)
    assert p.last_report["span"]["start"].startswith(f"{day.isoformat()}T05:55")


def test_probe_exception_is_a_refusal_not_a_pass(tmp_path):
    p = probe(tmp_path)
    p.registry_reader = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    ok, why = p.check(win(THU))
    assert not ok and why.startswith("drain probe error: RuntimeError")


def test_shipped_policy_is_valid_and_today_refuses_on_real_registry(tmp_path):
    """The shipped policy loads, and against the checked-in lane registry the 06:00 drain is NOT proven: Business
    Critical lanes fire inside the span. That refusal is the honest state until the operator reviews them."""
    pol = DR.load_policy()
    assert pol["slots"] == ["0600"] and pol["restart_tolerant"] == {}
    p = probe(tmp_path, registry=DR.read_registry(), pol=pol)
    ok, why = p.check(win(THU))
    assert not ok and why.startswith("schedule:"), why


# ── the controller: wiring, inertness, activation recheck ─────────────────────────────────────────

class _Probe:
    def __init__(self, results):
        self.results, self.calls = list(results), 0
        self.last_report = {"schema": "ReleaseTrainDrain@v1", "stub": True}

    def check(self, window):
        self.calls += 1
        r = self.results[min(self.calls - 1, len(self.results) - 1)]
        return r


def test_controller_default_is_still_unproven_and_the_production_path_wires_the_real_probe(tmp_path, monkeypatch):
    w = World(tmp_path, slot="0600", now=datetime(2026, 10, 22, 6, 2, tzinfo=ET))
    assert isinstance(w.controller().drain, T.UnprovenDrain)
    src = (ROOT / "scripts/lib/release_train_controller.py").read_text()
    body = src.split("def build_controller(", 1)[1].split("\ndef ", 1)[0]
    assert "drain=DR.default_drain_probe(state.root)" in body
    assert "TM.DEPLOY_HISTORY" in body
    assert isinstance(DR.default_drain_probe(tmp_path), DR.ReadOnlyDrainProbe)


def test_drain_report_is_recorded_and_a_failed_probe_skips_0600(tmp_path):
    w = World(tmp_path, slot="0600", now=datetime(2026, 10, 22, 6, 2, tzinfo=ET))
    c = w.controller()
    c.drain = _Probe([(False, "schedule: 1 critical lane(s) due inside the span: x@06:07")])
    code, rec = c.run()
    assert rec["outcome"] == "NO_OP" and rec["reason"] == "WINDOW_SKIPPED_NO_DRAIN"
    assert rec["drain"]["ok"] is False and rec["drain"]["report"]["stub"] is True


def test_disabled_0600_is_refused_before_the_probe_runs(tmp_path):
    w = World(tmp_path, slot="1800", now=datetime(2026, 10, 22, 6, 2, tzinfo=ET))  # 0600 disabled
    c = w.controller()
    c.drain = _Probe([(True, "drained")])
    code, rec = c.run()
    assert rec["reason"] == "REFUSED_WINDOW_DISABLED" and c.drain.calls == 0


def test_drain_is_rechecked_at_activation(tmp_path):
    w = World(tmp_path, slot="0600", now=datetime(2026, 10, 22, 6, 2, tzinfo=ET))
    c = w.controller()
    c.window = T.TrainWindow("0600", "r", datetime(2026, 10, 22, 6, 0, tzinfo=ET), 60, True)
    c.drain = _Probe([(False, "locks: critical lock(s) held: ['/tmp/x.lock']")])
    with pytest.raises(T.Halt) as h:
        c._check_drain("activation")
    assert h.value.outcome == "MERGED_NOT_LIVE" and h.value.reason == "DRAIN_LOST_AT_ACTIVATION"
    c.window = T.TrainWindow("1800", "canary", datetime(2026, 10, 22, 18, 0, tzinfo=ET), 90, True)
    c._check_drain("activation")  # other slots never consult the probe
    assert c.drain.calls == 1


def test_new_modules_and_policy_are_protected_surfaces():
    for path in ("scripts/lib/release_train_drain.py", "scripts/lib/release_train_timing.py",
                 "config/release_train_drain_policy.json"):
        assert T.is_protected(path), path


def test_every_slot_ships_disabled():
    assert all(s["enabled"] is False for s in T.DEFAULT_SLOTS)
    example = json.loads((ROOT / "config/release_train_delegation.example.json").read_text())
    assert all(s["enabled"] is False for s in example["windows"]["slots"])


# ── 08:00: measured durations, latest start, macro calendar ──────────────────────────────────────

def test_three_samples_of_each_duration_are_required(tmp_path):
    h = history(tmp_path, MEASURED[:2])
    assert h.worst_all()[0] is None and "promote_s 2/3" in h.worst_all()[1]
    h = history(tmp_path, MEASURED)
    assert h.worst_all() == ({"promote_s": 120.0, "verify_s": 60.0, "rollback_s": 90.0}, "measured")


def test_invalid_samples_never_count(tmp_path):
    bad = [{"promote_s": "120", "verify_s": True, "rollback_s": -1}, {"promote_s": 0, "verify_s": 99999,
                                                                      "rollback_s": None}]
    h = history(tmp_path, bad + MEASURED[:2])
    s = h.summary()["keys"]
    assert {k: v["count"] for k, v in s.items()} == {"promote_s": 2, "verify_s": 2, "rollback_s": 2}
    (tmp_path / "train_measurements.jsonl").write_text("not json\n" + json.dumps(MEASURED[0]) + "\n")
    assert h.summary()["keys"]["promote_s"]["count"] == 1


def test_worst_of_the_last_ten_samples_is_used(tmp_path):
    rows = [{"promote_s": 900, "verify_s": 60, "rollback_s": 60}] + [{"promote_s": 100, "verify_s": 60,
                                                                      "rollback_s": 60}] * 10
    assert history(tmp_path, rows).worst_all()[0]["promote_s"] == 100.0
    assert history(tmp_path, rows[:5]).worst_all()[0]["promote_s"] == 900.0


def test_deploy_receipt_history_supplies_promote_and_rollback_and_dedupes_the_train(tmp_path):
    sha = "a" * 40
    deploy = [
        {"schema": ER.HISTORY_SCHEMA, "mode": "promote", "ok": True, "duration_s": 150, "sha": sha},  # = train row
        {"schema": ER.HISTORY_SCHEMA, "mode": "promote", "ok": True, "duration_s": 140, "sha": "b" * 40},
        {"schema": ER.HISTORY_SCHEMA, "mode": "promote", "ok": False, "duration_s": 999, "sha": "c" * 40},
        {"schema": ER.HISTORY_SCHEMA, "mode": "prepare", "ok": True, "duration_s": 500, "sha": "d" * 40},
        {"schema": ER.HISTORY_SCHEMA, "mode": "rollback", "ok": True, "duration_s": 80, "sha": "e" * 40},
        {"schema": ER.HISTORY_SCHEMA, "mode": "rollback", "ok": True, "duration_s": None, "sha": "f" * 40},
        {"schema": "other", "mode": "rollback", "ok": True, "duration_s": 70},
    ]
    train = [{"sha": sha, "promote_s": 150, "verify_s": 50}] * 3
    s = history(tmp_path, train, deploy).summary()["keys"]
    assert s["promote_s"]["count"] == 4 and s["promote_s"]["sources"] == ["deploy_receipt", "train"]
    assert s["rollback_s"]["count"] == 1 and s["verify_s"]["count"] == 3
    assert s["verify_s"]["sources"] == ["train"]


def test_a_train_rollback_is_not_counted_twice(tmp_path):
    merged, prev = "a" * 40, "b" * 40
    train = [{"sha": merged, "rollback_sha": prev, "promote_s": 100, "verify_s": 50, "rollback_s": 70}]
    deploy = [{"schema": ER.HISTORY_SCHEMA, "mode": "rollback", "ok": True, "duration_s": 72, "sha": prev},
              {"schema": ER.HISTORY_SCHEMA, "mode": "promote", "ok": True, "duration_s": 101, "sha": merged}]
    s = history(tmp_path, train, deploy).summary()["keys"]
    assert s["rollback_s"]["count"] == 1 and s["promote_s"]["count"] == 1


def test_unreadable_history_refuses(tmp_path):
    (tmp_path / "dir").mkdir()
    h = TM.DurationHistory(tmp_path / "dir", None)
    assert h.worst_all()[0] is None and "unreadable" in h.worst_all()[1]


def test_receipt_writer_appends_a_duration_row_and_keeps_the_v2_receipt_shape(tmp_path):
    receipt = tmp_path / "deploy_receipt.json"
    releases = tmp_path / "releases"
    releases.mkdir()
    started = str(datetime.now(UTC).timestamp() - 42)
    rc = ER.main(["--releases-base", str(releases), "--receipt-file", str(receipt), "--ok", "false",
                  "--rolled-back", "false", "--mode", "promote", "--health", "fail", "--started-at", started])
    assert rc == 0
    doc = json.loads(receipt.read_text())
    assert "duration_s" not in doc and "started_at" not in doc          # the v2 field set is pinned elsewhere
    rows = [json.loads(x) for x in (tmp_path / ER.HISTORY_NAME).read_text().splitlines()]
    assert len(rows) == 1 and rows[0]["schema"] == ER.HISTORY_SCHEMA and rows[0]["mode"] == "promote"
    assert 41 <= rows[0]["duration_s"] <= 60 and rows[0]["ok"] is False
    assert (tmp_path / ER.HISTORY_NAME).stat().st_mode & 0o777 == 0o600
    # a second write appends; nothing is rewritten
    ER.main(["--releases-base", str(releases), "--receipt-file", str(receipt), "--ok", "false",
             "--rolled-back", "false", "--mode", "rollback", "--health", "fail"])
    rows = [json.loads(x) for x in (tmp_path / ER.HISTORY_NAME).read_text().splitlines()]
    assert len(rows) == 2 and rows[1]["duration_s"] is None and rows[1]["started_at"] is None


def test_successful_history_row_becomes_a_sample(tmp_path):
    rec = {"at": "2026-10-22T22:00:30+00:00", "mode": "promote", "ok": True, "attempted_target": {"sha": "a" * 40}}
    start = str(datetime(2026, 10, 22, 22, 0, 0, tzinfo=UTC).timestamp())
    row = ER.history_row(rec, start)
    assert row["duration_s"] == 30.0 and row["sha"] == "a" * 40
    assert TM.deploy_samples([row]) == [{"key": "promote_s", "value": 30.0, "sha": "a" * 40,
                                         "at": rec["at"], "source": "deploy_receipt"}]
    assert ER.history_row(rec, "garbage")["duration_s"] is None
    assert ER.history_row(rec, str(datetime(2026, 10, 22, 23, 0, tzinfo=UTC).timestamp()))["duration_s"] is None


def test_deploy_script_passes_its_start_time():
    src = (ROOT / "scripts/cio_phase2_exact_main_deploy.sh").read_text()
    assert 'DEPLOY_STARTED_AT="$(date +%s.%N)"' in src
    assert '--started-at "${DEPLOY_STARTED_AT:-}"' in src


@pytest.mark.parametrize("day,utc_hour", [
    (date(2026, 10, 22), 13),   # EDT: 09:00 local = 13:00Z
    (date(2026, 11, 2), 14),    # EST after fall-back: 09:00 local = 14:00Z
    (date(2026, 3, 9), 13),     # EDT after spring-forward
    (date(2026, 3, 6), 14),     # EST before spring-forward
])
def test_latest_start_is_09_local_minus_measured_minus_buffer_dst_safe(tmp_path, day, utc_hour):
    h = history(tmp_path, MEASURED)
    w = win(day, slot="0800", hhmm="0800", duration=30)
    latest, why = T.latest_activation_start(w, h, buffer_min=10)
    nine = datetime(day.year, day.month, day.day, utc_hour, 0, tzinfo=UTC)
    assert latest.astimezone(UTC) == nine - timedelta(seconds=120 + 60 + 90, minutes=10)
    # the delegation's static cap still applies
    w2 = T.TrainWindow("0800", "last", w.start, 30, True, "08:10", True)
    assert T.latest_activation_start(w2, h, buffer_min=10)[0] == T.local_start(day, "0810")


def test_latest_start_refuses_with_insufficient_measurements(tmp_path):
    w = win(THU, slot="0800", hhmm="0800", duration=30)
    latest, why = T.latest_activation_start(w, history(tmp_path, MEASURED[:2]), buffer_min=10)
    assert latest is None and "2/3" in why


def _calendar_clear(world, tmp):
    (tmp / "hostcfg" / "macro_calendar.json").write_text(json.dumps(_cal("2026-10-21T08:00:00-04:00")))


def test_0800_with_a_clear_calendar_and_two_measurements_is_skipped_unmeasured(tmp_path):
    w = World(tmp_path, slot="0800", now=datetime(2026, 10, 22, 8, 1, tzinfo=ET))
    _calendar_clear(w, tmp_path)
    (w.state_dir / "train_measurements.jsonl").write_text("".join(json.dumps(r) + "\n" for r in MEASURED[:2]))
    code, rec, _ = w.run()
    assert rec["outcome"] == "NO_OP" and rec["reason"] == "WINDOW_SKIPPED_UNMEASURED"
    assert "2/3" in rec["latest_activation_start"]["detail"]


def test_0800_with_three_measurements_passes_the_window_rules(tmp_path):
    w = World(tmp_path, slot="0800", now=datetime(2026, 10, 22, 8, 1, tzinfo=ET))
    _calendar_clear(w, tmp_path)
    (w.state_dir / "train_measurements.jsonl").write_text("".join(json.dumps(r) + "\n" for r in MEASURED))
    code, rec, _ = w.run()
    assert rec.get("reason") not in ("WINDOW_SKIPPED_UNMEASURED", "WINDOW_SKIPPED_PAST_LATEST_START"), rec
    assert rec["latest_activation_start"]["at"] == "2026-10-22T08:10:00-04:00"  # capped by latest_start_et


@pytest.mark.parametrize("cal,reason", [
    (_cal("2026-10-21T08:00:00-04:00", skip_days=("2026-10-22",)), "WINDOW_SKIPPED_MACRO_MACRO_DAY"),
    (_cal("2026-10-18T07:00:00-04:00"), "WINDOW_SKIPPED_MACRO_STALE"),
    (None, "WINDOW_SKIPPED_MACRO_UNAVAILABLE"),
])
def test_0800_macro_day_or_stale_calendar_skips_even_when_measured(tmp_path, cal, reason):
    w = World(tmp_path, slot="0800", now=datetime(2026, 10, 22, 8, 1, tzinfo=ET))
    if cal is not None:
        (tmp_path / "hostcfg" / "macro_calendar.json").write_text(json.dumps(cal))
    (w.state_dir / "train_measurements.jsonl").write_text("".join(json.dumps(r) + "\n" for r in MEASURED))
    code, rec, _ = w.run()
    assert rec["outcome"] == "NO_OP" and rec["reason"] == reason


def test_macro_calendar_is_dst_safe_on_the_window_day():
    """The calendar is keyed by the window's LOCAL date: 08:00 on the fall-back Sunday is still that date."""
    w = win(date(2026, 11, 1), slot="0800", hhmm="0800", duration=30)
    assert w.start.date() == date(2026, 11, 1) and w.start.utcoffset() == timedelta(hours=-5)
    assert MC.LANE_ID
