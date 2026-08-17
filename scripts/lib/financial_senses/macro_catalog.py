"""Governed macro series catalog for the FRED/ALFRED provider.

A configuration catalog of series IDs and interpretation metadata. No entry
carries directional trade authority — `decision_use` is descriptive only. The
catalog is data, not financial conclusions.
"""
from __future__ import annotations

from typing import Optional

# Each entry: series_id, name, category, units, frequency, transformation,
# decision_use (descriptive), source. No series gets directional authority.
DEFAULT_CATALOG: list[dict] = [
    {
        "series_id": "DFF",
        "name": "Effective Federal Funds Rate",
        "category": "policy_rate",
        "units": "percent",
        "frequency": "daily",
        "transformation": "none",
        "decision_use": "monetary policy stance",
        "source": "FRED",
    },
    {
        "series_id": "DGS10",
        "name": "10-Year Treasury Constant Maturity Rate",
        "category": "treasury_rate",
        "units": "percent",
        "frequency": "daily",
        "transformation": "none",
        "decision_use": "long-term risk-free rate",
        "source": "FRED",
    },
    {
        "series_id": "DGS2",
        "name": "2-Year Treasury Constant Maturity Rate",
        "category": "treasury_rate",
        "units": "percent",
        "frequency": "daily",
        "transformation": "none",
        "decision_use": "short-term policy expectations",
        "source": "FRED",
    },
    {
        "series_id": "T10Y2Y",
        "name": "10-Year Minus 2-Year Treasury Spread",
        "category": "yield_curve",
        "units": "percent",
        "frequency": "daily",
        "transformation": "none",
        "decision_use": "yield-curve slope",
        "source": "FRED",
    },
    {
        "series_id": "CPIAUCSL",
        "name": "Consumer Price Index for All Urban Consumers",
        "category": "inflation",
        "units": "index",
        "frequency": "monthly",
        "transformation": "none",
        "decision_use": "headline inflation level",
        "source": "FRED",
    },
    {
        "series_id": "UNRATE",
        "name": "Unemployment Rate",
        "category": "labor",
        "units": "percent",
        "frequency": "monthly",
        "transformation": "none",
        "decision_use": "labor market tightness",
        "source": "FRED",
    },
    {
        "series_id": "PAYEMS",
        "name": "Total Nonfarm Payrolls",
        "category": "labor",
        "units": "thousands",
        "frequency": "monthly",
        "transformation": "none",
        "decision_use": "employment growth",
        "source": "FRED",
    },
    {
        "series_id": "GDP",
        "name": "Gross Domestic Product",
        "category": "growth",
        "units": "billions of dollars",
        "frequency": "quarterly",
        "transformation": "none",
        "decision_use": "aggregate growth",
        "source": "FRED",
    },
    {
        "series_id": "BAA10Y",
        "name": "Moody's Baa Corporate Bond Minus 10-Year Treasury",
        "category": "credit",
        "units": "percent",
        "frequency": "daily",
        "transformation": "none",
        "decision_use": "credit spread",
        "source": "FRED",
    },
    {
        "series_id": "NFCI",
        "name": "Chicago Fed National Financial Conditions Index",
        "category": "financial_conditions",
        "units": "index",
        "frequency": "weekly",
        "transformation": "none",
        "decision_use": "broad financial conditions",
        "source": "FRED",
    },
    {
        "series_id": "M2SL",
        "name": "M2 Money Stock",
        "category": "money_liquidity",
        "units": "billions of dollars",
        "frequency": "monthly",
        "transformation": "none",
        "decision_use": "money/liquidity (governed)",
        "source": "FRED",
    },
    {
        "series_id": "MSPUS",
        "name": "Median Sales Price of Houses Sold",
        "category": "housing",
        "units": "dollars",
        "frequency": "quarterly",
        "transformation": "none",
        "decision_use": "housing market level",
        "source": "FRED",
    },
]


def load_catalog(entries: Optional[list[dict]] = None) -> list[dict]:
    return list(entries if entries is not None else DEFAULT_CATALOG)


def get_entry(series_id: str, entries: Optional[list[dict]] = None) -> Optional[dict]:
    sid = (series_id or "").strip().upper()
    for e in load_catalog(entries):
        if e["series_id"].upper() == sid:
            return dict(e)
    return None


def series_ids(entries: Optional[list[dict]] = None) -> list[str]:
    return [e["series_id"] for e in load_catalog(entries)]
