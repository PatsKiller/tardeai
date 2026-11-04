"""The disk bands must SAY a bad band again, not only when it changes.

2026-11-04: `scripts/disk_usage_monitor.py` alerted once per band CHANGE, so `/` sat at `critical` from 03:15Z for
23 hours on a single alert while the disk kept filling. The operator heard nothing until he asked. These controls pin
the property: a band change alerts, an UNCHANGED bad band re-alerts once the interval is due, and a healthy mount
stays quiet.
"""
import json
import sys
import time
import threading

import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import disk_usage_monitor as M  # noqa: E402

MON = {"warn_pct": 80.0, "critical_pct": 90.0, "realert_minutes": 60.0}
T0 = datetime(2026, 11, 4, 2, 0, tzinfo=timezone.utc)


def test_the_first_alert_is_immediate_and_every_later_one_respects_the_clock():
    """ONE clock governs everything. The first thing ever said about a mount is immediate (nobody has been told), and
    after that an escalation, a recovery and a repeat all wait for the interval (cx-openai-4 R3)."""
    assert M.alert_for(None, "critical", {}, T0, MON) == "critical"          # first ever
    fresh = {"alerted_at": (T0 - timedelta(minutes=61)).isoformat(), "alerted_band": "warn"}
    assert M.alert_for("warn", "critical", fresh, T0, MON) == "critical"     # interval passed: escalation is said
    inside = {"alerted_at": T0.isoformat(), "alerted_band": "warn"}
    assert M.alert_for("warn", "critical", inside, T0, MON) is None          # inside the window: silence
    assert M.alert_for("critical", "ok", inside, T0, MON) is None            # recovery too
    assert M.alert_for("critical", "ok", fresh, T0, MON) == "ok"             # after the interval: recovery said


def test_a_critical_band_that_STAYS_critical_alerts_again_after_the_interval():
    """The defect: two consecutive critical runs alerted once. The property: both (modulo the interval) alert."""
    entry = {"band": "critical", "alerted_at": T0.isoformat()}
    assert M.alert_for("critical", "critical", entry, T0 + timedelta(minutes=30), MON) is None
    assert M.alert_for("critical", "critical", entry, T0 + timedelta(minutes=61), MON) == "critical"
    # and a second re-alert after another interval, so it never settles into silence again
    later = {"band": "critical", "alerted_at": (T0 + timedelta(minutes=61)).isoformat()}
    assert M.alert_for("critical", "critical", later, T0 + timedelta(minutes=122), MON) == "critical"


def test_a_bad_band_with_no_record_of_ever_alerting_alerts_now():
    """A state written before this fix (or a lost alert) must not stay silent because nobody was ever told."""
    assert M.alert_for("critical", "critical", {}, T0, MON) == "critical"
    assert M.alert_for("critical", "critical", {"alerted_at": "not-a-date"}, T0, MON) == "critical"


def test_sixty_percent_is_quiet():
    assert M.band_of(60.0, MON) == "ok"
    assert M.alert_for("ok", "ok", {}, T0, MON) is None
    assert M.alert_for(None, "ok", {}, T0, MON) is None


def test_the_shipped_config_carries_a_realert_interval():
    cfg = json.loads((ROOT / "config" / "disk_hygiene_rules.json").read_text(encoding="utf-8"))["monitor"]
    assert float(cfg["realert_minutes"]) > 0, "a monitor with no re-alert interval is a one-shot"


def test_the_old_change_only_rule_was_silent_on_a_second_critical_run():
    """The rule the monitor relied on before this fix: unchanged band -> None. Kept as the explicit contrast, so the
    reason for alert_for() is in the suite rather than in a commit message."""
    assert M.transition("critical", "critical") is None
    assert M.transition("warn", "critical") == "critical"


def _flap_alerts(pattern, minutes_per_tick, mon):
    """Drive the real decision function over a sequence of observed bands, updating state exactly as the run does."""
    entry, alerts, t = {}, 0, T0
    for band in pattern:
        decision = M.alert_for(entry.get("band"), band, entry, t, mon)
        if entry.get("band") != band:
            entry["since"] = t.isoformat()          # the run records when the band began
        entry["band"] = band
        if decision:
            alerts += 1
            entry["alerted_at"] = t.isoformat()
            entry["alerted_band"] = band        # the run records this too; without it the flap guard cannot bite
        t += timedelta(minutes=minutes_per_tick)
    return alerts


def test_a_flapping_band_cannot_storm():
    """cc5 / cx-openai-4, review of 3a421ab9a: the transition path bypassed the interval, so an ok<->critical band
    flipping every 15 minutes produced 96 alerts in 24 hours (97 for warn<->critical). Bounded now to one per
    interval, which is the number the config text states."""
    ticks = 24 * 4                                   # 24 hours of 15-minute runs
    pattern = ["ok" if i % 2 == 0 else "critical" for i in range(ticks)]
    alerts = _flap_alerts(pattern, 15, MON)
    assert alerts > 0, "the monitor must still speak at all"
    # Measured bound: one per interval (24 at 60 minutes) plus the single initial escalation.
    assert alerts <= 25, f"a flapping band must stay at the stated bound (<=25/day), got {alerts}"


