"""LQ-20261113-3124R — the four portfolio measures, computed once by the writer and read by every surface.

Synthetic fixtures only. The defect: on 2026-11-13 the same book published two different figures under the name
"today"/"1D" — the header's stored-row sum and the Portfolio page's re-marked sum — and the difference between
them was a whole **valuation correction** (the broker mark -> live mark re-mark) that had been added into
"today". The production values of that day stay in persistent-state scratch (FINDING-3124R-recon) and are
deliberately not repeated here; the repository is public.

The operator's ruling (2026-11-13 23:10 ET) is the contract these tests pin:

* broker-reported values and broker evidence are the accounting anchor; Finviz marks are a separate,
  timestamped estimate, never added to any "today" figure;
* the four measures are distinct and carry their own labels:
  1. "Account value"
  2. "Estimated price movement of current holdings"
  3. "Account value change since prior close"
  4. "Verified daily P&L" (UNKNOWN until a stored, signed reconciliation exists);
* ONE shared function feeds both screens, and it runs in the WRITER: the read path publishes the stored block
  and never computes one (a second calculation carries a second clock).
"""
from __future__ import annotations

from datetime import datetime, timezone

from scripts.lib import cio_truth as truth
from scripts.lib import portfolio_measures as pm
from scripts import portfolio_repricer as repricer

NOW = datetime(2026, 11, 13, 22, 52, tzinfo=timezone.utc)   # 17:52 ET, 2026-11-13
TODAY = "2026-11-13"


def _row(symbol, shares=10, price=20.0, **kw):
    base = {"symbol": symbol, "account": "fixture_taxable", "shares": shares, "price": price,
            "current_price": price, "market_value": round(shares * price, 2),
            "broker_market_value": round(shares * price, 2), "broker_shares": shares}
    base.update(kw)
    return base


def _doc(rows, **kw):
    out = {"last_repriced": "2026-11-13 22:45:01 ET", "generated_at": "2026-11-13 22:45:01 ET",
           "positions_built_at": "2026-11-13 22:30:00 ET", "reprice_source": "finviz_live",
           "holdings": rows}
    out.update(kw)
    return out


def _prior(rows, as_of="2026-11-12T21:30:00-05:00", source="fixture snapshot run 1"):
    return {"as_of": as_of, "source": source, "rows": rows}


def _book(rows, *, prior=None, trades=(), income=None, external_flows=None, transfers=None, **doc_kw):
    return pm.portfolio_measures(_doc(rows, **doc_kw), prior_snapshot=prior,
                                 trades=None if trades is None else list(trades),
                                 income=income, external_flows=external_flows,
                                 transfers=None if transfers is None else list(transfers), now=NOW)


def _m(rows, **kw):
    return _book(rows, **kw)["measures"]


# ---------------------------------------------------------------- 1. Account value: the broker anchor

def test_account_value_is_the_broker_anchor_and_the_finviz_mark_is_a_separate_timestamped_estimate():
    rows = [_row("ZZAA", 10, 18.26, broker_market_value=182.60, canonical_mark=19.11,
                 canonical_mark_ingested_at="2026-11-13T22:45:00Z")]
    value = _m(rows)["account_value"]
    assert value["value"] == 182.60
    assert value["basis"] == pm.BASIS_STORE and value["status"] == "MEASURED"
    assert value["label"] == "Account value"
    estimate = value["finviz_estimate"]
    assert estimate["value"] == 191.10
    assert estimate["marks_at"] == "2026-11-13T22:45:00Z"
    assert estimate["delta"] == 8.50           # Finviz sits ABOVE the broker mark: a valuation gap, not profit
    assert "never added" in estimate["note"]


def test_a_cash_row_with_no_broker_fields_still_carries_its_balance():
    rows = [_row("ZZAA", 10, 20.0),
            _row("CASH", 5000, 1.0, is_cash=True, market_value=5000.0, broker_market_value=None,
                 broker_shares=None)]
    assert _m(rows)["account_value"]["value"] == 5200.0


def test_a_row_that_cannot_be_valued_makes_the_account_value_unknown_not_short():
    rows = [_row("ZZAA", 10, 20.0, broker_market_value=None)]
    value = _m(rows)["account_value"]
    assert value["value"] is None and value["status"] == "UNKNOWN"
    assert value["gap"]["unvalued_rows"][0]["symbol"] == "ZZAA"


# ---------------------------------------------------------------- 2. estimated price movement

def test_the_price_move_is_measured_from_the_brokers_own_prior_close():
    rows = [_row("ZZAA", 10, 19.00, prior_close=20.00)]
    move = _m(rows)["price_move_estimate"]
    assert move["value"] == -10.0 and move["status"] == "MEASURED"
    assert move["row_basis_census"] == {"broker_prior_close": 1}
    assert move["rows"][0]["baseline_source"] == "broker_prior_close"
    assert move["label"] == "Estimated price movement of current holdings"


def test_without_a_prior_close_the_last_observed_book_value_is_the_baseline():
    rows = [_row("ZZAA", 10, 20.0)]
    move = _m(rows, prior=_prior({("fixture_taxable", "ZZAA"): 180.0}))["price_move_estimate"]
    assert move["value"] == 20.0
    assert move["rows"][0]["baseline_source"] == "fixture snapshot run 1"


def test_the_brokers_day_pl_is_a_last_resort_baseline_only_when_its_own_check_agrees():
    ok = _m([_row("ZZAA", 10, 20.0, broker_day_pl=5.0)])["price_move_estimate"]
    assert ok["value"] == 5.0 and ok["rows"][0]["baseline_source"] == "broker_day_pl"
    contradicted = _m([_row("ZZAA", 10, 20.0, broker_day_pl=5.0,
                            day_change_broker_check={"ok": False})])["price_move_estimate"]
    assert contradicted["value"] is None and contradicted["status"] == "UNKNOWN"


def test_a_row_with_no_baseline_is_unknown_not_zero_and_the_move_is_partial():
    rows = [_row("ZZAA", 10, 19.00, prior_close=20.00), _row("ZZBB", 10, 10.0)]
    move = _m(rows)["price_move_estimate"]
    assert move["status"] == "PARTIAL" and move["value"] == -10.0
    assert move["coverage"]["unknown_rows"] == 1
    assert move["coverage"]["unknown"][0]["symbol"] == "ZZBB"


def test_cash_and_positions_sold_today_are_not_price_moves():
    rows = [_row("ZZAA", 10, 19.00, prior_close=20.00),
            _row("CASH", 5000, 1.0, is_cash=True, market_value=5000.0, broker_market_value=None,
                 broker_shares=None)]
    move = _m(rows)["price_move_estimate"]
    assert move["value"] == -10.0
    assert move["row_basis_census"].get("cash") == 1


# ---------------------------------------------------------------- 3. account value change since prior close

def _algebra_book(**over):
    """A book whose every dollar the drill-down must assign, with a fund NAV term and one sale.

    S = the open rows' price move; A = the fund's NAV step (arriving as a stored zero plus a broker term);
    X = the sale's effect against the prior close of what was sold. The header's figure is S + A; the
    store/page figure is S + X; both must reconcile to the same ending equity.
    """
    rows = [
        _row("ZZAA", 10, 19.00, prior_close=20.00),                                    # -10.00
        _row("ZZTB", 10, 10.00, prior_close=10.00),                                    #   0.00
        _row("FXFD", 2, 42.50, prior_close=50.00, day_change=0.0, day_change_pct=0.0,  # -15.00 (A)
             broker_day_pl=-15.00, broker_day_pl_at="2026-11-14T04:03:04Z"),
        _row("CASH", 1447.0, 1.0, is_cash=True, market_value=1447.0, broker_market_value=None,
             broker_shares=None),
    ]
    prior = _prior({("fixture_taxable", "ZZAA"): 200.0, ("fixture_taxable", "ZZTB"): 100.0,
                    ("fixture_taxable", "FXFD"): 100.0, ("fixture_taxable", "CASH"): 1000.0,
                    ("fixture_taxable", "ZZX"): 500.0})
    doc = {"closed_today": {"fixture_taxable": [{"symbol": "ZZX", "sold_qty": 100, "prev_close": 5.00,
                                                 "day_change": -52.00}]}}
    trades = [{"account": "fixture_taxable", "symbol": "ZZX", "action": "SELL",
               "quantity": 100, "amount": 448.00, "fees": 1.00}]
    doc.update(over)
    return rows, prior, trades, doc


