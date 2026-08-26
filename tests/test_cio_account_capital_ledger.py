"""Phase 6 — account-level capital ledger narrative."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from scripts.lib.cio_capital_plan import (  # noqa: E402
    build_account_capital_ledger,
    build_capital_plan,
    CAPITAL_PLAN_VERSION,
)


def test_plan_version_1_3():
    assert CAPITAL_PLAN_VERSION.startswith("capital_plan_1.3")


def test_earmark_not_new_capital_narrative():
    led = build_account_capital_ledger(
        account_cash=[
            {"account": "ira", "settled_cash_usd": 40_000.0},
            {"account": "taxable", "settled_cash_usd": 10_000.0},
        ],
        positions=[
            {"account": "ira", "market_value_usd": 200_000.0},
            {"account": "taxable", "market_value_usd": 50_000.0},
        ],
        portfolio_value=300_000.0,
        cash_total=50_000.0,
        reserve_usd=60_000.0,  # 20% band would be 60k — example
        earmarked_redeploy_usd=50_000.0,  # all cash earmarked (Phase 0 bug shape)
        prospective_raise_usd=5_000.0,
        net_deploy_usd=5_000.0,
        post_plan_cash_usd=50_000.0,
    )
    assert "not new capital" in led["narrative"].lower() or "not new" in led["earmark_language"].lower()
    assert "earmarked" in led["narrative"].lower()
    assert led["portfolio_aggregate"]["earmarked_usd"] == 50_000.0
    assert led["invariants"]["earmark_le_settled_cash"] is True
    assert len(led["accounts"]) == 2


def test_plan_embeds_account_ledger():
    plan = build_capital_plan(
        portfolio_value=100_000.0,
        cash_total=25_000.0,
        positions=[],
        account_cash=[{"account": "main", "settled_cash_usd": 25_000.0}],
    )
    assert "account_capital_ledger" in plan
    assert plan["earmark_narrative"]
    assert plan["account_capital_ledger"]["portfolio_aggregate"]["settled_cash_usd"] == 25_000.0
