"""content_scoring.py — Unified scoring for news, YouTube, and social media.

Provides quality_score, relevance_score, and validation_status for any ingested content.
Used by news_ingestion.py, youtube_transcript_ingest.py, and social_monitor.py.
"""
from datetime import datetime, timezone


# Keywords that boost relevance across the full investment research desk
# (equities, fixed income, ETFs/options income, crypto, commodities, macro,
# retirement/disability — retirement keywords retained for continuity).
RELEVANCE_KEYWORDS = {
    "high": [
        # Income / dividends / retirement (legacy — keep working)
        "dividend", "yield", "income", "roth", "ira", "401k", "retirement",
        "distribution", "payout", "ex-dividend", "dividend growth", "covered call",
        "bdc", "cef", "preferred", "reits", "reit", "mlp",
        "irmaa", "medicare", "social security", "rmd", "required minimum",
        "tax bracket", "capital gains", "tax loss", "conversion",
        "ssdi", "disability", "medicaid", "dual eligible", "special needs trust",
        "pooled trust", "able account", "spend down", "elder law",
        "medicaid planning", "disability income", "sga", "trial work period",
        "long term disability", "ltdi", "medicare supplement", "medigap",
        # Equities by style
        "growth stock", "growth investing", "value stock", "value investing",
        "small cap", "small-cap", "mid cap", "large cap", "megacap",
        "earnings growth", "free cash flow", "moat", "compounder",
        # Fixed income / bonds
        "treasury", "bond ladder", "fixed income", "duration risk",
        "yield curve", "corporate bond", "municipal bond", "tips", "ig bond",
        # Options / income ETFs
        "covered call etf", "put selling", "put etf", "cash secured put",
        "defined outcome", "buffer etf", "wheel strategy", "option premium",
        # Inverse / bearish
        "inverse etf", "bear etf", "short etf", "3x inverse", "hedge etf",
        # Crypto / commodities
        "bitcoin", "ethereum", "crypto etf", "spot bitcoin", "digital asset",
        "gold etf", "silver etf", "commodity", "oil futures", "copper",
        # International / emerging / macro
        "emerging market", "international equity", "developed market",
        "fx risk", "currency hedge", "global allocation",
        "macro thesis", "portfolio construction", "multi-asset",
        "secular theme", "investment thesis",
    ],
    "medium": [
        "earnings", "guidance", "revenue", "margin", "buyback", "debt",
        "interest rate", "fed", "inflation", "recession", "valuation",
        "pe ratio", "price target", "analyst", "upgrade", "downgrade",
        "sector rotation", "allocation", "rebalance", "risk",
        "bond", "treasury yield", "credit spread", "duration",
        "growth", "value", "smallcap", "factor investing", "quality factor",
        "etf", "options", "implied volatility", "put write", "covered call",
        "crypto", "bitcoin etf", "blockchain", "commodity etf", "gold",
        "emerging markets", "international", "developed markets", "china",
        "macro", "gdp", "pmi", "employment", "cpi", "fomc",
        "inverse", "bearish", "hedge", "tail risk",
    ],
    "low": [
        "stock", "market", "rally", "sell-off", "volatility", "s&p",
        "nasdaq", "dow", "bull", "bear", "momentum",
        "equities", "fixed income", "asset class", "diversify",
    ],
}

# Source quality tiers
SOURCE_QUALITY = {
    "seeking_alpha": 75,
    "morningstar": 85,
    "barrons": 80,
    "motley_fool": 55,
    "yahoo_finance": 50,
    "finnhub": 45,
    "youtube": 40,  # base, boosted by channel reputation
    "unknown": 30,
}

