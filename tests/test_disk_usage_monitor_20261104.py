"""The disk bands must SAY a bad band again, not only when it changes.

2026-11-04: `scripts/disk_usage_monitor.py` alerted once per band CHANGE, so `/` sat at `critical` from 03:15Z for
23 hours on a single alert while the disk kept filling. The operator heard nothing until he asked. These controls pin
the property: a band change alerts, an UNCHANGED bad band re-alerts once the interval is due, and a healthy mount
stays quiet.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import disk_usage_monitor as M  # noqa: E402

MON = {"warn_pct": 80.0, "critical_pct": 90.0, "realert_minutes": 60.0}
T0 = datetime(2026, 11, 4, 2, 0, tzinfo=timezone.utc)


def test_a_band_change_alerts_immediately():
    assert M.alert_for(None, "critical", {}, T0, MON) == "critical"
    assert M.alert_for("warn", "critical", {"alerted_at": T0.isoformat()}, T0, MON) == "critical"
    # A recovery is good news but not news worth a storm: it is throttled like any other non-escalation, and said
    # once the interval has passed (cc5 review: an immediate recovery restored the 96-alert flap).
    assert M.alert_for("critical", "ok", {"alerted_at": T0.isoformat()}, T0, MON) is None
    assert M.alert_for("critical", "ok", {"alerted_at": (T0 - timedelta(minutes=61)).isoformat()},
                       T0, MON) == "ok"


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
    entry = {"band": "critical", "alerted_at": T0.isoformat()}
    assert M.alert_for("critical", "ok", entry, T0 + timedelta(minutes=61), MON) == "ok"
    assert M.alert_for("critical", "ok", entry, T0 + timedelta(minutes=5), MON) is None