def test_warn_critical_flapping_is_bounded_too():
    ticks = 24 * 4
    pattern = ["warn" if i % 2 == 0 else "critical" for i in range(ticks)]
    alerts = _flap_alerts(pattern, 15, MON)
    assert alerts <= 25, f"warn<->critical flapping must stay bounded (<=25/day), got {alerts}"


def test_a_steady_critical_band_still_re_alerts_on_the_interval():
    """The first fix must not be lost to the second: a band that never changes still speaks every interval."""
    entry = {"band": "critical", "alerted_at": T0.isoformat()}
    assert M.alert_for("critical", "critical", entry, T0 + timedelta(minutes=61), MON) == "critical"


def test_a_recovery_still_alerts_when_the_interval_has_passed():
    entry = {"band": "critical", "alerted_at": T0.isoformat(), "alerted_band": "critical"}
    assert M.alert_for("critical", "ok", entry, T0 + timedelta(minutes=61), MON) == "ok"
    assert M.alert_for("critical", "ok", entry, T0 + timedelta(minutes=5), MON) is None


def test_a_recovery_is_interval_gated_like_every_other_alert():
    """The bound is only true if NOTHING bypasses the clock: a recovery inside the window is silent, and it is said
    once the interval has passed (cx-openai-4 R3: an immediate recovery reset the clock and the next critical then
    escalated above it, producing 65 alerts in 24 hours against a promise of 25)."""
    entry = {"band": "critical", "alerted_at": T0.isoformat(), "alerted_band": "critical",
             "since": T0.isoformat()}
    assert M.alert_for("critical", "ok", entry, T0 + timedelta(minutes=15), MON) is None
    assert M.alert_for("critical", "ok", entry, T0 + timedelta(minutes=61), MON) == "ok"


def _flap_alerts(pattern, minutes_per_tick, mon):
    """Drive the real decision function over a sequence of observed bands, updating state exactly as the run does."""
    entry, alerts, t = {}, 0, T0
    for band in pattern:
        decision = M.alert_for(entry.get("band"), band, entry, t, mon)
        if entry.get("band") != band:
            entry["since"] = t.isoformat()          # the run records when the band began
        entry["band"] = band
        if decision:
            alerts += 1
            entry["alerted_at"] = t.isoformat()
            entry["alerted_band"] = band        # the run records this too; without it the flap guard cannot bite
        t += timedelta(minutes=minutes_per_tick)
    return alerts


def test_a_flapping_band_cannot_storm():
    """cc5 / cx-openai-4, review of 3a421ab9a: the transition path bypassed the interval, so an ok<->critical band
    flipping every 15 minutes produced 96 alerts in 24 hours (97 for warn<->critical). Bounded now to one per
    interval, which is the number the config text states."""
    ticks = 24 * 4                                   # 24 hours of 15-minute runs
    pattern = ["ok" if i % 2 == 0 else "critical" for i in range(ticks)]
    alerts = _flap_alerts(pattern, 15, MON)
    assert alerts > 0, "the monitor must still speak at all"
    # Measured bound: one per interval (24 at 60 minutes) plus the single initial escalation.
    assert alerts <= 25, f"a flapping band must stay at the stated bound (<=25/day), got {alerts}"


def test_warn_critical_flapping_is_bounded_too():
    ticks = 24 * 4
    pattern = ["warn" if i % 2 == 0 else "critical" for i in range(ticks)]
    alerts = _flap_alerts(pattern, 15, MON)
    assert alerts <= 25, f"warn<->critical flapping must stay bounded (<=25/day), got {alerts}"


def test_a_steady_critical_band_still_re_alerts_on_the_interval():
    """The first fix must not be lost to the second: a band that never changes still speaks every interval."""
    entry = {"band": "critical", "alerted_at": T0.isoformat()}
    assert M.alert_for("critical", "critical", entry, T0 + timedelta(minutes=61), MON) == "critical"


def test_a_recovery_still_alerts_when_the_interval_has_passed():
    entry = {"band": "critical", "alerted_at": T0.isoformat(), "alerted_band": "critical"}
    assert M.alert_for("critical", "ok", entry, T0 + timedelta(minutes=61), MON) == "ok"
    assert M.alert_for("critical", "ok", entry, T0 + timedelta(minutes=5), MON) is None


def test_a_bad_healthy_cycle_cannot_exceed_the_stated_bound():
    """cx-openai-4 R3, the counterexample that broke the previous head: bytes 95, 95, 50 repeating every 15 minutes
    (bad held 30, healthy 15) over 24 hours produced 65 primary alert decisions against a promised maximum of 25,
    because the recovery reset the clock and the next critical escalated above the band just reported."""
    pattern = ["critical", "critical", "ok"] * 32          # 96 polls = 24 hours at 15 minutes
    alerts = _flap_alerts(pattern, 15, MON)
    assert alerts <= 25, f"the stated bound must hold through recovery/escalation cycles, got {alerts}"
    assert alerts > 0, "the monitor must still speak"


