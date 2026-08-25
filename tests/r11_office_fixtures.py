"""Shared R11 office fixtures. Isolated, no broker writes."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def policy(*, confirmed: bool = True, extra_fields: dict | None = None) -> dict[str, Any]:
    fields = {
        "cash_target_range_pct": {"value": {"min": 5.0, "max": 15.0}, "operator_confirmed": confirmed},
        "minimum_liquidity_reserve_usd": {"value": 25_000.0, "operator_confirmed": confirmed},
        "equity_range_pct": {"value": {"min": 50.0, "max": 70.0}, "operator_confirmed": confirmed},
        "fixed_income_range_pct": {"value": {"min": 10.0, "max": 25.0}, "operator_confirmed": confirmed},
        "alternatives_range_pct": {"value": {"min": 0.0, "max": 15.0}, "operator_confirmed": confirmed},
        "concentration_hierarchy": {
            "value": {"max_single_name_pct": 12.0},
            "operator_confirmed": confirmed,
        },
    }
    if extra_fields:
        fields.update(extra_fields)
    return {
        "status": "CONFIRMED" if confirmed else "POLICY_REQUIRED",
        "version": "policy_v1",
        "fields": fields,
        "missing_fields": [] if confirmed else ["cash_target_range_pct", "minimum_liquidity_reserve_usd"],
    }


def portfolio(
    *,
    verified: bool = True,
    cash_pct: float = 45.0,
    total: float = 1_000_000.0,
    holdings: list[dict] | None = None,
    truth: str | None = None,
) -> dict[str, Any]:
    cash = total * cash_pct / 100.0
    return {
        "version": "portfolio_v1",
        "truth_quality": truth or ("VERIFIED" if verified else "UNVERIFIED_INVESTABLE"),
        "total_portfolio_value_usd": total,
        "observed_cash_usd": cash,
        "investable_cash_usd": cash - 25_000.0 if verified else None,
        "allocation": {
            "cash": {"pct": cash_pct},
            "equity": {"pct": 60.0 if cash_pct <= 15 else max(0.0, 100.0 - cash_pct - 10.0)},
            "fixed_income": {"pct": 20.0 if cash_pct <= 15 else 10.0},
            "alternatives": {"pct": 0.0},
        },
        "cash_accounts": {"ira": {"reserved_cash_usd": 25_000.0 if verified else None}},
        "holdings": holdings or [],
    }


def market(*, verified: bool = True, regime: str = "risk_on_trend") -> dict[str, Any]:
    return {
        "version": "market_v1",
        "truth_quality": "VERIFIED" if verified else "PARTIAL",
        "fields": {
            "regime": {"value": regime},
            "fed_funds_rate_pct": {"value": 3.63},
            "ten_two_spread_pct": {"value": 0.5},
            "breadth": {"value": "broad"},
            "vix_close": {"value": 16.01},
            "valuation": {"value": None},
            "macro_calendar": {"value": None},
            "portfolio_earnings_calendar": {"value": None},
        },
    }


def thesis(*, current: bool = True) -> dict[str, Any]:
    return {
        "thesis_version": "cio_portfolio@v1",
        "state": "CURRENT" if current else "INSUFFICIENT_DATA",
        "underweight_sleeves": ["equity"] if current else [],
        "core_thesis": "Keep dry powder staged." if current else None,
    }


def seasonality(*, verified: bool = True, setup: str | None = None, material: bool = False) -> dict[str, Any]:
    return {
        "version": "season_v1",
        "truth_quality": "VERIFIED" if verified else "UNAVAILABLE",
        "setup": setup,
        "material_setup": material,
        "material_change": material,
        "what_changed": setup if material else None,
        "window": "Q3" if setup else None,
        "benchmark": "SPY",
    }


def office(**overrides: Any) -> dict[str, Any]:
    base = {
        "portfolio_id": "primary",
        "policy": policy(),
        "portfolio_state": portfolio(),
        "market_context": market(),
        "seasonality": seasonality(),
        "portfolio_thesis": thesis(),
        "ticker_cognition": {},
        "catalysts": [],
        "opportunities": [],
        "research_gaps": [],
        "contradictions": [],
        "outcomes": [],
        "prior_situations": {},
    }
    base.update(overrides)
    return base
