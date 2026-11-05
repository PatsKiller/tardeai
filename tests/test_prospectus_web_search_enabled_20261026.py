"""Prospectus web searches turn the routing engine on for their own caller."""
import types

from scripts.lib.prospectus import inputs


def test_search_passes_enabled_true(tmp_path, monkeypatch):
    seen = {}

    def route_query(query, **kw):
        seen.update(kw, query=query)
        return types.SimpleNamespace(ok=True, reason="FREE_SUFFICIENT", provider="searxng", cost_usd=0.0,
                                     results=[{"title": "t", "url": "https://example.com"}])

    monkeypatch.setattr(inputs, "_plib", lambda name: types.SimpleNamespace(route_query=route_query))
    monkeypatch.delenv("SEARCH_ROUTING_ENGINE", raising=False)
    out = inputs.HouseSources(tmp_path, read_only=True).search("ZZAA news", "ZZAA")
    assert seen["enabled"] is True and seen["caller"] == "prospectus_writer"
    assert out["ok"] is True and out["provider"] == "searxng"


def test_search_never_arms_paid_brave(monkeypatch, tmp_path):
    seen = {}

    def route_query(query, **kw):
        seen.update(kw)
        return types.SimpleNamespace(ok=False, reason="NO_COVERAGE", provider="", cost_usd=0.0, results=[])

    monkeypatch.setattr(inputs, "_plib", lambda name: types.SimpleNamespace(route_query=route_query))
    inputs.HouseSources(tmp_path, read_only=True).search("q", "ZZAA")
    assert "BRAVE_ROUTER_LIVE" not in str(seen) and "paid_transport" not in seen
