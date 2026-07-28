#!/usr/bin/env python3
"""L2 status API + dispatch truth: state-file existence never implies connected/T2."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "moomoo"))

from moomoo.quote_gateway import QuoteGateway, MockTransport, BookSnapshot  # noqa: E402
from moomoo.subscription_manager import SubscriptionManager  # noqa: E402
from moomoo.l2_feature_service import L2FeatureService  # noqa: E402
from moomoo.l2_lifecycle_config import load_l2_lifecycle_config  # noqa: E402
from active_trader.fire_performance import FirePerfTracker, FirePerfConfig  # noqa: E402
from active_trader.l2_runtime import L2Runtime  # noqa: E402
from active_trader import l2_status_api as api  # noqa: E402


def _runtime(transport=None):
    t = transport or MockTransport()
    gw = QuoteGateway(t)
    cfg = load_l2_lifecycle_config()
    mgr = SubscriptionManager(gw, cfg)
    mgr.refresh_quota("t")
    feats = L2FeatureService(gw, mgr)
    return L2Runtime(gw, mgr, feats, FirePerfTracker(FirePerfConfig()), cfg), gw, mgr, t


def test_none_runtime_is_disconnected_not_connected():
    body = api.build_l2_status(None)
    assert body["connected"] is False and body["provider_state"] == "PROVIDER_DISCONNECTED"
    assert body["write"] is False and body["order_path"] is False and body["read_only"] is True

def test_intent_restore_does_not_imply_connected():
    rt, gw, mgr, t = _runtime()
    mgr.restore_desired_from_state(["AAPL", "TSLA"])   # intent only
    body = api.build_l2_status(rt)
    assert body["subscribed_any"] is False and body["t2_any"] is False
    # symbols present but ARM_INTENT, not subscribed
    assert body["symbols"]["AAPL"]["state"] == "ARM_INTENT"
    assert body["confirmed_subscriptions"] == {}

def test_provider_down_reports_disconnected():
    rt, gw, mgr, t = _runtime(MockTransport(up=False))
    body = api.build_l2_status(rt)
    assert body["connected"] is False and body["provider_state"] == "PROVIDER_DISCONNECTED"

def test_confirmed_fresh_reports_t2_and_quota():
    rt, gw, mgr, t = _runtime()
    mgr.request_l2("AAPL", now=0)
    gw.on_book_push(BookSnapshot("AAPL", [(100.0, 200)], [(100.1, 80)], "p", "r", 1))
    mgr.on_book("AAPL", now=1, provider_at="p", received_at="r", sequence_id=1)
    body = api.build_l2_status(rt)
    assert body["connected"] is True
    assert body["subscribed_any"] is True and body["t2_any"] is True
    assert body["quota"]["total_quota"] is not None
    assert "AAPL" in body["confirmed_subscriptions"]
    assert body["symbols"]["AAPL"]["t2"]["is_t2"] is True

def test_symbol_detail_shape():
    rt, gw, mgr, t = _runtime()
    mgr.request_l2("AAPL", now=0)
    body = api.build_l2_status_symbol(rt, "aapl")
    assert body["symbol"] == "AAPL"
    for k in ("lifecycle", "t2", "confirmed_subtypes", "quota", "provider_state",
              "book_provider_at", "sequence_id"):
        assert k in body
    assert body["write"] is False and body["order_path"] is False

def test_unknown_symbol_not_requested():
    rt, gw, mgr, t = _runtime()
    body = api.build_l2_status_symbol(rt, "ZZZZ")
    assert body["lifecycle"]["state"] == "NOT_REQUESTED"
    assert body["t2"]["is_t2"] is False


# ── dispatch wiring ──────────────────────────────────────────────────────────
def test_dispatch_routes_l2_and_fire_endpoints(monkeypatch):
    from active_trader.read_http import dispatch
    from active_trader.read_api import ReadOnlyActiveTraderAPI
    rt, gw, mgr, t = _runtime()
    import active_trader.l2_runtime as l2rt
    l2rt.set_runtime_for_test(rt)
    a = ReadOnlyActiveTraderAPI()
    st, body = dispatch(a, "GET", "/api/v3/active-trader/l2-status", {})
    assert st == 200 and body["contract"] == "active-trader-l2-status-v1"
    st2, body2 = dispatch(a, "GET", "/api/v3/active-trader/l2-status/AAPL", {})
    assert st2 == 200 and body2["symbol"] == "AAPL"
    st3, body3 = dispatch(a, "GET", "/api/v3/active-trader/fire-performance", {})
    assert st3 == 200 and body3["order_path"] is False
    l2rt.reset_for_test()

def test_dispatch_rejects_non_get(monkeypatch):
    from active_trader.read_http import dispatch
    from active_trader.read_api import ReadOnlyActiveTraderAPI
    st, body = dispatch(ReadOnlyActiveTraderAPI(), "POST", "/api/v3/active-trader/l2-status", {})
    assert st == 405


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