def test_the_change_since_prior_close_is_two_observed_equities_with_the_sale_between_them():
    rows, prior, trades, doc = _algebra_book()
    change = pm.portfolio_measures(_doc(rows, **doc), prior_snapshot=prior, trades=trades,
                                   income=0.0, external_flows=0.0, transfers=[], now=NOW
                                   )["measures"]["account_value_change_1d"]
    assert change["value"] == -78.00
    assert change["status"] == "MEASURED"
    assert change["start"]["equity_usd"] == 1900.0
    assert change["start"]["as_of"] == "2026-11-12T21:30:00-05:00"
    assert change["end"]["equity_usd"] == 1822.0
    dd = change["drill_down"]
    assert dd["price_move_estimate"] == -25.00          # S + A, the fund's NAV step included once
    # The sale's effect is gross of its commission; the commission is its own NEGATIVE line. Netting the fee
    # into the effect (the earlier shape) gave a +1.00 component whose only purpose was to make it close.
    assert dd["closed_today_trade_effect"] == -52.00    # 448.00 gross - 500.00 prior close
    assert dd["fees_today"] == -1.00
    assert dd["reconciles"] is True                     # -25.00 + -52.00 + -1.00 == -78.00
    assert dd["reconciles_unobserved"] == []


def test_the_fund_nav_step_is_counted_once_on_both_sides():
    """The fund's NAV step must be present exactly once on the price-move side and exactly once in the ending
    equity. Summing the Finviz estimate as well would count it twice; dropping it would lose it."""
    rows, prior, trades, doc = _algebra_book()
    out = pm.portfolio_measures(_doc(rows, **doc), prior_snapshot=prior, trades=trades, now=NOW)
    move = out["measures"]["price_move_estimate"]
    change = out["measures"]["account_value_change_1d"]
    assert move["value"] == -25.00
    assert change["value"] == -78.00
    # The fund contributes its -15.00 to the move through its own prior close...
    fund = [r for r in move["rows"] if r["symbol"] == "FXFD"][0]
    assert fund["move_usd"] == -15.00 and fund["baseline_source"] == "broker_prior_close"
    # ...and the same -15.00 appears in the SEPARATE Finviz block as a broker NAV term, never added back.
    fin = move["finviz_estimate"]
    nav = fin["broker_nav_rows"]
    assert [(r["symbol"], r["value_usd"], r["reported_at"]) for r in nav] == [
        ("FXFD", -15.00, "2026-11-14T04:03:04Z")]
    # (d) The fund's day is dated by its observation pair, not by the broker's response stamp.
    assert nav[0]["prior_observed_usd"] == 100.0 and nav[0]["current_usd"] == 85.0
    assert "not the NAV publication time" in nav[0]["reported_at_is"]
    assert "never added" in fin["note"]
    assert change["drill_down"]["price_move_estimate"] == move["value"]


def test_a_change_without_a_prior_close_cash_observation_is_unknown_and_says_why():
    rows = [_row("ZZAA", 10, 19.00, prior_close=20.00),
            _row("CASH", 5000, 1.0, is_cash=True, market_value=5000.0, broker_market_value=None,
                 broker_shares=None)]
    change = _m(rows)["account_value_change_1d"]
    assert change["value"] is None and change["status"] == "PARTIAL"
    assert change["gap"]["start_unknown"][0]["symbol"] == "CASH"
    assert "derived" in change["gap"]["reason"]


def test_a_closed_row_with_no_trade_row_reports_gross_and_is_not_called_complete():
    rows = [_row("ZZAA", 10, 20.0, prior_close=20.00)]
    # ZZX is in the prior book, so the sale is inside the interval and the row is in scope (the per-row rule).
    prior = _prior({("fixture_taxable", "ZZAA"): 200.0, ("fixture_taxable", "CASH"): 0.0,
                    ("fixture_taxable", "ZZX"): 50.0})
    doc = {"closed_today": {"fixture_taxable": [{"symbol": "ZZX", "sold_qty": 10, "prev_close": 5.00,
                                                 "day_change": -3.00}]}}
    change = pm.portfolio_measures(_doc(rows, **doc), prior_snapshot=prior, trades=[],
                                   now=NOW)["measures"]["account_value_change_1d"]
    dd = change["drill_down"]
    assert dd["closed_today_trade_effect"] == -3.00
    # A component was never read, so `reconciles` is null with the gap named — "false" would claim a
    # contradiction the reader cannot actually see.
    assert dd["fees_today"] is None and dd["reconciles"] is None
    assert dd["reconciles_unobserved"] == ["fees_today", "income_today", "external_flows_today"]
    assert dd["closed_today_rows"][0]["source"] == "closed_today_stored_gross"
    assert dd["closed_today_complete"] is False


def test_a_sold_row_with_no_share_count_is_not_silently_treated_as_zero_shares():
    """A missing share count is an unknown, not a zero: reading it as 0 would set the prior-close value of the
    sale to 0.00 and inflate the day's trade effect by the whole proceeds. The stored row exists, so the
    component is published as unknown (``None``) rather than as 0.00, which would claim no effect at all."""
    rows = [_row("ZZAA", 10, 20.0, prior_close=20.00)]
    prior = _prior({("fixture_taxable", "ZZAA"): 200.0, ("fixture_taxable", "CASH"): 0.0,
                    ("fixture_taxable", "ZZX"): 50.0})
    doc = {"closed_today": {"fixture_taxable": [{"symbol": "ZZX", "prev_close": 5.00}]}}   # no sold_qty
    trades = [{"account": "fixture_taxable", "symbol": "ZZX", "action": "SELL",
               "quantity": 10, "amount": 55.00, "fees": 1.00}]
    dd = pm.portfolio_measures(_doc(rows, **doc), prior_snapshot=prior, trades=trades,
                               now=NOW)["measures"]["account_value_change_1d"]["drill_down"]
    assert dd["closed_today_trade_effect"] is None and dd["closed_today_rows"] == []
    assert dd["closed_today_complete"] is False and dd["reconciles"] is None


def test_a_matched_trade_with_an_unread_fee_is_an_upper_bound_and_is_not_called_reconciled():
    rows = [_row("ZZAA", 10, 20.0, prior_close=20.00)]
    prior = _prior({("fixture_taxable", "ZZAA"): 200.0, ("fixture_taxable", "CASH"): 0.0})
    doc = {"closed_today": {"fixture_taxable": [{"symbol": "ZZX", "sold_qty": 10, "prev_close": 5.00}]}}
    trades = [{"account": "fixture_taxable", "symbol": "ZZX", "action": "SELL",
               "quantity": 10, "amount": 55.00}]                                          # no fees column
    dd = pm.portfolio_measures(_doc(rows, **doc), prior_snapshot=prior, trades=trades,
                               now=NOW)["measures"]["account_value_change_1d"]["drill_down"]
    assert dd["closed_today_trade_effect"] == 5.00      # 55.00 - 50.00, before any unknown commission
    assert dd["closed_today_rows"][0]["fees_usd"] is None
    assert dd["closed_today_complete"] is False and dd["fees_today"] is None
    assert dd["reconciles"] is None and "fees_today" in dd["reconciles_unobserved"]


# ------------------------------------------- 3b. the signed per-account reconciliation + coverage

def _two_account_book(*, cash_moved=True):
    rows = [
        _row("ZZAA", 10, 19.00, prior_close=20.00, account="acct_a"),                 # -10.00
        _row("CASH", 1100, 1.0, account="acct_a", is_cash=True, market_value=1100.0,
             broker_market_value=None, broker_shares=None),
        _row("ZZBB", 5, 40.00, prior_close=40.00, account="acct_b"),                  #   0.00
        _row("CASH", 400, 1.0, account="acct_b", is_cash=True, market_value=400.0,
             broker_market_value=None, broker_shares=None),
    ]
    prior = _prior({("acct_a", "ZZAA"): 200.0, ("acct_a", "CASH"): 1000.0,
                    ("acct_b", "ZZBB"): 200.0, ("acct_b", "CASH"): 500.0})
    transfers = ([{"from_account": "acct_b", "to_account": "acct_a", "amount": 100.0,
                   "transfer_type": "internal", "transfer_date": "2026-11-13"}]
                 if cash_moved else [])
    return rows, prior, transfers


def test_the_reconciliation_is_signed_per_account_and_an_internal_transfer_cancels():
    """a: each account's own ending - starting against its named components; an internal transfer moves
    value between accounts and must cancel in the consolidated total (only the price move survives)."""
    rows, prior, transfers = _two_account_book()
    out = _book(rows, prior=prior, income=0.0, external_flows=0.0, transfers=transfers)
    recon = out["reconciliation"]
    by_acct = {a["account"]: a for a in recon["accounts"]}
    assert by_acct["acct_a"]["delta_usd"] == 90.00
    assert by_acct["acct_a"]["components"]["price_move"] == -10.00
    assert by_acct["acct_a"]["components"]["internal_transfers_today"] == 100.00
    assert by_acct["acct_b"]["components"]["internal_transfers_today"] == -100.00
    for acct in ("acct_a", "acct_b"):
        assert by_acct[acct]["status"] == "RECONCILED", acct
        assert by_acct[acct]["residual"]["value_usd"] == 0.00
        assert by_acct[acct]["residual"]["within_tolerance"] is True
    assert recon["total"]["delta_usd"] == -10.00        # +90.00 and -100.00 cancel; only the move remains
    assert recon["total"]["explained_usd"] == -10.00
    assert recon["total"]["status"] == "RECONCILED"
    assert recon["internal_transfers"][0]["internal"] is True
    # The transfers ledger WAS read and holds no external row: 0.00, not null. Null is reserved for "not read".
    assert recon["external_flows_net_usd"] == 0.00