# Known high-quality YouTube channels across asset classes
TRUSTED_YOUTUBE_CHANNELS = {
    # Existing — dividend / retirement / income
    "dividend bull": 75, "dividendbull": 75,
    "joseph carlson": 70, "josephcarlson": 70,
    "ppc ian": 65, "ppcian": 65,
    "dave ramsey": 60, "the plain bagel": 70,
    "ben felix": 80, "rob berger": 70,
    "nick murray": 75, "income investors": 65,
    "dividend data": 65, "investkaki": 55,
    "rational reminder": 70, "joe f. schmitz": 70,
    "peak retirement": 70, "strong man personal finance": 55,
    # Dividend & Compounding
    "dividend growth investing": 70, "genexdividendinvestor": 65,
    "josh invests": 60, "dividend guy": 60,
    "ryne williams": 55, "the wealthy listener": 55,
    "financial education": 65, "longacres finance": 55,
    "doctor dividend": 60,
    # Swing Trading
    "humbled trader": 70, "desire to trade": 60,
    "oliver velez": 65, "carter farr": 55,
    "swing trade pros": 55, "t3 live": 60, "t3live": 60,
    "trader talks": 60, "felix and friends": 55,
    # Retirement / SSDI / Tax
    "financial fast lane": 65, "paytaxeslater": 70, "james lange": 70,
    "mission financial": 65, "fedlife": 60,
    # Market Trends / Sectors (existing)
    "stockcharts": 70, "tastylive": 70,
    "yahoo finance": 65, "investors podcast": 65,
    "everything money": 65, "sven carlin": 70,
    "the swedish investor": 65, "brian stoffel": 60,
    "couch investor": 55,
    # Growth / equities / fundamental analysis
    "aswath damodaran": 85, "damodaran lectures": 80,
    "patrick boyle": 75, "new money": 65,
    "meet kevin": 55, "graham stephan": 55,
    "the investor channel": 60, "fundamental edge": 65,
    "value investing with sage": 60, "buffettsbooks": 70,
    # Macro / markets / Fed
    "bloomberg markets": 80, "bloomberg television": 75,
    "cnbc": 70, "reuters": 75,
    "real vision": 70, "macro voices": 70,
    "lynaldeninvestmentstrategy": 75, "lyn alden": 75,
    "forward guidance": 70, "blockworks macro": 65,
    "felix zulauf": 65, "campbell harvey": 70,
    # Options / ETF / income structures
    "option alpha": 70, "tastytrade": 70,
    "in the money": 65, "projectoption": 65,
    "etf.com": 70, "etf trends": 65,
    "theetfeducator": 60, "simplified trading": 55,
    # Crypto / commodities (reputable education-leaning)
    "coin bureau": 60, "whiteboard crypto": 55,
    "kitco news": 65, "commodities report": 55,
    # International / global
    "visualpolitik en": 55, "economics explained": 60,
}


def score_content(title: str, text: str, source: str = "unknown",
                  channel: str = "", symbols: list = None) -> dict:
    """Score content for quality and relevance.

    Returns:
        {
            "quality_score": 0-100,
            "relevance_score": 0.0-1.0,
            "validation_status": "ai_validated" | "low_confidence" | "unscored",
            "matched_keywords": [...],
            "content_type": "news" | "youtube" | "transcript",
        }
    """
    title_lower = (title or "").lower()
    text_lower = (text or "").lower()
    combined = f"{title_lower} {text_lower}"
    symbols = symbols or []

    # --- Quality Score ---
    base_quality = SOURCE_QUALITY.get(source.lower().replace(" ", "_"), 30)

    # YouTube channel boost — flexible matching (handles spaces, no spaces, partial names)
    if source.lower() == "youtube" and channel:
        ch_lower = channel.lower().replace(" ", "")
        ch_lower_spaced = channel.lower()
        for ch_name, ch_score in TRUSTED_YOUTUBE_CHANNELS.items():
            ch_key = ch_name.replace(" ", "")
            if ch_key in ch_lower or ch_name in ch_lower_spaced or ch_lower in ch_key:
                base_quality = max(base_quality, ch_score)
                break

    # Length penalty: very short = low quality
    text_len = len(text or "")
    if text_len < 100:
        base_quality = max(10, base_quality - 30)
    elif text_len < 500:
        base_quality = max(20, base_quality - 10)

    # Clickbait penalty
    clickbait_signals = ["🚀", "!!!!", "guaranteed", "get rich", "secret", "you won't believe"]
    for cb in clickbait_signals:
        if cb in combined:
            base_quality = max(10, base_quality - 15)
            break

    quality_score = min(100, max(0, base_quality))
    try:
        from hermes_source_policy import apply_quality_policy
        quality_score = apply_quality_policy(source, quality_score)
    except Exception:
        pass

    # --- Relevance Score ---
    matched = []
    relevance = 0.0

    for kw in RELEVANCE_KEYWORDS["high"]:
        if kw in combined:
            relevance += 0.15
            matched.append(kw)

    for kw in RELEVANCE_KEYWORDS["medium"]:
        if kw in combined:
            relevance += 0.08
            matched.append(kw)

    for kw in RELEVANCE_KEYWORDS["low"]:
        if kw in combined:
            relevance += 0.03
            matched.append(kw)

    # Symbol mention boost
    for sym in symbols:
        if sym.lower() in combined:
            relevance += 0.1
            matched.append(f"${sym}")

    relevance_score = min(1.0, relevance)

    # --- Validation Status ---
    if quality_score >= 60 and relevance_score >= 0.3:
        validation_status = "ai_validated"
    elif quality_score < 30 or relevance_score < 0.1:
        validation_status = "low_confidence"
    else:
        validation_status = "unscored"

    content_type = "youtube" if source.lower() == "youtube" else "social" if source.lower() in ("x", "twitter", "reddit", "stocktwits") else "news"

    return {
        "quality_score": quality_score,
        "relevance_score": round(relevance_score, 3),
        "validation_status": validation_status,
        "matched_keywords": matched[:10],
        "content_type": content_type,
    }


