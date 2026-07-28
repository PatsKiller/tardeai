#!/usr/bin/env python3
"""Deterministic subscription lifecycle and fail-closed quota tests."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "moomoo"))

from moomoo.quote_gateway import QuoteGateway, MockTransport  # noqa: E402
from moomoo.subscription_manager import (  # noqa: E402
    L2State,
    SUB_ORDER_BOOK,
    SUB_QUOTE,
    SUB_TICKER,
    SubscriptionManager,
)
from moomoo.l2_lifecycle_config import load_l2_lifecycle_config  # noqa: E402


def _manager(transport=None):
    selected = transport or MockTransport()
    gateway = QuoteGateway(selected)
    manager = SubscriptionManager(gateway, load_l2_lifecycle_config())
    manager.refresh_quota("t0")
    return manager, gateway, selected


def test_config_units_per_symbol_is_subtype_count():
    config = load_l2_lifecycle_config()
    assert config.units_per_symbol() == len(config.subtypes)
    assert {SUB_QUOTE, SUB_ORDER_BOOK, SUB_TICKER} <= set(config.subtypes)


def test_provider_down_never_subscribes():
    manager, _gateway, transport = _manager(MockTransport(up=False))
    lifecycle = manager.request_l2("AAPL", now=0)
    assert lifecycle.state == L2State.PROVIDER_DISCONNECTED
    assert transport.subscribe_calls == []


def test_entitlement_missing_blocks_subscribe():
    manager, _gateway, transport = _manager(MockTransport(up=True, entitled=False))
    lifecycle = manager.request_l2("AAPL", now=0)
    assert lifecycle.state == L2State.ENTITLEMENT_MISSING
    assert transport.subscribe_calls == []


def test_entitlement_alone_is_not_subscribed():
    manager, _gateway, _transport = _manager()
    assert "AAPL" not in manager.symbols
    assert manager.confirmed_subscriptions() == {}


def test_unknown_quota_blocks_every_priority():
    transport = MockTransport()
    transport.fail_quota_query = True
    manager, _gateway, transport = _manager(transport)
    assert manager.ledger.remain is None
    ordinary = manager.request_l2("AAPL", now=0, priority="P2")
    critical = manager.request_l2("MSFT", now=0, priority="P0")
    assert ordinary.state == L2State.QUOTA_DEFERRED
    assert critical.state == L2State.QUOTA_DEFERRED
    assert ordinary.error_code == critical.error_code == "QUOTA_UNKNOWN"
    assert transport.subscribe_calls == []


def test_reserved_capacity_blocks_discretionary_request():
    manager, _gateway, transport = _manager(MockTransport(total_quota=10))
    lifecycle = manager.request_l2("AAPL", now=0, priority="P2")
    assert lifecycle.state == L2State.QUOTA_DEFERRED
    assert "required_units=" in lifecycle.error_detail
    assert transport.subscribe_calls == []


def test_p0_may_use_reserved_capacity_but_not_hard_quota():
    manager, _gateway, transport = _manager(MockTransport(total_quota=10))
    lifecycle = manager.mark_operator_selected("AAPL", now=0)
    assert lifecycle.state == L2State.WAITING_FIRST_BOOK
    assert transport.subscribe_calls

    too_small, _gateway2, blocked_transport = _manager(MockTransport(total_quota=2))
    blocked = too_small.mark_operator_selected("MSFT", now=0)
    assert blocked.state == L2State.QUOTA_DEFERRED
    assert blocked.error_code == "QUOTA_DEFERRED"
    assert blocked_transport.subscribe_calls == []


def test_subscribe_acceptance_is_not_data_confirmation():
    manager, _gateway, transport = _manager()
    before_remain = manager.ledger.remain
    lifecycle = manager.request_l2("AAPL", now=0)
    assert lifecycle.state == L2State.WAITING_FIRST_BOOK
    assert lifecycle.requested_subtypes
    assert lifecycle.confirmed_subtypes == ()
    assert manager.confirmed_subscriptions() == {}
    assert transport.subscribe_calls[0][0] == "AAPL"
    assert manager.ledger.remain == before_remain - manager.cfg.units_per_symbol()


def test_book_tape_and_quote_confirm_their_own_subtypes():
    manager, _gateway, _transport = _manager()
    manager.request_l2("AAPL", now=0, require_tape=True)
    manager.on_book("AAPL", now=1, sequence_id=1)
    lifecycle = manager.symbols["AAPL"]
    assert lifecycle.state == L2State.WAITING_FIRST_TAPE
    assert lifecycle.confirmed_subtypes == (SUB_ORDER_BOOK,)

    manager.on_tape("AAPL", now=2)
    assert lifecycle.state == L2State.FRESH
    assert set(lifecycle.confirmed_subtypes) == {SUB_ORDER_BOOK, SUB_TICKER}

    manager.on_quote("AAPL", now=3)
    assert set(lifecycle.confirmed_subtypes) == {SUB_ORDER_BOOK, SUB_QUOTE, SUB_TICKER}


def test_quota_units_are_symbol_times_subtype():
    manager, _gateway, _transport = _manager(MockTransport(total_quota=200))
    units = manager.cfg.units_per_symbol()
    for index in range(manager.cfg.max_concurrent_l2_symbols):
        assert manager.request_l2(f"SY{index}", now=0).state == L2State.WAITING_FIRST_BOOK
    assert manager.ledger.own_used == manager.cfg.max_concurrent_l2_symbols * units
    assert manager.ledger.own_used > manager.cfg.max_concurrent_l2_symbols


def test_symbol_cap_defers_without_eviction():
    manager, _gateway, _transport = _manager(MockTransport(total_quota=999))
    for index in range(manager.cfg.max_concurrent_l2_symbols):
        assert manager.request_l2(f"S{index}", now=0).state == L2State.WAITING_FIRST_BOOK
    over = manager.request_l2("EXTRA", now=0)
    assert over.state == L2State.QUOTA_DEFERRED
    assert over.error_code == "SYMBOL_CAP"
    assert manager._concurrent_symbols() == manager.cfg.max_concurrent_l2_symbols


def test_book_makes_non_tape_request_fresh():
    manager, _gateway, _transport = _manager()
    manager.request_l2("AAPL", now=0)
    manager.on_book("AAPL", now=1, sequence_id=1)
    assert manager.symbols["AAPL"].state == L2State.FRESH
    assert manager.is_confirmed_fresh("AAPL") is True


def test_stale_transition_on_tick():
    manager, _gateway, _transport = _manager()
    manager.request_l2("AAPL", now=0)
    manager.on_book("AAPL", now=1, sequence_id=1)
    manager.tick(now=1 + manager.cfg.book_stale_after_ms / 1000.0 + 1)
    assert manager.symbols["AAPL"].state == L2State.STALE


def test_sequence_regression_blocks():
    manager, _gateway, _transport = _manager()
    manager.request_l2("AAPL", now=0)
    manager.on_book("AAPL", now=1, sequence_id=10)
    manager.on_book("AAPL", now=2, sequence_id=5)
    assert manager.symbols["AAPL"].state == L2State.SEQUENCE_GAP


def test_crossed_book_blocks():
    manager, _gateway, _transport = _manager()
    manager.request_l2("AAPL", now=0)
    manager.on_book("AAPL", now=1, sequence_id=1, crossed=True)
    assert manager.symbols["AAPL"].state == L2State.CROSSED_BOOK


def test_minimum_dwell_delays_unsubscribe():
    manager, _gateway, transport = _manager()
    manager.request_l2("AAPL", now=0)
    manager.on_book("AAPL", now=1, sequence_id=1)
    manager.release("AAPL", now=5)
    assert manager.symbols["AAPL"].state == L2State.UNSUBSCRIBE_PENDING
    assert transport.unsubscribe_calls == []
    manager.tick(now=manager.cfg.min_subscription_dwell_seconds + 1)
    assert manager.symbols["AAPL"].state == L2State.UNSUBSCRIBED
    assert transport.unsubscribe_calls


def test_unsubscribe_failure_retains_quota_and_pending_state():
    manager, _gateway, transport = _manager()
    lifecycle = manager.request_l2("AAPL", now=0)
    units = lifecycle.quota_units
    remaining = manager.ledger.remain
    transport.fail_next_unsubscribe = True
    manager.release("AAPL", now=manager.cfg.min_subscription_dwell_seconds + 1)
    assert lifecycle.state == L2State.UNSUBSCRIBE_PENDING
    assert lifecycle.error_code == "UNSUBSCRIBE_FAILED"
    assert lifecycle.quota_units == units
    assert manager.ledger.remain == remaining

    manager.tick(now=manager.cfg.min_subscription_dwell_seconds + 2)
    assert lifecycle.state == L2State.UNSUBSCRIBED
    assert lifecycle.quota_units == 0
    assert manager.ledger.remain == remaining + units


def test_post_fire_retention_then_release():
    manager, _gateway, _transport = _manager()
    manager.request_l2("AAPL", now=0)
    manager.on_book("AAPL", now=1, sequence_id=1)
    manager.enter_post_fire_retention("AAPL", now=100)
    assert manager.symbols["AAPL"].state == L2State.POST_FIRE_RETENTION
    manager.tick(now=100 + manager.cfg.default_post_fire_retention_seconds + 1)
    assert manager.symbols["AAPL"].state in {
        L2State.UNSUBSCRIBED,
        L2State.UNSUBSCRIBE_PENDING,
    }


def test_reconnect_resets_confirmation_and_sequence():
    manager, _gateway, transport = _manager()
    manager.request_l2("AAPL", now=0)
    manager.on_book("AAPL", now=1, sequence_id=100)
    before = len(transport.subscribe_calls)
    restored = manager.on_reconnect(now=200)
    assert restored == ["AAPL"]
    assert len(transport.subscribe_calls) == before + 1
    lifecycle = manager.symbols["AAPL"]
    assert lifecycle.reconnect_epoch == 1
    assert lifecycle.sequence_id is None
    assert lifecycle.confirmed_subtypes == ()
    manager.on_book("AAPL", now=201, sequence_id=1)
    assert lifecycle.state == L2State.FRESH


def test_restore_state_is_intent_only():
    manager, _gateway, _transport = _manager()
    manager.restore_desired_from_state(["AAPL", "TSLA"])
    assert all(manager.symbols[symbol].state == L2State.ARM_INTENT for symbol in ("AAPL", "TSLA"))
    assert manager.confirmed_subscriptions() == {}