def test_an_unexplained_residual_is_reported_and_never_allocated_to_a_component():
    """c: cash moved by 100.00 with no transfer row to explain it. The residual carries the 100.00, the
    components are untouched, and the verified P&L label does not move."""
    rows, prior, _ = _two_account_book(cash_moved=False)
    out = _book(rows, prior=prior, income=0.0, external_flows=0.0, transfers=[])
    recon = out["reconciliation"]
    by_acct = {a["account"]: a for a in recon["accounts"]}
    assert by_acct["acct_a"]["delta_usd"] == 90.00
    assert by_acct["acct_a"]["explained_usd"] == -10.00     # the move only; nothing absorbed the +100
    assert by_acct["acct_a"]["residual"]["value_usd"] == 100.00
    assert by_acct["acct_a"]["residual"]["within_tolerance"] is False
    assert by_acct["acct_a"]["status"] == "UNEXPLAINED"
    # The same 100.00 left acct_b: the two cancel in the consolidated total, which is why an unrecorded
    # internal movement can reconcile overall while no account can be signed on its own.
    assert by_acct["acct_b"]["residual"]["value_usd"] == -100.00
    assert recon["total"]["residual"]["value_usd"] == 0.00
    assert recon["total"]["status"] == "UNEXPLAINED"        # per-account signing is the operator's bar
    assert out["measures"]["verified_daily_pnl"]["status"] == "UNKNOWN"
    assert out["measures"]["verified_daily_pnl"]["known_components"]["reconciliation_residual_usd"] == 0.00


def test_an_unobserved_component_makes_the_account_partial_with_the_named_gap():
    rows, prior, transfers = _two_account_book()
    out = _book(rows, prior=prior, transfers=transfers)      # income and external flows not observed
    recon = out["reconciliation"]
    acct = recon["accounts"][0]
    assert acct["components"]["income_today"] is None          # not observed -> null, never 0
    assert acct["components"]["external_flows_today"] == 0.00  # ledger read, none found -> 0.00
    assert "income_today" in acct["unobserved"]
    assert acct["status"] == "PARTIAL"
    assert out["measures"]["verified_daily_pnl"]["status"] == "UNKNOWN"


def test_source_coverage_names_every_source_it_did_not_read():
    rows = [_row("ZZAA", 10, 19.00, prior_close=20.00)]
    cov = _book(rows, trades=None)["source_coverage"]
    assert cov["prior_close_book"]["observed"] is False and "stay UNKNOWN" in cov["prior_close_book"]["reason"]
    assert cov["trades_today"]["observed"] is False
    assert cov["transfers_today"]["observed"] is False
    assert cov["income"]["observed"] is False and "UNKNOWN rather than zero" in cov["income"]["reason"]
    full = _book(rows, prior=_prior({("fixture_taxable", "ZZAA"): 200.0}), trades=[], transfers=[],
                 income=0.0)
    cov = full["source_coverage"]
    assert cov["prior_close_book"]["observed"] is True
    assert cov["trades_today"]["observed"] is True and cov["transfers_today"]["observed"] is True
    assert cov["income"]["observed"] is True
    assert cov["transfers_today"]["rows"] == 0


def test_a_partial_total_never_publishes_a_signed_residual():
    """Live evidence, 2026-11-14: on the real book the sum of the KNOWN components equalled the consolidated
    delta exactly — a 0.00 residual, "within tolerance" — while every one of the five accounts was PARTIAL
    because income had no source. A 0.00 under a "residual" label is a signedness claim that reads as
    reconciled on screen. The signed value is withheld as null, the arithmetic over what WAS read is published
    beside it under its own name, and the unread component is named."""
    rows, prior, transfers = _two_account_book()
    recon = _book(rows, prior=prior, transfers=transfers)["reconciliation"]   # income not observed
    total = recon["total"]
    assert total["status"] == "PARTIAL"
    assert total["residual"]["value_usd"] is None           # never a confident 0.00
    assert total["residual"]["within_tolerance"] is False
    assert total["residual"]["provisional"] is True
    assert total["residual"]["unknown_components"] == ["income_today"]
    assert total["residual"]["known_components_residual_usd"] == 0.00    # the arithmetic, labelled as such
    acct = recon["accounts"][0]
    assert acct["residual"]["value_usd"] is None and acct["residual"]["provisional"] is True
    assert acct["residual"]["unknown_components"] == ["income_today"]
    # The arithmetic over what WAS read is still published, under its own name: +0.47 in this fixture.
    assert acct["residual"]["known_components_residual_usd"] == 0.00
    # ...and the verified label still does not move.
    assert _book(rows, prior=prior, transfers=transfers)["measures"]["verified_daily_pnl"]["status"] == "UNKNOWN"


def test_a_fee_is_a_negative_component_and_a_residual_is_reported_not_absorbed():
    """The sale's fee gets a fixed sign. A store whose cash has not yet reflected the commission leaves a
    residual that is REPORTED — the earlier shape netted the fee into the trade effect and then added it back
    positive, which closed every account by construction and hid exactly this case."""
    rows = [_row("CASH", 1448.0, 1.0, is_cash=True, market_value=1448.0, broker_market_value=None,
                 broker_shares=None)]                                   # gross booked, fee not yet charged
    prior = _prior({("fixture_taxable", "CASH"): 1000.0, ("fixture_taxable", "ZZX"): 500.0})
    doc = {"closed_today": {"fixture_taxable": [{"symbol": "ZZX", "sold_qty": 100, "prev_close": 5.00}]}}
    trades = [{"account": "fixture_taxable", "symbol": "ZZX", "action": "SELL",
               "quantity": 100, "amount": 448.00, "fees": 1.00}]
    out = _book(rows, prior=prior, trades=trades, income=0.0, external_flows=0.0, transfers=[], **doc)
    acct = out["reconciliation"]["accounts"][0]
    assert acct["delta_usd"] == -52.00                      # the cash the store holds
    assert acct["components"]["closed_today_trade_effect"] == -52.00   # gross proceeds - prior close
    assert acct["components"]["fees_today"] == -1.00                   # the cost, negative
    assert acct["explained_usd"] == -53.00
    assert acct["residual"]["value_usd"] == 1.00            # reported, never allocated to a component
    assert acct["residual"]["known_components_residual_usd"] == 1.00
    assert acct["residual"]["within_tolerance"] is False
    assert acct["status"] == "UNEXPLAINED"
    assert out["measures"]["verified_daily_pnl"]["status"] == "UNKNOWN"


def test_the_drill_down_and_the_signed_bridge_add_up_to_the_same_change():
    """ONE calculation feeds both screens: measure 3's drill-down and the per-account bridge are the same
    five named parts, so they cannot disagree about the day."""
    rows, prior, transfers = _two_account_book()
    out = _book(rows, prior=prior, income=0.0, external_flows=0.0, transfers=transfers)
    change = out["measures"]["account_value_change_1d"]
    dd = change["drill_down"]
    assert dd["reconciles"] is True and dd["reconciles_unobserved"] == []
    assert (round(dd["price_move_estimate"] + dd["closed_today_trade_effect"] + dd["fees_today"]
                  + dd["income_today"] + dd["external_flows_today"], 2)) == change["value"]
    for component in ("price_move_estimate", "closed_today_trade_effect", "fees_today",
                      "income_today", "external_flows_today"):
        assert dd[component] == out["measures"]["verified_daily_pnl"]["known_components"][component]


# ---------------------------------------------------------------- 4. verified daily P&L

def test_verified_daily_pnl_stays_unknown_until_a_stored_signed_reconciliation_exists():
    rows = [_row("ZZAA", 10, 19.00, prior_close=20.00)]
    verified = _m(rows)["verified_daily_pnl"]
    assert verified["value"] is None and verified["status"] == "UNKNOWN"
    assert verified["label"] == "Verified daily P&L"
    assert "matched" in verified["gap"]["reason"]
    assert verified["known_components"]["price_move_estimate"] == -10.0
    assert verified["known_components"]["income_today"] is None


def test_a_stored_verified_reconciliation_is_published_by_the_writer_not_recomputed():
    rows = [_row("ZZAA", 10, 19.00, prior_close=20.00)]
    stored = {"verified": True, "value": -12.5, "as_of": "2026-11-14T03:00:00Z",
              "source": "recon 3124R, signed"}
    verified = _m(rows, verified_reconciliation=stored)["verified_daily_pnl"]
    assert verified["value"] == -12.5 and verified["status"] == "VERIFIED"
    assert verified["source"] == "recon 3124R, signed"
    assert verified["candidate"] == -10.0            # the unverified candidate stays beside it


# ---------------------------------------------------------------- the contract itself

