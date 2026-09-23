"""Day P/L for shares traded today, and cost basis after a trade-sized share change.

2026-09-23, Schwab rollover IRA: MCD bought 100 @ 235.01 and 100 @ 236.36 while MCD fell
5.4%. Command Center read day P/L -$2,714 (the whole day's move on 200 shares) against
Schwab's +$289, and kept the first lot's $23,501 basis on 200 shares. DIV sold 411 of 415.65
shares and kept its 413-share basis. Hermetic: no DB, no Telegram.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import portfolio_repricer as pr  # noqa: E402
import schwab_position_sync as sps  # noqa: E402

MCD_FILLS = {"buys": [(100.0, 235.01), (100.0, 236.36)], "sells": []}


# ── day change ────────────────────────────────────────────────────────────────


def test_position_opened_today_matches_broker_day_pl():
    # Schwab at 237.13: (237.13 - 235.685 avg) * 200 = +289.00
    assert pr._intraday_day_change(200.0, 237.13, 250.35, MCD_FILLS) == pytest.approx(289.0)


def test_add_to_existing_position_splits_open_shares_and_new_lot():
    fills = {"buys": [(300.0, 110.42)], "sells": []}
    # 100 held at the open earn (110.27-109.96); 300 bought earn (110.27-110.42)
    assert pr._intraday_day_change(400.0, 110.27, 109.96, fills) == pytest.approx(100 * 0.31 + 300 * -0.15)


def test_partial_sell_counts_the_sold_shares_move_until_the_fill():
    fills = {"buys": [], "sells": [(411.0, 19.135)]}
    got = pr._intraday_day_change(4.6535, 19.17, 19.30, fills)
    # 415.6535 held at the open earn the day's move; the 411 sold earned (fill - prev_close)
    assert got == pytest.approx(round(415.6535 * (19.17 - 19.30) + 411 * (19.135 - 19.30), 2))


def test_no_fills_or_unreconcilable_fills_fall_back():
    assert pr._intraday_day_change(200.0, 237.13, 250.35, None) is None
    # more bought today than now held -> fills do not reconcile with shares
    assert pr._intraday_day_change(50.0, 237.13, 250.35, MCD_FILLS) is None


def _holding(**kw):
    base = {"symbol": "MCD", "account": "schwab_rollover_ira", "shares": 200.0, "price": 250.35}
    base.update(kw)
    return base


def test_apply_to_holdings_uses_fills_and_labels_the_basis():
    h = [_holding()]
    live = {"MCD": {"price": 237.13, "prev_close": 250.35, "change_pct": -5.28, "source": "test"}}
    pr._apply_to_holdings(h, live, {}, {("schwab_rollover_ira", "MCD"): MCD_FILLS})
    assert h[0]["day_change"] == pytest.approx(289.0)
    assert h[0]["day_change_basis"] == "intraday_fills"
    assert h[0]["day_change_pct"] == pytest.approx(-5.28)  # the security's move is unchanged


def test_apply_to_holdings_without_fills_keeps_plain_formula():
    h = [_holding(day_change_basis="intraday_fills")]
    live = {"MCD": {"price": 237.13, "prev_close": 250.35, "change_pct": -5.28, "source": "test"}}
    pr._apply_to_holdings(h, live, {})
    assert h[0]["day_change"] == pytest.approx(round((237.13 - 250.35) * 200, 2))
    assert "day_change_basis" not in h[0]


def test_fills_are_keyed_by_account_so_other_accounts_are_untouched():
    h = [_holding(account="schwab_taxable")]
    live = {"MCD": {"price": 237.13, "prev_close": 250.35, "change_pct": -5.28, "source": "test"}}
    pr._apply_to_holdings(h, live, {}, {("schwab_rollover_ira", "MCD"): MCD_FILLS})
    assert h[0]["day_change"] == pytest.approx(round((237.13 - 250.35) * 200, 2))


def test_load_intraday_fills_maps_roth_label_and_sides(monkeypatch):
    import db_adapter

    rows = [
        {"account": "schwab_roth_ira", "symbol": "SCHD", "action": "Buy", "quantity": 10, "price": 27.5},
        {"account": "schwab_taxable", "symbol": "DIV", "action": "Sell", "quantity": 411, "price": 19.135},
    ]
    monkeypatch.setattr(db_adapter, "_execute", lambda sql, params=None, fetch=None: rows)
    got = pr._load_intraday_fills()
    assert got[("schwab_roth", "SCHD")] == {"buys": [(10.0, 27.5)], "sells": []}
    assert got[("schwab_taxable", "DIV")] == {"buys": [], "sells": [(411.0, 19.135)]}


def test_load_intraday_fills_is_fail_soft(monkeypatch):
    import db_adapter

    def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(db_adapter, "_execute", boom)
    assert pr._load_intraday_fills() == {}


# ── cost basis after a trade ─────────────────────────────────────────────────


@pytest.fixture
def no_side_effects(monkeypatch):
    import share_reconciliation

    monkeypatch.setattr(share_reconciliation, "_now", lambda: "2026-09-23T17:52:10+00:00", raising=False)
    monkeypatch.setattr(sps, "_record", lambda *a, **k: None)
    monkeypatch.setattr(sps, "_alert", lambda *a, **k: None)


def test_buy_on_existing_position_rebases_cost_basis(no_side_effects):
    prior = {
        "symbol": "MCD",
        "account": "schwab_rollover_ira",
        "shares": 100.0,
        "system_shares": 100.0,
        "cost_basis": 23501.0,
        "cost_basis_source": "broker_api",
        "name": "MCD",
    }
    live = [{"symbol": "MCD", "qty": 200, "current_price": 237.13, "market_value": 47426.0, "avg_entry_price": 235.685}]
    rows, _ = sps._build_account_rows("schwab_rollover_ira", live, {("MCD", "schwab_rollover_ira"): prior})
    (row,) = rows
    assert row["shares"] == 200
    assert row["cost_basis"] == pytest.approx(47137.0)
    assert row["gain_loss"] == pytest.approx(47426.0 - 47137.0)


def test_unchanged_share_count_keeps_stored_basis(no_side_effects):
    prior = {
        "symbol": "SCHD",
        "account": "schwab_rollover_ira",
        "shares": 100.0,
        "system_shares": 100.0,
        "cost_basis": 2500.0,
        "cost_basis_source": "csv_lot",
        "gain_loss": 250.0,
    }
    live = [{"symbol": "SCHD", "qty": 100, "current_price": 27.5, "market_value": 2750.0, "avg_entry_price": 30.0}]
    rows, _ = sps._build_account_rows("schwab_rollover_ira", live, {("SCHD", "schwab_rollover_ira"): prior})
    assert rows[0]["cost_basis"] == 2500.0  # tax-grade basis is not replaced by broker avg


def _doc(rows):
    total = sum(r["market_value"] for r in rows)
    return {"holdings": rows, "portfolio_totals": {"total_value": total}}


def test_shield_lets_a_trade_change_the_basis_but_guards_unchanged_shares(tmp_path, no_side_effects):
    path = tmp_path / "holdings.json"
    cur = [
        {"symbol": "MCD", "account": "schwab_rollover_ira", "shares": 100.0, "market_value": 23700.0,
         "cost_basis": 23501.0, "cost_basis_source": "broker_api"},
        {"symbol": "SCHD", "account": "schwab_rollover_ira", "shares": 100.0, "market_value": 2750.0,
         "cost_basis": 2500.0, "cost_basis_source": "csv_lot"},
    ]
    # The write guard requires every governed account to be present; these rows are unchanged.
    others = [
        {"symbol": "V", "account": "schwab_taxable", "shares": 10.0, "market_value": 3600.0, "cost_basis": 3000.0},
        {"symbol": "SCHG", "account": "schwab_roth", "shares": 10.0, "market_value": 330.0, "cost_basis": 300.0},
    ]
    cur = cur + others
    path.write_text(json.dumps(_doc(cur)), encoding="utf-8")
    new = [
        dict(cur[0], shares=200.0, market_value=47426.0, cost_basis=47137.0),  # a buy: basis must move
        dict(cur[1], cost_basis=9999.0),  # same shares: stale writer, must be shielded
        *others,
    ]
    res = sps.protected_holdings_write(_doc(new), source="schwab_sync", account_key="schwab_rollover_ira",
                                 target_path=str(path), skip_transfer_detect=True)
    assert res.get("wrote"), res
    out = {r["symbol"]: r for r in json.loads(path.read_text(encoding="utf-8"))["holdings"]}
    assert out["MCD"]["cost_basis"] == pytest.approx(47137.0)
    assert out["SCHD"]["cost_basis"] == pytest.approx(2500.0)
