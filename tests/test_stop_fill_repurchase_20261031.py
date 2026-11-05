"""A filled broker stop is settled by the trade ledger, not shown as "awaiting holdings sync" forever.

Operator 2026-10-31: "V was stopped and repurchased so some of this is stale fix and make accurate going forward".
Schwab's order read keeps returning a FILLED stop order for weeks. ``cio_truth.stop_for`` kept that observation as
the position's state whenever no newer working order existed, so a name that was stopped out and later re-bought read
"stop filled · awaiting holdings sync" on Home, Risk and Prospectus long after the sale was in the ledger. The ledger
names each fill's order id ("order <id>"); ``fill_ledger`` uses it to settle the fill. Synthetic tickers only.
"""

from datetime import datetime, timezone

from scripts.lib import cio_truth as truth

NOW = datetime(2031, 3, 9, 18, 0, tzinfo=timezone.utc)  # Sun 14:00 ET
READ = "2031-03-07T20:55:00-05:00"  # Fri 20:55 ET broker read
ACCT = "schwab_roth"


def _obs(symbol, order_id, status, at=READ, stop=10.0):
    return {
        "account": ACCT,
        "symbol": symbol,
        "order_id": order_id,
        "stop_price": stop,
        "qty": 1,
        "status": status,
        "captured_at": at,
    }


def _tx(symbol, action, at, order_id=None):
    return {
        "account": ACCT,
        "symbol": symbol,
        "action": action,
        "trade_time": at,
        "trade_date": at[:10],
        "description": f"order {order_id}" if order_id else "reinvestment",
    }


SOLD = "2031-03-04T10:21:00-05:00"
REBOUGHT = "2031-03-04T16:28:00-05:00"


def _holdings(symbols, updated_at=READ):
    return {
        "last_repriced": READ,
        "portfolio_totals": {"total_value": 1000, "day_change": 0},
        "holdings": [
            {
                "symbol": s,
                "account": ACCT,
                "shares": 10,
                "price": 50.0,
                "market_value": 500.0,
                "day_change": 0,
                "as_of": READ,
                "updated_at": updated_at,
            }
            for s in symbols
        ],
    }


def _resolve(holdings, broker, ledger, tmp):
    fills = truth.fill_ledger(broker, ledger_rows=ledger) if ledger is not None else None
    inputs = {
        "holdings": holdings,
        "broker_stops": broker,
        "planned_stops": {},
        "companies": {},
        "policy": {},
        "cio_status": {},
        "stop_freshness": {"open_h": 0.25, "closed_h": 72.0},
        "stop_fills": fills,
    }
    return truth.resolve(tmp, NOW, inputs=inputs)


def _row(doc, symbol):
    return next(r for r in doc["stops"]["rows"] if r["symbol"] == symbol)


def test_fill_then_rebuy_then_snapshot_is_history_not_awaiting_sync(tmp_path):
    broker = [_obs("ZZV", "1000000000001", "FILLED"), _obs("ZZV", "1000000000002", "REPLACED")]
    ledger = [_tx("ZZV", "Sell", SOLD, "1000000000001"), _tx("ZZV", "Buy", REBOUGHT, "1000000000003")]
    doc = _resolve(_holdings(["ZZV"]), broker, ledger, tmp_path)
    row = _row(doc, "ZZV")
    assert row["stop_state"] == "none"
    assert row["stop_note"] == (
        "previous stop filled Tue Mar 4 10:21 ET · re-bought Tue Mar 4 16:28 ET"
        " · no broker stop on the current position"
    )
    assert doc["stops"]["filled_awaiting_sync"] == []
    assert doc["stops"]["filled_count"] == 0
    assert doc["stops"]["unprotected_count"] == 1  # the new lot really has no broker stop


def test_rebuy_with_a_new_resting_stop_reads_the_new_stop(tmp_path):
    broker = [_obs("ZZV", "1000000000001", "FILLED"), _obs("ZZV", "1000000000009", "PENDING_ACTIVATION")]
    ledger = [_tx("ZZV", "Sell", SOLD, "1000000000001"), _tx("ZZV", "Buy", REBOUGHT, "1000000000003")]
    row = _row(_resolve(_holdings(["ZZV"]), broker, ledger, tmp_path), "ZZV")
    assert row["stop_state"] == "pending_activation"
    assert row["stop_note"] == "previous stop filled Tue Mar 4 10:21 ET · re-bought Tue Mar 4 16:28 ET"


