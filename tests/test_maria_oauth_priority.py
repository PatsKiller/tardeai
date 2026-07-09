#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import maria_oauth_priority as mop  # noqa: E402


def test_portfolio_holding_in_tier():
    assert mop.maria_priority_tier(
        "AAPL",
        portfolio_symbols={"AAPL"},
        wait_symbols=set(),
    )


def test_wait_setup_in_tier():
    assert mop.maria_priority_tier(
        "SMCI",
        portfolio_symbols=set(),
        wait_symbols={"SMCI"},
    )


def test_tail_symbol_out_of_tier():
    assert not mop.maria_priority_tier(
        "ZZZZ",
        portfolio_symbols={"AAPL"},
        wait_symbols={"SMCI"},
        submitted_from="research_scheduler",
        priority=5,
        request_type="scheduled_research",
    )


def test_manual_requeue_in_tier():
    assert mop.maria_priority_tier(
        "TSLA",
        portfolio_symbols=set(),
        wait_symbols=set(),
        submitted_from="watchlist_requeue",
        priority=0,
        request_type="full_analysis",
    )


def test_command_center_holdings_priority():
    assert mop.maria_priority_tier(
        "NVDA",
        portfolio_symbols=set(),
        wait_symbols=set(),
        submitted_from="command_center",
        priority=1,
        request_type="scheduled_research",
    )


def test_command_center_tail_not_manual():
    assert not mop.is_manual_refresh("command_center", priority=3, request_type="scheduled_research")