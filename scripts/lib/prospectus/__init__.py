"""Ticker Prospectus — one sourced, versioned research document per held or watched symbol.

Contract (operator-approved 2026-10-26): persistent-state ``coordination/handoffs/prospectus-20261026/CONTRACT.md``.
READ_ONLY_ADVISORY: nothing here sizes, orders, stops or weights (MBI_BEHAVIOR=0). Real data lives only under the
private state root (``data/prospectus``); the public repo carries code and synthetic fixtures only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
CONFIG_REL = "config/prospectus.json"
SCHEMA = "Prospectus@v1"
INDEX_SCHEMA = "ProspectusIndex@v1"
QUEUE_SCHEMA = "ProspectusQueue@v1"

SECTION_IDS = (
    "summary_verdict", "business_and_moat", "financials_and_trend", "valuation_vs_peers",
    "catalysts_and_dates", "risks", "analyst_view", "thesis_breakers", "position_and_plan",
)
SECTION_TITLES = {
    "summary_verdict": "Summary verdict",
    "business_and_moat": "Business and moat",
    "financials_and_trend": "Financials and trend",
    "valuation_vs_peers": "Valuation vs peers",
    "catalysts_and_dates": "Catalysts and dates",
    "risks": "Risks",
    "analyst_view": "Analyst view",
    "thesis_breakers": "Thesis breakers",
    "position_and_plan": "Position and plan",
}
DELTA_SECTION_IDS = ("summary_verdict", "catalysts_and_dates", "position_and_plan")
CHART_IDS = ("price_1y", "relative_performance", "revenue_eps_trend", "eps_surprise", "valuation_vs_peers",
             "analyst_targets", "position_pl")
BLOCK_IDS = ("relative_performance", "peer_comparison", "estimates", "ownership_flows", "risk_technicals", "scenarios",
             "macro_sensitivity", "sec_filings", "earnings_call", "options_sentiment_dividends", "fund_lookthrough",
             "stop_plan")


def sections_for(scope: str) -> tuple[str, ...]:
    """Holdings carry position_and_plan; watch items do not."""
    return SECTION_IDS if scope == "holding" else SECTION_IDS[:-1]


def load_config(root: Path | None = None) -> dict[str, Any]:
    return json.loads(((root or ROOT) / CONFIG_REL).read_text(encoding="utf-8"))
