"""Read-only Agent Runtime health monitor tests."""
from __future__ import annotations

from agent_runtime import health_monitor


def test_collect_reports_manual_mode_without_timers(monkeypatch):
    def fake_get(url: str):
        if url.endswith("/readiness"):
            return {
                "wiring": {
                    "read_api": {"state": "CONNECTED"},
                    "dispatch": {"state": "WIRED"},
                }
            }
        if url.endswith("/operations"):
            return {"agents": [{"timer_state": "NOT_INSTALLED"}]}
        return {"data": [{"status": "COMPLETED"}]}

    monkeypatch.setattr(health_monitor, "_get_json", fake_get)
    payload = health_monitor.collect("http://example")
    assert payload["state"] == "HEALTHY"
    assert payload["execution_mode"] == "MANUAL_DISPATCH_ONLY"
    assert payload["authority"]["dispatch"] is False


def test_collect_degrades_on_wiring_failure(monkeypatch):
    def fake_get(url: str):
        if url.endswith("/readiness"):
            return {
                "wiring": {
                    "read_api": {"state": "CONNECTED"},
                    "dispatch": {"state": "MISSING_PROVIDER"},
                }
            }
        if url.endswith("/operations"):
            return {"agents": []}
        return {"data": []}

    monkeypatch.setattr(health_monitor, "_get_json", fake_get)
    assert health_monitor.collect("http://example")["state"] == "DEGRADED"
