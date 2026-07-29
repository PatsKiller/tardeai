#!/usr/bin/env python3
"""T2 admission gate + feature snapshot + explicit-owner gateway tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "moomoo"))

from moomoo.quote_gateway import (  # noqa: E402
    BookSnapshot,
    MockTransport,
    QuoteGateway,
    TapePrint,
    get_gateway,
    set_gateway_for_test,
)
from moomoo.subscription_manager import SubscriptionManager  # noqa: E402
from moomoo.l2_feature_service import L2FeatureService  # noqa: E402
from moomoo.l2_lifecycle_config import load_l2_lifecycle_config  # noqa: E402


def _stack(transport=None):
    selected = transport or MockTransport()
    gateway = QuoteGateway(selected)
    manager = SubscriptionManager(gateway, load_l2_lifecycle_config())
    manager.refresh_quota("t")
    service = L2FeatureService(gateway, manager)
    return selected, gateway, manager, service


def _push_book(gateway, symbol, seq=1, crossed=False):
    bids = [(100.0, 200), (99.95, 100)]
    asks = [(99.9, 50)] if crossed else [(100.1, 80), (100.2, 20)]
    gateway.on_book_push(
        BookSnapshot(
            symbol,
            bids,
            asks,
            "2026-07-28T14:00:00Z",
            "2026-07-28T14:00:00Z",
            seq,
        )
    )


def test_t2_requires_fresh_book_not_just_arm():
    _transport, _gateway, manager, service = _stack()
    manager.request_l2("AAPL", now=0)
    decision = service.evaluate_t2("AAPL", now=1, feature_at_iso="f")
    assert decision.is_t2 is False and decision.reason == "WAITING_FIRST_DATA"


def test_provider_down_is_not_t2_even_with_book():
    _transport, gateway, _manager, service = _stack(MockTransport(up=False))
    _push_book(gateway, "AAPL")
    decision = service.evaluate_t2("AAPL", now=1, feature_at_iso="f")
    assert decision.is_t2 is False and decision.reason == "PROVIDER_DISCONNECTED"


def test_entitlement_alone_is_not_t2():
    _transport, _gateway, _manager, service = _stack()
    decision = service.evaluate_t2("AAPL", now=1, feature_at_iso="f")
    assert decision.is_t2 is False and decision.reason == "NOT_REQUESTED"


def test_full_gate_passes_when_confirmed_and_fresh():
    _transport, gateway, manager, service = _stack()
    manager.request_l2("AAPL", now=0)
    _push_book(gateway, "AAPL", seq=1)
    manager.on_book("AAPL", now=1, provider_at="p", received_at="r", sequence_id=1)
    decision = service.evaluate_t2(
        "AAPL", now=1, feature_at_iso="2026-07-28T14:00:01Z"
    )
    assert decision.is_t2 is True and decision.reason == "OK"
    assert decision.freshness_state == "FRESH"
    assert decision.feature["best_bid"] == 100.0
    assert decision.feature["best_ask"] == 100.1
    assert decision.feature["book_imbalance"] == pytest.approx((300 - 100) / 400)


def test_stale_book_is_not_t2():
    _transport, gateway, manager, service = _stack()
    manager.request_l2("AAPL", now=0)
    _push_book(gateway, "AAPL", seq=1)
    manager.on_book("AAPL", now=1, sequence_id=1)
    manager.tick(now=1 + manager.cfg.book_stale_after_ms / 1000.0 + 1)
    decision = service.evaluate_t2("AAPL", now=5, feature_at_iso="f")
    assert decision.is_t2 is False
    assert decision.reason == "STALE_BOOK"
    assert decision.freshness_state == "STALE"


def test_sequence_gap_is_not_t2():
    _transport, _gateway, manager, service = _stack()
    manager.request_l2("AAPL", now=0)
    manager.on_book("AAPL", now=1, sequence_id=10)
    manager.on_book("AAPL", now=2, sequence_id=3)
    decision = service.evaluate_t2("AAPL", now=2, feature_at_iso="f")
    assert decision.is_t2 is False
    assert decision.reason == "SEQUENCE_GAP"
    assert decision.sequence_state == "GAP"


def test_crossed_book_is_not_t2():
    _transport, _gateway, manager, service = _stack()
    manager.request_l2("AAPL", now=0)
    manager.on_book("AAPL", now=1, sequence_id=1, crossed=True)
    decision = service.evaluate_t2("AAPL", now=1, feature_at_iso="f")
    assert decision.is_t2 is False and decision.reason == "CROSSED_BOOK"


def test_l2_momentum_cannot_fire_without_fresh_tape():
    _transport, gateway, manager, service = _stack()
    manager.request_l2("AAPL", now=0, require_tape=True)
    _push_book(gateway, "AAPL", seq=1)
    manager.on_book("AAPL", now=1, sequence_id=1)
    decision = service.evaluate_t2("AAPL", now=1, feature_at_iso="f")
    assert decision.is_t2 is False and decision.reason == "TAPE_REQUIRED_MISSING"
    manager.on_tape("AAPL", now=1)
    gateway.on_tape_push("AAPL", [TapePrint(100.05, 10, "BUY", "p", "r")])
    decision_after_tape = service.evaluate_t2("AAPL", now=1, feature_at_iso="f")
    assert decision_after_tape.is_t2 is True


def test_feature_snapshot_shape_and_no_secret():
    _transport, gateway, manager, service = _stack()
    manager.request_l2("AAPL", now=0)
    _push_book(gateway, "AAPL", seq=7)
    gateway.on_tape_push(
        "AAPL",
        [
            TapePrint(100.05, 10, "BUY", "p", "r"),
            TapePrint(100.0, 5, "SELL", "p", "r"),
        ],
    )
    feature = service.feature_snapshot("AAPL", now=1, feature_at_iso="F")
    for key in (
        "best_bid",
        "best_ask",
        "spread_cents",
        "spread_bps",
        "top_n_bid_depth",
        "top_n_ask_depth",
        "book_imbalance",
        "microprice",
        "weighted_mid",
        "tape_velocity",
        "aggressor_buy_ratio",
        "aggressor_sell_ratio",
        "replenishment",
        "cancellation_pressure",
        "provider_at",
        "received_at",
        "feature_at",
        "sequence_id",
    ):
        assert key in feature
    assert feature["aggressor_buy_ratio"] == pytest.approx(0.5)
    assert feature["sequence_id"] == 7
    assert not any(
        "pwd" in key or "password" in key or "token" in key for key in feature
    )


def test_gateway_singleton_requires_explicit_first_owner_and_reuses_it():
    set_gateway_for_test(None)
    transport = MockTransport()
    first = get_gateway(transport)
    second = get_gateway()
    assert first is second
    with pytest.raises(RuntimeError, match="different transport"):
        get_gateway(MockTransport())
    set_gateway_for_test(None)


def test_bounded_tape_buffer():
    gateway = QuoteGateway(MockTransport(), tape_maxlen=3)
    gateway.on_tape_push(
        "AAPL", [TapePrint(1, 1, "BUY", None, "r") for _ in range(10)]
    )
    assert len(gateway.tape("AAPL")) == 3


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
