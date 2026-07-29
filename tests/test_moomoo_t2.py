#!/usr/bin/env python3
"""Moomoo/T2 tests — order-book metrics + conserving arm intent + fail-closed defaults."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "market_observations"))

import scalp_t2_metrics as t2  # noqa: E402
from moomoo_t2 import ArmedSubscriptionManager, MoomooT2Provider, default_provider  # noqa: E402
from observation import ObservationType, EntitlementState as ES, DataTier  # noqa: E402


BIDS = [(100.0, 200), (99.95, 100)]
ASKS = [(100.10, 80), (100.20, 20)]


def test_book_imbalance():
    assert t2.book_imbalance(BIDS, ASKS, levels=5) == pytest.approx((300 - 100) / 400)


def test_book_imbalance_empty_none():
    assert t2.book_imbalance([], [], 5) is None


def test_quoted_spread_bps():
    assert t2.quoted_spread_bps(99.95, 100.05) == pytest.approx(1e4 * 0.1 / 100.0)


def test_microprice_leans_to_thin_side():
    assert t2.microprice(100.0, 100.1, 100, 300) == pytest.approx(100.025)


def test_depth_within():
    bid, ask = t2.depth_within(BIDS, ASKS, mid=100.05, pct=0.005)
    assert bid == 300 and ask == 100


def test_book_summary_shape():
    summary = t2.book_summary(BIDS, ASKS)
    assert summary["book_imbalance"] == pytest.approx(0.5)
    assert summary["best_bid"] == 100.0 and summary["best_ask"] == 100.10


def test_arm_disarm_and_is_armed():
    manager = ArmedSubscriptionManager(max_armed=4, ttl_seconds=120)
    assert manager.arm("AAPL", now=0) is True
    assert manager.is_armed("aapl", now=10) is True
    manager.disarm("AAPL")
    assert manager.is_armed("AAPL", now=11) is False


def test_budget_is_hard_and_never_evicts():
    manager = ArmedSubscriptionManager(max_armed=2, ttl_seconds=120)
    assert manager.arm("A", 0) and manager.arm("B", 0)
    assert manager.arm("C", 0) is False
    assert manager.rejected_budget == 1
    assert set(manager.armed_symbols(0)) == {"A", "B"}
    manager.disarm("A")
    assert manager.arm("C", 0) is True


def test_ttl_auto_disarms():
    manager = ArmedSubscriptionManager(max_armed=4, ttl_seconds=60)
    manager.arm("X", now=0)
    assert manager.is_armed("X", now=59) is True
    assert manager.is_armed("X", now=61) is False


def test_arm_refreshes_ttl():
    manager = ArmedSubscriptionManager(max_armed=4, ttl_seconds=60)
    manager.arm("X", now=0)
    manager.arm("X", now=50)
    assert manager.is_armed("X", now=100) is True


def test_budget_used():
    manager = ArmedSubscriptionManager(max_armed=3)
    manager.arm("A", 0)
    manager.arm("B", 0)
    assert manager.budget_used(0) == (2, 3)


class FakeClient:
    def __init__(self, up):
        self._up = up

    @property
    def opend_up(self):
        return self._up


def _book():
    return {"bids": BIDS, "asks": ASKS, "ts": "2026-07-27T20:00:00Z", "seq": 42}


def test_entitlement_scaffold_when_opend_down():
    provider = MoomooT2Provider(client=FakeClient(up=False), book_fetcher=lambda _s: _book())
    assert provider.entitlement() == ES.SCAFFOLD_ONLY


def test_entitlement_scaffold_when_no_fetcher():
    provider = MoomooT2Provider(client=FakeClient(up=True), book_fetcher=None)
    assert provider.entitlement() == ES.SCAFFOLD_ONLY


def test_entitlement_realtime_only_when_up_and_fetcher():
    provider = MoomooT2Provider(client=FakeClient(up=True), book_fetcher=lambda _s: _book())
    assert provider.entitlement() == ES.AVAILABLE_REALTIME


def test_fetch_book_none_when_not_armed_conserves_budget():
    provider = MoomooT2Provider(client=FakeClient(up=True), book_fetcher=lambda _s: _book())
    assert provider.fetch_book("AAPL", now=0, now_iso="t") is None


def test_fetch_book_none_when_opend_down_even_if_armed():
    provider = MoomooT2Provider(client=FakeClient(up=False), book_fetcher=lambda _s: _book())
    provider.arm("AAPL", now=0)
    assert provider.fetch_book("AAPL", now=0, now_iso="t") is None


def test_fetch_book_returns_t2_observation_when_explicitly_injected():
    provider = MoomooT2Provider(client=FakeClient(up=True), book_fetcher=lambda _s: _book())
    provider.arm("AAPL", now=0)
    observation = provider.fetch_book("AAPL", now=1, now_iso="2026-07-27T20:00:01Z")
    assert observation is not None
    assert observation.observation_type == ObservationType.ORDER_BOOK
    assert observation.data_tier == DataTier.T2
    assert observation.source_system == "moomoo" and observation.sequence_id == 42
    assert observation.payload_ref["book_imbalance"] == pytest.approx(0.5)


def test_default_provider_is_always_scaffold_only():
    """A legacy cron caller may not create a second production OpenD context."""
    assert default_provider(live=False).entitlement() == ES.SCAFFOLD_ONLY
    assert default_provider(live=True).entitlement() == ES.SCAFFOLD_ONLY


from moomoo_t2 import sync_arm_from_states  # noqa: E402


def test_sync_arms_only_armed_symbols():
    provider = MoomooT2Provider(client=FakeClient(up=False))
    result = sync_arm_from_states(
        provider, {"A": "ARMED", "B": "IDLE", "C": "ARMED", "D": "PULLBACK"}, now=0
    )
    assert result["armed"] == ["A", "C"]
    assert provider.manager.is_armed("A", 0) and not provider.manager.is_armed("B", 0)


def test_sync_disarms_when_leaving_armed():
    provider = MoomooT2Provider(client=FakeClient(up=False))
    sync_arm_from_states(provider, {"A": "ARMED"}, now=0)
    result = sync_arm_from_states(provider, {"A": "TRIGGERED", "B": "ARMED"}, now=1)
    assert "A" in result["disarmed"] and result["armed"] == ["B"]
    assert not provider.manager.is_armed("A", 1)


def test_sync_respects_budget():
    provider = MoomooT2Provider(
        client=FakeClient(up=False), manager=ArmedSubscriptionManager(max_armed=2)
    )
    result = sync_arm_from_states(provider, {"A": "ARMED", "B": "ARMED", "C": "ARMED"}, now=0)
    assert len(result["armed"]) == 2 and len(result["skipped_budget"]) == 1


def test_state_persistence_round_trip():
    manager = ArmedSubscriptionManager(max_armed=4, ttl_seconds=180)
    manager.arm("AAPL", now=100)
    state = manager.to_state(now=101)
    restored = ArmedSubscriptionManager(max_armed=4, ttl_seconds=180)
    restored.load_state(state)
    assert restored.is_armed("AAPL", now=150) is True
    assert restored.is_armed("AAPL", now=9999) is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
