import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/journal_ticker_lifecycle.py"


def load_module():
    spec = importlib.util.spec_from_file_location("journal_ticker_lifecycle", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def fidelity_example_rows():
    return [
        {"trade_date": "2026-06-18", "action": "Buy", "symbol": "HPE", "quantity": 800, "price": 47.495, "amount": -37996.00, "account": "fidelity_rollover_ira"},
        {"trade_date": "2026-06-18", "action": "Buy", "symbol": "HPE", "quantity": 200, "price": 47.4999, "amount": -9499.98, "account": "fidelity_rollover_ira"},
        {"trade_date": "2026-06-29", "action": "Sell", "symbol": "HPE", "quantity": 1000, "price": 42.58912, "amount": 42589.12, "account": "fidelity_rollover_ira"},
        {"trade_date": "2026-06-18", "action": "Buy", "symbol": "GCTS", "quantity": 1000, "price": 5.97, "amount": -5970.00, "account": "fidelity_rollover_ira"},
        {"trade_date": "2026-06-26", "action": "Sell", "symbol": "GCTS", "quantity": 1000, "price": 4.5999, "amount": 4599.90, "account": "fidelity_rollover_ira"},
        {"trade_date": "2026-06-29", "action": "Dividend", "symbol": "SCHD", "quantity": 0, "price": 0, "amount": 505.00, "account": "fidelity_rollover_ira"},
        {"trade_date": "2026-06-29", "action": "Dividend", "symbol": "SCHG", "quantity": 0, "price": 0, "amount": 67.40, "account": "fidelity_rollover_ira"},
        {"trade_date": "2026-06-24", "action": "Dividend", "symbol": "XAR", "quantity": 0, "price": 0, "amount": 6.18, "account": "fidelity_rollover_ira"},
        {"trade_date": "2026-06-18", "action": "Cash Receipt", "symbol": "CASH", "quantity": 0, "price": 0, "amount": 170900.82, "description": "ROLLOVER CASH DIRECT ROLLOVER", "account": "fidelity_rollover_ira"},
    ]


def test_hpe_two_buys_one_sell_realizes_uploaded_loss():
    mod = load_module()
    agg = mod.aggregate_ticker_activity(fidelity_example_rows())
    hpe = agg["HPE"]
    assert hpe["total_buys"] == 47495.98
    assert hpe["total_sells"] == 42589.12
    assert hpe["realized_pnl"] == -4906.86
    assert hpe["realized_pnl_pct"] == -10.33
    assert hpe["exits"] == 1
    assert hpe["losses"] == 1
    assert hpe["current_open_shares"] == 0


def test_gcts_round_trip_realizes_uploaded_loss():
    mod = load_module()
    agg = mod.aggregate_ticker_activity(fidelity_example_rows())
    gcts = agg["GCTS"]
    assert gcts["total_buys"] == 5970.00
    assert gcts["total_sells"] == 4599.90
    assert gcts["realized_pnl"] == -1370.10
    assert gcts["realized_pnl_pct"] == -22.95
    assert gcts["losses"] == 1


def test_dividends_are_income_not_trade_wins_and_rollovers_do_not_pollute_pnl():
    mod = load_module()
    agg = mod.aggregate_ticker_activity(fidelity_example_rows())
    assert agg["SCHD"]["dividends_received"] == 505.00
    assert agg["SCHG"]["dividends_received"] == 67.40
    assert agg["XAR"]["dividends_received"] == 6.18
    assert agg["SCHD"]["wins"] == 0
    assert agg["SCHG"]["wins"] == 0
    assert agg["CASH"]["cash_movement"] == 170900.82
    assert agg["CASH"]["realized_pnl"] == 0


def test_reinvested_dividend_counts_as_income_and_open_lot():
    mod = load_module()
    agg = mod.aggregate_ticker_activity([
        {"trade_date": "2026-06-29", "action": "Reinvested Dividend", "symbol": "SCHD", "quantity": 12.5, "price": 40.4, "amount": 505.00},
    ])
    assert agg["SCHD"]["dividends_received"] == 505.00
    assert agg["SCHD"]["entries"] == 1
    assert agg["SCHD"]["current_open_shares"] == 12.5
    assert agg["SCHD"]["weighted_average_cost"] == 40.4
