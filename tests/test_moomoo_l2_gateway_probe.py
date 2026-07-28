from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from moomoo_l2_gateway_probe import evaluate_snapshot


def test_probe_requires_full_data_only_round_trip():
    payload = {
        "source_commit": "abc", "service_state": "RUNNING", "heartbeat_at": "now", "order_path": False,
        "authority": {"mutation": False, "order": False, "session_authorize": False, "canary": False, "financial_action": False, "trade_unlock": False},
        "owner": {"exclusive_lock_held": True},
        "provider": {"connected": True, "entitled_realtime": True, "reconnect_epoch": 1, "subscriptions_by_symbol": {"AAPL": ["QUOTE", "ORDER_BOOK", "TICKER"]}},
        "quota": {"remain": 97}, "desired_intent": {"AAPL": {}},
        "symbols": {"AAPL": {
            "provider_subtypes": ["QUOTE", "ORDER_BOOK", "TICKER"],
            "confirmed_subtypes": ["QUOTE", "ORDER_BOOK", "TICKER"],
            "book": {"provider_at": "p", "received_at": "r", "sequence_id": 1, "sequence_source": "gateway_monotonic"},
            "tape": {"provider_at": "p", "received_at": "r", "provider_sequence": 2},
            "quote": {"provider_at": "p", "received_at": "r"},
            "t2": {"is_t2": True},
        }},
        "current_marks": {"AAPL": {"available": True, "stale": False, "received_at": "r"}},
        "journal": {"durable_replay_available": True},
    }
    result = evaluate_snapshot(payload, "AAPL", require_t2=True)
    assert result["pass"] is True
    assert result["failures"] == []
    assert result["authority"]["subscription_change"] is False


def test_probe_fails_when_ticker_evidence_missing():
    payload = {
        "service_state": "RUNNING", "order_path": False, "authority": {}, "owner": {"exclusive_lock_held": True},
        "provider": {"connected": True, "entitled_realtime": True, "subscriptions_by_symbol": {"AAPL": ["QUOTE", "ORDER_BOOK"]}},
        "quota": {"remain": 10}, "desired_intent": {"AAPL": {}}, "symbols": {"AAPL": {}}, "current_marks": {}, "journal": {"durable_replay_available": True},
    }
    result = evaluate_snapshot(payload, "AAPL")
    assert result["pass"] is False
    assert "provider_subtypes" in result["failures"]
    assert "observed_subtypes" in result["failures"]
