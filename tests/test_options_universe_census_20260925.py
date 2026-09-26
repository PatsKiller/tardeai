"""Ideas census states the limited universe. No broker."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.options_universe_census import BANNER, build_universe_census


def test_fixture_universe_is_not_a_market_search():
    holdings = [
        {"symbol": "V", "shares": 130},
        {"symbol": "SCHD", "shares": 1912},
        {"symbol": "CASH", "is_cash": True, "shares": 1},
        {"symbol": "NOC", "shares": 0.23},
    ]
    convictions = [
        {"symbol": "DXCM", "source": "layer4"},
        {"symbol": "ACIO", "source": "operator_starred"},
    ]
    listed = [
        {"symbol": "V", "enterprise": {"live_eligible": False, "blocks": ["spread 34% > 12%"]}},
        {"symbol": "DXCM", "enterprise": {"blocks": ["OI 0 < 50"]}},
    ]
    census = build_universe_census(
        holdings=holdings,
        convictions=convictions,
        scored=2,
        listed=listed,
        inputs_recorded=True,
    )
    assert census["claim"] == "not_a_market_wide_search"
    assert census["banner"] == BANNER
    assert "not a market-wide" in census["banner"]
    assert census["screened"] == 5  # V, SCHD, NOC, DXCM, ACIO
    assert census["sources"]["holdings"] == 3
    assert census["sources"]["liquid_options_core_included"] is False
    assert census["sources"]["layer4_limit"] == 40
    assert census["scored"] == 2
    assert census["listed"] == 2
    assert census["blocked"] == 2
    assert census["ranking"].startswith("edge_score")
