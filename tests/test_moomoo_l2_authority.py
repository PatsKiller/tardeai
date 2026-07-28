#!/usr/bin/env python3
"""Authority and ownership guards for the Moomoo L2 read plane."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "moomoo"))

READ_PLANE_FILES = [
    ROOT / "scripts" / "moomoo" / "quote_gateway.py",
    ROOT / "scripts" / "moomoo" / "subscription_manager.py",
    ROOT / "scripts" / "moomoo" / "l2_feature_service.py",
    ROOT / "scripts" / "moomoo" / "l2_lifecycle_config.py",
    ROOT / "scripts" / "moomoo" / "real_gateway_transport.py",
    ROOT / "scripts" / "active_trader" / "l2_runtime.py",
    ROOT / "scripts" / "active_trader" / "l2_status_api.py",
    ROOT / "scripts" / "active_trader" / "fire_performance.py",
    ROOT / "scripts" / "active_trader" / "fire_performance_api.py",
    ROOT / "scripts" / "active_trader" / "live_mark.py",
]

LEGACY_SCALP_FILES = [
    ROOT / "scripts" / "market_observations" / "moomoo_t2.py",
    ROOT / "scripts" / "scalp_shadow_logger.py",
]

FORBIDDEN_ORDER_TOKENS = (
    "place_order",
    "submit_order",
    "unlock_trade",
    "lock_trade",
    "cancel_order",
    "modify_order",
    "execute_trade",
    "OpenSecTradeContext",
)
FORBIDDEN_LLM_TOKENS = (
    "import openai",
    "from openai",
    "ollama",
    "anthropic",
    "langchain",
    "gemma",
    "qwen",
    "chat/completions",
    "generativeai",
)


def test_request_and_scalp_paths_do_not_construct_openquotecontext():
    """Only a future dedicated gateway service may own production subscriptions."""
    for file_path in READ_PLANE_FILES + LEGACY_SCALP_FILES:
        source = file_path.read_text(encoding="utf-8")
        assert "OpenQuoteContext(" not in source, f"{file_path.name} constructs OpenQuoteContext"
    for file_path in LEGACY_SCALP_FILES:
        source = file_path.read_text(encoding="utf-8")
        assert "FutuTransport(" not in source, f"{file_path.name} creates a competing transport"


def test_production_l2_runtime_is_disabled_pending_dedicated_owner():
    from active_trader import l2_runtime

    l2_runtime.reset_for_test()
    assert l2_runtime.get_runtime() is None
    assert l2_runtime.runtime_posture()["owner_ready"] is False


def test_read_plane_has_no_order_path_tokens():
    for file_path in READ_PLANE_FILES:
        source = file_path.read_text(encoding="utf-8")
        for token in FORBIDDEN_ORDER_TOKENS:
            assert token not in source, f"{file_path.name} references order token {token!r}"


def test_no_llm_in_market_data_path():
    for file_path in READ_PLANE_FILES:
        source = file_path.read_text(encoding="utf-8").lower()
        for token in FORBIDDEN_LLM_TOKENS:
            assert token not in source, f"{file_path.name} references LLM token {token!r}"


def test_gateway_transport_surface_has_no_trade_methods():
    from moomoo.quote_gateway import MockTransport, QuoteGateway

    gateway = QuoteGateway(MockTransport())
    for forbidden in ("place_order", "unlock_trade", "submit_order", "cancel_order"):
        assert not hasattr(gateway, forbidden)


def test_subscription_manager_only_calls_read_subscription_surface():
    tree = ast.parse((ROOT / "scripts" / "moomoo" / "subscription_manager.py").read_text())
    gateway_attributes = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "gateway"
        ):
            gateway_attributes.add(node.attr)
    allowed = {"subscribe", "unsubscribe", "query_subscription", "ping", "entitlement_ok"}
    assert gateway_attributes <= allowed, f"unexpected gateway calls: {gateway_attributes - allowed}"


def test_l2_status_and_fire_payloads_declare_zero_authority():
    from active_trader.l2_status_api import build_l2_status, _disconnected_payload
    from active_trader.fire_performance_api import build_fire_performance
    from active_trader.fire_performance import FirePerfTracker

    body = build_l2_status(None)
    assert body["write"] is False and body["order_path"] is False and body["read_only"] is True
    disconnected = _disconnected_payload(None)
    assert disconnected["connected"] is False
    performance = build_fire_performance([], resolver=None, tracker=FirePerfTracker(), now_iso="t")
    assert performance["write"] is False and performance["order_path"] is False


def test_subscription_manager_calls_transport_in_injected_tests():
    """The deterministic manager still exercises subscribe/unsubscribe with a mock owner."""
    from moomoo.quote_gateway import QuoteGateway, MockTransport
    from moomoo.subscription_manager import SubscriptionManager
    from moomoo.l2_lifecycle_config import load_l2_lifecycle_config

    transport = MockTransport()
    manager = SubscriptionManager(QuoteGateway(transport), load_l2_lifecycle_config())
    manager.refresh_quota("t")
    manager.request_l2("AAPL", now=0)
    assert transport.subscribe_calls
    manager.release("AAPL", now=1000)
    assert transport.unsubscribe_calls


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
