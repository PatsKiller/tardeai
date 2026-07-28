#!/usr/bin/env python3
"""T2 admission gate + feature snapshot + single-owner gateway tests (mock transport)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "moomoo"))

from moomoo.quote_gateway import (  # noqa: E402
    QuoteGateway, MockTransport, BookSnapshot, TapePrint, get_gateway, set_gateway_for_test)
from moomoo.subscription_manager import SubscriptionManager, L2State  # noqa: E402
from moomoo.l2_feature_service import L2FeatureService  # noqa: E402
from moomoo.l2_lifecycle_config import load_l2_lifecycle_config  # noqa: E402


def _stack(transport=None):
    t = transport or MockTransport()
    gw = QuoteGateway(t)
    mgr = SubscriptionManager(gw, load_l2_lifecycle_config())
    mgr.refresh_quota("t")
    svc = L2FeatureService(gw, mgr)
    return t, gw, mgr, svc


def _push_book(gw, sym, seq=1, crossed=False):
    bids = [(100.0, 200), (99.95, 100)]
    asks = [(99.9, 50)] if crossed else [(100.1, 80), (100.2, 20)]
    gw.on_book_push(BookSnapshot(sym, bids, asks, "2026-07-28T14:00:00Z", "2026-07-28T14:00:00Z", seq))


# ── the gate ─────────────────────────────────────────────────────────────────
def test_t2_requires_fresh_book_not_just_arm():
    t, gw, mgr, svc = _stack()
    mgr.request_l2("AAPL", now=0)                 # subscribed, WAITING_FIRST_BOOK
    d = svc.evaluate_t2("AAPL", now=1, feature_at_iso="f")
    assert d.is_t2 is False and d.reason == "WAITING_FIRST_DATA"

def test_provider_down_is_not_t2_even_with_book():
    t, gw, mgr, svc = _stack(MockTransport(up=False))
    _push_book(gw, "AAPL")
    d = svc.evaluate_t2("AAPL", now=1, feature_at_iso="f")
    assert d.is_t2 is False and d.reason == "PROVIDER_DISCONNECTED"

def test_entitlement_alone_is_not_t2():
    t, gw, mgr, svc = _stack(MockTransport(up=True, entitled=True))
    # entitled + up, but never requested/subscribed
    d = svc.evaluate_t2("AAPL", now=1, feature_at_iso="f")
    assert d.is_t2 is False and d.reason == "NOT_REQUESTED"

def test_full_gate_passes_when_confirmed_and_fresh():
    t, gw, mgr, svc = _stack()
    mgr.request_l2("AAPL", now=0)
    _push_book(gw, "AAPL", seq=1)
    mgr.on_book("AAPL", now=1, provider_at="p", received_at="r", sequence_id=1)
    d = svc.evaluate_t2("AAPL", now=1, feature_at_iso="2026-07-28T14:00:01Z")
    assert d.is_t2 is True and d.reason == "OK" and d.freshness_state == "FRESH"
    assert d.feature["best_bid"] == 100.0 and d.feature["best_ask"] == 100.1
    assert d.feature["book_imbalance"] == pytest.approx((300 - 100) / 400)

def test_stale_book_is_not_t2():
    t, gw, mgr, svc = _stack()
    mgr.request_l2("AAPL", now=0)
    _push_book(gw, "AAPL", seq=1)
    mgr.on_book("AAPL", now=1, sequence_id=1)
    mgr.tick(now=1 + mgr.cfg.book_stale_after_ms / 1000.0 + 1)   # → STALE
    d = svc.evaluate_t2("AAPL", now=5, feature_at_iso="f")
    assert d.is_t2 is False and d.reason == "STALE_BOOK" and d.freshness_state == "STALE"

def test_sequence_gap_is_not_t2():
    t, gw, mgr, svc = _stack()
    mgr.request_l2("AAPL", now=0)
    mgr.on_book("AAPL", now=1, sequence_id=10)
    mgr.on_book("AAPL", now=2, sequence_id=3)
    d = svc.evaluate_t2("AAPL", now=2, feature_at_iso="f")
    assert d.is_t2 is False and d.reason == "SEQUENCE_GAP" and d.sequence_state == "GAP"

def test_crossed_book_is_not_t2():
    t, gw, mgr, svc = _stack()
    mgr.request_l2("AAPL", now=0)
    mgr.on_book("AAPL", now=1, sequence_id=1, crossed=True)
    d = svc.evaluate_t2("AAPL", now=1, feature_at_iso="f")
    assert d.is_t2 is False and d.reason == "CROSSED_BOOK"

def test_l2_momentum_cannot_fire_without_fresh_tape():
    """require_tape=True → fresh book alone is NOT T2 until tape arrives (L2_MOMENTUM rule)."""
    t, gw, mgr, svc = _stack()
    mgr.request_l2("AAPL", now=0, require_tape=True)
    _push_book(gw, "AAPL", seq=1)
    mgr.on_book("AAPL", now=1, sequence_id=1)
    d = svc.evaluate_t2("AAPL", now=1, feature_at_iso="f")
    assert d.is_t2 is False and d.reason in ("WAITING_FIRST_DATA", "TAPE_REQUIRED_MISSING")
    mgr.on_tape("AAPL", now=1)
    gw.on_tape_push("AAPL", [TapePrint(100.05, 10, "BUY", "p", "r")])
    d2 = svc.evaluate_t2("AAPL", now=1, feature_at_iso="f")
    assert d2.is_t2 is True

def test_feature_snapshot_shape_and_no_secret():
    t, gw, mgr, svc = _stack()
    mgr.request_l2("AAPL", now=0)
    _push_book(gw, "AAPL", seq=7)
    gw.on_tape_push("AAPL", [TapePrint(100.05, 10, "BUY", "p", "r"),
                             TapePrint(100.0, 5, "SELL", "p", "r")])
    feat = svc.feature_snapshot("AAPL", now=1, feature_at_iso="F")
    for k in ("best_bid", "best_ask", "spread_cents", "spread_bps", "top_n_bid_depth",
              "top_n_ask_depth", "book_imbalance", "microprice", "weighted_mid",
              "tape_velocity", "aggressor_buy_ratio", "aggressor_sell_ratio",
              "replenishment", "cancellation_pressure", "provider_at", "received_at",
              "feature_at", "sequence_id"):
        assert k in feat
    assert feat["aggressor_buy_ratio"] == pytest.approx(0.5)
    assert feat["sequence_id"] == 7
    # nothing credential-like
    assert not any("pwd" in k or "password" in k or "token" in k for k in feat)


# ── single-owner gateway ─────────────────────────────────────────────────────
def test_gateway_singleton_returns_same_instance():
    set_gateway_for_test(None)
    g1 = get_gateway(MockTransport())
    g2 = get_gateway(MockTransport())      # second call ignores new transport
    assert g1 is g2
    set_gateway_for_test(None)

def test_bounded_tape_buffer():
    gw = QuoteGateway(MockTransport(), tape_maxlen=3)
    gw.on_tape_push("AAPL", [TapePrint(1, 1, "BUY", None, "r") for _ in range(10)])
    assert len(gw.tape("AAPL")) == 3      # bounded, not unbounded growth


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