def test_a_future_stamp_is_a_clock_correction_not_a_silence():
    """cx-openai-4 R2: a real run under a skewed clock left alerted_at ahead of now; the negative elapsed read as
    'not due' and an ongoing 95% critical emitted nothing for 25 hours. Unknown timing must be treated as due."""
    ahead = (T0 + timedelta(hours=5)).isoformat()
    entry = {"band": "critical", "alerted_at": ahead, "since": ahead}
    assert M.alert_for("critical", "critical", entry, T0, MON) == "critical"
    assert M.alert_for("critical", "critical", entry, T0 + timedelta(minutes=60), MON) == "critical"


def _drive(pairs, mon):
    """Drive the real decision over (minute, band) pairs, updating state exactly as the run does: the observed band,
    the time the band began, and - only when an alert is actually sent - alerted_at and alerted_band."""
    entry, said = {}, []
    for minute, band in pairs:
        t = T0 + timedelta(minutes=minute)
        decision = M.alert_for(entry.get("band"), band, entry, t, mon)
        if entry.get("band") != band:
            entry["since"] = t.isoformat()
        entry["band"] = band
        if decision:
            said.append((minute, decision))
            entry["alerted_at"] = t.isoformat()
            entry["alerted_band"] = band
    return said


def test_a_recovery_inside_the_window_is_delayed_not_discarded():
    """cx-openai-4 R4: critical at 0 and 60, healthy from 75. The recovery is throttled at 75 — correctly — but the run
    records the observed band as ok, so every later poll used to look "unchanged ok" and the recovery was DISCARDED:
    no recovered intent at 120 or 180, every receipt ok. The last REPORTED band stays critical and must still be owed."""
    pairs = [(0, "critical"), (60, "critical"), (75, "ok"), (120, "ok"), (180, "ok")]
    said = _drive(pairs, MON)
    assert said == [(0, "critical"), (60, "critical"), (120, "ok")], f"the recovery must be delayed, not lost: {said}"


def test_a_recovery_is_retained_for_the_inode_metric_too():
    """The same real-run fixture through the INODE policy: one decision function, so the second metric cannot behave
    differently (cx-openai-4 asked for both)."""
    cfg = json.loads((ROOT / "config" / "disk_hygiene_rules.json").read_text(encoding="utf-8"))["monitor"]
    ino = M.metric_policy(cfg, cfg["inodes"])
    pairs = [(0, "critical"), (60, "critical"), (75, "ok"), (120, "ok"), (180, "ok")]
    said = _drive(pairs, ino)
    assert said == [(0, "critical"), (60, "critical"), (120, "ok")], said


def test_the_state_lock_serialises_two_apply_runs_and_is_keyed_to_the_state_file(tmp_path):
    """cx-openai-2 R5, the lost-update: run A reads the snapshot, run B reports a critical band, A's stale write
    replaces the whole file and erases B's reported band, so the recovery is never emitted. atomic_json_store prevents
    TORN json, not a lost read-modify-write. This drives the real lock with two bodies that pause inside their
    read/write window: without the lock their windows overlap and the later write wins; with it, the second body only
    starts once the first has finished, so nothing written in between can be lost.

    Scope, stated honestly: this proves the SERIALISATION property and that the lock is keyed to the state file. The
    full two-OS-process reproduction is cx-openai-2's artifact, not this test."""
    state = tmp_path / "disk_usage_monitor_state.json"
    state.write_text('{"reported": "seed"}')
    order, started = [], []

    def body(name, pause, wrote):
        with M._state_lock(state):                      # the same lock every apply entrypoint takes
            started.append(name)
            current = json.loads(state.read_text())     # read
            time.sleep(pause)                           # decide/queue window
            current["reported"] = wrote                # write
            state.write_text(json.dumps(current))
            order.append(name)

    a = threading.Thread(target=body, args=("A", 0.25, "healthy"))
    a.start()
    deadline = time.monotonic() + 2.0
    while "A" not in started and time.monotonic() < deadline:   # A is inside its window first
        time.sleep(0.01)
    b = threading.Thread(target=body, args=("B", 0.0, "critical"))
    b.start()
    a.join()
    b.join()

    assert order == ["A", "B"], f"the second body must wait for the first: {order}"
    assert json.loads(state.read_text())["reported"] == "critical", "B's reported band was lost"


def test_every_apply_entrypoint_routes_through_the_locking_run():
    """A new caller inherits the lock by going through run(); main() must not reach the body directly."""
    src = (ROOT / "scripts" / "disk_usage_monitor.py").read_text(encoding="utf-8")
    assert "return run(rules=rules, state_root=state_root, ledger=ledger" in src
    assert "with _state_lock(state_path):" in src
    assert "_run_locked(" in src
