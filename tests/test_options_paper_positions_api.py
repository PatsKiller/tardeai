#!/usr/bin/env python3
"""PR3 — paper positions API serializers + unified open options.

    .venv/bin/python -m pytest tests/test_options_paper_positions_api.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.options_pipeline import paper_positions_api as api  # noqa: E402
from telegram_alert_router import classify_alert  # noqa: E402


def test_serialize_monitored_row_includes_semantics():
    row = {
        "id": 3, "proposal_id": "opt_rtx_test", "broker": "alpaca",
        "execution_route": "alpaca_paper", "status": "OPEN", "paper_only": True,
        "underlying_symbol": "RTX", "option_symbol": "RTX260918C00160000",
        "strategy": "deep_itm_call", "side": "BUY", "option_type": "call",
        "strike": 160.0, "expiration": "2026-09-18", "contracts": 1,
        "entry_fill_price": 40.10, "entry_debit_credit": "debit",
        "meta_json": {},
    }
    snap = {
        "advice_label": "CONSIDER_CLOSE_PAPER",
        "advice_reason": "Profit target advisory (30%)",
        "option_mark": 50.25, "unrealized_pnl": 1015.0, "unrealized_pnl_pct": 25.2,
        "delta": 0.82, "dte": 40, "quote_source": "schwab_chain",
        "max_favorable_excursion": 1100.0, "max_adverse_excursion": -50.0,
        "risk_flags_json": '[{"code": "profit_target"}]',
    }
    card = api.serialize_monitored_row(row, snap)
    assert card["position_source"] == "monitored"
    assert card["execution_route_kind"] == "alpaca_paper"
    assert card["safety_status_badge"]["label"] == "NO LIVE PATH"
    assert card["recommended_action"] == "Consider close (paper advisory)"
    assert card["mfe"] == 1100.0


def test_build_unified_dedupes_occ():
    broker = [{"id": "b1", "occ_symbol": "RTX260918C00160000", "underlying": "RTX"}]
    monitored = [{"position_id": 1, "occ_symbol": "RTX260918C00160000", "underlying": "RTX"}]
    unified = api.build_unified_open_positions(broker, monitored)
    assert len(unified) == 1
    assert unified[0]["position_source"] == "broker"


def test_filter_positions_by_route():
    positions = [
        {"underlying": "RTX", "execution_route_kind": "alpaca_paper", "position_source": "monitored"},
        {"underlying": "V", "execution_route_kind": "schwab_live", "position_source": "broker"},
    ]
    out = api.filter_positions(positions, route="alpaca_paper")
    assert len(out) == 1 and out[0]["underlying"] == "RTX"


def test_position_filter_facets_counts():
    facets = api.position_filter_facets([
        {"position_source": "monitored", "execution_route_kind": "alpaca_paper",
         "broker": "alpaca", "option_type": "call", "side": "buy",
         "paper_only": True, "still_working": False, "severity": "warn"},
    ])
    assert facets["total"] == 1
    assert facets["by_source"]["monitored"] == 1
    assert facets["needs_action"] == 1
    assert facets["paper_only"] == 1