def test_the_four_measures_are_distinct_and_named_for_what_they_measure():
    out = _book([_row("ZZAA", 10, 19.00, prior_close=20.00)])
    labels = out["labels"]
    assert set(labels) == {"account_value", "price_move_estimate", "account_value_change_1d",
                           "verified_daily_pnl"}
    assert labels["account_value"] == "Account value"
    assert labels["price_move_estimate"] == "Estimated price movement of current holdings"
    assert labels["account_value_change_1d"] == "Account value change since prior close"
    assert labels["verified_daily_pnl"] == "Verified daily P&L"
    assert len(set(labels.values())) == 4
    assert out["basis"]["applied"] == pm.BASIS_STORE
    assert "anchor" in out["basis"]["why"]


def test_the_finviz_estimate_never_moves_any_of_the_four_measures():
    """Same broker facts, different Finviz marks: measures 1-4 must not budge."""
    base = _row("ZZAA", 10, 19.00, prior_close=20.00, broker_day_pl=None)
    low = _m([{**base, "canonical_mark": 19.00, "day_change": -10.0}])
    high = _m([{**base, "canonical_mark": 25.00, "day_change": 60.0,
                "canonical_mark_ingested_at": "2026-11-13T22:45:00Z"}])
    for key in ("account_value", "price_move_estimate", "account_value_change_1d", "verified_daily_pnl"):
        assert low[key]["value"] == high[key]["value"], key
    assert low["price_move_estimate"]["finviz_estimate"]["total_with_broker_nav"] == -10.0
    assert high["price_move_estimate"]["finviz_estimate"]["total_with_broker_nav"] == 60.0


def test_a_row_with_no_mark_is_counted_unmeasured_in_the_estimate_not_passed_through_as_zero():
    row = {"symbol": "ZZNM", "account": "fixture_taxable", "shares": 10, "broker_shares": 10}
    fin = _m([_row("ZZAA", 10, 19.00, prior_close=20.00, day_change=-10.0),
              row])["price_move_estimate"]["finviz_estimate"]
    assert fin["unmeasured_rows"] == 1 and fin["unmeasured"][0]["symbol"] == "ZZNM"
    assert fin["measured_rows"] == 1


def test_a_document_with_no_stored_measures_publishes_unknown_and_get_does_not_compute():
    absent = pm.measures_absent({"holdings": [_row("ZZAA", 10, 19.00, prior_close=20.00)]})
    assert absent["materialized"] is False and absent["status"] == "UNKNOWN"
    assert absent["measures"]["price_move_estimate"]["value"] is None
    assert "GET never computes" in absent["gap"]["reason"]


# ---------------------------------------------------------------- the writer materializes, the read reads

def _fake_db(rows_by_sql, calls=None):
    def db_query(sql, params=None, fetch="all"):
        if calls is not None:
            calls.append((sql, params))
        for marker, rows in rows_by_sql:
            if marker in sql:
                return rows
        return []
    return db_query


def test_the_writer_stores_the_measures_on_the_document_it_writes():
    rows = [_row("ZZAA", 10, 19.00, prior_close=20.00),
            _row("CASH", 1000.0, 1.0, is_cash=True, market_value=1000.0, broker_market_value=None,
                 broker_shares=None)]
    portfolio = _doc(rows, portfolio_totals={"total_value": 1190.0})
    db = _fake_db([
        ("position_snapshots", [
            {"sync_run_id": 7, "captured_at": datetime(2026, 11, 12, 21, 30, tzinfo=timezone.utc),
             "account_key": "fixture_taxable", "symbol": "ZZAA", "qty": 10,
             "broker_market_value": 200.0, "is_cash": False},
            {"sync_run_id": 7, "captured_at": datetime(2026, 11, 12, 21, 30, tzinfo=timezone.utc),
             "account_key": "fixture_taxable", "symbol": "CASH", "qty": 1000.0,
             "broker_market_value": None, "is_cash": True},
        ]),
        ("trade_transactions", []),
    ])
    repricer._materialize_measures(portfolio, db_query=db, now=NOW)
    block = portfolio["measures"]
    assert block["materialized"] is True
    assert block["contract_version"] == pm.CONTRACT_VERSION
    assert block["measures"]["account_value"]["value"] == 1190.0
    assert block["measures"]["price_move_estimate"]["value"] == -10.0
    change = block["measures"]["account_value_change_1d"]
    assert change["value"] == -10.00
    assert change["start"]["equity_usd"] == 1200.0   # 10 x 20.00 prior close + 1000 observed cash
    assert "input_gap" not in block
    # The transfers ledger was read (and had nothing for today): observed, 0 rows -- not "unknown".
    assert block["source_coverage"]["transfers_today"]["observed"] is True
    assert block["source_coverage"]["transfers_today"]["rows"] == 0
    assert block["reconciliation"]["total"]["status"] == "PARTIAL"   # income is not sourced by the writer
    assert block["measures"]["verified_daily_pnl"]["status"] == "UNKNOWN"


def test_a_database_outage_degrades_to_unknown_with_the_reason_and_never_fails_the_write():
    portfolio = _doc([_row("ZZAA", 10, 19.00, prior_close=20.00),
                      _row("CASH", 1000.0, 1.0, is_cash=True, market_value=1000.0,
                           broker_market_value=None, broker_shares=None)])

    def broken(sql, params=None, fetch="all"):
        raise RuntimeError("db down")

    repricer._materialize_measures(portfolio, db_query=broken, now=NOW)
    block = portfolio["measures"]
    assert block["materialized"] is True
    assert block["measures"]["account_value"]["value"] == 1190.0       # anchor measures still publish
    assert block["measures"]["price_move_estimate"]["value"] == -10.0
    change = block["measures"]["account_value_change_1d"]
    assert change["value"] is None
    assert "prior_close_book" in block["input_gap"]


def test_trades_are_read_for_the_et_trade_date_and_the_fee_is_paid_out_of_the_proceeds():
    calls = []
    db = _fake_db([("trade_transactions", [
        {"account": "fixture_taxable", "symbol": "ZZX", "action": "SELL", "quantity": 100,
         "amount": 448.0, "fees": 1.0}])], calls=calls)
    trades = repricer._trades_today(db, NOW)
    assert trades[0]["amount"] == 448.0 and trades[0]["fees"] == 1.0
    assert calls[0][1] == (TODAY,)                    # the ET date, not the UTC one


def test_transfers_are_read_for_the_et_date_and_classified_internal_or_external():
    calls = []
    db = _fake_db([("account_transfers", [
        {"transfer_date": TODAY, "from_account": "acct_b", "to_account": "acct_a", "amount": 100.0,
         "transfer_type": "internal"},
        {"transfer_date": TODAY, "from_account": None, "to_account": "acct_a", "amount": 250.0,
         "transfer_type": "deposit"}])], calls=calls)
    transfers = repricer._transfers_today(db, NOW)
    assert calls[0][1] == (TODAY,)
    block = pm._transfers_block(transfers, ["acct_a", "acct_b"])
    assert len(block["internal"]) == 1 and block["internal"][0]["to_account"] == "acct_a"
    assert len(block["external"]) == 1 and block["external"][0]["signed_usd"] == 250.00
    assert block["external_net_usd"] == 250.00


def test_a_transfer_with_no_readable_amount_is_unknown_not_a_zero_transfer():
    block = pm._transfers_block([{"from_account": None, "to_account": "acct_a", "amount": None}],
                                ["acct_a"])
    assert block["internal"] == [] and block["external"] == []
    assert block["unread"][0]["reason"] == "the transfer amount was not read"
    rows = [_row("ZZAA", 10, 19.00, prior_close=20.00)]
    out = _book(rows, prior=_prior({("fixture_taxable", "ZZAA"): 200.0}), trades=[], income=0.0,
                transfers=[{"from_account": None, "to_account": "fixture_taxable", "amount": None}])
    assert out["source_coverage"]["transfers_today"]["unread"] == 1
    assert "UNKNOWN" in out["source_coverage"]["transfers_today"]["reason"]
    acct = out["reconciliation"]["accounts"][0]
    assert acct["components"]["internal_transfers_today"] is None
    assert acct["status"] == "PARTIAL"


def test_a_failed_transfers_read_is_unknown_and_named_in_the_written_block():
    portfolio = _doc([_row("ZZAA", 10, 19.00, prior_close=20.00)])
    db = _fake_db([("position_snapshots", []), ("trade_transactions", [])])

    def db_query(sql, params=None, fetch="all"):
        if "account_transfers" in sql:
            raise RuntimeError("ledger down")
        return db(sql, params, fetch=fetch)

    repricer._materialize_measures(portfolio, db_query=db_query, now=NOW)
    block = portfolio["measures"]
    assert block["source_coverage"]["transfers_today"]["observed"] is False
    assert "transfers_today" in block["input_gap"]


# ---------------------------------------------------------------- one block, every surface

def _resolve(rows, **doc_kw):
    return truth.resolve(root=".", now=NOW,
                         inputs={"holdings": _doc(rows, **doc_kw), "do_now": None, "companies": {}})


