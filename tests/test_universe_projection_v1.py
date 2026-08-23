from __future__ import annotations

import json

from scripts.lib.universe_projection import build_universe_projection


def test_projection_declares_memberships_and_denominators(tmp_path):
    holdings = tmp_path / "data/portfolios/state/holdings.json"
    holdings.parent.mkdir(parents=True)
    holdings.write_text(json.dumps({"holdings": [
        {"symbol": "NOC", "quantity": 2, "asset_type": "equity"},
        {"symbol": "NOC", "quantity": 1, "asset_type": "equity"},
        {"symbol": "BND", "quantity": 3, "asset_type": "bond_etf"},
        {"symbol": "CASH", "quantity": 100, "asset_type": "cash"},
        {"symbol": "91282C", "quantity": 1, "asset_type": "bond"},
    ]}))
    reconciled = {
        "symbols": {
            "NOC": {"memberships": ["HELD", "WATCHLIST"], "source_refs": ["holdings.json"]},
            "BND": {"memberships": ["HELD"], "source_refs": ["holdings.json"]},
            "LHX": {"memberships": ["FORMER_HOLDING", "REENTRY"]},
        },
        "errors": [],
    }

    def query(sql):
        if "paper_trade_proposals" in sql:
            return [{"symbol": "RKLB"}]
        if "incubator_universe" in sql:
            return [{"symbol": "ASTS"}]
        if "symbol_profiles" in sql:
            return [{"symbol": s} for s in ("NOC", "BND", "LHX", "RKLB", "ASTS", "COLD")]
        return []

    out = build_universe_projection(root=tmp_path, query=query, reconciled=reconciled)
    assert out["schema"] == "UniverseProjection@v1"
    assert out["counts"]["holding_position_rows_non_cash"] == 4
    assert out["counts"]["held_unique_symbols"] == 3
    assert out["symbols"]["NOC"]["memberships"] == ["HELD", "WATCH"]
    assert out["symbols"]["BND"]["memberships"] == ["HELD", "NON_TICKER/BOND"]
    assert out["symbols"]["91282C"]["memberships"] == ["HELD", "NON_TICKER/BOND"]
    assert out["symbols"]["LHX"]["memberships"] == ["FORMER_HOLDING", "REENTRY"]
    assert out["symbols"]["RKLB"]["memberships"] == ["PROPOSAL"]
    assert out["symbols"]["ASTS"]["memberships"] == ["INCUBATOR"]
    assert out["symbols"]["COLD"]["memberships"] == ["COLD"]
    assert out["denominators"]["held_thesis_coverage"]["value"] == 3
    assert out["denominators"]["research_universe"]["value"] == 7
    assert out["financial_action"] is False