# ── Social media scoring ────────────────────────────────────────────────

# Known credible finance accounts on X/Twitter
TRUSTED_SOCIAL_ACCOUNTS = {
    "dividendgrowth": 70,
    "divgro": 70,
    "earlyretirementnow": 75,
    "modestmoney": 60,
    "thefinancebuff": 70,
    "boaborern": 65,  # Bogleheads
    "morningstar": 80,
    "seekingalpha": 70,
    "marketwatch": 65,
    "cnaborern": 60,
    "unusual_whales": 55,
}

MISINFO_SIGNALS = [
    "guaranteed returns", "100x", "1000x", "to the moon", "not financial advice",
    "act now", "limited time", "free money", "insider info", "pump",
    "manipulation", "short squeeze imminent", "trust me bro",
]

SENTIMENT_POSITIVE = ["bullish", "upgrade", "beat", "raised guidance", "strong buy", "outperform", "dividend increase", "special dividend"]
SENTIMENT_NEGATIVE = ["bearish", "downgrade", "miss", "cut dividend", "sell", "underperform", "warning", "bankruptcy"]


def score_social_post(text: str, username: str = "", platform: str = "x",
                      followers: int = 0, verified: bool = False,
                      likes: int = 0, retweets: int = 0, replies: int = 0,
                      post_date: datetime = None, symbols: list = None) -> dict:
    """Score a social media post using the unified scoring dimensions.

    Weights: relevance 35%, recency 20%, engagement 15%, credibility 15%,
             sentiment 10%, misinfo risk 5%.

    Returns same shape as score_content() plus social-specific fields.
    """
    text_lower = (text or "").lower()
    symbols = symbols or []

    # 1. RELEVANCE (35%) — reuse keyword matching
    matched = []
    relevance_raw = 0.0
    for kw in RELEVANCE_KEYWORDS["high"]:
        if kw in text_lower:
            relevance_raw += 0.15
            matched.append(kw)
    for kw in RELEVANCE_KEYWORDS["medium"]:
        if kw in text_lower:
            relevance_raw += 0.08
            matched.append(kw)
    for kw in RELEVANCE_KEYWORDS["low"]:
        if kw in text_lower:
            relevance_raw += 0.03
            matched.append(kw)
    for sym in symbols:
        if f"${sym.lower()}" in text_lower or sym.lower() in text_lower:
            relevance_raw += 0.12
            matched.append(f"${sym}")
    relevance_score = min(1.0, relevance_raw)
    relevance_pts = min(35, relevance_score * 35)

    # 2. RECENCY (20%)
    recency_pts = 10  # default mid
    if post_date:
        now = datetime.now(timezone.utc)
        pd = post_date if post_date.tzinfo else post_date.replace(tzinfo=timezone.utc)
        age_hours = max(0, (now - pd).total_seconds() / 3600)
        if age_hours < 1:
            recency_pts = 20
        elif age_hours < 6:
            recency_pts = 17
        elif age_hours < 24:
            recency_pts = 14
        elif age_hours < 72:
            recency_pts = 10
        elif age_hours < 168:
            recency_pts = 6
        else:
            recency_pts = 2

    # 3. ENGAGEMENT VELOCITY (15%)
    total_engagement = likes + retweets + replies
    if total_engagement > 1000:
        engage_pts = 15
    elif total_engagement > 500:
        engage_pts = 12
    elif total_engagement > 100:
        engage_pts = 9
    elif total_engagement > 20:
        engage_pts = 6
    else:
        engage_pts = 2

    # 4. SOURCE CREDIBILITY (15%)
    cred_pts = 5  # base
    user_lower = (username or "").lower()
    if user_lower in TRUSTED_SOCIAL_ACCOUNTS:
        cred_pts = int(TRUSTED_SOCIAL_ACCOUNTS[user_lower] / 100 * 15)
    elif verified:
        cred_pts = 10
    elif followers > 100000:
        cred_pts = 9
    elif followers > 10000:
        cred_pts = 7
    elif followers > 1000:
        cred_pts = 5
    else:
        cred_pts = 3

    # 5. SENTIMENT (10%)
    pos_count = sum(1 for s in SENTIMENT_POSITIVE if s in text_lower)
    neg_count = sum(1 for s in SENTIMENT_NEGATIVE if s in text_lower)
    if pos_count > neg_count:
        sentiment = "positive"
        sentiment_val = min(1.0, pos_count * 0.3)
    elif neg_count > pos_count:
        sentiment = "negative"
        sentiment_val = min(1.0, neg_count * 0.3) * -1
    else:
        sentiment = "neutral"
        sentiment_val = 0.0
    # Having clear sentiment (either way) is useful
    sentiment_pts = min(10, (pos_count + neg_count) * 3) if (pos_count + neg_count) > 0 else 2

    # 6. MISINFO RISK (5%) — penalty
    misinfo_hits = sum(1 for m in MISINFO_SIGNALS if m in text_lower)
    misinfo_pts = max(0, 5 - misinfo_hits * 2)

    # Composite quality score
    quality_score = min(100, max(0, int(
        relevance_pts + recency_pts + engage_pts + cred_pts + sentiment_pts + misinfo_pts
    )))

    # Validation status
    if quality_score >= 60 and relevance_score >= 0.3:
        validation_status = "ai_validated"
    elif quality_score < 25 or relevance_score < 0.1 or misinfo_hits >= 2:
        validation_status = "low_confidence"
    else:
        validation_status = "unscored"

    return {
        "quality_score": quality_score,
        "relevance_score": round(relevance_score, 3),
        "validation_status": validation_status,
        "matched_keywords": matched[:10],
        "content_type": "social",
        "sentiment": sentiment,
        "sentiment_score": round(sentiment_val, 3),
        "misinfo_flags": misinfo_hits,
        "score_breakdown": {
            "relevance": round(relevance_pts, 1),
            "recency": recency_pts,
            "engagement": engage_pts,
            "credibility": cred_pts,
            "sentiment": sentiment_pts,
            "misinfo": misinfo_pts,
        },
    }