def _stored(rows, **kw):
    return pm.portfolio_measures(_doc(rows), now=NOW, **kw)


def test_resolve_publishes_the_stored_block_verbatim_and_computes_nothing():
    rows = [_row("ZZAA", 10, 19.00, prior_close=20.00)]
    stored = {**_stored(rows), "generated_at": "2026-11-13T21:00:00Z"}
    doc = _resolve(rows, measures=stored)
    assert doc["measures"] == stored
    # The block's own clock is preserved: a recomputation on the read would stamp NOW instead.
    assert doc["measures"]["generated_at"] == "2026-11-13T21:00:00Z"


def test_a_document_written_before_the_block_publishes_unknown_measures():
    doc = _resolve([_row("ZZAA", 10, 19.00, prior_close=20.00)])
    assert doc["measures"]["materialized"] is False
    assert doc["measures"]["measures"]["price_move_estimate"]["value"] is None


def test_holdings_overview_and_today_move_all_read_the_same_measure():
    rows = [_row("ZZAA", 10, 19.00, prior_close=20.00)]
    stored = _stored(rows, prior_snapshot=_prior({("fixture_taxable", "ZZAA"): 200.0,
                                                  ("fixture_taxable", "CASH"): 0.0}))
    doc = _resolve(rows, measures=stored)
    page = truth.holdings_payload({"holdings": []}, document=doc)
    overview = truth.overview_payload({}, document=doc)
    move = truth.today_move_payload({"change": 999.0, "change_pct": 1.0}, {}, overview["today_pnl"])
    canonical = doc["measures"]["measures"]["price_move_estimate"]["value"]
    assert page["today_change"] == canonical == -10.0
    assert page["today_change_label"] == "Estimated price movement of current holdings"
    assert page["today_change_measure"] == "price_move_estimate"
    assert page["total_value"] == 190.0
    assert page["account_value_change_1d"] == -10.0
    assert page["account_value_change_1d_status"] == "MEASURED"
    assert page["verified_daily_pnl"] is None
    assert page["verified_daily_pnl_status"] == "UNKNOWN"
    assert move["change"] == canonical and move["measure"] == "price_move_estimate"
    assert move["market_day_cross_check"] == 999.0     # the other computation is kept as a named cross-check


def test_the_page_publishes_the_signed_reconciliation_and_its_source_coverage():
    """The drill-down the operator asked for: per-account evidence and which sources were read —
    published verbatim from the writer's block, with nothing computed on the GET."""
    rows = [_row("ZZAA", 10, 19.00, prior_close=20.00),
            _row("CASH", 1000.0, 1.0, is_cash=True, market_value=1000.0, broker_market_value=None,
                 broker_shares=None)]
    stored = _stored(rows, prior_snapshot=_prior({("fixture_taxable", "ZZAA"): 200.0,
                                                 ("fixture_taxable", "CASH"): 1000.0}),
                     trades=[], transfers=[], income=0.0)
    doc = _resolve(rows, measures=stored)
    page = truth.holdings_payload({"holdings": []}, document=doc)
    recon = page["reconciliation"]
    assert recon["contract_version"] == pm.RECONCILIATION_VERSION
    assert recon["accounts"][0]["account"] == "fixture_taxable"
    assert recon["accounts"][0]["residual"]["value_usd"] == 0.00
    assert page["reconciliation_status"] == "RECONCILED"
    assert page["source_coverage"]["transfers_today"]["observed"] is True
    assert page["source_coverage"]["income"]["observed"] is True
    assert page["source_coverage"]["prior_close_book"]["observed"] is True
    # The block the page shows is the stored one, not a second calculation.
    assert page["reconciliation"] is doc["measures"]["reconciliation"]
    assert page["source_coverage"] is doc["measures"]["source_coverage"]


def test_the_performance_1d_period_names_its_measure_and_its_baseline_is_still_derived():
    rows = [_row("ZZAA", 10, 19.00, prior_close=20.00)]
    stored = _stored(rows)
    doc = _resolve(rows, measures=stored)
    perf = truth.performance_payload({"periods": {"1D": {"change": -10.0, "start_value": 200.0}}},
                                     holdings_doc=_doc(rows), measures=doc["measures"])
    one_d = perf["periods"]["1D"]
    assert one_d["label"] == "Estimated price movement of current holdings"
    assert one_d["measure"] == "price_move_estimate"
    assert one_d["baseline_observed"] is False
    assert "derived" in one_d["baseline_note"]
    assert one_d["account_value_change_1d"] == -10.0
    assert one_d["account_value_change_1d_status"] == "MEASURED"
    assert one_d["account_value_change_1d_start_as_of"] is None   # no prior snapshot was supplied
    assert one_d["verified_daily_pnl_status"] == "UNKNOWN"


# ---------------------------------------------------------------- F1 (review cc-deepseek-8, rev 5)

OVERNIGHT = datetime(2026, 11, 14, 5, 37, tzinfo=timezone.utc)   # 00:37 ET, the scheduler's own interval


def test_the_closed_set_from_the_previous_fills_session_is_not_added_to_a_later_days_change():
    """F1: at 00:37 ET the closed set names the 11-13 fills session and the prior book is already after its
    close. Adding the sold position to ``start`` again counted the whole sale twice (the live book published
    MEASURED -27,791.20 for a -4,446.74 move). The closed set, the trade read and the prior-book cutoff must
    describe the same interval; when they cannot, measure 3 must not carry the closed rows.
    """
    rows = [_row("ZZZZ", 10, 19.00, prior_close=20.00),
            _row("CASH", 500.0, 1.0, is_cash=True, market_value=500.0, broker_market_value=None,
                 broker_shares=None)]
    portfolio = _doc(rows, closed_today={"fixture_taxable": [
        {"symbol": "ZZX", "day_change": -50.0, "prev_close": 2.00, "sold_qty": 100}]})
    fill = {"account": "fixture_taxable", "symbol": "ZZX", "action": "SELL", "quantity": 100,
            "amount": 250.0, "fees": 1.0}

    def db_query(sql, params=None, fetch="all"):
        if "position_snapshots" in sql:
            captured = datetime(2026, 11, 13, 23, 30, 5, tzinfo=timezone.utc)   # after the fill: post-sale book
            return [{"sync_run_id": 4242, "captured_at": captured, "account_key": "fixture_taxable",
                     "symbol": "ZZZZ", "qty": 10, "broker_market_value": 200.0, "is_cash": False},
                    {"sync_run_id": 4242, "captured_at": captured, "account_key": "fixture_taxable",
                     "symbol": "CASH", "qty": 500.0, "broker_market_value": None, "is_cash": True}]
        if "trade_transactions" in sql:
            # The fill exists on the fills session's date; the ET calendar day being measured has none.
            return [fill] if params and params[0] == "2026-11-13" else []
        return []

    repricer._materialize_measures(portfolio, db_query=db_query, now=OVERNIGHT)
    block = portfolio["measures"]
    change = block["measures"]["account_value_change_1d"]
    price_move = block["measures"]["price_move_estimate"]
    assert change["value"] == -10.00
    assert change["value"] == price_move["value"]                  # the sale is already in the prior book
    assert change["start"]["equity_usd"] == 700.00                 # never 700 + 2.00 x 100
    assert block["reconciliation"]["total"]["residual"]["known_components_residual_usd"] == 0.0
    assert change["drill_down"]["closed_today_trade_effect"] == 0.0
    # The row is still published -- the decision is visible, not a silent deletion -- and it says the prior book
    # no longer holds the position, so adding it to `start` would double the sale.
    scope_row = change["drill_down"]["closed_today_rows"][0]
    assert scope_row["symbol"] == "ZZX"
    assert scope_row["held_at_prior_close"] is False
    assert scope_row["counted_in_start"] is False
    assert scope_row["counted_in_components"] is False
    assert "double" in scope_row["not_added_reason"]
    assert "prior-close book" in scope_row["not_added_reason"]
    # Income has no bound source in the writer, so the drill-down is honest about the one unread part instead of
    # declaring a closure; every part it did read adds up to the change.
    assert change["drill_down"]["reconciles"] is None
    assert change["drill_down"]["reconciles_unobserved"] == ["income_today"]
    # The panel keeps showing the fills session; only the measures omit it.
    assert portfolio["closed_today"]["fixture_taxable"][0]["symbol"] == "ZZX"
    # The trade read describes the day being measured, not the fills session (kills M5).
    assert block["source_coverage"]["trades_today"]["rows"] == 0


# ---------------------------------------------------------------- the measurement session, at seven instants (operator 2026-11-14)


def _et(y, mo, d, h, mi):
    from zoneinfo import ZoneInfo
    return datetime(y, mo, d, h, mi, tzinfo=ZoneInfo("America/New_York"))


