"""Sector momentum: governed notify, no bypass_router, restart-persistent."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from industry_momentum import (  # noqa: E402
    decide_sector_notifications,
    emit_telegram,
    sector_semantic_uid,
)


ALERTS = [
    {"sector": "Technology", "etf": "XLK", "from": "LEADING", "to": "WEAKENING",
     "severity": "warning", "line": "⚠ Technology: LEADING→WEAKENING"},
    {"sector": "Financials", "etf": "XLF", "from": "LAGGING", "to": "IMPROVING",
     "severity": "info", "line": "⚠ Financials: LAGGING→IMPROVING"},
]


def test_source_never_bypasses():
    text = (ROOT / "scripts" / "sector_momentum_engine.py").read_text()
    assert "bypass_router=True" not in text
    assert "decide_sector_notifications" in text
    assert "emit_telegram" in text


def test_close_once_then_replay_silent(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ALERT_STATE_PATH", str(tmp_path / "state.json"))
    sends = []
    first = decide_sector_notifications(ALERTS, session="2026-08-18")
    emit_telegram(first, lambda msg: sends.append(msg), title="SECTOR MOMENTUM")
    assert len(first["send"]) == 2
    assert len(sends) == 1
    assert sends[0].startswith("SECTOR MOMENTUM")

    for _ in range(20):
        again = decide_sector_notifications(ALERTS, session="2026-08-18")
        emit_telegram(again, lambda msg: sends.append(msg), title="SECTOR MOMENTUM")
        assert again["send"] == []
        assert len(again["suppressed"]) == 2
    assert len(sends) == 1


def test_process_restart_replay_still_suppressed(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ALERT_STATE_PATH", str(tmp_path / "state.json"))
    decide_sector_notifications(ALERTS, session="2026-08-18")
    replay = decide_sector_notifications(ALERTS, session="2026-08-18")
    assert replay["send"] == []


def test_new_transition_notifies_once(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ALERT_STATE_PATH", str(tmp_path / "state.json"))
    decide_sector_notifications(ALERTS, session="2026-08-18")
    moved = [{**ALERTS[0], "from": "WEAKENING", "to": "LAGGING",
              "line": "⚠ Technology: WEAKENING→LAGGING"}]
    out = decide_sector_notifications(moved, session="2026-08-18")
    assert len(out["send"]) == 1
    replay = decide_sector_notifications(moved, session="2026-08-18")
    assert replay["send"] == []


def test_uid_stable():
    a = sector_semantic_uid("Technology", "LEADING", "WEAKENING", "2026-08-18")
    b = sector_semantic_uid("Technology", "LEADING", "WEAKENING", "2026-08-18")
    assert a == b
    assert a.startswith("sector_momentum:")
