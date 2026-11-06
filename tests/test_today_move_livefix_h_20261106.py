"""LIVEFIX-H 2026-11-06: header TODAY / Home "Today" vs Home Accounts 1D.

Live: the header read "TODAY ECONOMIC UNKNOWN · P&L session UNDATED" and the
Home summary "Today —" while the Accounts table showed a dated 1D move. Root
cause: overview_payload always nulls today_change and marks today_pnl UNKNOWN
(OI-044, no economic-day proof), and the header/summary read nothing else.
The fix republishes the Accounts-table figure (/portfolio/performance
periods.1D, portfolio_market_day over the same holdings) as overview.today_move
with its mark session and coverage. All fixtures are synthetic.
"""
from datetime import datetime, timezone

from scripts.lib import cio_truth as truth
from scripts.portfolio_snapshot_sanity import account_market_days, apply_market_day_1d, portfolio_market_day

NOW = datetime(2026, 11, 4, 19, 0, tzinfo=timezone.utc)  # Wed 14:00 ET, session open


def _holdings(extra=None):
    rows = [
        {"account": "synthetic_alpha", "symbol": "ZZAA", "shares": 10, "price": 110,
         "market_value": 1100, "day_change": 100.0},
        {"account": "synthetic_beta", "symbol": "ZZBB", "shares": 5, "price": 40,
         "market_value": 200, "day_change": -20.0},
        {"account": "synthetic_beta", "symbol": "CASH", "is_cash": True, "market_value": 50},
    ] + list(extra or [])
    return {"generated_at": "2026-11-04T18:59:00Z", "last_repriced": "2026-11-04T18:58:00Z",
            "reprice_source": "synthetic", "account_summaries": {},
            "portfolio_totals": {"total_value": sum(r["market_value"] for r in rows)},
            "_finviz_day_pct": {}, "holdings": rows}


def _doc(p):
    return {"portfolio": p, "approvals": {"total": 0}, "paper": {},
            "regime": {"label": None, "vix": None, "vix_as_of": None}}


def _overview_with_move(h):
    out = truth.overview_payload({}, document=_doc(truth.portfolio_for(h, now=NOW)), now=NOW)
    out["today_move"] = truth.today_move_payload(portfolio_market_day(h), account_market_days(h), out["today_pnl"])
    return out


def test_header_move_equals_accounts_table_1d_and_is_dated():
    h = _holdings()
    out = _overview_with_move(h)
    # Reference truth: the performance endpoint's 1D (Home Accounts table) from the same holdings.
    perf = apply_market_day_1d({"periods": {}, "accounts": {}}, h)
    move = out["today_move"]
    assert move["status"] == "REPORTED"
    assert move["change"] == perf["periods"]["1D"]["change"] == 80.0
    for acct, row in perf["accounts"].items():
        assert move["by_account"][acct]["change"] == row["periods"]["1D"]["change"]
    # The bug: no session date reached the header. The move carries its mark session.
    assert move["session_date"] == "2026-11-04"
    assert move["session_source"] == "holdings.last_repriced"
    assert move["market_session"]["latest_open_session"] == "2026-11-04"
    assert move["complete"] is True and move["missing_accounts"] == [] and move["partial_accounts"] == []
    # The economic contract is unchanged: still UNKNOWN, still null, and the move says so.
    assert out["today_change"] is None and out["today_pnl"]["status"] == "UNKNOWN"
    assert move["economic_status"] == "UNKNOWN" and "OI-044" in move["note"]


def test_partial_coverage_keeps_the_number_and_names_the_gap():
    h = _holdings([{"account": "synthetic_gamma", "symbol": "ZZCC", "shares": 1, "price": 30, "market_value": 30}])
    move = _overview_with_move(h)["today_move"]
    assert move["change"] == portfolio_market_day(h)["change"]
    assert move["complete"] is False
    # gamma's only row has no day change: named as MISSING beside the number, not hidden.
    assert move["missing_accounts"] == ["synthetic_gamma"]
    assert move["unknown_rows"] == 1
    assert "MISSING synthetic_gamma" in move["coverage_reason"]


def test_no_market_day_figure_is_unknown_never_invented():
    out = truth.overview_payload({}, document=_doc(truth.portfolio_for(_holdings(), now=NOW)), now=NOW)
    move = truth.today_move_payload(None, {}, out["today_pnl"])
    assert move["status"] == "UNKNOWN" and move["change"] is None and move["session_date"] is None
    assert move["gap"]["reason"]


def test_overview_route_and_performance_share_one_overlay():
    import inspect

    import scripts.api_v2 as api_v2

    assert "_market_day_holdings(holdings)" in inspect.getsource(api_v2.portfolio_performance)
    route = inspect.getsource(api_v2._overview_with_today_move)
    assert "_market_day_holdings(" in route and "today_move_payload(" in route
    assert "_overview_with_today_move()" in inspect.getsource(api_v2.ROUTES["/api/v2/overview"])
