"""C1 firing test for scripts/backup_enforcer.py's one alert site (2026-10-31, AGENTS.md §24.15).

The enforcer alerts once per condition (unverified Drive copy, Drive unreachable past its grace, newest dump not
offsite) through ``default_notify`` -> ``telegram_alert.send_telegram``. This drives that site to the transport
boundary with ``alarm_capture`` (nothing is sent) and proves the text and priority survive the trip.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

COVERS = [
    "scripts/backup_enforcer.py",
]


def _load():
    spec = importlib.util.spec_from_file_location("backup_enforcer_alarm", ROOT / "scripts" / "backup_enforcer.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_backup_enforcer_alert_reaches_the_transport(alarm_capture):
    be = _load()
    result = be.default_notify("C1 probe backup_enforcer: newest dump unverified on Drive (md5 mismatch)", "P2")
    assert result == "accepted"
    alarm_capture.assert_fired(contains="newest dump unverified on Drive")


def test_backup_enforcer_has_exactly_the_one_driven_site():
    """The whole-file COVERS claim holds only while default_notify is the file's single send site."""
    import sys

    sys.path.insert(0, str(ROOT / "scripts" / "lib"))
    from alarm_firing_coverage import call_sites

    sites = [ln for f, ln in call_sites(ROOT / "scripts") if f == "scripts/backup_enforcer.py"]
    assert len(sites) == 1, sites
