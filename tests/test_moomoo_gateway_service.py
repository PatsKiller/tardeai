from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import json

import pytest

from moomoo.gateway_ipc import OwnerLockError, SnapshotClient
from moomoo.gateway_service import GatewayServiceConfig, MoomooL2GatewayService


class Clock:
    def __init__(self):
        self.mono = 100.0
        self.wall = 2_000_000_000.0

    def monotonic(self):
        return self.mono

    def wall_time(self):
        return self.wall

    def advance(self, seconds):
        self.mono += seconds
        self.wall += seconds


class FakeTransport:
    def __init__(self, *, emit=True):
        self.up = True
        self.entitled = True
        self.total_quota = 100
        self.subs: dict[str, set[str]] = {}
        self.subscribe_calls = []
        self.unsubscribe_calls = []
        self.fail_unsubscribe_count = 0
        self.emit = emit
        self.sequence = 100
        self.callbacks = {}
        self.closed = False

    def bind_callbacks(self, **callbacks):
        self.callbacks = callbacks

    def ping(self):
        return self.up

    def entitlement_ok(self):
        return self.up and self.entitled

    def _own(self):
        return sum(len(value) for value in self.subs.values())

    def query_subscription(self, is_all_conn=True):
        used = self._own()
        by_type = {}
        for values in self.subs.values():
            for subtype in values:
                by_type[subtype] = by_type.get(subtype, 0) + 1
        return {
            "total_quota": self.total_quota,
            "total_used": used,
            "own_used": used,
            "remain": self.total_quota - used,
            "other_connection_usage": 0,
            "subscriptions_by_type": by_type,
            "subscriptions_by_symbol": {symbol: sorted(values) for symbol, values in self.subs.items()},
        }

    def subscribe(self, symbol, subtypes):
        self.subscribe_calls.append((symbol, tuple(subtypes)))
        self.subs.setdefault(symbol, set()).update(subtypes)
        return True, "ok"

    def unsubscribe(self, symbol, subtypes):
        self.unsubscribe_calls.append((symbol, tuple(subtypes)))
        if self.fail_unsubscribe_count:
            self.fail_unsubscribe_count -= 1
            return False, "simulated"
        for subtype in subtypes:
            self.subs.get(symbol, set()).discard(subtype)
        if symbol in self.subs and not self.subs[symbol]:
            self.subs.pop(symbol)
        return True, "ok"

    def get_quote(self, symbol):
        if not self.emit:
            return {"code": f"US.{symbol}"}
        return {"code": f"US.{symbol}", "bid_price": 100.0, "ask_price": 100.2, "last_price": 100.1, "timestamp": "2026-07-28T14:00:00+00:00"}

    def get_order_book(self, symbol, levels=10):
        if not self.emit:
            return {"code": f"US.{symbol}", "bids": [], "asks": []}
        return {"code": f"US.{symbol}", "bids": [(100.0, 100)], "asks": [(100.2, 80)], "ts": "2026-07-28T14:00:00+00:00"}

    def get_ticker(self, symbol, count=200):
        if not self.emit:
            return []
        self.sequence += 1
        return [{"code": f"US.{symbol}", "time": "2026-07-28T10:00:00", "price": 100.1, "volume": 5, "ticker_direction": "BUY", "sequence": self.sequence}]

    def close(self):
        self.closed = True


def config(tmp_path: Path, intent: Path) -> GatewayServiceConfig:
    return GatewayServiceConfig(
        enabled=True,
        snapshot_path=tmp_path / "snapshot.json",
        state_path=tmp_path / "state.json",
        lock_path=tmp_path / "owner.lock",
        journal_dir=tmp_path / "journal",
        intent_paths=(intent,),
        health_interval_seconds=5,
        quota_refresh_seconds=5,
        heartbeat_seconds=.1,
        book_poll_seconds=.1,
        quote_poll_seconds=.1,
        ticker_poll_seconds=.1,
    )


def write_intent(path: Path, clock: Clock, symbols=("AAPL",)):
    path.write_text(json.dumps({"armed": {symbol: {"armed_at": clock.wall, "expires_at": clock.wall + 600, "priority": "P0", "require_tape": True, "reason": "test"} for symbol in symbols}}))


def test_service_owns_once_ingests_all_subtypes_and_publishes_snapshot(tmp_path):
    clock = Clock(); intent = tmp_path / "intent.json"; write_intent(intent, clock)
    transport = FakeTransport()
    service = MoomooL2GatewayService(config(tmp_path, intent), transport=transport, monotonic=clock.monotonic, wall_time=clock.wall_time, sleep=lambda _: None)
    service.start()
    try:
        read = SnapshotClient(tmp_path / "snapshot.json", max_age_seconds=30).read()
        assert read.fresh is True
        payload = read.payload
        assert payload["owner"]["exclusive_lock_held"] is True
        assert payload["provider"]["subscriptions_by_symbol"]["AAPL"] == ["ORDER_BOOK", "QUOTE", "TICKER"]
        symbol = payload["symbols"]["AAPL"]
        assert set(symbol["confirmed_subtypes"]) == {"ORDER_BOOK", "QUOTE", "TICKER"}
        assert symbol["book"]["sequence_source"].startswith("gateway_monotonic")
        assert symbol["tape"]["provider_sequence"] is not None
        assert symbol["t2"]["is_t2"] is True
        assert payload["current_marks"]["AAPL"]["available"] is True
        assert transport.subscribe_calls == [("AAPL", ("QUOTE", "ORDER_BOOK", "TICKER"))]
    finally:
        service.stop()