#: The stored run cadence around a midnight (position_snapshots, every 15 min in RTH and every 30 min outside).
_RUNS = {
    "thu_2330": (_et(2026, 11, 12, 23, 30), 900),
    "fri_1530": (_et(2026, 11, 13, 15, 30), 903),
    "fri_2330": (_et(2026, 11, 13, 23, 30), 906),
    "sat_0000": (_et(2026, 11, 14, 0, 0), 907),
    "sat_2330": (_et(2026, 11, 14, 23, 30), 950),
    "sun_2330": (_et(2026, 11, 15, 23, 30), 998),
}


def _run_rows(captured, run_id, holds_closed):
    """One stored book. ``holds_closed`` says whether the book still holds the position the closed set names
    (ZZX): true before the sale, false after it -- the store's own record of whether the sale is inside the
    book the change starts from."""
    rows = [{"sync_run_id": run_id, "captured_at": captured, "account_key": "fixture_taxable",
             "symbol": "ZZZZ", "qty": 10, "broker_market_value": 200.0, "is_cash": False},
            {"sync_run_id": run_id, "captured_at": captured, "account_key": "fixture_taxable",
             "symbol": "CASH", "qty": 500.0, "broker_market_value": None, "is_cash": True}]
    if holds_closed:
        rows.append({"sync_run_id": run_id, "captured_at": captured, "account_key": "fixture_taxable",
                     "symbol": "ZZX", "qty": 100, "broker_market_value": 200.0, "is_cash": False})
    return rows


def _session_db(calls, runs):
    """A fake read that answers each query the way the store would at the instant under test."""
    runs = sorted(runs, key=lambda item: item[0])

    def db_query(sql, params=None, fetch="all"):
        if "position_snapshots" in sql:
            since, until = params
            eligible = [rows for at, rows in runs if since <= at < until]
            return eligible[-1] if eligible else []
        if "trade_transactions" in sql or "account_transfers" in sql:
            calls.append(("read", "trades" if "trade_transactions" in sql else "transfers", params[0]))
            return []
        return []
    return db_query


def _session_measures(now, calls, runs=None):
    if runs is None:
        # The sale happened on Friday: the Thursday book holds ZZX, every book from Friday's RTH onwards does not.
        runs = [(_t, _run_rows(_t, rid, holds_closed=(_t < _et(2026, 11, 13, 9, 30))))
                for _t, rid in _RUNS.values()]
    portfolio = _doc([_row("ZZZZ", 10, 19.00, prior_close=20.00),
                      _row("CASH", 500.0, 1.0, is_cash=True, market_value=500.0,
                           broker_market_value=None, broker_shares=None)],
                     closed_today={"fixture_taxable": [
                         {"symbol": "ZZX", "day_change": -50.0, "prev_close": 2.00, "sold_qty": 100}]})
    repricer._materialize_measures(portfolio, db_query=_session_db(calls, runs), now=now)
    return portfolio["measures"]


def _closed_in(block):
    """Whether the closed row is part of the interval the change measures -- read off the row's own decision
    (``counted_in_start``/``counted_in_components``), not off whether the panel lists it. The list is always
    populated; a row outside the interval is published with the flags false and a reason."""
    rows = block["measures"]["account_value_change_1d"]["drill_down"]["closed_today_rows"]
    return bool(rows) and all(r.get("counted_in_start") for r in rows)


def test_the_measured_session_at_seven_instants():
    """Operator correction (2026-11-14): establish, not assume, which session the day change measures.

    Measure 3 is a **calendar-day ET** measure: it spans the last stored book strictly before the current ET
    date's midnight to now. The trades read always follows the day being measured; a closed row enters when the
    book the interval starts from still holds that position (the sale is inside the interval), and not when the
    book already reflects it. Here the sale is Friday's, so Friday's baselines still hold ZZX and every later
    one does not. Every instant below is checked against the stored run cadence.
    """
    # Monday premarket measures Monday's own fills; its fixture is the position held through the weekend and
    # sold on Monday, so the Monday closed row is inside the interval and its Sunday-midnight book still holds it.
    monday_runs = [(_t, _run_rows(_t, rid, holds_closed=(_t < _et(2026, 11, 16, 9, 30))))
                   for _t, rid in _RUNS.values()]
    cases = [
        # instant,                              fills/trades date,  closed rows enter,  baseline run,   runs
        (_et(2026, 11, 13, 15, 59), "2026-11-13", True, "thu_2330", None),   # Friday RTH
        (_et(2026, 11, 13, 16, 1), "2026-11-13", True, "thu_2330", None),    # Friday, one minute after the close
        (_et(2026, 11, 13, 23, 59), "2026-11-13", True, "thu_2330", None),   # Friday, last minute of its ET date
        (_et(2026, 11, 14, 0, 1), "2026-11-14", False, "fri_2330", None),    # Saturday, the date has rolled
        (_et(2026, 11, 14, 0, 37), "2026-11-14", False, "fri_2330", None),   # Saturday 00:37 (the live dry run)
        (_et(2026, 11, 15, 20, 0), "2026-11-15", False, "sat_2330", None),   # Sunday 20:00 (overnight, not a trading day)
        (_et(2026, 11, 16, 9, 29), "2026-11-16", True, "sun_2330", monday_runs),  # Monday premarket
    ]
    for now, trade_date, closed_enters, baseline_key, runs in cases:
        calls = []
        block = _session_measures(now, calls, runs=runs)
        change = block["measures"]["account_value_change_1d"]
        reads = {name: date for kind, name, date in calls if kind == "read"}
        assert reads.get("trades") == trade_date, (now.isoformat(), reads)
        assert reads.get("transfers") == trade_date, (now.isoformat(), reads)
        assert _closed_in(block) is closed_enters, (now.isoformat(), change["drill_down"]["closed_today_rows"])
        # Arithmetic, not just the drill list: the start is 700.00 (ZZZZ 200 + cash 500) and the sale's prior
        # value (100 x 2.00 = 200) is in it only when the interval contains the sale -- 900.00.
        assert change["start"]["equity_usd"] == (900.0 if closed_enters else 700.0), (now.isoformat(),
                                                                                    change["start"])
        assert change["start"]["as_of"] == _RUNS[baseline_key][0].isoformat(), (now.isoformat(), change["start"])
        # The row itself carries the decision and, when it is out of the interval, the reason -- never silent.
        row = change["drill_down"]["closed_today_rows"][0]
        assert row["held_at_prior_close"] is closed_enters, (now.isoformat(), row)
        assert row["counted_in_components"] is closed_enters, (now.isoformat(), row)
        if closed_enters:
            assert "not_added_reason" not in row, (now.isoformat(), row)
        else:
            assert "double" in row["not_added_reason"], (now.isoformat(), row)


def test_a_book_stale_before_the_sale_keeps_the_closed_row():
    """Review cc-deepseek-8 §4 (stale same-date book): the guard keys on the position, not on a date. A writer
    that missed the window between Friday's sale and ET midnight leaves a Saturday baseline captured earlier the
    same ET date, still holding the position. The sale is inside the interval, so its prior value must be added
    to ``start`` -- a date predicate (``_fills_trade_date(now) == _et_today(now)``) would drop it and understate
    the change by the whole sale (measured: 240.0 vs the truth +40).
    """
    captured = _et(2026, 11, 13, 9, 35)         # Friday morning, before the 15:00 sale, same ET date as it
    runs = [(captured, 905, [{"sync_run_id": 905, "captured_at": captured, "account_key": "fixture_taxable",
                              "symbol": "ZZX", "qty": 100, "broker_market_value": 900.0, "is_cash": False},
                             {"sync_run_id": 905, "captured_at": captured, "account_key": "fixture_taxable",
                              "symbol": "CASH", "qty": 0.0, "broker_market_value": None, "is_cash": True}])]

    def db_query(sql, params=None, fetch="all"):
        if "position_snapshots" in sql:
            since, until = params
            eligible = [rows for at, _rid, rows in runs if since <= at < until]
            return eligible[-1] if eligible else []
        return []                                # the sale is Friday's; the ET day being measured has no trades

    portfolio = _doc([_row("CASH", 940.0, 1.0, is_cash=True, market_value=940.0,
                           broker_market_value=None, broker_shares=None)],
                     closed_today={"fixture_taxable": [
                         {"symbol": "ZZX", "day_change": 40.0, "prev_close": 9.00, "sold_qty": 100}]})
    repricer._materialize_measures(portfolio, db_query=db_query, now=_et(2026, 11, 14, 0, 37))
    change = portfolio["measures"]["measures"]["account_value_change_1d"]
    assert change["start"]["equity_usd"] == 900.0          # the stale book's ZZX position, added once
    assert change["start"]["as_of"] == captured.isoformat()
    assert change["value"] == 40.0                          # 940.00 ending cash - 900.00 start; never 240.00
    row = change["drill_down"]["closed_today_rows"][0]
    assert row["held_at_prior_close"] is True
    assert row["counted_in_start"] is True and row["counted_in_components"] is True
    assert "not_added_reason" not in row
    assert (portfolio["measures"].get("input_gap") or {}).get("closed_today") is None


