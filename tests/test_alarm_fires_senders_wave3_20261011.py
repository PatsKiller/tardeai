"""C1 alarm firing — the senders wave 2/3 notifier changes, observed reaching the transport (2026-10-11).

Senders wave 3 made two notifiers declare intents:

* scripts/system_health_alerts.py main() now has THREE send sites, one per severity: CRITICAL -> P1,
  WARN -> P2, OK (only with HEALTH_ALERT_SEND_OK) -> P3. Before, one undifferentiated site was named debt in
  config/alarm_firing_baseline.txt. Each of the three is driven below and observed at the transport with its
  declared priority, so the file is declared WHOLE in COVERS and its baseline entry is removed (debt paid, not
  absorbed). ``test_system_health_alerts_has_exactly_the_three_driven_sites`` keeps the whole-file claim honest.
* scripts/credential_monitor.py _send_tg keeps ONE transport call (tests/test_alarm_fires_batch6_20260922.py covers
  the file whole); P1 (operator action) turns the dedupe off, P3 keeps the router default. Both paths are driven.

Hermetic: the transport is telegram_alert.send_telegram replaced by a recorder; the shadow comms ledger publish
is replaced; state and log dirs are tmp_path; load_env is a no-op (no .env is read). Nothing reaches Telegram.
"""
from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "scripts" / "lib")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

#: literal strings: alarm_firing_coverage.declared_covers reads ast.Constant elements only.
COVERS = [
    "scripts/system_health_alerts.py",
]


@pytest.fixture
def transport(monkeypatch):
    captured: list[tuple[str, dict]] = []

    def _send(msg, *args, **kwargs):
        captured.append((msg, dict(kwargs)))
        return True

    import telegram_alert

    monkeypatch.setattr(telegram_alert, "send_telegram", _send)
    monkeypatch.setitem(sys.modules, "lib.comms", types.SimpleNamespace(
        CommunicationEvent=lambda **kw: kw, publish_communication=lambda ev: None))
    return captured


def _alert(severity: str) -> dict:
    return {"checked_at": "2026-10-11T12:00:00Z", "severity": severity, "latest_freshness": [],
            "recent_failures": [], "agent_reliability": [], "stale_now_count": 1 if severity != "OK" else 0,
            "degraded_agent_count": 0, "telegram_text": f"C1 probe system health {severity}"}


@pytest.mark.parametrize("severity,send_ok,priority", [
    ("CRITICAL", "", "P1"),
    ("WARN", "", "P2"),
    ("OK", "1", "P3"),
])
def test_system_health_alert_reaches_the_transport_with_its_priority(severity, send_ok, priority, transport,
                                                                     monkeypatch, tmp_path, capsys):
    SHA = importlib.import_module("system_health_alerts")
    monkeypatch.setattr(SHA, "load_env", lambda: None)
    monkeypatch.setattr(SHA, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(SHA, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(SHA, "build_alert", lambda: _alert(severity))
    monkeypatch.setenv("HEALTH_ALERT_SEND_OK", send_ok)

    SHA.main()

    assert transport == [(f"C1 probe system health {severity}",
                          {"priority": priority, "producer": "system_health_alerts"})]
    doc = json.loads((tmp_path / "state" / "system_health_alert.json").read_text())
    assert doc["telegram_result"] == {"sent": True, "via": "router"}


def test_system_health_ok_without_the_flag_does_not_send(transport, monkeypatch, tmp_path, capsys):
    SHA = importlib.import_module("system_health_alerts")
    monkeypatch.setattr(SHA, "load_env", lambda: None)
    monkeypatch.setattr(SHA, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(SHA, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(SHA, "build_alert", lambda: _alert("OK"))
    monkeypatch.delenv("HEALTH_ALERT_SEND_OK", raising=False)
    SHA.main()
    assert transport == []


def test_system_health_alerts_has_exactly_the_three_driven_sites():
    """The whole-file COVERS claim holds only while main() has exactly the three severity sites driven above."""
    from alarm_firing_coverage import call_sites

    sites = [ln for f, ln in call_sites(ROOT / "scripts") if f == "scripts/system_health_alerts.py"]
    assert len(sites) == 3, sites


@pytest.mark.parametrize("priority,expected", [
    ("P1", {"priority": "P1", "producer": "credential_monitor", "dedupe_minutes": 0}),
    ("P3", {"priority": "P3", "producer": "credential_monitor", "dedupe_minutes": None}),
])
def test_credential_monitor_both_priorities_reach_the_transport(priority, expected, transport):
    CM = importlib.import_module("credential_monitor")
    CM._send_tg("C1 probe credential_monitor", priority=priority)
    assert transport == [("C1 probe credential_monitor", expected)]