def test_same_read_working_order_outranks_filled_even_without_ledger():
    broker = [_obs("ZZQ", "1000000000001", "FILLED"), _obs("ZZQ", "1000000000002", "WORKING")]
    for rows in (broker, list(reversed(broker))):
        st = truth.stop_for(ACCT, "ZZQ", broker_rows=rows, now=NOW)
        assert st["stop_state"] == "active"


def test_fill_then_snapshot_showing_closed_leaves_no_row(tmp_path):
    broker = [_obs("ZZC", "1000000000001", "FILLED")]
    ledger = [_tx("ZZC", "Sell", SOLD, "1000000000001")]
    doc = _resolve(_holdings(["ZZK"]), broker, ledger, tmp_path)  # ZZC no longer held
    assert [r["symbol"] for r in doc["stops"]["rows"]] == ["ZZK"]
    assert doc["stops"]["filled_awaiting_sync"] == []


def test_sale_in_ledger_but_holdings_older_says_waiting_for_holdings_sync(tmp_path):
    broker = [_obs("ZZS", "1000000000001", "FILLED")]
    ledger = [_tx("ZZS", "Sell", SOLD, "1000000000001")]
    doc = _resolve(_holdings(["ZZS"], updated_at="2031-03-03T20:00:00-05:00"), broker, ledger, tmp_path)
    row = _row(doc, "ZZS")
    assert row["stop_state"] == "filled"
    assert row["stop_note"] == (
        "stop filled Tue Mar 4 10:21 ET · waiting for the holdings sync (holdings last updated Mon Mar 3 20:00 ET)"
    )
    assert [p["reason"] for p in doc["stops"]["filled_awaiting_sync"]] == [row["stop_note"]]


def test_holdings_refreshed_after_the_sale_without_rebuy_is_history(tmp_path):
    broker = [_obs("ZZP", "1000000000001", "FILLED")]
    ledger = [_tx("ZZP", "Sell", SOLD, "1000000000001")]
    row = _row(_resolve(_holdings(["ZZP"]), broker, ledger, tmp_path), "ZZP")  # holdings updated Fri, after Tue sale
    assert row["stop_state"] == "none"
    assert row["stop_note"].startswith("previous stop filled Tue Mar 4 10:21 ET · holdings refreshed since")


def test_fill_not_yet_in_ledger_says_so(tmp_path):
    broker = [_obs("ZZN", "1000000000001", "FILLED")]
    row = _row(_resolve(_holdings(["ZZN"]), broker, [], tmp_path), "ZZN")
    assert row["stop_state"] == "filled"
    assert (
        row["stop_note"]
        == "stop filled (broker read Fri Mar 7 20:55 ET) · waiting for the sale to reach the trade ledger"
    )


def test_unreadable_ledger_is_unknown_not_settled():
    broker = [_obs("ZZU", "1000000000001", "FILLED")]
    assert truth.fill_ledger(broker) is None  # no db_query and no rows: unreadable, never "settled"
    st = truth.stop_for(ACCT, "ZZU", broker_rows=broker, now=NOW, fills=None)
    assert st["stop_state"] == "filled" and "not yet checked against the trade ledger" in st["stop_note"]


def test_buy_before_the_sale_does_not_count_as_a_rebuy():
    broker = [_obs("ZZB", "1000000000001", "FILLED")]
    ledger = [
        _tx("ZZB", "Buy", "2031-03-01T10:00:00-05:00", "1000000000000"),
        _tx("ZZB", "Sell", SOLD, "1000000000001"),
    ]
    fills = truth.fill_ledger(broker, ledger_rows=ledger)
    assert fills == {"1000000000001": {"sold_at": "2031-03-04T10:21:00-05:00", "rebought_at": None}}


def test_without_holding_context_a_ledger_sale_is_stated_not_awaited():
    broker = [_obs("ZZL", "1000000000001", "FILLED")]
    fills = truth.fill_ledger(broker, ledger_rows=[_tx("ZZL", "Sell", SOLD, "1000000000001")])
    st = truth.stop_for(ACCT, "ZZL", broker_rows=broker, now=NOW, fills=fills)
    assert st["stop_state"] == "filled"
    assert st["stop_note"] == "stop filled Tue Mar 4 10:21 ET · sale recorded in the trade ledger"
