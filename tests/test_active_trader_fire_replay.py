from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import pytest

from active_trader.fire_performance import FirePerfConfig
from moomoo.gateway_journal import GatewayJournal, JournalBackedFirePerfTracker

FIRE = {"fire_id": "f1", "symbol": "AAPL", "fired_at": "2026-07-28T14:00:00+00:00", "fire_price": 100.0, "stop_ref": 99.0}


def test_durable_replay_computes_extrema_and_complete_coverage(tmp_path):
    journal = GatewayJournal(tmp_path)
    journal.append("COVERAGE_START", symbol="AAPL", event_at="2026-07-28T13:59:00+00:00")
    journal.append("MARK", symbol="AAPL", event_at="2026-07-28T14:00:01+00:00", payload={"last": 101.0})
    journal.append("MARK", symbol="AAPL", event_at="2026-07-28T14:00:02+00:00", payload={"bid": 98.5, "ask": 98.7})
    tracker = JournalBackedFirePerfTracker(journal, FirePerfConfig(mark_stale_after_ms=60_000))
    result = tracker.update(FIRE, current_bid=100.5, current_ask=100.7, current_last=100.6, mark_source="test", mark_at_iso="2026-07-28T14:00:03+00:00", now_iso="2026-07-28T14:00:03+00:00")
    assert result["high_since_fire"] == 101.0
    assert result["low_since_fire"] == 98.6
    assert result["mfe_since_fire"] == 1.0
    assert result["mae_since_fire"] == pytest.approx(-1.4)
    assert result["coverage_complete_since_fire"] is True
    assert result["mfe_mae_scope"] == "DURABLE_JOURNAL_REPLAY"


def test_gap_makes_replay_honestly_incomplete(tmp_path):
    journal = GatewayJournal(tmp_path)
    journal.append("COVERAGE_START", symbol="AAPL", event_at="2026-07-28T13:59:00+00:00")
    journal.append("MARK", symbol="AAPL", event_at="2026-07-28T14:00:01+00:00", payload={"last": 101.0})
    journal.append("COVERAGE_GAP", symbol="AAPL", event_at="2026-07-28T14:00:02+00:00", payload={"reason": "DISCONNECT"})
    replay = journal.replay_extrema("AAPL", FIRE["fired_at"], "2026-07-28T14:00:05+00:00")
    assert replay.coverage_complete is False
    assert replay.coverage_reason == "GAP_AFTER_COVERAGE_START"
    assert replay.high == 101.0


def test_no_pre_fire_coverage_never_claims_complete(tmp_path):
    journal = GatewayJournal(tmp_path)
    journal.append("COVERAGE_START", symbol="AAPL", event_at="2026-07-28T14:00:01+00:00")
    journal.append("MARK", symbol="AAPL", event_at="2026-07-28T14:00:02+00:00", payload={"last": 102.0})
    replay = journal.replay_extrema("AAPL", FIRE["fired_at"], "2026-07-28T14:00:05+00:00")
    assert replay.coverage_complete is False
    assert replay.coverage_reason == "NO_COVERAGE_START_BEFORE_FIRE"
