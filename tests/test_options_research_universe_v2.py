"""Research-universe and OptionsDecisionPacket@v2 contracts."""
from __future__ import annotations

from scripts.lib.options_decision_packet_v2 import build_options_decision_packet_v2
from scripts.lib.options_research_universe import merge_research_rows, reentry_research_rows


def test_watchlist_and_reentry_rows_merge_without_losing_lanes():
    rows = merge_research_rows([
        {"symbol": "DXCM", "source": "watchlist", "summary": "researched watch row"},
        {"symbol": "DXCM", "source": "reentry", "reentry_signal": "WATCH", "thesis": "former holding"},
    ])
    assert len(rows) == 1
    assert rows[0]["research_qualified"] is True
    assert rows[0]["source_lanes"] == ["reentry", "watchlist"]
    assert rows[0]["summary"] == "researched watch row"


def test_reentry_snapshot_is_a_research_lane():
    rows = reentry_research_rows({"rows": [{
        "symbol": "AMZN", "watch_id": 7, "analyst_verdict": "reentry_candidate",
        "analyst_summary": "retest prior support", "reentry_signal": "IN_ZONE",
    }]})
    assert rows[0]["source_lanes"] == ["reentry"]
    assert rows[0]["research_status"] == "researched"
    assert rows[0]["reentry_signal"] == "IN_ZONE"


def test_packet_v2_is_honest_and_never_sized():
    row = {
        "symbol": "DXCM", "strategy": "credit_spread", "data_source": "schwab_chain",
        "max_profit": 40, "max_loss": 160, "breakeven": 120,
        "pop_pct": 72, "delta": 0.24, "oi": 0, "volume": 0,
        "bid_ask_spread_pct": 18.0,
        "enterprise": {"blocks": ["OPEN_INTEREST_ZERO"]},
        "research_context": {"source_lanes": ["watchlist", "reentry"]},
    }
    memo = {
        "thesis": {
            "why_option_instead_of_stock": "defined risk",
            "catalyst": "missing", "timeframe": "21 DTE",
            "reward_to_risk": 0.25, "position_size": "not sized",
        },
        "structures": [
            {"structure": "calendar_spread", "status": "not_available"},
        ],
        "committee": {
            "risk_officer": ["OPEN_INTEREST_ZERO"],
            "options_strategist": "defined risk",
            "macro_analyst": "missing",
            "quant_analyst": {"probability_of_profit": 72},
        },
    }
    packet = build_options_decision_packet_v2(
        row, memo=memo, research=row["research_context"], generated_at="2026-09-25T19:00:00Z",
    )
    assert packet["schema"] == "OptionsDecisionPacket@v2"
    assert packet["research"]["source_lanes"] == ["watchlist", "reentry"]
    assert packet["decision"]["first_hard_block"] == "OPEN_INTEREST_ZERO"
    assert packet["decision"]["size"] == {"status": "not_sized", "display": "Not sized"}
    assert packet["contract"]["gamma"] is None
    assert packet["cio"]["status"] == "unreviewed"
    assert packet["structures"][0]["status"] == "not_available"
