from scripts.defense_account_exposure import (
    account_sector_exposure,
    sector_weight_for_account,
)


def test_account_exposure_separates_accounts_and_fund_lookthrough():
    holdings = [
        {"account": "ira", "symbol": "XLE", "value": 10_000},
        {"account": "ira", "symbol": "MIX", "value": 20_000},
        {"account": "taxable", "symbol": "XLK", "value": 40_000},
    ]
    fund = {"MIX": {"weights": {"Energy": 0.25, "Technology": 0.50}}}
    sectors = {"XLE": "Energy", "XLK": "Technology"}

    out = account_sector_exposure(holdings, fund, sectors)

    assert out["ira"]["account_equity_dollars"] == 30_000
    assert out["ira"]["sectors"]["Energy"]["dollars"] == 15_000
    assert out["ira"]["sectors"]["Technology"]["dollars"] == 10_000
    assert out["ira"]["unmapped_dollars"] == 5_000
    assert sector_weight_for_account(out, "ira", "Energy") == 50.0

    assert out["taxable"]["account_equity_dollars"] == 40_000
    assert sector_weight_for_account(out, "taxable", "Technology") == 100.0
    assert sector_weight_for_account(out, "taxable", "Energy") is None


def test_unknown_direct_holding_remains_unmapped():
    out = account_sector_exposure(
        [{"account": "ira", "symbol": "UNKNOWN", "market_value": 1_250}],
        {},
        {},
    )
    assert out["ira"]["mapped_dollars"] == 0
    assert out["ira"]["unmapped_dollars"] == 1_250
    assert out["ira"]["unmapped_pct"] == 100.0


def test_cash_zero_and_invalid_rows_are_excluded():
    out = account_sector_exposure(
        [
            {"account": "ira", "symbol": "CASH", "value": 50_000, "is_cash": True},
            {"account": "ira", "symbol": "XLE", "value": 0},
            {"account": "", "symbol": "XLK", "value": 100},
        ],
        {},
        {"XLE": "Energy", "XLK": "Technology"},
    )
    assert out == {}


def test_fund_weights_are_capped_and_never_create_negative_unmapped():
    out = account_sector_exposure(
        [{"account": "ira", "symbol": "FUND", "value": 10_000}],
        {"FUND": {"weights": {"Energy": 0.8, "Technology": 0.7}}},
        {},
    )
    assert out["ira"]["sectors"]["Energy"]["dollars"] == 8_000
    assert out["ira"]["sectors"]["Technology"]["dollars"] == 7_000
    assert out["ira"]["unmapped_dollars"] == 0
