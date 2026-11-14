"""LQ-20261113-3047 (A05): Home's data input reads the one protection floor, never its own $100 literal.

LQ-20261113-3068 C1 (review 3047): a $0, negative, missing or unreadable value is UNVALUED (UNKNOWN, with why), never
"under $100"; it stays counted. The floor value itself is the operator's ruling: tests read count_floor_usd().

Synthetic: the floor config is pointed at a scratch file (portfolio_total_contract.CONFIG_PATH); no DB.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from scripts import home_status_verdict as hsv  # noqa: E402
from scripts.lib import home_trade_ready as htr  # noqa: E402
from scripts.lib import portfolio_total_contract as ptc  # noqa: E402
from scripts.lib import protection_policy as pp  # noqa: E402


def test_home_floor_and_exemptions_are_the_policy():
    assert hsv.DATA_NOT_COUNTED_UNDER_USD == pp.count_floor_usd() == 100.0
    assert hsv.DATA_EXEMPT_ASSET_TYPES == pp.POLICY_EXEMPT_ASSET_TYPES


def test_data_not_counted_follows_the_config_owner(tmp_path, monkeypatch):
    row = {"symbol": "MID", "market_value": 250.0}
    assert hsv.data_not_counted(row) is False                    # $250 >= $100: counted
    cfg = tmp_path / "position_count_authority.json"
    cfg.write_text(json.dumps({"min_position_usd": 1000.0}))
    monkeypatch.setattr(ptc, "CONFIG_PATH", str(cfg))
    assert hsv.data_not_counted(row) is True                     # the owner moved: Home moves with it
    assert hsv.data_not_counted({"symbol": "X", "market_value": None}) is False   # unknown stays counted


# ── LQ-20261113-3068 C1: $0 / missing / unreadable is UNVALUED, never "under $100" ──────────────────────────────
NOW = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)       # Thursday 10:00 ET, market open
FLOOR = pp.count_floor_usd()


def _row(symbol, mv, asset_type="EQUITY"):
    return {"symbol": symbol, "asset_type": asset_type, "as_of": NOW - timedelta(minutes=2), "market_value": mv}


def test_only_a_known_positive_value_under_the_floor_is_not_counted():
    for mv in (0.0, -0.0, -5.0, None, "n/a", float("nan")):
        assert hsv.data_not_counted({"symbol": "X", "market_value": mv}) is False, mv
    assert hsv.data_not_counted({"symbol": "X", "market_value": 0.01}) is True
    assert hsv.data_not_counted({"symbol": "X", "market_value": round(FLOOR - 0.01, 2)}) is True
    assert hsv.data_not_counted({"symbol": "X", "market_value": FLOOR}) is False      # the floor is strict


def test_data_unvalued_names_why():
    assert hsv.data_unvalued({"symbol": "X", "market_value": None}) == "market value missing"
    assert hsv.data_unvalued({"symbol": "X", "market_value": "n/a"}) == "market value unreadable"
    # D2 (REVIEW-3079 Z2): NaN (Postgres numeric 'NaN' arrives as Decimal('NaN')) is unreadable, never a value
    from decimal import Decimal
    for nan in (float("nan"), Decimal("NaN"), "NaN"):
        assert hsv.data_unvalued({"symbol": "X", "market_value": nan}) == "market value unreadable", nan
        assert hsv.data_not_counted({"symbol": "X", "market_value": nan}) is False, nan
    assert hsv.data_unvalued({"symbol": "X", "market_value": 0.0}) == "market value <= 0 on a held quantity"
    assert hsv.data_unvalued({"symbol": "X", "market_value": 12.0}) is None
    assert hsv.data_unvalued({"symbol": hsv.VIX_SYMBOL, "market_value": None}) is None   # an index, not a holding


def test_read_data_lists_a_zero_value_as_unvalued_not_under_the_floor():
    rows = [_row(hsv.VIX_SYMBOL, None, "INDEX"), _row("BIG", 5000.0), _row("DUST", 40.0), _row("ZERO", 0.0),
            _row("NOVAL", None), _row("CASH", 900.0, "CASH")]
    r = hsv.read_data(lambda sql, params=None: rows, NOW)
    assert r.value["listed_not_counted"] == ["DUST"]
    assert r.value["unvalued"] == [{"symbol": "NOVAL", "state": htr.UNKNOWN, "why": "market value missing"},
                                   {"symbol": "ZERO", "state": htr.UNKNOWN,
                                    "why": "market value <= 0 on a held quantity"}]
    assert r.value["exempt"] == ["CASH"]
    assert r.value["symbols"] == 4                     # VIX, BIG, ZERO, NOVAL: unvalued rows stay counted
    assert "ZERO" not in r.value["listed_not_counted"]


def test_read_data_lists_unvalued_rows_when_a_quote_is_missing_too():
    rows = [_row(hsv.VIX_SYMBOL, None, "INDEX"), dict(_row("ZERO", 0.0), as_of=None)]
    r = hsv.read_data(lambda sql, params=None: rows, NOW)
    assert r.state != htr.OK and r.value["missing"] == ["ZERO"]
    assert r.value["listed_not_counted"] == []
    assert [u["symbol"] for u in r.value["unvalued"]] == ["ZERO"]
