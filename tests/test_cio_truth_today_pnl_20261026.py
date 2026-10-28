"""Header TODAY after a morning holdings reload (2026-10-26).

Live: TODAY rendered "—" during market hours. A broker reload re-added
delisted $0 CUSIP rows and a fractional row without a day_change, and
cio_truth summed day changes all-or-nothing, so one unknown row nulled the
total and every account but one. The census beside it said "5/5 represented,
all zero change" because it compared raw holdings keys to canonical keys and
treated None as flat. Fixtures are invented symbols and amounts.
"""
from datetime import datetime, timezone

from scripts.lib import cio_truth as truth

NOW = datetime(2026, 10, 26, 14, 45, tzinfo=timezone.utc)


def _holdings():
    return {"last_repriced": "2026-10-26 10:45:02 ET", "generated_at": "2026-10-26 10:45:02 ET",
            "reprice_source": "finviz_live", "holdings": [
                {"symbol": "ZZAA", "account": "schwab_taxable", "shares": 10, "price": 50,
                 "market_value": 500, "day_change": 12.5},
                {"symbol": "ZZBB", "account": "schwab_roth", "shares": 4, "price": 25,
                 "market_value": 100, "day_change": -3.0},
                # delisted CUSIP carried at $0, re-added by the reload without a day change
                {"symbol": "000000ZZ9", "account": "schwab_rollover_ira", "shares": 300, "price": 0.0,
                 "market_value": 0.0, "delisted": True},
                {"symbol": "ZZCC", "account": "schwab_rollover_ira", "shares": 2, "price": 40,
                 "market_value": 80, "day_change": 1.0},
                # fractional row with a mark but no prior close: genuinely unknown
                {"symbol": "ZZDD", "account": "moomoo_taxable_live", "shares": 0.25, "price": 80,
                 "market_value": 20.0},
                {"symbol": "CASH", "account": "moomoo_taxable_live", "shares": 5, "market_value": 5,
                 "is_cash": True},
                {"symbol": "CASH", "account": "alpaca_taxable_live", "shares": 0, "market_value": 0,
                 "is_cash": True},
            ]}


def test_one_unknown_row_no_longer_blanks_the_book():
    p = truth.portfolio_for(_holdings(), now=NOW)
    assert p["day_pl_usd"] == 10.5  # 12.5 - 3.0 + 0 (delisted) + 1.0; ZZDD left out, not guessed
    assert p["day_pl_complete"] is False
    assert p["day_pl_coverage"]["unknown_rows"] == 1
    assert p["day_pl_coverage"]["unknown_value_usd"] == 20.0
    assert p["day_pl_coverage"]["unknown_accounts"] == ["moomoo_taxable_live"]
    assert "partial" in p["gap"]["reason"]
    by = {a["account_id"]: a for a in p["accounts"]}
    assert by["schwab_rollover_ira"]["day_pl_usd"] == 1.0 and by["schwab_rollover_ira"]["day_pl_complete"]
    assert by["schwab_roth_ira"]["day_pl_usd"] == -3.0
    assert by["moomoo_taxable_live"]["day_pl_usd"] == 0.0
    assert by["moomoo_taxable_live"]["day_pl_complete"] is False


def test_delisted_zero_value_row_is_a_known_zero_but_a_live_priced_row_is_not():
    h = _holdings()
    p = truth.portfolio_for(h, now=NOW)
    row = next(r for r in p["holdings"] if r["symbol"] == "000000ZZ9")
    assert row["day_change"] == 0.0 and row["day_change_basis"] == "delisted_zero_value"
    assert "day_change" not in h["holdings"][2]  # input never mutated
    # A delisted flag on a row that still carries value is NOT assumed flat.
    h["holdings"][2].update(price=1.0, market_value=300.0)
    p = truth.portfolio_for(h, now=NOW)
    assert p["day_pl_coverage"]["unknown_rows"] == 2


def test_complete_book_reports_complete():
    h = _holdings()
    h["holdings"][4]["day_change"] = 0.5
    p = truth.portfolio_for(h, now=NOW)
    assert p["day_pl_usd"] == 11.0 and p["day_pl_complete"] is True and p["gap"] is None


def _doc(p):
    return {"portfolio": p, "approvals": {"total": 0}, "paper": {},
            "regime": {"label": None, "vix": None, "vix_as_of": None}}


def test_header_shows_partial_sum_and_a_census_on_canonical_keys():
    p = truth.portfolio_for(_holdings(), now=NOW)
    # The legacy census as it shipped: raw keys, every account "flat".
    prior = {"empty_accounts": ["fidelity_rollover_ira"],
             "zero_change_accounts": ["alpaca_taxable_live", "moomoo_taxable_live", "schwab_rollover_ira",
                                      "schwab_roth", "schwab_taxable"], "contributing_accounts": []}
    out = truth.overview_payload({"today_pnl": prior}, document=_doc(p))
    assert out["today_change"] == 10.5 and out["today_pct"] is not None
    tp = out["today_pnl"]
    assert tp["contributing_accounts"] == ["schwab_rollover_ira", "schwab_roth_ira", "schwab_taxable"]
    assert tp["zero_change_accounts"] == ["alpaca_taxable_live", "moomoo_taxable_live"]
    assert "schwab_roth" not in tp["zero_change_accounts"]
    assert tp["missing_accounts"] == [] and tp["empty_accounts"] == ["fidelity_rollover_ira"]
    assert tp["partial_accounts"] == ["moomoo_taxable_live"] and tp["unknown_rows"] == 1
    assert tp["complete"] is False
    assert tp["funded_account_count"] == 5 and tp["represented_account_count"] == 5
    assert "PARTIAL moomoo_taxable_live" in tp["coverage_reason"]
    # The census keys match the per-account figures it describes.
    assert set(tp["contributing_accounts"] + tp["zero_change_accounts"]) == set(out["today_by_account"])


def test_an_account_with_no_known_row_is_missing_not_flat():
    h = _holdings()
    h["holdings"] = [r for r in h["holdings"] if r["account"] != "schwab_taxable"]
    h["holdings"].append({"symbol": "ZZEE", "account": "schwab_taxable", "shares": 1, "price": 9,
                          "market_value": 9})
    p = truth.portfolio_for(h, now=NOW)
    tp = truth.overview_payload({"today_pnl": {"empty_accounts": []}}, document=_doc(p))["today_pnl"]
    assert tp["missing_accounts"] == ["schwab_taxable"]
    assert "schwab_taxable" not in tp["zero_change_accounts"] and tp["complete"] is False