def test_a_same_session_round_trip_is_a_component_but_never_a_start_addition():
    """Review cc-deepseek-8 §4 (round trip): a name bought and sold inside the interval was never in the
    prior-close book. Adding its ``prev_close x sold_qty`` to ``start`` invents a position the baseline never
    held (measured: -900.0 vs the truth +100). Its realized gain is a real component of the change, so the
    component stays while the start addition goes -- the two predicates are deliberately different.
    """
    captured = _et(2026, 11, 12, 23, 30)        # Thursday's last book: Friday's prior close, before the buy
    runs = [(captured, 907, [{"sync_run_id": 907, "captured_at": captured, "account_key": "fixture_taxable",
                              "symbol": "CASH", "qty": 5000.0, "broker_market_value": None, "is_cash": True}])]
    fill = {"account": "fixture_taxable", "symbol": "ZZX", "action": "SELL", "quantity": 100,
            "amount": 2100.0, "fees": 0.0}

    def db_query(sql, params=None, fetch="all"):
        if "position_snapshots" in sql:
            since, until = params
            eligible = [rows for at, _rid, rows in runs if since <= at < until]
            return eligible[-1] if eligible else []
        if "trade_transactions" in sql:
            return [fill] if params and params[0] == "2026-11-13" else []
        return []

    portfolio = _doc([_row("CASH", 5100.0, 1.0, is_cash=True, market_value=5100.0,
                           broker_market_value=None, broker_shares=None)],
                     closed_today={"fixture_taxable": [
                         {"symbol": "ZZX", "day_change": 100.0, "prev_close": 20.00, "sold_qty": 100}]})
    repricer._materialize_measures(portfolio, db_query=db_query, now=_et(2026, 11, 13, 16, 1))
    change = portfolio["measures"]["measures"]["account_value_change_1d"]
    assert change["start"]["equity_usd"] == 5000.0          # never 5000 + 20.00 x 100
    assert change["value"] == 100.0                          # 5100.00 - 5000.00
    row = change["drill_down"]["closed_today_rows"][0]
    assert row["held_at_prior_close"] is False
    assert row["counted_in_start"] is False
    assert row["counted_in_components"] is True
    assert "never held" in row["not_added_reason"]
    dd = change["drill_down"]
    assert dd["closed_today_trade_effect"] == 100.0          # 2100.00 gross - 2000.00 prior close
    assert dd["fees_today"] == 0.0
    # A cash-only ending book has no price-move term to read, so the drill names it; the bridge still closes.
    assert portfolio["measures"]["reconciliation"]["total"]["residual"][
        "known_components_residual_usd"] == 0.0


def test_a_partial_sale_starts_from_the_observed_book_and_measures_the_trim():
    """Lead ruling 06:29Z, option (a) (follow-up LQ-3124R-partial): the start of the change is the observed
    prior-close book, never today's share count re-marked at the prior close. A trim of half the position used
    to drop the sold shares' prior value (published 1100.0 for a truth of +100 through the writer path). The
    sale itself is still carried separately by the drill-down; here the producer emits no closed row because the
    position is still held.
    """
    captured = _et(2026, 11, 12, 23, 30)        # Thursday's book: 100 shares worth 2,000.00, cash 5,000.00
    runs = [(captured, 908, [{"sync_run_id": 908, "captured_at": captured, "account_key": "fixture_taxable",
                              "symbol": "ZZX", "qty": 100, "broker_market_value": 2000.0, "is_cash": False},
                             {"sync_run_id": 908, "captured_at": captured, "account_key": "fixture_taxable",
                              "symbol": "CASH", "qty": 5000.0, "broker_market_value": None, "is_cash": True}])]
    fill = {"account": "fixture_taxable", "symbol": "ZZX", "action": "SELL", "quantity": 50,
            "amount": 1050.0, "fees": 0.0}

    def db_query(sql, params=None, fetch="all"):
        if "position_snapshots" in sql:
            since, until = params
            eligible = [rows for at, _rid, rows in runs if since <= at < until]
            return eligible[-1] if eligible else []
        if "trade_transactions" in sql:
            return [fill] if params and params[0] == "2026-11-13" else []
        return []

    portfolio = _doc([_row("ZZX", 50, 21.0, prior_close=20.0, broker_market_value=1050.0),
                      _row("CASH", 6050.0, 1.0, is_cash=True, market_value=6050.0,
                           broker_market_value=None, broker_shares=None)])
    repricer._materialize_measures(portfolio, db_query=db_query, now=_et(2026, 11, 13, 16, 1))
    change = portfolio["measures"]["measures"]["account_value_change_1d"]
    assert change["start"]["equity_usd"] == 7000.0          # 2,000.00 + 5,000.00, the whole position's book value
    assert change["end"]["equity_usd"] == 7100.0            # 1,050.00 + 6,050.00
    assert change["value"] == 100.0                          # never 1100.0
    assert change["gap"] is None
    assert change["drill_down"]["closed_today_rows"] == []   # still held: no closed row is invented


def test_a_same_day_buy_starts_from_the_observed_book_and_is_not_credited_to_prior_close():
    """Lead ruling 06:29Z, option (a): a position bought inside the interval was not in the prior-close book, so
    the start must not credit its 50 new shares at the prior close (published -900.0 for a truth of +100). The
    buy moved cash into the position; only the shares held since the prior close can re-mark.
    """
    captured = _et(2026, 11, 12, 23, 30)        # Thursday's book: 100 shares worth 2,000.00, cash 5,000.00
    runs = [(captured, 909, [{"sync_run_id": 909, "captured_at": captured, "account_key": "fixture_taxable",
                              "symbol": "ZZX", "qty": 100, "broker_market_value": 2000.0, "is_cash": False},
                             {"sync_run_id": 909, "captured_at": captured, "account_key": "fixture_taxable",
                              "symbol": "CASH", "qty": 5000.0, "broker_market_value": None, "is_cash": True}])]
    fill = {"account": "fixture_taxable", "symbol": "ZZX", "action": "BUY", "quantity": 50,
            "amount": 1050.0, "fees": 0.0}

    def db_query(sql, params=None, fetch="all"):
        if "position_snapshots" in sql:
            since, until = params
            eligible = [rows for at, _rid, rows in runs if since <= at < until]
            return eligible[-1] if eligible else []
        if "trade_transactions" in sql:
            return [fill] if params and params[0] == "2026-11-13" else []
        return []

    portfolio = _doc([_row("ZZX", 150, 21.0, prior_close=20.0, broker_market_value=3150.0),
                      _row("CASH", 3950.0, 1.0, is_cash=True, market_value=3950.0,
                           broker_market_value=None, broker_shares=None)])
    repricer._materialize_measures(portfolio, db_query=db_query, now=_et(2026, 11, 13, 16, 1))
    change = portfolio["measures"]["measures"]["account_value_change_1d"]
    assert change["start"]["equity_usd"] == 7000.0          # never 7,000 + 50 x 20 = 8,000
    assert change["end"]["equity_usd"] == 7100.0
    assert change["value"] == 100.0                          # never -900.0
    assert change["gap"] is None


def test_a_partial_sale_never_enters_the_closed_set():
    """A closed row means the position is *gone*. A partially sold holding is still held, so the producer emits
    no closed row for it -- otherwise the per-key rule would add the whole position's day change on a partial
    sale, which is the same double count in miniature."""
    holdings = [{"account": "fixture_taxable", "symbol": "ZZX", "shares": 50.0, "is_cash": False}]
    fills = {("fixture_taxable", "ZZX"): {"sells": [(50.0, 19.0)]}}
    assert repricer._closed_today_day_change(holdings, fills, {"ZZX": 18.0}) == {}
    # The fully sold case does produce the row, so the pin above is not vacuous.
    sold_out = repricer._closed_today_day_change([], fills, {"ZZX": 18.0})
    assert sold_out["fixture_taxable"][0]["symbol"] == "ZZX"


def test_a_renamed_account_falls_back_to_the_estimate_and_never_reads_its_book_as_empty():
    """The live book's account keys can change under the measure (the store itself has carried a
    ``schwab_roth`` row under a later ``schwab_roth_ira`` key). A prior book that holds an account under a
    different key must not be read as "this account held nothing at the prior close": the positions keep their
    estimated start (prior shares x prior close), and the cash -- which no fallback can estimate -- makes the
    change PARTIAL with the reason named, never a fabricated jump.
    """
    captured = _et(2026, 11, 12, 23, 30)
    runs = [(captured, 910, [{"sync_run_id": 910, "captured_at": captured,
                              "account_key": "fixture_taxable", "symbol": "ZZX", "qty": 10,
                              "broker_market_value": 200.0, "is_cash": False},
                             {"sync_run_id": 910, "captured_at": captured,
                              "account_key": "fixture_taxable", "symbol": "CASH", "qty": 5000.0,
                              "broker_market_value": None, "is_cash": True}])]

    def db_query(sql, params=None, fetch="all"):
        if "position_snapshots" in sql:
            since, until = params
            eligible = [rows for at, _rid, rows in runs if since <= at < until]
            return eligible[-1] if eligible else []
        return []

    portfolio = _doc([_row("ZZX", 10, 21.0, account="fixture_taxable_ira", prior_close=20.0,
                           broker_market_value=210.0),
                      _row("CASH", 5000.0, 1.0, account="fixture_taxable_ira", is_cash=True,
                           market_value=5000.0, broker_market_value=None, broker_shares=None)])
    repricer._materialize_measures(portfolio, db_query=db_query, now=_et(2026, 11, 13, 16, 1))
    change = portfolio["measures"]["measures"]["account_value_change_1d"]
    # The position is NOT zeroed by the absent key: 10 shares of the book's own count at the row's prior close.
    assert change["start"]["equity_usd"] == 5200.0          # 200.00 estimated + 5,000.00 cash at face
    assert change["status"] == "PARTIAL"
    assert change["value"] is None                          # the unobserved cash start is named, not invented
    assert any("prior cash not observed" in str(u.get("reason"))
               for u in (change.get("gap") or {}).get("start_unknown") or [])


