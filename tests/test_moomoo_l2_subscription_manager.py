#!/usr/bin/env python3
"""Deterministic L2 subscription-lifecycle + quota-truth tests (mock transport, no live OpenD)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "moomoo"))

from moomoo.quote_gateway import QuoteGateway, MockTransport  # noqa: E402
from moomoo.subscription_manager import (  # noqa: E402
    SubscriptionManager, L2State, SUB_ORDER_BOOK, SUB_TICKER, SUB_QUOTE)
from moomoo.l2_lifecycle_config import load_l2_lifecycle_config  # noqa: E402


def _mgr(transport=None, **cfg_over):
    t = transport or MockTransport()
    gw = QuoteGateway(t)
    cfg = load_l2_lifecycle_config()
    mgr = SubscriptionManager(gw, cfg)
    mgr.refresh_quota("t0")
    return mgr, gw, t


def test_config_units_per_symbol_is_subtype_count():
    cfg = load_l2_lifecycle_config()
    # example ships QUOTE + ORDER_BOOK + TICKER = 3 units per symbol
    assert cfg.units_per_symbol() == len(cfg.subtypes)
    assert SUB_ORDER_BOOK in cfg.subtypes and SUB_TICKER in cfg.subtypes


# ── entitlement / connection gates ───────────────────────────────────────────
def test_provider_down_never_subscribes():
    mgr, gw, t = _mgr(MockTransport(up=False))
    life = mgr.request_l2("AAPL", now=0)
    assert life.state == L2State.PROVIDER_DISCONNECTED
    assert t.subscribe_calls == []          # nothing sent to OpenD

def test_entitlement_missing_blocks_subscribe():
    mgr, gw, t = _mgr(MockTransport(up=True, entitled=False))
    life = mgr.request_l2("AAPL", now=0)
    assert life.state == L2State.ENTITLEMENT_MISSING
    assert t.subscribe_calls == []

def test_entitlement_alone_is_not_subscribed():
    """OpenD up + entitled does NOT by itself mean SUBSCRIBED until request_l2 runs."""
    mgr, gw, t = _mgr()
    assert "AAPL" not in mgr.symbols
    assert mgr.confirmed_subscriptions() == {}


# ── arm intent ≠ subscribed/T2 ───────────────────────────────────────────────
def test_arm_intent_is_not_confirmed_when_quota_deferred():
    # tiny quota so the very first request defers
    mgr, gw, t = _mgr(MockTransport(total_quota=1))
    mgr.refresh_quota("t")
    life = mgr.request_l2("AAPL", now=0, priority="P2")
    assert life.state == L2State.QUOTA_DEFERRED
    assert "required_units=" in (life.error_detail or "")
    assert mgr.confirmed_subscriptions() == {}    # deferred is not confirmed


# ── successful subscribe path ────────────────────────────────────────────────
def test_request_l2_subscribes_and_waits_for_book():
    mgr, gw, t = _mgr()
    life = mgr.request_l2("AAPL", now=0)
    assert life.state == L2State.WAITING_FIRST_BOOK
    assert life.confirmed_subtypes and SUB_ORDER_BOOK in life.confirmed_subtypes
    assert t.subscribe_calls and t.subscribe_calls[0][0] == "AAPL"
    assert life.quota_units == mgr.cfg.units_per_symbol()

def test_quota_units_count_symbol_times_subtype():
    """8 symbols × (QUOTE+ORDER_BOOK+TICKER) units are charged per-subtype, not per-symbol."""
    mgr, gw, t = _mgr(MockTransport(total_quota=200))
    mgr.refresh_quota("t")
    per = mgr.cfg.units_per_symbol()
    for i in range(mgr.cfg.max_concurrent_l2_symbols):
        mgr.request_l2(f"SY{i}", now=0)
    mgr.refresh_quota("t2")
    # own usage = symbols × subtypes (e.g. 8 × 3 = 24), never just 8
    assert mgr.ledger.own_used == mgr.cfg.max_concurrent_l2_symbols * per
    assert mgr.ledger.own_used > mgr.cfg.max_concurrent_l2_symbols


def test_symbol_cap_defers_not_evicts():
    mgr, gw, t = _mgr(MockTransport(total_quota=999))
    mgr.refresh_quota("t")
    for i in range(mgr.cfg.max_concurrent_l2_symbols):
        assert mgr.request_l2(f"S{i}", now=0).state == L2State.WAITING_FIRST_BOOK
    over = mgr.request_l2("EXTRA", now=0)
    assert over.state == L2State.QUOTA_DEFERRED and over.error_code == "SYMBOL_CAP"
    # existing subscriptions are NOT evicted
    assert mgr._concurrent_symbols() == mgr.cfg.max_concurrent_l2_symbols


def test_insufficient_quota_reports_exact_numbers():
    # reserved carve-out makes discretionary room small; a P2 request should defer with detail
    t = MockTransport(total_quota=10)   # remain 10, reserved 20 → available 0
    mgr, gw, _t = _mgr(t)
    mgr.refresh_quota("t")
    life = mgr.request_l2("AAPL", now=0, priority="P2")
    assert life.state == L2State.QUOTA_DEFERRED
    assert "available_units=" in life.error_detail and "required_units=" in life.error_detail


def test_p0_bypasses_reserved_carveout():
    t = MockTransport(total_quota=10)
    mgr, gw, _t = _mgr(t)
    mgr.refresh_quota("t")
    life = mgr.mark_operator_selected("AAPL", now=0)
    assert life.state == L2State.WAITING_FIRST_BOOK   # P0 (operator/fire/open pos) not deferred


# ── book/tape ingest → FRESH ─────────────────────────────────────────────────
def _feed_book(gw, sym, seq=1):
    from moomoo.quote_gateway import BookSnapshot
    gw.on_book_push(BookSnapshot(sym, [(100.0, 200)], [(100.1, 100)], "p", "r", sequence_id=seq))

def test_book_makes_it_fresh():
    mgr, gw, t = _mgr()
    mgr.request_l2("AAPL", now=0)
    _feed_book(gw, "AAPL")
    mgr.on_book("AAPL", now=1, provider_at="p", received_at="r", sequence_id=1)
    assert mgr.symbols["AAPL"].state == L2State.FRESH

def test_tape_required_waits_without_tape():
    mgr, gw, t = _mgr()
    mgr.request_l2("AAPL", now=0, require_tape=True)
    mgr.on_book("AAPL", now=1, sequence_id=1)
    assert mgr.symbols["AAPL"].state == L2State.WAITING_FIRST_TAPE
    mgr.on_tape("AAPL", now=1)
    assert mgr.symbols["AAPL"].state == L2State.FRESH

def test_stale_transition_on_tick():
    mgr, gw, t = _mgr()
    mgr.request_l2("AAPL", now=0)
    mgr.on_book("AAPL", now=1, sequence_id=1)
    assert mgr.symbols["AAPL"].state == L2State.FRESH
    mgr.tick(now=1 + (mgr.cfg.book_stale_after_ms / 1000.0) + 1)
    assert mgr.symbols["AAPL"].state == L2State.STALE

def test_sequence_gap_blocks():
    mgr, gw, t = _mgr()
    mgr.request_l2("AAPL", now=0)
    mgr.on_book("AAPL", now=1, sequence_id=10)
    mgr.on_book("AAPL", now=2, sequence_id=5)   # regressed → gap
    assert mgr.symbols["AAPL"].state == L2State.SEQUENCE_GAP

def test_crossed_book_blocks():
    mgr, gw, t = _mgr()
    mgr.request_l2("AAPL", now=0)
    mgr.on_book("AAPL", now=1, sequence_id=1, crossed=True)
    assert mgr.symbols["AAPL"].state == L2State.CROSSED_BOOK


# ── dwell + release ──────────────────────────────────────────────────────────
def test_min_dwell_respected_before_unsubscribe():
    mgr, gw, t = _mgr()
    mgr.request_l2("AAPL", now=0)
    mgr.on_book("AAPL", now=1, sequence_id=1)
    mgr.release("AAPL", now=5)                 # < 60s dwell
    assert mgr.symbols["AAPL"].state == L2State.UNSUBSCRIBE_PENDING
    assert t.unsubscribe_calls == []           # NOT yet unsubscribed
    mgr.tick(now=mgr.cfg.min_subscription_dwell_seconds + 1)
    assert mgr.symbols["AAPL"].state == L2State.UNSUBSCRIBED
    assert t.unsubscribe_calls and t.unsubscribe_calls[0][0] == "AAPL"

def test_release_after_dwell_unsubscribes_immediately():
    mgr, gw, t = _mgr()
    mgr.request_l2("AAPL", now=0)
    mgr.release("AAPL", now=mgr.cfg.min_subscription_dwell_seconds + 5)
    assert mgr.symbols["AAPL"].state == L2State.UNSUBSCRIBED
    assert t.unsubscribe_calls


# ── post-fire retention ──────────────────────────────────────────────────────
def test_post_fire_retention_then_expiry_releases():
    mgr, gw, t = _mgr()
    mgr.request_l2("AAPL", now=0)
    mgr.on_book("AAPL", now=1, sequence_id=1)
    mgr.enter_post_fire_retention("AAPL", now=100)
    assert mgr.symbols["AAPL"].state == L2State.POST_FIRE_RETENTION
    # after retention window AND past dwell → released
    mgr.tick(now=100 + mgr.cfg.default_post_fire_retention_seconds + 1)
    assert mgr.symbols["AAPL"].state in (L2State.UNSUBSCRIBED, L2State.UNSUBSCRIBE_PENDING)


# ── reconnect restores without duplication ───────────────────────────────────
def test_reconnect_restores_subscriptions_no_duplicate():
    mgr, gw, t = _mgr()
    mgr.request_l2("AAPL", now=0)
    mgr.request_l2("TSLA", now=0)
    n_before = len(t.subscribe_calls)
    restored = mgr.on_reconnect(now=200)
    assert set(restored) == {"AAPL", "TSLA"}
    assert mgr.reconnect_epoch == 1
    # each symbol re-subscribed exactly once more (no duplicate rows / double add)
    assert len(t.subscribe_calls) == n_before + 2
    for sym in ("AAPL", "TSLA"):
        assert mgr.symbols[sym].reconnect_epoch == 1
        assert mgr.symbols[sym].first_book_at is None   # stream state reset for new epoch

def test_reconnect_lower_sequence_is_not_a_gap():
    mgr, gw, t = _mgr()
    mgr.request_l2("AAPL", now=0)
    mgr.on_book("AAPL", now=1, sequence_id=100)
    mgr.on_reconnect(now=200)
    mgr.on_book("AAPL", now=201, sequence_id=1)   # new epoch, low seq is legit
    assert mgr.symbols["AAPL"].state == L2State.FRESH


# ── restore-from-state is intent only ────────────────────────────────────────
def test_restore_from_state_is_intent_not_connected():
    mgr, gw, t = _mgr()
    mgr.restore_desired_from_state(["AAPL", "TSLA"])
    for s in ("AAPL", "TSLA"):
        assert mgr.symbols[s].state == L2State.ARM_INTENT   # NOT subscribed/fresh
    assert mgr.confirmed_subscriptions() == {}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