# ── Intelligence tagging ─────────────────────────────────────────────────

# Strategy keywords → strategy_type tag (full asset-class desk)
STRATEGY_TAG_RULES = {
    "dividend_growth_compounder": [
        "dividend growth", "dividend increase", "payout ratio", "dividend aristocrat",
        "consecutive years", "dgi", "dividend compounder",
    ],
    "high_yield_income_bdc": [
        "bdc", "cef", "closed-end", "high yield", "yield >5", "monthly dividend",
        "preferred stock", "mlp", "covered call etf",
    ],
    "core_growth_compounder": [
        "growth stock", "compounder", "revenue growth", "earnings growth",
        "moat", "competitive advantage", "buyback", "growth investing",
    ],
    "value_equity": [
        "value stock", "value investing", "deep value", "book value",
        "price to book", "margin of safety", "value factor",
    ],
    "small_cap_equity": [
        "small cap", "small-cap", "microcap", "russell 2000", "smallcap",
        "emerging growth company",
    ],
    "swing_trade": [
        "swing trade", "momentum", "breakout", "technical analysis",
        "relative volume", "sma cross", "rsi oversold", "rsi overbought",
    ],
    "tactical_income": [
        "tactical", "covered call", "option income", "premium",
        "income strategy", "cash secured put",
    ],
    "put_selling_etf": [
        "put selling", "put etf", "put-write", "put write", "cash secured put etf",
        "defined outcome etf", "buffer etf", "put premium",
    ],
    "inverse_bearish_etf": [
        "inverse etf", "bear etf", "short etf", "3x bear", "inverse fund",
        "bearish etf", "hedge etf",
    ],
    "retirement_planning": [
        "roth", "ira", "401k", "retirement", "irmaa", "medicare", "medicaid",
        "social security", "rmd", "required minimum", "conversion ladder",
        "tax bracket", "tax loss", "capital gains", "estate planning",
    ],
    "bond_income": [
        "bond", "treasury", "fixed income", "duration", "yield curve",
        "interest rate", "corporate bond", "municipal", "bond ladder", "tips",
    ],
    "crypto_assets": [
        "bitcoin", "ethereum", "crypto", "blockchain", "spot bitcoin etf",
        "digital asset", "altcoin", "crypto etf",
    ],
    "commodity_assets": [
        "commodity", "gold etf", "silver", "oil futures", "copper",
        "natural gas", "agriculture commodity", "precious metal",
    ],
    "international_emerging": [
        "emerging market", "international equity", "developed market",
        "ex-us", "global equity", "china stocks", "frontier market",
        "currency hedge", "adr",
    ],
    "macro_multi_asset": [
        "macro", "multi-asset", "portfolio construction", "secular theme",
        "investment thesis", "asset allocation thesis", "regime",
        "fomc", "macro outlook", "cross-asset",
    ],
    "defense_sector": [
        "defense", "aerospace", "military", "contractor", "geopolitical",
    ],
    "reit_income": [
        "reit", "real estate", "rental income", "property", "nnn lease",
        "triple net", "occupancy",
    ],
    "disability_retirement_planning": [
        "disability", "disabled", "ssdi", "social security disability",
        "disability insurance", "disability benefits", "disabled person",
        "married filing separately", "mfs", "married disabled",
        "ira while disabled", "roth while disabled", "disability retirement",
        "substantial gainful activity", "sga", "trial work period",
        "disability and roth", "disability and ira", "disability and 401k",
        "disability income", "disability planning",
    ],
}

