"""Unit tests: content-intelligence taxonomy covers all asset classes.

No live LLM / DB — exercises scoring, tagging, and SUB_TAG_RULES only.
"""
from __future__ import annotations

from content_scoring import score_content, tag_content, STRATEGY_TAG_RULES, AGENT_TAG_RULES
from transcript_tagger import detect_strategy_tag, STRATEGY_AGENTS, STRATEGY_PATTERNS
from transcript_processor import extract_sub_tags, SUB_TAG_RULES, HIGHLIGHT_KEYWORDS


# Enough body text to avoid short-text quality penalty (<500 chars).
_PAD = (" This segment walks through portfolio implications, risk tradeoffs,"
        " and how the thesis fits a multi-year investment research process." * 4)


def test_growth_stock_transcript_scores_relevant_not_low_confidence():
    title = "Best Growth Stocks for Earnings Growth and Moat Analysis"
    text = (
        "This deep dive covers growth stock selection, earnings growth catalysts, "
        "free cash flow quality, valuation vs peers, and competitive moat durability."
        + _PAD
    )
    result = score_content(
        title=title,
        text=text,
        source="youtube",
        channel="Patrick Boyle",
    )
    assert result["relevance_score"] >= 0.3
    assert result["validation_status"] != "low_confidence"
    assert result["validation_status"] == "ai_validated"
    assert result["quality_score"] >= 60


def test_bond_put_covered_call_macro_strategy_tags():
    bond = tag_content(
        "Building a treasury bond ladder for fixed income duration management",
        title="Bond ladder and yield curve",
    )
    assert "bond_income" in bond["strategy_tags"]

    put_etf = tag_content(
        "New put selling and put-write ETF strategies harvesting put premium",
        title="Put ETF overview",
    )
    assert "put_selling_etf" in put_etf["strategy_tags"]

    covered = tag_content(
        "How covered call ETF products generate option income premiums",
        title="Covered call income",
    )
    assert any(
        s in covered["strategy_tags"]
        for s in ("tactical_income", "high_yield_income_bdc")
    )

    macro = tag_content(
        "A macro multi-asset investment thesis on portfolio construction and regime shifts",
        title="Macro outlook",
    )
    assert "macro_multi_asset" in macro["strategy_tags"]
    assert "CIO" in macro["agent_tags"] or any(
        a in macro["agent_tags"] for a in ("CIO", "Maria", "Steph")
    )


def test_retirement_content_still_scores_high():
    title = "Roth Conversion Ladder and SSDI Disability Retirement Planning"
    text = (
        "Walkthrough of Roth IRA conversion, IRMAA brackets, Medicare premiums, "
        "SSDI rules, Medicaid planning, required minimum distributions, and "
        "disability income strategy for retirement."
        + _PAD
    )
    result = score_content(
        title=title,
        text=text,
        source="youtube",
        channel="Ben Felix",
    )
    assert result["relevance_score"] >= 0.45
    assert result["validation_status"] == "ai_validated"
    tags = tag_content(text, title=title)
    assert any(
        s in tags["strategy_tags"]
        for s in ("retirement_planning", "disability_retirement_planning")
    )
    assert "Alex" in tags["agent_tags"]


def test_tagger_detects_bond_put_growth_strategies():
    bond_tag, bond_conf = detect_strategy_tag(
        "Treasury Bond Ladder for Fixed Income",
        "Duration and yield curve",
        "We build a bond ladder with treasury bond and corporate bond fixed income "
        "exposure, managing duration and tips allocation across the yield curve.",
    )
    assert bond_tag == "bond_fixed_income"
    assert bond_conf > 0.3

    put_tag, put_conf = detect_strategy_tag(
        "Put Selling ETF Strategies",
        "Put-write income",
        "This put selling and put etf deep dive covers put-write, put premium, "
        "and defined outcome buffer etf structures for cash secured put etf income.",
    )
    assert put_tag == "put_selling_etf"
    assert put_conf > 0.3

    growth_tag, growth_conf = detect_strategy_tag(
        "Growth Stock Compounders",
        "Earnings growth",
        "Focus on growth stock and growth investing with earnings growth, "
        "revenue growth, and secular growth compounders.",
    )
    assert growth_tag == "growth_equity"
    assert growth_conf > 0.3

    # Non-retirement strategies must not default-route only to investment_general agents
    assert "maria" in STRATEGY_AGENTS["growth_equity"]
    assert "steph" in STRATEGY_AGENTS["bond_fixed_income"]
    assert "cio" in STRATEGY_AGENTS["macro_multi_asset"]
    assert "risk" in STRATEGY_AGENTS["put_selling_etf"]


def test_processor_sub_tag_rules_match_new_keywords():
    assert "growth_equity" in SUB_TAG_RULES
    assert "put_selling_etf" in SUB_TAG_RULES
    assert "fixed_income" in SUB_TAG_RULES
    assert "macro_multi_asset" in SUB_TAG_RULES
    assert "valuation_analysis" in SUB_TAG_RULES

    growth_tags = extract_sub_tags(
        "A growth stock with strong earnings growth and secular growth runway"
    )
    assert "growth_equity" in growth_tags

    bond_tags = extract_sub_tags(
        "Corporate bond and fixed income duration along the yield curve"
    )
    assert "fixed_income" in bond_tags

    put_tags = extract_sub_tags("New put selling put etf buffer etf product")
    assert "put_selling_etf" in put_tags

    covered_tags = extract_sub_tags("Selling calls for covered call premium income")
    assert "covered_call_income" in covered_tags

    macro_tags = extract_sub_tags(
        "Macro thesis and multi-asset portfolio construction under a new market regime"
    )
    assert "macro_multi_asset" in macro_tags

    # Retirement keywords still work
    roth_tags = extract_sub_tags("Backdoor Roth conversion ladder planning")
    assert "roth_conversion_ladder" in roth_tags

    # Highlight lexicon broadened
    for kw in ("growth stock", "valuation", "put selling", "inverse etf", "macro", "bond"):
        assert kw in HIGHLIGHT_KEYWORDS


def test_taxonomy_tables_include_full_desk():
    for key in (
        "bond_income",
        "value_equity",
        "small_cap_equity",
        "put_selling_etf",
        "inverse_bearish_etf",
        "crypto_assets",
        "commodity_assets",
        "international_emerging",
        "macro_multi_asset",
        "retirement_planning",
        "disability_retirement_planning",
    ):
        assert key in STRATEGY_TAG_RULES

    for agent in ("Maria", "Steph", "Risk", "Aegis", "Tax", "Alex", "CIO"):
        assert agent in AGENT_TAG_RULES

    pattern_names = {name for name, _kw, _w in STRATEGY_PATTERNS}
    for name in (
        "bond_fixed_income",
        "growth_equity",
        "put_selling_etf",
        "covered_call_etf",
        "inverse_bearish_etf",
        "macro_multi_asset",
        "disability_retirement",
    ):
        assert name in pattern_names
