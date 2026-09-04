#!/usr/bin/env python3
"""portfolio_aggregate_contract — oldest/newest from the same accounts[] clocks.

Reproduces the 2026-09-03 live-acceptance failure shape from deploy evidence
(candidate abbe880e): top-level data_as_of named alpaca@2026-09-03 as "oldest"
while accounts[] carried schwab_rollover_ira@2026-07-17 and newest=2026-07-17.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.portfolio_aggregate_contract import (  # noqa: E402
    SCOPE_ALL_ACCOUNTS,
    build_portfolio_aggregate,
    derive_observation_bounds,
)


# Exact shape from post__api_v2_overview.json (deploy evidence 20260904T002700Z).
LIVE_FAIL_SUMMARIES = {
    "alpaca_taxable_live": {"total_value": 100.0, "holdings_count": 1, "as_of": ""},
    "fidelity_rollover_ira": {
        "total_value": 200.0,
        "holdings_count": 2,
        "as_of": "2026-07-16",
    },
    "moomoo_taxable_live": {"total_value": 300.0, "holdings_count": 3, "as_of": ""},
    "schwab_rollover_ira": {
        "total_value": 400.0,
        "holdings_count": 4,
        "as_of": "2026-07-17",
    },
    "schwab_roth": {"total_value": 500.0, "holdings_count": 5, "as_of": ""},
    "schwab_taxable": {"total_value": 600.0, "holdings_count": 6, "as_of": ""},
}


def test_live_fail_shape_no_longer_reverses_oldest_newest():
    """The defect: data_as_of stamped oldest while accounts[] max was earlier."""
    now = datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc)
    agg = build_portfolio_aggregate(
        aggregate_value=1_284_446.4,
        account_summaries=LIVE_FAIL_SUMMARIES,
        data_as_of="2026-09-03",
        data_as_of_account="alpaca_taxable_live",
        now=now,
    )
    assert agg["portfolio_scope"] == SCOPE_ALL_ACCOUNTS
    assert agg["aggregate_scope"] == SCOPE_ALL_ACCOUNTS
    assert agg["included_account_count"] == 6

    # Named empty row is stamped from data_as_of so alpaca enters the clock set.
    alpaca = next(a for a in agg["accounts"] if a["account"] == "alpaca_taxable_live")
    assert alpaca["observation_time"] == "2026-09-03"

    # Oldest is the earliest dated row, not the holdings-row data_as_of account.
    assert agg["oldest_observation_account"] == "fidelity_rollover_ira"
    assert agg["oldest_observation_time"] == "2026-07-16"
    assert agg["newest_observation_time"] == "2026-09-03"

    o = datetime.fromisoformat(agg["oldest_observation_time"])
    n = datetime.fromisoformat(agg["newest_observation_time"])
    assert o <= n
    # Stale vs a Sep-3 clock with July oldest.
    assert agg["freshness_state"] == "STALE"


def test_derive_bounds_ignores_empty_observation_times():
    accounts = [
        {"account": "a", "observation_time": ""},
        {"account": "b", "observation_time": "2026-07-16"},
        {"account": "c", "observation_time": "2026-07-17"},
    ]
    oldest, acct, newest = derive_observation_bounds(accounts)
    assert oldest == "2026-07-16"
    assert acct == "b"
    assert newest == "2026-07-17"


def test_no_dated_rows_yields_partial_without_invented_oldest():
    agg = build_portfolio_aggregate(
        aggregate_value=1.0,
        account_summaries={"x": {"total_value": 1, "as_of": ""}},
        data_as_of=None,
        data_as_of_account=None,
    )
    assert agg["oldest_observation_time"] is None
    assert agg["oldest_observation_account"] is None
    assert agg["newest_observation_time"] is None
    assert agg["freshness_state"] == "PARTIAL"
