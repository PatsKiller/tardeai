"""Hermes rank/score alerts use durable semantic identity, not score timestamps."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

from watchlist_priority import rank_alert_worthy, rank_band  # noqa: E402
from alert_condition_state import observe  # noqa: E402


def test_same_band_is_not_alert_worthy():
    assert rank_alert_worthy(85, 99) is False
    assert rank_band(85) == rank_band(99) == "top100"


def test_crossing_into_top_n_is_worthy():
    assert rank_alert_worthy(180, 250) is True


def test_rank_replay_same_state_suppresses(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_ALERT_STATE_PATH", str(tmp_path / "s.json"))
    first = observe("hermes_rank:AAPL", "outside->top200", alertable=True)
    assert first["notify"] is True
    replay = observe("hermes_rank:AAPL", "outside->top200", alertable=True)
    assert replay["notify"] is False
    assert first["uid"] == replay["uid"]
    assert "2026" not in first["uid"] or "hermes_rank:AAPL" in first["uid"]
