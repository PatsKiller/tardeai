"""Slice 6: watch BLOCK reasons on the product. Do not map BLOCK→READY or fire S7."""
from __future__ import annotations

from scripts.lib.cio_investment_product import collect_watch_block_summary
from scripts.lib.cio_situation_detector import eval_s7


def test_block_fixture_in_summary_ready_not_remapped():
    payload = {
        "items": [
            {"symbol": "FOO", "trade_ai_state": "WAIT"},
            {"symbol": "BAR", "proposal_allowed": True},
            {"symbol": "BAZ", "status": "NEAR", "score": 80, "strong_near": True},
        ]
    }
    s = collect_watch_block_summary(payload)
    assert s["fires_s7"] is False
    assert s["count"] >= 1
    assert any(t["symbol"] == "FOO" for t in s["top"])
    assert s["ready_count"] >= 1
    assert "FOO" not in {t["symbol"] for t in s["top"] if t.get("reason") == "READY"}
    from scripts.lib.data_broker.watch_intelligence import project_watch_intelligence_for_cio
    proj = project_watch_intelligence_for_cio(payload)
    s7 = eval_s7({"watch_intelligence": proj}, {"thresholds": {"watch_statuses": ["READY", "GO", "NEAR"]}})
    syms = {row["symbols"][0] for row in s7}
    assert "BAR" in syms or "BAZ" in syms
    assert "FOO" not in syms
