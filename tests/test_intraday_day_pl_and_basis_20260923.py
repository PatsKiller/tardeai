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


def test_partial_sell_realizes_sold_shares_and_marks_only_what_is_left():
    fills = {"buys": [], "sells": [(411.0, 19.135)]}
    got = pr._intraday_day_change(4.6535, 19.17, 19.30, fills)
    # 415.6535 held at the open: 411 sold realize (19.135-19.30); the 4.6535 kept mark (19.17-19.30).
    # (The first version valued all 415.65 at the current price AND counted the 411 sold.)
    assert got == pytest.approx(round(411 * (19.135 - 19.30) + 4.6535 * (19.17 - 19.30), 2))


def test_same_day_round_trip_realizes_sell_minus_buy():
    # held 0 at the open; buy 100 @ 10 then sell 100 @ 11 -> realized +100, nothing left to mark
    fills = {"events": [("buy", 100.0, 10.0), ("sell", 100.0, 11.0)]}
    assert pr._intraday_day_change(0.0, 12.0, 9.0, fills) == pytest.approx(100.0)


def test_sell_consumes_open_shares_before_todays_buys():
    # 100 held at the open (prev 50); buy 100 @ 52; sell 100 @ 53 -> sells the open lot first
    fills = {"events": [("buy", 100.0, 52.0), ("sell", 100.0, 53.0)]}
    got = pr._intraday_day_change(100.0, 54.0, 50.0, fills)
    assert got == pytest.approx(100 * (53 - 50) + 100 * (54 - 52))


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
    assert got[("schwab_roth", "SCHD")] == {"events": [("buy", 10.0, 27.5)], "buys": [(10.0, 27.5)], "sells": []}
    assert got[("schwab_taxable", "DIV")] == {
        "events": [("sell", 411.0, 19.135)],
        "buys": [],
        "sells": [(411.0, 19.135)],
    }


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


# ── positions fully sold today ───────────────────────────────────────────────


def test_closed_today_position_counts_its_realized_day_pl():
    holdings = [{"symbol": "MCD", "account": "schwab_rollover_ira", "shares": 200.0}]
    fills = {("schwab_taxable", "DIV"): {"events": [("sell", 415.6535, 19.135)], "buys": [],
                                         "sells": [(415.6535, 19.135)]}}
    out = pr._closed_today_day_change(holdings, fills, {"DIV": 19.30})
    (row,) = out["schwab_taxable"]
    assert row["symbol"] == "DIV"
    assert row["day_change"] == pytest.approx(round(415.6535 * (19.135 - 19.30), 2))


def test_closed_today_skips_held_symbols_and_reports_missing_prev_close():
    holdings = [{"symbol": "MCD", "account": "schwab_rollover_ira", "shares": 200.0}]
    fills = {
        ("schwab_rollover_ira", "MCD"): {"events": [("sell", 10.0, 240.0)], "buys": [], "sells": [(10.0, 240.0)]},
        ("schwab_taxable", "XYZ"): {"events": [("sell", 5.0, 10.0)], "buys": [], "sells": [(5.0, 10.0)]},
    }
    out = pr._closed_today_day_change(holdings, fills, {})
    assert "schwab_rollover_ira" not in out
    assert out["schwab_taxable"] == [{"symbol": "XYZ", "day_change": None, "reason": "no_prev_close"}]


def test_account_total_includes_closed_today_and_clears_it_next_run():
    portfolio = {
        "holdings": [{"symbol": "MCD", "account": "schwab_taxable", "shares": 10.0, "market_value": 2400.0,
                      "day_change": 50.0, "cost_basis": 2300.0, "gain_loss": 100.0}],
        "account_summaries": {"schwab_taxable": {"source": "schwab"}},
        "closed_today": {"schwab_taxable": [{"symbol": "DIV", "day_change": -68.58}]},
    }
    pr._recalc_totals(portfolio)
    acct = portfolio["account_summaries"]["schwab_taxable"]
    assert acct["day_change"] == pytest.approx(50.0 - 68.58)
    assert acct["closed_today_day_change"] == pytest.approx(-68.58)
    portfolio["closed_today"] = {}
    pr._recalc_totals(portfolio)
    assert acct["day_change"] == pytest.approx(50.0)
    assert "closed_today" not in acct


# ── cross-check against Schwab's own P/L Day ─────────────────────────────────


def _today_utc_iso():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def test_broker_check_matches_schwab_at_its_mark():
    # Live 2026-09-23: Schwab MCD day_pl 369.0 at 237.53 — ours at that mark is identical.
    h = {"broker_day_pl": 369.0, "broker_day_pl_price": 237.53, "broker_day_pl_at": _today_utc_iso()}
    chk = pr._broker_day_pl_check(h, 200.0, 250.35, MCD_FILLS)
    assert chk["ours_at_broker_mark"] == pytest.approx(369.0)
    assert chk["ok"] is True


def test_broker_check_tolerates_prev_close_rounding():
    # Live 2026-09-23 DIV: Schwab -76.98 vs ours -74.79 — half a cent of prev close on 415 shares.
    h = {"broker_day_pl": -76.98, "broker_day_pl_price": 19.1146, "broker_day_pl_at": _today_utc_iso()}
    fills = {"events": [("sell", 411.0, 19.135)], "buys": [], "sells": [(411.0, 19.135)]}
    chk = pr._broker_day_pl_check(h, 4.6535, 19.315, fills)
    assert chk["ok"] is True and abs(chk["diff"]) > 1.0


def test_broker_check_flags_a_disagreement_and_ignores_stale_figures():
    h = {"broker_day_pl": 369.0, "broker_day_pl_price": 237.53, "broker_day_pl_at": _today_utc_iso()}
    chk = pr._broker_day_pl_check(h, 200.0, 250.35, None)  # plain formula: -2,564
    assert chk["ok"] is False and chk["diff"] < -2000
    stale = dict(h, broker_day_pl_at="2026-09-01T15:00:00+00:00")
    assert pr._broker_day_pl_check(stale, 200.0, 250.35, MCD_FILLS) is None


def test_transport_normalizer_carries_schwab_day_pl():
    import schwab_transport

    raw = {"securitiesAccount": {"positions": [{
        "instrument": {"symbol": "MCD"}, "longQuantity": 200, "averagePrice": 235.685,
        "marketValue": 47506.0, "longOpenProfitLoss": 369.0,
        "currentDayProfitLoss": 369.0, "currentDayProfitLossPercentage": 0.78}]}}
    (p,) = schwab_transport.normalize_positions(raw)
    assert p["day_pl"] == 369.0 and p["day_pl_pct"] == 0.78


def test_position_sync_stores_broker_day_pl_with_its_mark(no_side_effects):
    live = [{"symbol": "MCD", "qty": 200, "current_price": 237.53, "market_value": 47506.0,
             "avg_entry_price": 235.685, "day_pl": 369.0}]
    rows, _ = sps._build_account_rows("schwab_rollover_ira", live, {})
    (row,) = rows
    assert row["broker_day_pl"] == 369.0
    assert row["broker_day_pl_price"] == pytest.approx(237.53)
    assert row["broker_day_pl_at"]