# Agent responsibility mapping — full research desk model
AGENT_TAG_RULES = {
    "Alex": [
        "roth", "ira", "401k", "retirement", "irmaa", "medicare", "medicaid",
        "social security", "rmd", "conversion", "tax bracket", "tax loss",
        "income gap", "withdrawal", "estate", "pension",
        "disability", "ssdi", "disabled", "mfs", "disability insurance",
        "special needs trust", "pooled trust", "able account", "elder law",
        "medicaid planning", "spend down", "dual eligible", "sga",
        "trial work period", "long term disability", "ltdi", "medigap",
        "medicare supplement", "extra help", "low income subsidy",
        "irrevocable trust", "revocable trust", "asset protection",
        "five year lookback", "medicaid lookback", "disability tax",
    ],
    "Maria": [
        "earnings", "revenue", "guidance", "catalyst", "upgrade", "downgrade",
        "price target", "analyst", "fundamental", "valuation", "pe ratio",
        "growth", "moat", "competitive", "value stock", "small cap",
        "free cash flow", "balance sheet", "margin expansion",
    ],
    "Steph": [
        "allocation", "rebalance", "portfolio", "account", "position size",
        "weight", "diversification", "sector rotation", "income",
        "dividend", "yield", "payout", "covered call", "put selling",
        "bond ladder", "fixed income", "etf income",
    ],
    "Risk": [
        "risk", "volatility", "drawdown", "stop loss", "correlation",
        "concentration", "beta", "var", "stress test", "rsi",
        "overbought", "oversold", "support", "resistance",
        "inverse etf", "tail risk", "hedge", "duration risk",
    ],
    "Aegis": [
        "overnight", "after hours", "pre-market", "earnings surprise",
        "gap", "halt", "breaking", "urgent", "alert",
    ],
    "Tax": [
        "capital gains", "tax loss harvest", "tax bracket", "wash sale",
        "qualified dividend", "ordinary income", "cost basis",
        "tax efficiency", "taxable account", "nontaxable",
    ],
    "CIO": [
        "macro", "multi-asset", "portfolio construction", "investment thesis",
        "secular theme", "regime", "cross-asset", "strategic allocation",
        "research theme", "cio view", "market regime", "asset class rotation",
    ],
}


