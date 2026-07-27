#!/usr/bin/env python3
"""Moomoo/T2 tests — order-book metrics (hand-computed) + conserving arm-on-demand + fail-closed."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "market_observations"))

import scalp_t2_metrics as t2                                   # noqa: E402
from moomoo_t2 import (ArmedSubscriptionManager, MoomooT2Provider, default_provider)  # noqa: E402
from observation import ObservationType, EntitlementState as ES, DataTier  # noqa: E402


# ── T2 book metrics (hand-computed) ─────────────────────────────────
BIDS = [(100.0, 200), (99.95, 100)]      # top sizes 300
ASKS = [(100.10, 80), (100.20, 20)]      # top sizes 100

def test_book_imbalance():
    assert t2.book_imbalance(BIDS, ASKS, levels=5) == pytest.approx((300 - 100) / 400)  # 0.5

def test_book_imbalance_empty_none():
    assert t2.book_imbalance([], [], 5) is None

def test_quoted_spread_bps():
    assert t2.quoted_spread_bps(99.95, 100.05) == pytest.approx(1e4 * 0.1 / 100.0)   # 10 bps

def test_microprice_leans_to_thin_side():
    # bid 100 (size 100), ask 100.1 (size 300) → (100.1*100 + 100*300)/400 = 100.025
    assert t2.microprice(100.0, 100.1, 100, 300) == pytest.approx(100.025)

def test_depth_within():
    b, a = t2.depth_within(BIDS, ASKS, mid=100.05, pct=0.005)
    assert b == 300 and a == 100         # all levels within 0.5% here

def test_book_summary_shape():
    s = t2.book_summary(BIDS, ASKS)
    assert s["book_imbalance"] == pytest.approx(0.5) and s["best_bid"] == 100.0 and s["best_ask"] == 100.10


# ── conserving arm-on-demand manager ────────────────────────────────
def test_arm_disarm_and_is_armed():
    m = ArmedSubscriptionManager(max_armed=4, ttl_seconds=120)
    assert m.arm("AAPL", now=0) is True
    assert m.is_armed("aapl", now=10) is True
    m.disarm("AAPL")
    assert m.is_armed("AAPL", now=11) is False

def test_budget_is_hard_and_never_evicts():
    m = ArmedSubscriptionManager(max_armed=2, ttl_seconds=120)
    assert m.arm("A", 0) and m.arm("B", 0)
    assert m.arm("C", 0) is False               # budget full → refused, NOT evicted
    assert m.rejected_budget == 1
    assert set(m.armed_symbols(0)) == {"A", "B"}   # A/B still armed
    m.disarm("A")
    assert m.arm("C", 0) is True                 # room now

def test_ttl_auto_disarms():
    m = ArmedSubscriptionManager(max_armed=4, ttl_seconds=60)
    m.arm("X", now=0)
    assert m.is_armed("X", now=59) is True
    assert m.is_armed("X", now=61) is False      # expired → auto-disarmed

def test_arm_refreshes_ttl():
    m = ArmedSubscriptionManager(max_armed=4, ttl_seconds=60)
    m.arm("X", now=0)
    m.arm("X", now=50)                            # refresh
    assert m.is_armed("X", now=100) is True       # 50+60 > 100

def test_budget_used():
    m = ArmedSubscriptionManager(max_armed=3)
    m.arm("A", 0); m.arm("B", 0)
    assert m.budget_used(0) == (2, 3)


# ── provider: fail-closed + conserving ──────────────────────────────
class FakeClient:
    def __init__(self, up): self._up = up
    @property
    def opend_up(self): return self._up

def _book(): return {"bids": BIDS, "asks": ASKS, "ts": "2026-07-27T20:00:00Z", "seq": 42}

def test_entitlement_scaffold_when_opend_down():
    p = MoomooT2Provider(client=FakeClient(up=False), book_fetcher=lambda s: _book())
    assert p.entitlement() == ES.SCAFFOLD_ONLY

def test_entitlement_scaffold_when_no_fetcher():
    p = MoomooT2Provider(client=FakeClient(up=True), book_fetcher=None)
    assert p.entitlement() == ES.SCAFFOLD_ONLY

def test_entitlement_realtime_only_when_up_and_fetcher():
    p = MoomooT2Provider(client=FakeClient(up=True), book_fetcher=lambda s: _book())
    assert p.entitlement() == ES.AVAILABLE_REALTIME

def test_fetch_book_none_when_not_armed_conserves_budget():
    p = MoomooT2Provider(client=FakeClient(up=True), book_fetcher=lambda s: _book())
    assert p.fetch_book("AAPL", now=0, now_iso="t") is None      # not armed → no fetch (conserve)

def test_fetch_book_none_when_opend_down_even_if_armed():
    p = MoomooT2Provider(client=FakeClient(up=False), book_fetcher=lambda s: _book())
    p.arm("AAPL", now=0)
    assert p.fetch_book("AAPL", now=0, now_iso="t") is None      # fail-closed

def test_fetch_book_returns_t2_observation_when_armed_up_and_wired():
    p = MoomooT2Provider(client=FakeClient(up=True), book_fetcher=lambda s: _book())
    p.arm("AAPL", now=0)
    obs = p.fetch_book("AAPL", now=1, now_iso="2026-07-27T20:00:01Z")
    assert obs is not None
    assert obs.observation_type == ObservationType.ORDER_BOOK and obs.data_tier == DataTier.T2
    assert obs.source_system == "moomoo" and obs.sequence_id == 42
    assert obs.payload_ref["book_imbalance"] == pytest.approx(0.5)

def test_default_provider_is_scaffold_on_this_host():
    # OpenD not configured on ms01 → real provider resolves to SCAFFOLD_ONLY (no manufactured T2)
    assert default_provider().entitlement() == ES.SCAFFOLD_ONLY


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
