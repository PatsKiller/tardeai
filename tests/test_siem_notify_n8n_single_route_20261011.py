"""SIEM critical notifier skips n8n-siem-bridge rows: one route per n8n item (2026-10-11).

The n8n-siem-bridge writes ``system_health_events`` rows with component ``n8n:<lane>`` for findings the n8n
incident fan-in already routes to the incident notifier. ``siem_critical_notify`` paged them again from the SIEM
dashboard, so every n8n item alerted twice. The fan-in owns them; this notifier must skip them and keep paging
everything else exactly as before.

No network, no Telegram, no real state file, no .env: the module is loaded from source, the SIEM read, the sender,
PROJECT_ROOT and STATE are all replaced with in-test doubles.
"""

from __future__ import annotations

import importlib.util
import io
import json
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def notify(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "siem_critical_notify_under_test", ROOT / "scripts" / "siem_critical_notify.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "PROJECT_ROOT", tmp_path)  # no .env here
    monkeypatch.setattr(mod, "STATE", tmp_path / "siem_notified.json")
    sent: list[str] = []
    monkeypatch.setattr(mod, "_send", lambda msg: sent.append(msg) or True)
    mod._sent = sent
    return mod


def _inc(component, severity="P0", event_type="PIPELINE_FAILURE", events=3):
    return {
        "component": component,
        "event_type": event_type,
        "severity": severity,
        "events": events,
        "groups": 1,
        "first": datetime.now().isoformat(),
        "last": datetime.now().isoformat(),
    }


def _serve(mod, monkeypatch, correlated):
    body = json.dumps({"data": {"correlated": correlated}}).encode()

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda url, timeout=0: _Resp(body))


def test_select_skips_n8n_bridge_components(notify):
    rows = [
        _inc("n8n:enterprise-backtester"),
        _inc("n8n:n8n-incident-fanin", severity="P1", event_type="N8N_DOWN"),
        _inc("atm_auto_approver"),
        _inc("db", severity="P1", event_type="DB_CONNECTION"),
    ]
    got = notify.select_incidents(rows)
    assert [c["component"] for c in got] == ["atm_auto_approver", "db"]


def test_select_unchanged_for_non_n8n(notify):
    rows = [
        _inc("atm_auto_approver", severity="P2"),  # not critical
        {**_inc("feed"), "last": "2020-01-01T00:00:00"},  # stale
        _inc(None),  # component missing is not an n8n row
        _inc("my_n8n:thing"),  # prefix only, not substring
    ]
    got = notify.select_incidents(rows)
    assert [c["component"] for c in got] == [None, "my_n8n:thing"]


def test_main_pages_only_non_n8n_and_records_no_n8n_state(notify, monkeypatch):
    _serve(notify, monkeypatch, [_inc("n8n:strategy-backtester"), _inc("atm_auto_approver")])
    assert notify.main() == 0
    assert len(notify._sent) == 1
    assert "atm_auto_approver" in notify._sent[0]
    assert "n8n:" not in notify._sent[0]
    state = json.loads(notify.STATE.read_text())
    assert list(state) == ["atm_auto_approver|PIPELINE_FAILURE|P0"]


def test_main_only_n8n_rows_sends_nothing(notify, monkeypatch, capsys):
    _serve(notify, monkeypatch, [_inc("n8n:a"), _inc("n8n:b", severity="P1")])
    assert notify.main() == 0
    assert notify._sent == []
    assert "0 critical incident(s), 0 new Telegram alert(s)" in capsys.readouterr().out
