#!/usr/bin/env python3
"""Authority / AST guards for the Moomoo L2 read plane.

Proves the new market-data/read-plane modules cannot reach an order path, cannot open a
second production OpenQuoteContext, and contain no LLM in the data path. These are structural
invariants — a future edit that violates them fails here.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "moomoo"))

# The new read-plane modules (single-owner gateway + lifecycle + feature + API surface).
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

FORBIDDEN_ORDER_TOKENS = ("place_order", "submit_order", "unlock_trade", "lock_trade",
                          "cancel_order", "modify_order", "execute_trade", "OpenSecTradeContext")
FORBIDDEN_LLM_TOKENS = ("import openai", "from openai", "ollama", "anthropic", "langchain",
                        "gemma", "qwen", "chat/completions", "generativeai")


def test_no_module_constructs_a_second_openquotecontext():
    """Only client.FutuTransport may construct OpenQuoteContext — the single owner.
    No read-plane module may call OpenQuoteContext(...) directly."""
    for f in READ_PLANE_FILES:
        src = f.read_text(encoding="utf-8")
        assert "OpenQuoteContext(" not in src, f"{f.name} constructs a second OpenQuoteContext"


def test_read_plane_has_no_order_path_tokens():
    for f in READ_PLANE_FILES:
        src = f.read_text(encoding="utf-8")
        for tok in FORBIDDEN_ORDER_TOKENS:
            assert tok not in src, f"{f.name} references order-path token {tok!r}"


def test_no_llm_in_market_data_path():
    for f in READ_PLANE_FILES:
        src = f.read_text(encoding="utf-8").lower()
        for tok in FORBIDDEN_LLM_TOKENS:
            assert tok not in src, f"{f.name} references LLM token {tok!r}"


def test_gateway_transport_surface_has_no_trade_methods():
    from moomoo.quote_gateway import MockTransport, QuoteGateway
    gw = QuoteGateway(MockTransport())
    for bad in ("place_order", "unlock_trade", "submit_order", "cancel_order"):
        assert not hasattr(gw, bad)


def test_subscription_manager_only_calls_subscribe_unsubscribe():
    """The manager drives the transport ONLY through subscribe/unsubscribe/query_subscription —
    never an order/unlock method (defect 4: real conserving control, no order path)."""
    tree = ast.parse((ROOT / "scripts" / "moomoo" / "subscription_manager.py").read_text())
    gateway_attrs = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute)
                and node.value.attr == "gateway"):
            gateway_attrs.add(node.attr)
    allowed = {"subscribe", "unsubscribe", "query_subscription", "ping", "entitlement_ok"}
    assert gateway_attrs <= allowed, f"unexpected gateway calls: {gateway_attrs - allowed}"


def test_l2_status_and_fire_payloads_declare_zero_authority():
    from active_trader.l2_status_api import build_l2_status, _disconnected_payload
    from active_trader.fire_performance_api import build_fire_performance
    from active_trader.fire_performance import FirePerfTracker
    body = build_l2_status(None)
    assert body["write"] is False and body["order_path"] is False and body["read_only"] is True
    dp = _disconnected_payload(None)
    assert dp["connected"] is False
    fp = build_fire_performance([], resolver=None, tracker=FirePerfTracker(), now_iso="t")
    assert fp["write"] is False and fp["order_path"] is False


def test_subscription_manager_actually_calls_transport(monkeypatch):
    """Defect 4 proof: arming/releasing issues REAL subscribe/unsubscribe (not a local dict only)."""
    from moomoo.quote_gateway import QuoteGateway, MockTransport
    from moomoo.subscription_manager import SubscriptionManager
    from moomoo.l2_lifecycle_config import load_l2_lifecycle_config
    t = MockTransport()
    mgr = SubscriptionManager(QuoteGateway(t), load_l2_lifecycle_config())
    mgr.refresh_quota("t")
    mgr.request_l2("AAPL", now=0)
    assert t.subscribe_calls, "arming did not call OpenD subscribe"
    mgr.release("AAPL", now=1000)     # well past dwell
    assert t.unsubscribe_calls, "release did not call OpenD unsubscribe"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