def test_second_service_owner_is_rejected(tmp_path):
    clock = Clock(); intent = tmp_path / "intent.json"; write_intent(intent, clock)
    first = MoomooL2GatewayService(config(tmp_path, intent), transport=FakeTransport(), monotonic=clock.monotonic, wall_time=clock.wall_time, sleep=lambda _: None)
    second = MoomooL2GatewayService(config(tmp_path, intent), transport=FakeTransport(), monotonic=clock.monotonic, wall_time=clock.wall_time, sleep=lambda _: None)
    first.start()
    try:
        with pytest.raises(OwnerLockError):
            second.start()
    finally:
        first.stop()


def test_provider_subscription_is_adopted_after_restart_without_duplicate_subscribe(tmp_path):
    clock = Clock(); intent = tmp_path / "intent.json"; write_intent(intent, clock)
    transport = FakeTransport()
    first = MoomooL2GatewayService(config(tmp_path, intent), transport=transport, monotonic=clock.monotonic, wall_time=clock.wall_time, sleep=lambda _: None)
    first.start(); first.stop()
    assert len(transport.subscribe_calls) == 1
    clock.advance(10)
    second = MoomooL2GatewayService(config(tmp_path, intent), transport=transport, monotonic=clock.monotonic, wall_time=clock.wall_time, sleep=lambda _: None)
    second.start()
    try:
        assert len(transport.subscribe_calls) == 1
        assert second.manager.symbols["AAPL"].reconnect_epoch >= 1
        assert second._provider_subscriptions["AAPL"] == ["ORDER_BOOK", "QUOTE", "TICKER"]
    finally:
        second.stop()


def test_disconnect_records_gap_and_reconnect_resets_sequences_without_duplicate_subscribe(tmp_path):
    clock = Clock(); intent = tmp_path / "intent.json"; write_intent(intent, clock)
    transport = FakeTransport()
    service = MoomooL2GatewayService(config(tmp_path, intent), transport=transport, monotonic=clock.monotonic, wall_time=clock.wall_time, sleep=lambda _: None)
    service.start()
    initial_epoch = service.manager.reconnect_epoch
    calls = len(transport.subscribe_calls)
    transport.up = False; clock.advance(6); service.run_once(force=True)
    assert service._connected is False
    transport.up = True; clock.advance(6); service.run_once(force=True)
    try:
        assert service.manager.reconnect_epoch == initial_epoch + 1
        assert len(transport.subscribe_calls) == calls
        journal_text = "".join(path.read_text() for path in (tmp_path / "journal").glob("*.jsonl"))
        assert '"event_type":"COVERAGE_GAP"' in journal_text
        assert '"event_type":"RECONNECT"' in journal_text
    finally:
        service.stop()


def test_failed_unsubscribe_stays_pending_and_retains_provider_subscription(tmp_path):
    clock = Clock(); intent = tmp_path / "intent.json"; write_intent(intent, clock)
    transport = FakeTransport()
    service = MoomooL2GatewayService(config(tmp_path, intent), transport=transport, monotonic=clock.monotonic, wall_time=clock.wall_time, sleep=lambda _: None)
    service.start()
    intent.write_text(json.dumps({"armed": {}}))
    transport.fail_unsubscribe_count = 2
    clock.advance(90)
    service.run_once(force=True)
    assert service.manager.symbols["AAPL"].state.value == "UNSUBSCRIBE_PENDING"
    assert service.manager.symbols["AAPL"].quota_units == 3
    assert "AAPL" in transport.subs
    clock.advance(1)
    service.run_once(force=True)
    try:
        assert service.manager.symbols["AAPL"].state.value == "UNSUBSCRIBED"
        assert "AAPL" not in transport.subs
    finally:
        service.stop()


def test_provider_acceptance_without_data_is_not_observed_confirmation(tmp_path):
    clock = Clock(); intent = tmp_path / "intent.json"; write_intent(intent, clock)
    transport = FakeTransport(emit=False)
    service = MoomooL2GatewayService(config(tmp_path, intent), transport=transport, monotonic=clock.monotonic, wall_time=clock.wall_time, sleep=lambda _: None)
    service.start()
    try:
        detail = service._snapshot_payload()["symbols"]["AAPL"]
        assert set(detail["provider_subtypes"]) == {"ORDER_BOOK", "QUOTE", "TICKER"}
        assert not detail["confirmed_subtypes"]
        assert detail["t2"]["is_t2"] is False
    finally:
        service.stop()
