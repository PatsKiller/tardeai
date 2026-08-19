"""Industry momentum: one logical notification per confirmed transition."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from industry_momentum import (  # noqa: E402
    build_alerts, decide_notifications, emit_telegram, is_confirmed, semantic_uid,
)


FIXTURE = [
    {"industry": "Asset Management", "sector": "Financials",
     "from": "LEADING", "to": "WEAKENING", "rel1w": -1.2,
     "held": ["BLK"], "watched": []},
    {"industry": "Credit Services", "sector": "Financials",
     "from": "LAGGING", "to": "IMPROVING", "rel1w": 2.1,
     "held": ["V"], "watched": []},
    {"industry": "Pollution & Treatment Controls", "sector": "Industrials",
     "from": "LEADING", "to": "LAGGING", "rel1w": -3.4,
     "held": ["WM"], "watched": []},
]


def test_confirm_requires_debounce_history():
    assert is_confirmed(["WEAKENING", "LEADING"], "WEAKENING", 2) is True
    assert is_confirmed(["LEADING"], "WEAKENING", 2) is False
    assert is_confirmed(["WEAKENING", "WEAKENING"], "WEAKENING", 2) is False


def test_close_once_then_twenty_replays_send_once(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ALERT_STATE_PATH", str(tmp_path / "state.json"))
    alerts = build_alerts(FIXTURE, max_alerts=10)
    assert len(alerts) == 3
    sends = []

    first = decide_notifications(alerts, session="2026-08-18")
    emit_telegram(first, lambda msg: sends.append(msg))
    assert len(first["send"]) == 3
    assert len(sends) == 1

    for _ in range(20):
        again = decide_notifications(alerts, session="2026-08-18")
        emit_telegram(again, lambda msg: sends.append(msg))
        assert again["send"] == []
        assert len(again["suppressed"]) == 3

    assert len(sends) == 1


def test_process_restart_replay_still_suppressed(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ALERT_STATE_PATH", str(tmp_path / "state.json"))
    alerts = build_alerts(FIXTURE, max_alerts=10)
    decide_notifications(alerts, session="2026-08-18")
    # "restart" is just a new call using the same durable store
    replay = decide_notifications(alerts, session="2026-08-18")
    assert replay["send"] == []


def test_new_confirmed_state_notifies_once(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ALERT_STATE_PATH", str(tmp_path / "state.json"))
    alerts = build_alerts(FIXTURE, max_alerts=10)
    decide_notifications(alerts, session="2026-08-18")
    moved = [{**FIXTURE[0], "from": "WEAKENING", "to": "LAGGING"}]
    new_alerts = build_alerts(moved, max_alerts=10)
    out = decide_notifications(new_alerts, session="2026-08-18")
    assert len(out["send"]) == 1
    replay = decide_notifications(new_alerts, session="2026-08-18")
    assert replay["send"] == []


def test_semantic_uid_stable():
    a = semantic_uid("Asset Management", "LEADING", "WEAKENING", "2026-08-18")
    b = semantic_uid("Asset Management", "LEADING", "WEAKENING", "2026-08-18")
    assert a == b
    assert "industry_momentum:" in a