def test_a_closed_row_that_could_not_be_valued_leaves_the_days_fee_unknown():
    """C1 (review cc-deepseek-8, rev-7 delta §7): the producer emits a closed row it could not value at all --
    ``{"day_change": null, "reason": "no_prev_close"}`` -- and the trades pass drops it before the per-row fee
    predicate, so its commission was never read. The day's fee total must then be unknown, never a number
    published over the subset that happened to parse (rev 7 published -1.00 here).
    """
    rows = [_row("ZZAA", 10, 20.0, prior_close=20.00)]
    prior = _prior({("fixture_taxable", "ZZAA"): 200.0, ("fixture_taxable", "CASH"): 0.0,
                    ("fixture_taxable", "ZZX"): 50.0, ("fixture_taxable", "ZZY"): 50.0})
    closed = {"fixture_taxable": [{"symbol": "ZZX", "sold_qty": 10, "prev_close": 5.00},
                                  {"symbol": "ZZY", "day_change": None, "reason": "no_prev_close"}]}
    trades = [{"account": "fixture_taxable", "symbol": "ZZX", "action": "SELL",
               "quantity": 10, "amount": 55.00, "fees": 1.00}]
    dd = pm.portfolio_measures(_doc(rows, closed_today=closed), prior_snapshot=prior,
                               trades=trades, now=NOW)["measures"]["account_value_change_1d"]["drill_down"]
    assert dd["closed_today_trade_effect"] == 5.00       # the valued row's own effect still publishes
    assert dd["fees_today"] is None                       # ZZY's commission was never read: never -1.00
    assert dd["reconciles"] is None and "fees_today" in dd["reconciles_unobserved"]
    assert dd["closed_today_complete"] is False


def test_a_closed_row_outside_the_interval_does_not_make_the_days_fee_unknown():
    """The other way (C1 must not over-reach): a stored-gross row whose exit predates the prior-close book is
    not part of this interval at all, so its unread commission says nothing about the day's fee -- fees stay
    0.00, while the set itself is still reported as read gross."""
    rows = [_row("ZZAA", 10, 20.0, prior_close=20.00)]
    prior = _prior({("fixture_taxable", "ZZAA"): 200.0, ("fixture_taxable", "CASH"): 0.0})   # ZZX absent
    closed = {"fixture_taxable": [{"symbol": "ZZX", "sold_qty": 10, "prev_close": 5.00,
                                   "day_change": -3.00}]}
    dd = pm.portfolio_measures(_doc(rows, closed_today=closed), prior_snapshot=prior, trades=[],
                               now=NOW)["measures"]["account_value_change_1d"]["drill_down"]
    assert dd["closed_today_rows"][0]["counted_in_components"] is False
    assert dd["closed_today_rows"][0]["fee_complete"] is False
    assert dd["fees_today"] == 0.00                        # no in-scope commission is missing
    assert dd["closed_today_complete"] is False            # the set was still read gross


def test_a_position_moved_between_two_covered_accounts_keeps_its_prior_value():
    """LQ-3124R-partial (review cc-deepseek-8 rev-8 note 2): an internal transfer moves a position from one
    account the prior book covers to another the book also covers. The destination's key is absent from the book,
    but the symbol is not absent from the book -- reading the row as "bought inside the interval" and valuing it at
    0.0 would drop the whole position's prior value. The estimate keeps it, and the transfer itself cancels as an
    internal flow.
    """
    rows = [_row("ZZX", 100, 21.0, account="acct_b", prior_close=20.0, broker_market_value=2100.0),
            _row("CASH", 5000.0, 1.0, account="acct_b", is_cash=True, market_value=5000.0,
                 broker_market_value=None, broker_shares=None)]
    prior = _prior({("acct_a", "ZZX"): 2000.0, ("acct_a", "CASH"): 0.0, ("acct_b", "CASH"): 5000.0})
    transfers = [{"from_account": "acct_a", "to_account": "acct_b", "amount": 2000.0,
                  "transfer_type": "internal", "transfer_date": "2026-11-13"}]
    change = pm.portfolio_measures(_doc(rows, closed_today={}), prior_snapshot=prior, trades=[],
                                   transfers=transfers, now=NOW)["measures"]["account_value_change_1d"]
    assert change["start"]["equity_usd"] == 7000.0     # the moved position keeps its 2,000.00, never 0.00
    assert change["end"]["equity_usd"] == 7100.0
    assert change["value"] == 100.0                    # never 2100.0


def test_a_same_day_buy_of_a_symbol_held_in_another_account_starts_at_zero():
    """LQ-3124R-partial r2 (review cc-deepseek-8 2026-11-14 C1): adding to a name the book already holds in a
    DIFFERENT account is an ordinary purchase, not a transfer. The symbol-elsewhere guard valued acct_b's new
    lot at shares x prior_close and fabricated a 5,000.00 start -- published change -5,200.00 where the
    measure's own definition (end - start) gives -200.00, and base was exact there. The day's BUY names the
    row, so it keeps the 0.00 start a purchase has.
    """
    rows = [_row("ZZX", 100, 50.0, account="acct_a", prior_close=50.0, broker_market_value=5000.0),
            _row("CASH", 0.0, 1.0, account="acct_a", is_cash=True, market_value=0.0,
                 broker_market_value=None, broker_shares=None),
            _row("ZZX", 100, 50.0, account="acct_b", prior_close=50.0, broker_market_value=5000.0),
            _row("CASH", 0.0, 1.0, account="acct_b", is_cash=True, market_value=0.0,
                 broker_market_value=None, broker_shares=None)]
    prior = _prior({("acct_a", "ZZX"): 5000.0, ("acct_a", "CASH"): 0.0, ("acct_b", "CASH"): 5200.0})
    trades = [{"account": "acct_b", "symbol": "ZZX", "action": "BUY", "quantity": 100,
               "amount": 5200.0, "fees": 0.0}]
    change = pm.portfolio_measures(_doc(rows, closed_today={}), prior_snapshot=prior, trades=trades,
                                   now=NOW)["measures"]["account_value_change_1d"]
    assert change["start"]["equity_usd"] == 10200.0    # the cash that bought the lot, never the lot's prior value
    assert change["end"]["equity_usd"] == 10000.0
    assert change["value"] == -200.0                   # the lot's move since purchase, never -5,200.00


def test_a_moved_position_is_not_read_as_a_purchase_from_another_accounts_trade():
    """The purchase discriminator matches the trade's exact ``(account, symbol)`` key, never a symbol match:
    with a BUY of ZZX in ``acct_a`` today (a top-up there) and ZZX moved into ``acct_b``, a symbol-wide match
    would label the moved lot a purchase and zero the prior value this ticket restored. Same fixture as the
    transfer pin, plus that BUY.
    """
    rows = [_row("ZZX", 100, 21.0, account="acct_b", prior_close=20.0, broker_market_value=2100.0),
            _row("CASH", 5000.0, 1.0, account="acct_b", is_cash=True, market_value=5000.0,
                 broker_market_value=None, broker_shares=None)]
    prior = _prior({("acct_a", "ZZX"): 2000.0, ("acct_a", "CASH"): 0.0, ("acct_b", "CASH"): 5000.0})
    trades = [{"account": "acct_a", "symbol": "ZZX", "action": "BUY", "quantity": 50,
               "amount": 1050.0, "fees": 0.0}]
    transfers = [{"from_account": "acct_a", "to_account": "acct_b", "amount": 2000.0,
                  "transfer_type": "internal", "transfer_date": "2026-11-13"}]
    change = pm.portfolio_measures(_doc(rows, closed_today={}), prior_snapshot=prior, trades=trades,
                                   transfers=transfers, now=NOW)["measures"]["account_value_change_1d"]
    assert change["start"]["equity_usd"] == 7000.0     # the moved position still keeps its 2,000.00
    assert change["end"]["equity_usd"] == 7100.0
    assert change["value"] == 100.0                    # never 2100.0 from a zeroed start
