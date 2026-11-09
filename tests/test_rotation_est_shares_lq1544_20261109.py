"""The rotation writer publishes the broker share count.

ANCHOR: ROTATION_EST_SHARES_LQ1544_20261109

Page defect 146: /v3/rotation set est_shares to current value divided by the
live quote. The holdings row already carries the broker quantity. Synthetic
rows only.
"""
from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest

from scripts.lib.rotation_publication import bind_candidate_shares, position_share_count

ROOT = Path(__file__).resolve().parents[1]


def test_position_share_count_prefers_the_broker_quantity():
    assert position_share_count({"shares": 10, "quantity": 9}) == 10.0
    assert position_share_count({"quantity": 4}) == 4.0
    assert position_share_count({"broker_actual_shares": 7.0}) == 7.0
    assert position_share_count({"shares": float("nan")}) is None
    assert position_share_count({"shares": True}) is None
    assert position_share_count({}) is None


def test_bind_uses_the_account_quantity_not_value_over_price():
    quote = 140.0
    holdings = [
        {"symbol": "SYN", "account_key": "acct_a", "shares": 10.0, "market_value": 1500.0},
        {"symbol": "SYN", "account_key": "acct_b", "shares": 4.0, "market_value": 600.0},
    ]
    cands = [
        {
            "symbol": "SYN",
            "account_key": "acct_a",
            "current_value": 1500.0,
            "est_shares": round(1500.0 / quote, 2),
        },
        {
            "symbol": "SYN",
            "account_key": "acct_b",
            "current_value": 600.0,
            "est_shares": round(600.0 / quote, 2),
        },
    ]
    assert cands[0]["est_shares"] == pytest.approx(10.71, abs=0.02)
    assert cands[1]["est_shares"] == pytest.approx(4.29, abs=0.02)

    bind_candidate_shares(cands, holdings)

    assert cands[0]["est_shares"] == 10.0
    assert cands[1]["est_shares"] == 4.0
    assert cands[0]["est_shares"] != round(cands[0]["current_value"] / quote, 2)
    assert math.isfinite(cands[1]["est_shares"])


def test_bind_withholds_when_the_position_is_missing_or_has_no_quantity():
    missing = [{"symbol": "ZZZ", "account_key": "acct_a", "est_shares": 3.0}]
    bind_candidate_shares(missing, [])
    assert "est_shares" not in missing[0]

    no_qty = [{"symbol": "SYN", "account_key": "acct_a", "current_value": 1000.0, "est_shares": 8.0}]
    holdings = [{"symbol": "SYN", "account_key": "acct_a", "market_value": 1000.0}]
    bind_candidate_shares(no_qty, holdings)
    assert "est_shares" not in no_qty[0]


def _est_share_divisions(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Subscript):
                continue
            sl = target.slice
            if isinstance(sl, ast.Constant) and sl.value == "est_shares":
                if any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div) for n in ast.walk(node.value)):
                    lines.append(node.lineno)
    return lines


def test_the_rotation_writer_does_not_divide_value_by_price():
    source = (ROOT / "scripts" / "api_v2.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert _est_share_divisions(tree) == []
    called = any(
        isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "bind_candidate_shares")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "bind_candidate_shares")
        )
        for node in ast.walk(tree)
    )
    assert called
