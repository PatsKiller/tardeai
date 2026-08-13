"""Dry tests for the Checkpoint 2 evidence-provenance script (zero fabrication)."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.cio_evidence_checkpoint2 import build_checkpoint2_cases


def _write(tmp: Path, name: str, data) -> None:
    p = tmp / name
    p.write_text(json.dumps(data))
    return p


def test_checkpoint2_cases_are_complete_and_non_fabricating(tmp_path):
    state = tmp_path / "state"
    state.mkdir()

    holdings = {
        "as_of": "2026-08-13",
        "last_repriced": "2026-08-13 15:45:01 ET",
        "portfolio_totals": {"total_value": 100000.0, "total_cash": 20000.0, "as_of": "2026-08-13"},
        "holdings": [
            {"symbol": "V", "name": "Visa", "account": "a", "market_value": 10000.0,
             "current_price": 300.0, "is_cash": False},
            {"symbol": "SCHD", "name": "Schwab Div", "account": "a", "market_value": 15000.0,
             "current_price": 80.0, "is_cash": False},
            {"symbol": "CASH", "name": "Cash", "account": "a", "market_value": 20000.0,
             "is_cash": True},
        ],
    }
    watchlist = {"PLTR": {"thesis": "AI", "target_intent": "growth_speculative", "added": "2026-04-03"}}
    watch_intel = {
        "last_updated": "2026-08-13 07:37",
        "watchlist": [{"symbol": "PLTR", "currently_hold": False}],
    }
    journal = {
        "last_updated": "2026-08-13 07:15",
        "closed_trades": [
            {"symbol": "AMD", "account": "a", "exit_date": "2025-09-30", "realized_pnl": 71.5},
        ],
    }
    sector_cache = {"V": "Financial Services", "SCHD": ""}

    _write(state, "holdings.json", holdings)
    _write(state, "watchlist.json", watchlist)
    _write(state, "watchlist_intelligence.json", watch_intel)
    _write(state, "trade_journal.json", journal)
    _write(state, "sector_cache.json", sector_cache)

    report = build_checkpoint2_cases(state)

    assert report["cases_total"] == 15
    assert report["fabricated_fields"] == 0
    assert report["source_traceability_pct"] == 100.0

    # Every ref must carry a deterministic value_hash (value was actually read).
    for case in report["cases"]:
        for ref in case["refs"]:
            assert ref.get("value_hash"), f"{case['case_id']} ref missing value_hash"
            assert ref.get("source"), f"{case['case_id']} ref missing source"

    # TSLA is absent from the journal fixture — must be DATA_UNAVAILABLE, not invented.
    tsla = next(c for c in report["cases"] if c["case_id"] == "closed_reentry_TSLA")
    assert tsla["refs"][0]["quality_state"] == "DATA_UNAVAILABLE"
    assert tsla["refs"][0]["value"] == {"symbol": "TSLA"}

    # AMD present — realized_pnl read through, no fabrication.
    amd = next(c for c in report["cases"] if c["case_id"] == "closed_reentry_AMD")
    assert amd["refs"][0]["value"]["realized_pnl"] == 71.5


def test_checkpoint2_aggregates_multi_account_holding(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    holdings = {
        "as_of": "2026-08-13",
        "last_repriced": "2026-08-13 15:45:01 ET",
        "portfolio_totals": {"total_value": 100000.0, "as_of": "2026-08-13"},
        "holdings": [
            {"symbol": "V", "name": "Visa", "account": "ira", "market_value": 60000.0,
             "current_price": 300.0, "is_cash": False},
            {"symbol": "V", "name": "Visa", "account": "roth", "market_value": 40000.0,
             "current_price": 300.0, "is_cash": False},
        ],
    }
    _write(state, "holdings.json", holdings)
    for name in ("watchlist.json", "watchlist_intelligence.json", "trade_journal.json", "sector_cache.json"):
        _write(state, name, {})

    report = build_checkpoint2_cases(state)
    v = next(c for c in report["cases"] if c["case_id"] == "held_equity_V")
    value = v["refs"][0]["value"]
    assert value["market_value"] == 100000.0
    assert value["weight_pct"] == 100.0
    assert set(value["accounts"]) == {"ira", "roth"}
