"""Every registry domain is read for the prospectus or excluded with a reason (operator 2026-10-26:
"I want to make sure we're not missing any information"). Adding a domain to config/data_source_authority.json
without wiring it here fails CI."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib.prospectus import load_config  # noqa: E402
from scripts.lib.prospectus import domains as dm  # noqa: E402

TICKER_DOMAINS = {
    "quote_price", "symbol_identity", "analyst_opinion", "catalyst_news", "technicals", "sector_momentum",
    "industry_momentum", "market_regime", "earnings_date", "earnings_calendar", "holdings_accounts", "positions_store",
    "options_iv", "research_thesis", "watch_directives", "web_search", "private_company", "dividends", "macro",
    "fundamentals", "agent_opinion", "agent_debate", "ai_reports", "sec_filing_events", "finviz_enrichment",
    "news_sentiment", "social_posts", "yfinance_info_snapshot", "cio_prospect", "opportunity_assessment",
    "counterfactual_ledger", "intelligence_research_index",
}


def test_every_registry_domain_is_consumed_or_excluded_with_a_reason():
    mapping = load_config()["registry_domains"]
    registry = dm.registry_domains()
    missing = [d for d in registry if d not in mapping]
    assert not missing, f"wire these registry domains into config/prospectus.json registry_domains: {missing}"
    for domain in registry:
        spec = mapping[domain]
        if "excluded" in spec:
            assert len(spec["excluded"].strip()) >= 20, domain
        elif "covered_by" in spec:
            assert spec["covered_by"], domain
        else:
            assert spec.get("reader", domain) in dm.READERS, domain


def test_operator_named_ticker_domains_are_all_read():
    mapping = load_config()["registry_domains"]
    excluded = sorted(d for d in TICKER_DOMAINS if "excluded" in mapping.get(d, {"excluded": "absent"}))
    assert excluded == [], excluded


def test_registry_is_the_one_in_the_repo():
    names = [d["domain"] for d in json.loads((ROOT / "config/data_source_authority.json").read_text())["domains"]]
    assert names == dm.registry_domains() and len(names) >= 61