def tag_content(text: str, title: str = "", matched_keywords: list = None) -> dict:
    """Tag content with matching strategies and responsible agents.

    Args:
        text: Content body
        title: Content title
        matched_keywords: Pre-computed keywords from scoring (optional, for efficiency)

    Returns:
        {"strategy_tags": ["dividend_growth_compounder", ...], "agent_tags": ["Alex", "Steph", ...]}
    """
    combined = f"{(title or '').lower()} {(text or '').lower()}"

    # Strategy tagging
    strategy_tags = []
    for strategy, keywords in STRATEGY_TAG_RULES.items():
        for kw in keywords:
            if kw in combined:
                strategy_tags.append(strategy)
                break

    # Agent tagging
    agent_tags = []
    for agent, keywords in AGENT_TAG_RULES.items():
        for kw in keywords:
            if kw in combined:
                agent_tags.append(agent)
                break

    # If no agents matched but we have strategies, assign defaults
    if not agent_tags and strategy_tags:
        if any(s in strategy_tags for s in ("retirement_planning", "disability_retirement_planning")):
            agent_tags.append("Alex")
        if any(s in strategy_tags for s in (
            "dividend_growth_compounder", "high_yield_income_bdc", "tactical_income",
            "reit_income", "bond_income", "put_selling_etf",
        )):
            agent_tags.append("Steph")
        if any(s in strategy_tags for s in (
            "core_growth_compounder", "value_equity", "small_cap_equity",
            "swing_trade", "crypto_assets", "commodity_assets", "international_emerging",
        )):
            agent_tags.append("Maria")
        if any(s in strategy_tags for s in ("inverse_bearish_etf",)):
            agent_tags.append("Risk")
        if any(s in strategy_tags for s in ("macro_multi_asset",)):
            agent_tags.append("CIO")

    return {
        "strategy_tags": sorted(set(strategy_tags)),
        "agent_tags": sorted(set(agent_tags)),
    }


# ── Embedding Engine (Ollama nomic-embed-text + TF-IDF fallback) ──────
# Uses local Ollama nomic-embed-text (768-dim) for real vector embeddings.
# Falls back to TF-IDF keyword matching if Ollama unavailable.

import re as _re
import math as _math
import json as _json_emb
from collections import Counter as _Counter
from pathlib import Path as _Path_emb

_EMBED_MODEL = "nomic-embed-text"
_EMBED_DIM = 768

_STOP_WORDS = frozenset("the a an is are was were be been being have has had do does did will would shall should "
    "may might can could of in to for on with at by from as into through during before after above below between "
    "and or but not no nor so yet both either neither each every all any few more most other some such than too "
    "very it its he she they them their this that these those i me my we us our you your who what which when where "
    "how why if then else also just only even still already again once here there now then".split())


def _tokenize(text: str) -> list:
    words = _re.findall(r'[a-zA-Z]{3,}', text.lower())
    return [w for w in words if w not in _STOP_WORDS]


def _get_embedding(text: str) -> list:
    """Get 768-dim embedding from Ollama nomic-embed-text. Returns [] on failure."""
    try:
        from lib.ollama_embedding_policy import embed
        return embed(text[:2000], timeout_s=10)
    except Exception:
        pass
    return []


