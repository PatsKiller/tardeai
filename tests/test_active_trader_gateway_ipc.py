from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from datetime import datetime, timedelta, timezone

from active_trader.current_marks_api import current_marks_payload
from active_trader.l2_runtime import IPCSnapshotRuntime
from active_trader.l2_status_api import build_l2_status, build_l2_status_symbol
from active_trader.read_api import ReadOnlyActiveTraderAPI
from active_trader.read_http import dispatch
from moomoo.gateway_ipc import SnapshotClient, SnapshotPublisher, atomic_write_json


def snapshot_body(now):
    return {
        "heartbeat_at": now.isoformat(),
        "source_commit": "abc123",
        "owner": {"pid": 123, "exclusive_lock_held": True},
        "provider": {"connected": True, "entitled_realtime": True, "reconnect_epoch": 2, "subscriptions_by_symbol": {"AAPL": ["QUOTE", "ORDER_BOOK", "TICKER"]}},
        "quota": {"total_quota": 100, "remain": 97, "own_used": 3},
        "symbols": {
            "AAPL": {
                "symbol": "AAPL", "state": "FRESH", "confirmed_subtypes": ["ORDER_BOOK", "QUOTE", "TICKER"],
                "provider_subtypes": ["ORDER_BOOK", "QUOTE", "TICKER"], "reconnect_epoch": 2,
                "book": {"provider_at": "bp", "bid_provider_at": "bb", "ask_provider_at": "ba", "received_at": now.isoformat(), "sequence_id": 7, "sequence_source": "gateway_monotonic_per_reconnect_epoch"},
                "tape": {"provider_at": "tp", "received_at": now.isoformat(), "provider_sequence": 11},
                "quote": {"provider_at": "qp", "received_at": now.isoformat()},
                "t2": {"is_t2": True, "reason": "OK"},
            }
        },
        "current_marks": {"AAPL": {"symbol": "AAPL", "bid": 100, "ask": 100.2, "last": 100.1, "source": "moomoo_quote", "provider_at": "qp", "received_at": now.isoformat(), "age_ms": 10, "available": True, "stale": False}},
        "journal": {"directory": "/tmp/journal", "durable_replay_available": True},
        "concurrent_symbols": 1,
        "max_concurrent_l2_symbols": 8,
        "min_dwell_seconds": 60,
    }


def test_status_reads_fresh_ipc_snapshot_and_preserves_separate_timestamps(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "snapshot.json"
    SnapshotPublisher(path).publish(snapshot_body(now))
    runtime = IPCSnapshotRuntime(SnapshotClient(path, max_age_seconds=30))
    body = build_l2_status(runtime)
    assert body["connected"] is True and body["t2_any"] is True
    assert body["gateway_source_commit"] == "abc123"
    detail = build_l2_status_symbol(runtime, "aapl")
    assert detail["book_bid_provider_at"] == "bb"
    assert detail["book_ask_provider_at"] == "ba"
    assert detail["tape_received_at"] == now.isoformat()
    assert detail["quote_provider_at"] == "qp"
    assert detail["sequence_source"].startswith("gateway_monotonic")


def test_stale_snapshot_is_disconnected_not_live(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "snapshot.json"
    payload = snapshot_body(now - timedelta(seconds=30))
    SnapshotPublisher(path).publish(payload)
    runtime = IPCSnapshotRuntime(SnapshotClient(path, max_age_seconds=5))
    body = build_l2_status(runtime)
    assert body["connected"] is False
    assert body["provider_state"] == "SNAPSHOT_STALE"
    assert body["ipc_snapshot_reason"] == "SNAPSHOT_STALE"


def test_current_marks_uses_fresh_gateway_then_batch_fallback(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "snapshot.json"
    SnapshotPublisher(path).publish(snapshot_body(now))
    calls = []

    def batch(symbols):
        calls.append(symbols)
        return {"TSLA": {"symbol": "TSLA", "last": 250.0, "bid": 249.9, "ask": 250.1, "source": "approved", "received_at": now.isoformat(), "available": True, "stale": False}}

    body = current_marks_payload(["AAPL", "TSLA"], client=SnapshotClient(path, max_age_seconds=30), approved_batch=batch)
    assert body["marks"][0]["source"] == "moomoo_quote"
    assert body["marks"][0]["fallback"] is False
    assert body["marks"][1]["source"] == "approved"
    assert calls == [["TSLA"]]


def test_current_marks_dispatch_is_get_only_and_requires_symbols(monkeypatch):
    status, body = dispatch(ReadOnlyActiveTraderAPI(), "GET", "/api/v3/active-trader/current-marks", {})
    assert status == 400 and body["write"] is False
    status2, body2 = dispatch(ReadOnlyActiveTraderAPI(), "POST", "/api/v3/active-trader/current-marks", {"symbols": "AAPL"})
    assert status2 == 405 and body2["authority"]["order"] is False
