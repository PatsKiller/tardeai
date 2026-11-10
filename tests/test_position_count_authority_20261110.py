"""LQ-20261107-1820 (Reality Drift #10): one position-count authority on /api/v2/overview.

Synthetic fixtures only. One holding is marked $99.07 by the store and $101.50 by the live re-mark: before the
fix the headline said the re-mark's count while the store said one fewer.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.lib import portfolio_total_contract as ptc
from scripts.lib.position_count_authority import publish_position_counts

ROOT = Path(__file__).resolve().parents[1]


def _row(sym, live, store, acct="acct_a", cash=False):
    return {"account_id": acct, "symbol": sym, "is_cash": cash, "shares": 10, "quantity": 10,
            "market_value": live, "broker_market_value": store}


def _portfolio():
    return {"holdings": [_row("AAA", 500, 499), _row("BBB", 101.5, 99.07), _row("CCC", 50, 49),
                         _row("CASH", 1000, 1000, cash=True)]}


def _out():
    return {"totals_basis": {"basis": "positions_store"},
            "portfolio_total": {"as_of": "2026-01-01T00:00:00Z"},
            "observation": {"position_counts": {"scopes": {"overview.non_cash_over_100": 1,
                                                           "risk.risk_included": 2}}},
            "position_count": 2, "position_counts": {"counted": 2}}


def test_store_basis_count_wins_and_live_mark_difference_is_stated():
    out = publish_position_counts(_out(), _portfolio())
    c = out["position_counts"]
    assert c["source"] == "positions_current" and c["as_of"] == "2026-01-01T00:00:00Z"
    assert c["scopes"][ptc.OVER_100_SCOPE] == 1          # store: only AAA is over the floor
    assert c["live_mark_scopes"][ptc.OVER_100_SCOPE] == 2  # re-mark would have said 2
    assert c["findings"][0]["code"] == "LIVE_MARK_COUNT_DIFFERS"
    assert len(c["findings"][0]["instruments_crossing_floor"]) == 1


def test_every_surface_reads_the_same_headline():
    out = publish_position_counts(_out(), _portfolio())
    rec = out["position_counts"]["reconciliation"]
    assert rec["agree"] is True
    assert len(set(rec["surfaces"].values())) == 1
    assert out["position_count"] == out["portfolio_total"]["position_count"] == 3
    obs = out["observation"]["position_counts"]["scopes"]
    assert obs[ptc.OVER_100_SCOPE] == 1 and "overview.non_cash_over_100" not in obs
    assert obs["risk.risk_included"] == 2


def test_live_mark_basis_is_named_when_store_unavailable():
    o = _out()
    o["totals_basis"] = {"basis": "live_mark"}
    out = publish_position_counts(o, _portfolio())
    assert out["position_counts"]["source"] == "live_mark_rows"
    assert out["position_counts"]["scopes"][ptc.OVER_100_SCOPE] == 2
    assert out["position_counts"]["live_mark_scopes"] is None


def test_floor_comes_from_config_not_code():
    cfg = json.loads((ROOT / "config" / "position_count_authority.json").read_text())
    assert ptc.MIN_POSITION_USD == float(cfg["min_position_usd"])
    out = publish_position_counts(_out(), _portfolio(), min_position_usd=40)
    assert out["position_counts"]["scopes"][ptc.OVER_100_SCOPE] == 3  # store marks 499, 99.07, 49 are all over 40
    assert out["position_counts"]["min_position_usd"] == 40.0


def test_no_hardcoded_floor_in_cio_truth_or_api():
    api = (ROOT / "scripts/api_v2.py").read_text()
    assert '(p.get("market_value") or 0) > 100]' not in api
    assert '(_number(r.get("market_value")) or 0) >= 100]' not in (ROOT / "scripts/lib/cio_truth.py").read_text()
