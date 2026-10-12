"""AST-extracted display helper only; the trading pipeline is never imported or run."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def formatter():
    tree = ast.parse((ROOT / "scripts" / "trade_ai_orchestrator.py").read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_market_context_detail")
    namespace = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<isolated-market-context-display>", "exec"), namespace)
    return namespace["_market_context_detail"]


def test_real_zero_change_and_known_numbers_keep_their_format():
    rendered = formatter()(
        {
            "indices": {"SPY": {"change_percent": 0.0}},
            "vix": {"price": 18.25},
            "breadth_label": "mixed",
            "sector_leader": {"symbol": "XLK"},
            "sector_laggard": {"symbol": "XLE"},
        }
    )
    assert rendered == "SPY +0.00%  VIX 18.2  mixed  ▲XLK  ▼XLE"


@pytest.mark.parametrize(
    "snapshot",
    [{}, {"indices": None, "vix": None}, {"indices": {"SPY": {"change_percent": None}}, "vix": {"price": None}}],
)
def test_missing_or_null_observations_are_unavailable_instead_of_zero(snapshot):
    rendered = formatter()(snapshot)
    assert "SPY unavailable" in rendered and "VIX unavailable" in rendered
    assert "+0.00" not in rendered and "VIX 0.0" not in rendered


@pytest.mark.parametrize(
    "snapshot",
    [
        None,
        [],
        {"indices": []},
        {"indices": {"SPY": []}},
        {"indices": {"SPY": {"change_percent": False}}},
        {"vix": {"price": "18.0"}},
        {"vix": {"price": float("nan")}},
        {"vix": {"price": float("inf")}},
        {"breadth_label": []},
        {"sector_leader": {"symbol": 7}},
    ],
)
def test_malformed_market_observations_refuse_display(snapshot):
    with pytest.raises(ValueError, match="invalid market context"):
        formatter()(snapshot)


def test_formatter_is_used_at_market_context_stage_without_snapshot_mutation():
    tree = ast.parse((ROOT / "scripts" / "trade_ai_orchestrator.py").read_text())
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_ok"
        and n.args
        and isinstance(n.args[0], ast.Constant)
        and n.args[0].value == "market_context"
    ]
    assert len(calls) == 1 and ast.unparse(calls[0].args[1]) == "_market_context_detail(market_snapshot)"
    snapshot = {"indices": {"SPY": {"change_percent": None}}, "vix": {"price": None}}
    before = repr(snapshot)
    formatter()(snapshot)
    assert repr(snapshot) == before
