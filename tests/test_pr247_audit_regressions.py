#!/usr/bin/env python3
"""Independent audit regressions for PR #247's truth and ownership boundaries."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "moomoo"))
sys.path.insert(0, str(ROOT / "scripts" / "market_observations"))


def test_production_request_path_does_not_construct_opend_runtime():
    from active_trader import l2_runtime

    l2_runtime.reset_for_test()
    assert l2_runtime.get_runtime() is None
    posture = l2_runtime.runtime_posture()
    assert posture["mode"] == "DISABLED_PENDING_DEDICATED_GATEWAY"
    assert posture["owner_ready"] is False and posture["connected"] is False


def test_legacy_scalp_provider_cannot_open_second_context():
    from moomoo_t2 import default_provider

    assert default_provider(live=True).entitlement().value == "SCAFFOLD_ONLY"
    source = (ROOT / "scripts" / "market_observations" / "moomoo_t2.py").read_text()
    assert "OpenQuoteContext(" not in source
    assert "FutuTransport(" not in source


def test_unsequenced_book_cannot_be_canonical_t2():
    from moomoo.quote_gateway import QuoteGateway, MockTransport, BookSnapshot
    from moomoo.subscription_manager import SubscriptionManager
    from moomoo.l2_feature_service import L2FeatureService
    from moomoo.l2_lifecycle_config import load_l2_lifecycle_config

    gateway = QuoteGateway(MockTransport())
    manager = SubscriptionManager(gateway, load_l2_lifecycle_config())
    manager.refresh_quota("t")
    manager.request_l2("AAPL", now=0)
    gateway.on_book_push(
        BookSnapshot(
            "AAPL",
            [(100.0, 200)],
            [(100.1, 80)],
            "2026-07-28T14:00:00Z",
            "2026-07-28T14:00:00Z",
            None,
        )
    )
    manager.on_book("AAPL", now=1, sequence_id=None)
    decision = L2FeatureService(gateway, manager).evaluate_t2(
        "AAPL", now=1, feature_at_iso="2026-07-28T14:00:01Z"
    )
    assert decision.is_t2 is False
    assert decision.reason == "SEQUENCE_UNVERIFIED"
    assert decision.sequence_state == "UNVERIFIED"


def test_mark_without_timestamp_is_stale():
    from active_trader.fire_performance import compute_fire_performance, FirePerfConfig, DATA_STALE

    fire = {
        "fire_id": "f1",
        "symbol": "AAPL",
        "fired_at": "2026-07-28T14:00:00+00:00",
        "fire_price": 100.0,
        "stop_ref": 99.0,
    }
    result = compute_fire_performance(
        fire,
        current_bid=100.0,
        current_ask=100.2,
        current_last=100.1,
        mark_source="unknown_clock",
        mark_at_iso=None,
        now_iso="2026-07-28T14:00:05+00:00",
        cfg=FirePerfConfig(),
    )
    assert result["mark_stale"] is True
    assert result["mark_time_state"] == "MISSING"
    assert result["lifecycle_state"] == DATA_STALE


def test_material_future_clock_skew_is_stale():
    from active_trader.fire_performance import compute_fire_performance, FirePerfConfig, DATA_STALE

    fire = {
        "fire_id": "f2",
        "symbol": "AAPL",
        "fired_at": "2026-07-28T14:00:00+00:00",
        "fire_price": 100.0,
        "stop_ref": 99.0,
    }
    result = compute_fire_performance(
        fire,
        current_bid=None,
        current_ask=None,
        current_last=100.1,
        mark_source="skewed",
        mark_at_iso="2026-07-28T14:00:10+00:00",
        now_iso="2026-07-28T14:00:05+00:00",
        cfg=FirePerfConfig(max_future_clock_skew_ms=1000),
    )
    assert result["mark_stale"] is True
    assert result["mark_time_state"] == "FUTURE_CLOCK_SKEW"
    assert result["lifecycle_state"] == DATA_STALE


def test_fire_query_dedupes_before_global_limit_and_marks_are_batched():
    source = (ROOT / "scripts" / "active_trader" / "fire_performance_api.py").read_text()
    assert "WITH latest_per_symbol AS" in source
    assert "FROM latest_per_symbol\n                   ORDER BY fired_at DESC" in source
    assert "WHERE symbol = ANY(%s)" in source
    assert source.count("FROM ticker_prices") == 1


def test_mfe_mae_are_not_claimed_as_complete_replay_coverage():
    from active_trader.fire_performance import compute_fire_performance, FirePerfConfig

    result = compute_fire_performance(
        {
            "fire_id": "f3",
            "symbol": "AAPL",
            "fired_at": "2026-07-28T14:00:00+00:00",
            "fire_price": 100.0,
            "stop_ref": 99.0,
        },
        current_bid=None,
        current_ask=None,
        current_last=101.0,
        mark_source="test",
        mark_at_iso="2026-07-28T14:00:01+00:00",
        now_iso="2026-07-28T14:00:01+00:00",
        cfg=FirePerfConfig(),
    )
    assert result["mfe_mae_scope"] == "OBSERVED_MARKS_ONLY"
    assert result["coverage_complete_since_fire"] is False