def cosine_similarity(vec_a: list, vec_b: list) -> float:
    """Cosine similarity between two vectors. Returns 0.0 to 1.0."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = _math.sqrt(sum(a * a for a in vec_a))
    norm_b = _math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def compute_tfidf(text: str, top_n: int = 30) -> dict:
    """TF-IDF fallback when Ollama unavailable."""
    tokens = _tokenize(text)
    if not tokens:
        return {}
    tf = _Counter(tokens)
    total = len(tokens)
    DOMAIN_BOOST = {"retirement": 2.0, "dividend": 2.0, "ssdi": 3.0, "disability": 2.5,
                    "roth": 2.5, "conversion": 2.0, "medicaid": 2.5, "irmaa": 3.0,
                    "medicare": 2.0, "income": 1.5, "yield": 1.5, "tax": 1.5,
                    "portfolio": 1.5, "rebalance": 2.0, "etf": 1.5, "growth": 1.3,
                    "bond": 1.5, "treasury": 1.5, "macro": 1.5, "valuation": 1.4,
                    "crypto": 1.3, "commodity": 1.3, "bitcoin": 1.4, "inverse": 1.3}
    weights = {}
    for term, count in tf.items():
        w = (1 + _math.log(count)) / (1 + _math.log(total))
        w *= DOMAIN_BOOST.get(term, 1.0)
        weights[term] = round(w, 4)
    return dict(sorted(weights.items(), key=lambda x: -x[1])[:top_n])


def semantic_similarity(query: str, doc_terms: dict = None, query_vec: list = None, doc_vec: list = None) -> float:
    """Compute similarity. Uses embeddings if available, falls back to TF-IDF keyword match."""
    # Prefer vector cosine similarity
    if query_vec and doc_vec:
        return cosine_similarity(query_vec, doc_vec)
    # TF-IDF fallback
    if doc_terms:
        query_tokens = set(_tokenize(query))
        if not query_tokens or not doc_terms:
            return 0.0
        overlap = query_tokens & set(doc_terms.keys())
        if not overlap:
            return 0.0
        score = sum(doc_terms[t] for t in overlap)
        max_possible = sum(sorted(doc_terms.values(), reverse=True)[:len(query_tokens)])
        return min(1.0, score / max_possible) if max_possible > 0 else 0.0
    return 0.0


def _emb_conn():
    import psycopg2
    pw = ""
    for line in _Path_emb(__file__).resolve().parent.parent.joinpath(".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def index_content(source_type: str, source_id: int, title: str, text: str) -> dict:
    """Generate embedding via Ollama + TF-IDF terms, store in content_embeddings."""
    combined = f"{title}. {text}"[:2000]
    terms = compute_tfidf(combined)
    top_kw = list(terms.keys())[:10]
    embedding = _get_embedding(combined)

    try:
        conn = _emb_conn()
        cur = conn.cursor()
        cur.execute("""INSERT INTO content_embeddings
            (source_type, source_id, title, tfidf_terms, top_keywords, embedding, embedding_model, embedding_dim)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_type, source_id) DO UPDATE SET
                tfidf_terms=EXCLUDED.tfidf_terms, top_keywords=EXCLUDED.top_keywords,
                embedding=EXCLUDED.embedding, embedding_model=EXCLUDED.embedding_model,
                embedding_dim=EXCLUDED.embedding_dim, created_at=NOW()""",
            (source_type, source_id, title[:200], _json_emb.dumps(terms), top_kw,
             _json_emb.dumps(embedding) if embedding else None,
             _EMBED_MODEL if embedding else None,
             len(embedding) if embedding else 0))
        conn.commit()
        conn.close()
    except Exception:
        pass

    return {"terms": terms, "top_keywords": top_kw, "embedding_dim": len(embedding)}


def batch_index_all(batch_size: int = 50) -> dict:
    """Index all unindexed news articles + YouTube transcripts. Run once to backfill."""
    import psycopg2.extras
    conn = _emb_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    indexed = 0

    # News articles not yet indexed
    cur.execute("""SELECT na.id, na.title, COALESCE(na.summary, '') as text
        FROM news_articles na
        LEFT JOIN content_embeddings ce ON ce.source_type='news' AND ce.source_id=na.id
        WHERE ce.id IS NULL
        ORDER BY na.created_at DESC LIMIT %s""", (batch_size,))
    for row in cur.fetchall():
        index_content("news", row["id"], row["title"] or "", row["text"] or "")
        indexed += 1

    # YouTube transcripts not yet indexed
    cur.execute("""SELECT yt.id, yt.title, COALESCE(yt.summary, LEFT(yt.cleaned_text, 500), LEFT(yt.transcript_text, 500), '') as text
        FROM youtube_transcripts yt
        LEFT JOIN content_embeddings ce ON ce.source_type='youtube' AND ce.source_id=yt.id
        WHERE ce.id IS NULL
        ORDER BY yt.ingested_at DESC LIMIT %s""", (batch_size,))
    for row in cur.fetchall():
        index_content("youtube", row["id"], row["title"] or "", row["text"] or "")
        indexed += 1

    conn.close()
    print(f"[embeddings] Indexed {indexed} items via {_EMBED_MODEL}")
    return {"indexed": indexed, "model": _EMBED_MODEL, "dim": _EMBED_DIM}
