"""State-transition semantics for health / staleness / generic conditions."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from alert_condition_state import observe, today_metrics  # noqa: E402


def test_fresh_to_stale_notifies_once(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ALERT_STATE_PATH", str(tmp_path / "s.json"))
    first = observe("data_staleness:holdings.json", "STALE:40h", alertable=True)
    assert first["notify"] is True
    assert first["action"] == "new"
    again = observe("data_staleness:holdings.json", "STALE:40h", alertable=True)
    assert again["notify"] is False
    assert again["action"] == "ongoing"


def test_stale_to_recovered_notifies(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ALERT_STATE_PATH", str(tmp_path / "s.json"))
    observe("data_staleness:holdings.json", "STALE:40h", alertable=True)
    rec = observe("data_staleness:holdings.json", "FRESH", alertable=False)
    assert rec["action"] == "recovered"
    assert rec["notify"] is True


def test_metrics_count_suppressed(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ALERT_STATE_PATH", str(tmp_path / "s.json"))
    observe("system_health:locks", "STALE", alertable=True)
    observe("system_health:locks", "STALE", alertable=True)
    observe("system_health:locks", "STALE", alertable=True)
    m = today_metrics()
    assert m["new"] == 1
    assert m["suppressed"] >= 2
