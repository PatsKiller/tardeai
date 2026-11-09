"""ANCHOR: ROTATION_EST_SHARES_LQ1407_20261109 — share count is the broker position, never value÷quote.

LQ-20261107-1407 / page defect 146: /v3/rotation showed SPCX as 601.97 and 200.6 shares while the
broker held 600 and 200. api_v2 estimated est_shares = current_value / live_quote; the snapshot
market value and the live quote used different marks.
"""
from __future__ import annotations

import math

import pytest

from scripts.lib.rotation_publication import (
    PublicationError,
    bind_candidate_shares,
    position_share_count,
)


def test_position_share_count_prefers_broker_quantity_fields():
    assert position_share_count({"shares": 600, "quantity": 599, "broker_shares": 598}) == 600.0
    assert position_share_count({"quantity": 200}) == 200.0
    assert position_share_count({"broker_actual_shares": 7.0}) == 7.0
    assert position_share_count({"shares": float("nan")}) is None
    assert position_share_count({"shares": True}) is None  # bool is not a quantity
    assert position_share_count({}) is None


def test_bind_candidate_shares_uses_exact_account_qty_not_value_over_price():
    """The live defect: value 82_704 at quote 137.40 → 601.92; broker shares stay 600."""
    holdings = [
        {"symbol": "SPCX", "account_key": "schwab_rollover_ira", "shares": 600.0,
         "market_value": 82704.0},
        {"symbol": "SPCX", "account_key": "schwab_taxable", "shares": 200.0,
         "market_value": 27568.0},
    ]
    live_quote = 137.40
    cands = [
        {"symbol": "SPCX", "account_key": "schwab_rollover_ira", "current_value": 82704.0,
         "est_shares": round(82704.0 / live_quote, 2)},  # the false estimate
        {"symbol": "SPCX", "account_key": "schwab_taxable", "current_value": 27568.0,
         "est_shares": round(27568.0 / live_quote, 2)},
    ]
    assert cands[0]["est_shares"] == pytest.approx(601.92, abs=0.02)
    assert cands[1]["est_shares"] == pytest.approx(200.64, abs=0.02)

    bind_candidate_shares(cands, holdings)

    assert cands[0]["est_shares"] == 600.0
    assert cands[1]["est_shares"] == 200.0
    # And never equal to value/quote again
    assert cands[0]["est_shares"] != round(cands[0]["current_value"] / live_quote, 2)


def test_bind_candidate_shares_withholds_when_position_missing():
    cands = [{"symbol": "ZZZZ", "account_key": "schwab_taxable", "est_shares": 1.0}]
    bind_candidate_shares(cands, [])
    assert "est_shares" not in cands[0]


def test_bind_candidate_shares_does_not_invent_from_value_alone():
    holdings = [{"symbol": "X", "account_key": "a", "market_value": 1000.0}]  # no shares field
    cands = [{"symbol": "X", "account_key": "a", "current_value": 1000.0, "est_shares": 99.0}]
    bind_candidate_shares(cands, holdings)
    assert "est_shares" not in cands[0]
