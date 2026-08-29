"""Wave 2 slice 05: name READY/NEAR watch symbols; fires_s7 stays false."""
from __future__ import annotations

from scripts.lib.cio_investment_product import collect_watch_block_summary


def test_ready_and_near_symbols_named(monkeypatch):
    payload = {
        "items": [
            {"symbol": "AAA", "status": "READY", "map_reason": "x"},
            {"symbol": "BBB", "status": "NEAR", "map_reason": "y"},
            {"symbol": "CCC", "status": "BLOCK", "map_reason": "z"},
            {"symbol": "DDD", "status": "GO", "map_reason": "g"},
        ]
    }

    def fake_list(_):
        return payload

    def fake_proj(p):
        return p

    monkeypatch.setattr(
        "scripts.lib.data_broker.watch_intelligence.list_watch_intelligence",
        fake_list,
    )
    monkeypatch.setattr(
        "scripts.lib.data_broker.watch_intelligence.project_watch_intelligence_for_cio",
        fake_proj,
    )
    w = collect_watch_block_summary(payload)
    assert w["fires_s7"] is False
    assert w["ready_symbols"] == ["AAA", "DDD"]
    assert w["near_symbols"] == ["BBB"]
    assert w["ready_count"] == 3
    assert w["count"] == 1  # BLOCK only


def test_empty_ready_is_honest_not_invented(monkeypatch):
    payload = {"items": [{"symbol": "ZZZ", "status": "BLOCK", "map_reason": "gate"}]}

    monkeypatch.setattr(
        "scripts.lib.data_broker.watch_intelligence.list_watch_intelligence",
        lambda _: payload,
    )
    monkeypatch.setattr(
        "scripts.lib.data_broker.watch_intelligence.project_watch_intelligence_for_cio",
        lambda p: p,
    )
    w = collect_watch_block_summary(payload)
    assert w["ready_symbols"] == []
    assert w["near_symbols"] == []
    assert w["ready_count"] == 0
    assert w["fires_s7"] is False
