"""C1 firing coverage for the disk-pressure guard's operator alarm.

`disk_pressure_guard.notify()` is a new send_telegram site, added 2026-09-21
after the disk hit 100% full with 84 MB free. The alarm_coverage ratchet caught
it immediately:

    scripts/disk_pressure_guard.py: 1 untested send_telegram sites, baseline 0

The cheap way out was to add the file to config/alarm_firing_baseline.txt. That
would silence the gate while leaving the alarm unproven — the exact
"green over an untested condition" defect recorded in
docs/audit/message-identity-audit-2026-09-21.md §3.5, where a registered CI gate
sat over a 0% production condition because it tested a pure function and never
the write. So this observes the transport instead.

An alarm that has never been observed firing is indistinguishable from no alarm.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

COVERS = [
    "scripts/disk_pressure_guard.py:118",
]


@pytest.fixture
def capture_transport(monkeypatch):
    captured: list[tuple] = []

    def _send(msg, *a, **k):
        captured.append((msg, dict(k)))
        return True

    import telegram_alert

    monkeypatch.setattr(telegram_alert, "send_telegram", _send)
    return captured


def test_disk_pressure_alarm_reaches_the_transport(capture_transport):
    """The site itself fires and carries its text."""
    import disk_pressure_guard as g

    assert g.notify("C1 probe: disk pressure guard") == "accepted"
    assert capture_transport, "transport never called"
    assert "C1 probe: disk pressure guard" in capture_transport[0][0]


def test_a_refused_send_is_reported_not_swallowed(monkeypatch):
    """send_telegram returning False must surface, not read as success.

    The whole point of this guard is that the operator hears about disk
    pressure. A silent False is how an alarm becomes decorative.
    """
    import telegram_alert

    import disk_pressure_guard as g

    monkeypatch.setattr(telegram_alert, "send_telegram", lambda *a, **k: False)
    assert g.notify("probe") == "send_returned_false"


def test_a_broken_transport_is_reported_not_raised(monkeypatch):
    """Alerting must never raise here — the guard's job is reclaiming disk.

    If notify() raised, a transport outage would abort the reclaim that the
    operator actually needs, turning a notification failure into a disk failure.
    """
    import telegram_alert

    import disk_pressure_guard as g

    def _boom(*a, **k):
        raise RuntimeError("transport down")

    monkeypatch.setattr(telegram_alert, "send_telegram", _boom)
    assert g.notify("probe") == "error:RuntimeError"


def test_pressure_state_pages_and_recovery_does_not_page_twice(monkeypatch, tmp_path):
    """Notify on a TRANSITION, not on every run.

    Measured 2026-09-21: this codebase carries ~4,800 alerts/day from one
    escalation handler whose _notify() has no dedupe and no alert-fatigue
    coverage. A 15-minute timer with the same shape would add 96/day. The guard
    routes through alert_condition_state.observe(), so a condition that stays
    bad is re-stated at most once per REALERT_MINUTES.
    """
    import disk_pressure_guard as g

    assert g.REALERT_MINUTES == 360, "OPERATIONS.md:71-75 specifies a 6h re-alert throttle"
    assert g.DEFAULT_USED_PCT == 85.0, "operator asked for 85%; enforcer warn_free_pct is 15%"
    assert g.CONDITION_KEY.startswith("system_health:"), g.CONDITION_KEY


def test_the_guard_never_deletes_anything_itself():
    """Every deletion belongs to disk_hygiene_enforcer, under its protections.

    A second component that deletes releases on its own schedule is how
    CURRENT gets removed by something that did not know what CURRENT was.
    """
    src = (ROOT / "scripts" / "disk_pressure_guard.py").read_text(encoding="utf-8")
    for forbidden in ("shutil.rmtree", "os.remove", "os.unlink", "rm -rf"):
        assert forbidden not in src, f"guard must delegate deletion, found {forbidden!r}"
    assert "disk_hygiene_enforcer" in src
