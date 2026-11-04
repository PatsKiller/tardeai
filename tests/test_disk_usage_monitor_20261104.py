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
    assert M.alert_for("critical", "ok", {"alerted_at": T0.isoformat()}, T0, MON) == "ok"


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
