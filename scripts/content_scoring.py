"""content_scoring.py — Unified scoring for news, YouTube, and social media.

Provides quality_score, relevance_score, and validation_status for any ingested content.
Used by news_ingestion.py, youtube_transcript_ingest.py, and social_monitor.py.
"""
from datetime import datetime, timezone


# Keywords that boost relevance for retirement income investing
RELEVANCE_KEYWORDS = {
    "high": [
        "dividend", "yield", "income", "roth", "ira", "401k", "retirement",
        "distribution", "payout", "ex-dividend", "dividend growth", "covered call",
        "bdc", "cef", "preferred", "reits", "reit", "mlp",
        "irmaa", "medicare", "social security", "rmd", "required minimum",
        "tax bracket", "capital gains", "tax loss", "conversion",
    ],
    "medium": [
        "earnings", "guidance", "revenue", "margin", "buyback", "debt",
        "interest rate", "fed", "inflation", "recession", "valuation",
        "pe ratio", "price target", "analyst", "upgrade", "downgrade",
        "sector rotation", "allocation", "rebalance", "risk",
    ],
    "low": [
        "stock", "market", "rally", "sell-off", "volatility", "s&p",
        "nasdaq", "dow", "bull", "bear", "momentum",
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

# Known high-quality YouTube channels for finance
TRUSTED_YOUTUBE_CHANNELS = {
    "dividend bull": 75,
    "dividendbull": 75,
    "joseph carlson": 70,
    "josephcarlson": 70,
    "ppc ian": 65,
    "ppcian": 65,
    "dave ramsey": 60,
    "the plain bagel": 70,
    "ben felix": 80,
    "rob berger": 70,
    "nick murray": 75,
    "income investors": 65,
    "dividend data": 65,
    "investkaki": 55,
    "rational reminder": 70,
    "joe f. schmitz": 70,
    "peak retirement": 70,
    "strong man personal finance": 55,
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

# Strategy keywords → strategy_type tag
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
        "moat", "competitive advantage", "buyback",
    ],
    "swing_trade": [
        "swing trade", "momentum", "breakout", "technical analysis",
        "relative volume", "sma cross", "rsi oversold", "rsi overbought",
    ],
    "tactical_income": [
        "tactical", "covered call", "option income", "premium",
        "income strategy", "cash secured put",
    ],
    "retirement_planning": [
        "roth", "ira", "401k", "retirement", "irmaa", "medicare", "medicaid",
        "social security", "rmd", "required minimum", "conversion ladder",
        "tax bracket", "tax loss", "capital gains", "estate planning",
    ],
    "bond_income": [
        "bond", "treasury", "fixed income", "duration", "yield curve",
        "interest rate", "corporate bond", "municipal",
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

# Agent responsibility mapping — which keywords trigger which agent
AGENT_TAG_RULES = {
    "Alex": [
        "roth", "ira", "401k", "retirement", "irmaa", "medicare", "medicaid",
        "social security", "rmd", "conversion", "tax bracket", "tax loss",
        "income gap", "withdrawal", "estate", "pension",
        "disability", "ssdi", "disabled", "mfs", "disability insurance",
    ],
    "Maria": [
        "earnings", "revenue", "guidance", "catalyst", "upgrade", "downgrade",
        "price target", "analyst", "fundamental", "valuation", "pe ratio",
        "growth", "moat", "competitive",
    ],
    "Steph": [
        "allocation", "rebalance", "portfolio", "account", "position size",
        "weight", "diversification", "sector rotation", "income",
        "dividend", "yield", "payout",
    ],
    "Risk": [
        "risk", "volatility", "drawdown", "stop loss", "correlation",
        "concentration", "beta", "var", "stress test", "rsi",
        "overbought", "oversold", "support", "resistance",
    ],
    "Aegis": [
        "overnight", "after hours", "pre-market", "earnings surprise",
        "gap", "halt", "breaking", "urgent", "alert",
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
        if any(s in strategy_tags for s in ("retirement_planning",)):
            agent_tags.append("Alex")
        if any(s in strategy_tags for s in ("dividend_growth_compounder", "high_yield_income_bdc", "tactical_income", "reit_income")):
            agent_tags.append("Steph")
        if any(s in strategy_tags for s in ("core_growth_compounder", "swing_trade")):
            agent_tags.append("Maria")

    return {
        "strategy_tags": sorted(set(strategy_tags)),
        "agent_tags": sorted(set(agent_tags)),
    }
