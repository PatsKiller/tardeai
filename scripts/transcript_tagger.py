#!/usr/bin/env python3
"""transcript_tagger.py — Per-transcript deep tagging for YouTube content.

Every transcript gets individually analyzed based on its actual content —
not just inherited channel tags. Quality scores reflect the actual value
of each specific video, not a channel-level average.

TWO LAYERS:
  Layer 1 — Channel baseline: channel category assigns default agents
  Layer 2 — Content analysis: title + full transcript text overrides
             Layer 1 if confidence >= 60%

Usage:
    python3 scripts/transcript_tagger.py               # show stats
    python3 scripts/transcript_tagger.py --test         # test 10 transcripts
    python3 scripts/transcript_tagger.py --all          # tag untagged
    python3 scripts/transcript_tagger.py --retag-all    # force re-tag all
    python3 scripts/transcript_tagger.py --id 123       # tag single
"""
import json, os, sys, re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _get_conn_dict():
    import psycopg2, psycopg2.extras
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    conn = psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn, cur


# ═══════════════════════════════════════════════════════
# QUALITY SCORING MODEL — per transcript characteristics
# ═══════════════════════════════════════════════════════

# High-value keywords: (boost_points, [agent_tags])
HIGH_VALUE_KEYWORDS = {
    # Alex / disability specific
    "irmaa": (8, ["alex", "tax"]),
    "ssdi": (10, ["alex"]),
    "medicaid": (10, ["alex", "tax"]),
    "special needs trust": (12, ["alex", "tax"]),
    "roth conversion": (8, ["alex", "tax"]),
    "medicare advantage": (8, ["alex"]),
    "spend down": (10, ["alex", "tax"]),
    "able account": (12, ["alex", "tax"]),
    "pooled trust": (10, ["alex", "tax"]),
    "dual eligible": (10, ["alex"]),
    "medigap": (8, ["alex"]),
    "social security disability": (10, ["alex"]),
    "trial work period": (10, ["alex"]),
    # Maria / fundamentals
    "earnings per share": (6, ["maria"]),
    "insider buying": (8, ["maria", "risk"]),
    "analyst upgrade": (6, ["maria"]),
    "analyst downgrade": (6, ["maria"]),
    "price target": (6, ["maria"]),
    "dividend growth": (6, ["steph", "maria"]),
    "growth stock": (7, ["maria"]),
    "value investing": (6, ["maria"]),
    "small cap": (6, ["maria", "risk"]),
    "free cash flow": (6, ["maria"]),
    "valuation": (5, ["maria"]),
    # Risk / technical
    "support level": (6, ["risk"]),
    "resistance level": (6, ["risk"]),
    "stop loss": (8, ["risk"]),
    "moving average": (6, ["risk"]),
    "rsi": (5, ["risk"]),
    "inverse etf": (7, ["risk"]),
    "tail risk": (7, ["risk"]),
    # Steph / allocation / income
    "income floor": (8, ["steph", "alex"]),
    "asset allocation": (6, ["steph"]),
    "rebalance": (6, ["steph"]),
    "covered call": (6, ["steph", "maria"]),
    "put selling": (7, ["steph", "risk"]),
    "bond ladder": (7, ["steph"]),
    "fixed income": (6, ["steph"]),
    "yield on cost": (6, ["steph"]),
    # Tax
    "tax loss harvest": (8, ["tax", "alex"]),
    "capital gains": (6, ["tax"]),
    "required minimum": (8, ["alex", "tax"]),
    "backdoor roth": (8, ["alex", "tax"]),
    # CIO / macro / multi-asset
    "macro thesis": (8, ["cio", "maria"]),
    "portfolio construction": (7, ["cio", "steph"]),
    "investment thesis": (7, ["cio", "maria"]),
    "multi-asset": (7, ["cio", "steph"]),
    "market regime": (6, ["cio", "risk"]),
    # Crypto / commodities / international
    "bitcoin": (5, ["maria", "risk"]),
    "crypto etf": (6, ["maria"]),
    "commodity": (5, ["maria"]),
    "emerging market": (6, ["maria", "steph"]),
}

# Specific title indicators that boost quality
SPECIFIC_INDICATORS = [
    "how to", "step by step", "complete guide", "deep dive",
    "explained", "strategy", "case study", "real numbers",
    "actual numbers", "mistakes", "avoid", "warning",
    "critical", "must know", "changed", "new rules",
]

# Category modifiers (full desk — non-retirement categories included)
CATEGORY_MODIFIERS = {
    "disability_retirement": 10,
    "tax_strategy": 8,
    "retirement_planning": 6,
    "dividend_income": 4,
    "bond_fixed_income": 5,
    "growth_equity": 5,
    "value_equity": 4,
    "small_cap_equity": 4,
    "put_selling_etf": 5,
    "covered_call_etf": 5,
    "inverse_bearish_etf": 4,
    "crypto_assets": 3,
    "commodity_assets": 3,
    "international_emerging": 4,
    "macro_economics": 5,
    "macro_multi_asset": 5,
    "investment_general": 0,
    "etf_indexing": 2,
    "financial_education": 0,
}


def score_transcript_quality(title, summary, transcript_text,
                             channel_category, channel_agent_tags,
                             base_score=50):
    """Score a transcript's content value.
    Returns (score, reasons, detected_agents).
    """
    score = base_score
    reasons = []

    all_text = " ".join(filter(None, [title, summary, (transcript_text or "")[:3000]])).lower()
    word_count = len((transcript_text or "").split())

    # Content length quality
    if word_count > 5000:
        score += 12
        reasons.append(f"+12 long transcript ({word_count:,} words)")
    elif word_count > 2000:
        score += 8
        reasons.append(f"+8 medium transcript ({word_count:,} words)")
    elif word_count > 500:
        score += 3
        reasons.append(f"+3 short transcript ({word_count:,} words)")
    elif word_count > 0:
        score -= 10
        reasons.append(f"-10 very short transcript ({word_count} words)")

    # Title quality signals
    title_lower = (title or "").lower()

    if "2026" in title:
        score += 8
        reasons.append("+8 current year (2026) in title")
    elif "2025" in title:
        score += 4
        reasons.append("+4 recent year (2025) in title")

    specific_hits = sum(1 for s in SPECIFIC_INDICATORS if s in title_lower)
    if specific_hits > 0:
        bonus = min(8, specific_hits * 4)
        score += bonus
        reasons.append(f"+{bonus} specific/actionable title")

    if any(w in title_lower for w in ["interview", "conversation", "chat with", "talking with"]):
        score -= 5
        reasons.append("-5 interview format (lower content density)")

    # High-value keyword density
    confirmed_agents = set(channel_agent_tags or [])
    quality_boosts = {}

    for keyword, (boost, kw_agents) in HIGH_VALUE_KEYWORDS.items():
        if keyword in all_text:
            freq = all_text.count(keyword)
            actual_boost = min(boost * 2, boost + freq * 2)
            quality_boosts[keyword] = actual_boost
            confirmed_agents.update(kw_agents)

    # Apply top 5 keyword boosts
    top_boosts = sorted(quality_boosts.items(), key=lambda x: x[1], reverse=True)[:5]
    for kw, boost in top_boosts:
        score += boost
        reasons.append(f"+{boost} keyword: \"{kw}\"")

    # Multi-agent content = extra value
    if "alex" in confirmed_agents and "steph" in confirmed_agents:
        score += 6
        reasons.append("+6 cross-domain: disability + allocation")
    if "alex" in confirmed_agents and "tax" in confirmed_agents:
        score += 4
        reasons.append("+4 cross-domain: disability + tax")
    if len(confirmed_agents) >= 4:
        score += 5
        reasons.append(f"+5 broad relevance: {len(confirmed_agents)} agents")

    # Channel category modifier
    cat_mod = CATEGORY_MODIFIERS.get(channel_category or "", 0)
    if cat_mod > 0:
        score += cat_mod
        reasons.append(f"+{cat_mod} channel category: {channel_category}")

    score = max(0, min(100, score))
    return score, reasons, list(confirmed_agents)


# ═══════════════════════════════════════════════════════
# STRATEGY TAG DETECTION — per transcript
# ═══════════════════════════════════════════════════════

STRATEGY_PATTERNS = [
    # Most specific — disability intersection (keep working)
    ("disability_retirement", [
        "ssdi", "medicaid", "medicare", "irmaa", "disability benefits",
        "dual eligible", "spend down", "able account", "special needs trust",
        "disability planning", "medicare advantage",
    ], 1.5),
    ("trust_estate", [
        "special needs trust", "pooled trust", "snt", "estate planning",
        "irrevocable trust", "revocable trust", "probate", "elder law",
        "beneficiary designation", "inheritance planning",
    ], 1.5),
    ("roth_conversion", [
        "roth conversion", "backdoor roth", "mega backdoor",
        "roth ladder", "convert to roth", "roth rollover",
    ], 1.3),
    ("tax_planning", [
        "tax bracket", "capital gains tax", "tax loss harvest",
        "tax efficiency", "magi", "tax strategy", "estimated taxes",
    ], 1.2),
    ("retirement_planning", [
        "retirement income", "401k withdrawal", "ira distribution",
        "required minimum", "retire early", "retirement planning",
        "pension", "social security claiming",
    ], 1.0),
    ("put_selling_etf", [
        "put selling", "put etf", "put-write", "put write", "put premium",
        "cash secured put etf", "defined outcome", "buffer etf",
    ], 1.2),
    ("covered_call_etf", [
        "covered call etf", "covered call", "option income etf",
        "call writing", "premium income etf", "wheel strategy",
    ], 1.1),
    ("inverse_bearish_etf", [
        "inverse etf", "bear etf", "short etf", "3x bear", "inverse fund",
        "bearish etf", "hedge etf",
    ], 1.1),
    ("bond_fixed_income", [
        "bond ladder", "fixed income", "treasury bond", "corporate bond",
        "municipal bond", "yield curve", "duration", "tips", "bond etf",
    ], 1.1),
    ("growth_equity", [
        "growth stock", "growth investing", "earnings growth", "revenue growth",
        "growth compounder", "high growth", "secular growth",
    ], 1.1),
    ("value_equity", [
        "value stock", "value investing", "deep value", "margin of safety",
        "price to book", "value factor",
    ], 1.0),
    ("small_cap_equity", [
        "small cap", "small-cap", "microcap", "russell 2000", "smallcap",
    ], 1.0),
    ("crypto_assets", [
        "bitcoin", "ethereum", "crypto etf", "spot bitcoin", "digital asset",
        "blockchain investing", "crypto",
    ], 1.0),
    ("commodity_assets", [
        "commodity", "gold etf", "silver etf", "oil futures", "precious metal",
        "natural gas", "copper price",
    ], 1.0),
    ("international_emerging", [
        "emerging market", "international equity", "developed market",
        "ex-us", "global equity", "china stocks", "currency hedge",
    ], 1.0),
    ("dividend_income", [
        "dividend growth", "dividend income", "high yield", "schd",
        "income investing", "dividend stock", "yield on cost",
    ], 1.0),
    ("macro_multi_asset", [
        "macro thesis", "multi-asset", "portfolio construction",
        "investment thesis", "asset allocation", "market regime",
        "cross-asset", "secular theme",
    ], 1.0),
    ("etf_indexing", [
        "index fund", "expense ratio", "passive investing",
        "total market", "vanguard", "low cost",
    ], 0.8),
    ("macro_fed", [
        "federal reserve", "interest rate", "inflation",
        "yield curve", "economic outlook", "fed meeting", "fomc",
    ], 0.8),
    ("investment_general", [
        "stock market", "invest", "portfolio", "financial", "wealth",
    ], 0.5),
]


def detect_strategy_tag(title, summary, transcript_text):
    """Detect primary strategy tag. Returns (strategy_tag, confidence)."""
    all_text = " ".join(filter(None,
        [title, summary, (transcript_text or "")[:5000]]
    )).lower()

    strategy_scores = {}
    for strategy, keywords, weight in STRATEGY_PATTERNS:
        freq = sum(all_text.count(kw) for kw in keywords)
        title_hits = sum(1 for kw in keywords if kw in (title or "").lower())
        strategy_scores[strategy] = (freq + title_hits * 3) * weight

    if not any(v > 0 for v in strategy_scores.values()):
        return "investment_general", 0.3

    best = max(strategy_scores, key=strategy_scores.get)
    best_score = strategy_scores[best]
    total_score = sum(v for v in strategy_scores.values() if v > 0)
    confidence = min(1.0, best_score / max(total_score, 1))
    return best, round(confidence, 2)


# Agent mapping for strategy tags (full desk routing)
STRATEGY_AGENTS = {
    "disability_retirement": ["alex", "tax"],
    "trust_estate": ["alex", "tax"],
    "roth_conversion": ["alex", "tax"],
    "tax_planning": ["tax", "alex"],
    "retirement_planning": ["alex", "steph"],
    "dividend_income": ["maria", "steph"],
    "covered_call_etf": ["steph", "maria"],
    "put_selling_etf": ["steph", "risk"],
    "inverse_bearish_etf": ["risk", "maria"],
    "bond_fixed_income": ["steph", "risk"],
    "growth_equity": ["maria"],
    "value_equity": ["maria"],
    "small_cap_equity": ["maria", "risk"],
    "crypto_assets": ["maria", "risk"],
    "commodity_assets": ["maria", "risk"],
    "international_emerging": ["maria", "steph"],
    "macro_multi_asset": ["cio", "maria", "steph"],
    "etf_indexing": ["maria", "steph"],
    "macro_fed": ["cio", "maria"],
    "investment_general": ["maria"],
}


# ═══════════════════════════════════════════════════════
# MAIN TAGGER — per transcript
# ═══════════════════════════════════════════════════════

def tag_single_transcript(transcript_id, conn=None):
    """Fully tag a single transcript with deep content analysis.
    Returns the full classification result.
    """
    import psycopg2.extras

    close_conn = conn is None
    if conn is None:
        conn = _get_conn()

    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get transcript with channel context
    cur.execute("""
        SELECT
            t.id, t.title, t.summary, t.transcript_text,
            t.quality_score, t.agent_tags as current_tags,
            t.strategy_tags, t.content_category,
            t.promoted_to_whiteboard,
            c.channel_name, c.category as channel_category,
            c.agent_tags as channel_agent_tags,
            c.auto_promote_threshold
        FROM youtube_transcripts t
        LEFT JOIN youtube_channels c ON c.channel_name = t.channel_name
        WHERE t.id = %s
    """, (transcript_id,))

    t = cur.fetchone()
    if not t:
        if close_conn:
            conn.close()
        return {"ok": False, "error": f"Transcript {transcript_id} not found"}

    title = t["title"] or ""
    summary = t["summary"] or ""
    transcript_text = t["transcript_text"] or ""
    channel_category = t["channel_category"] or "investment_general"

    # Channel baseline tags — handle both TEXT[] and JSONB
    raw_ch_tags = t["channel_agent_tags"]
    if isinstance(raw_ch_tags, list):
        channel_tags = raw_ch_tags
    elif isinstance(raw_ch_tags, str):
        try:
            channel_tags = json.loads(raw_ch_tags)
        except (json.JSONDecodeError, TypeError):
            channel_tags = [raw_ch_tags] if raw_ch_tags else []
    else:
        channel_tags = []

    # Step 1: Strategy tag detection (content-driven)
    strategy_tag, strategy_confidence = detect_strategy_tag(
        title, summary, transcript_text
    )

    # Step 2: Quality scoring with agent detection
    quality_score, quality_reasons, detected_agents = score_transcript_quality(
        title=title,
        summary=summary,
        transcript_text=transcript_text,
        channel_category=channel_category,
        channel_agent_tags=channel_tags,
        base_score=50,
    )

    # Step 3: Merge channel tags with content-detected agents
    final_agents = set(channel_tags)

    if strategy_confidence >= 0.6:
        strategy_agents = STRATEGY_AGENTS.get(strategy_tag, [])
        if set(strategy_agents).isdisjoint(set(channel_tags)):
            # No overlap — content says something different than channel
            final_agents = set(strategy_agents)
            quality_reasons.append(
                f"Override: {channel_tags} -> {strategy_agents} "
                f"(strategy: {strategy_tag}, conf: {strategy_confidence:.0%})"
            )
        else:
            final_agents.update(strategy_agents)
    else:
        final_agents.update(detected_agents)

    # alex always comes with tax
    if "alex" in final_agents:
        final_agents.add("tax")

    final_agents_list = sorted(final_agents)

    # Step 4: Promotion threshold
    if "alex" in final_agents_list:
        promote_threshold = 55
    elif strategy_tag in (
        "retirement_planning", "roth_conversion", "disability_retirement",
        "macro_multi_asset", "growth_equity", "bond_fixed_income",
    ):
        promote_threshold = 60
    else:
        promote_threshold = t["auto_promote_threshold"] or 70

    # Step 5: Write to DB
    wcur = conn.cursor()
    # agent_tags is JSONB on transcripts
    wcur.execute("""
        UPDATE youtube_transcripts
        SET agent_tags = %s::jsonb,
            strategy_tags = %s::jsonb,
            quality_score = %s,
            content_category = %s
        WHERE id = %s
    """, (
        json.dumps(final_agents_list),
        json.dumps([strategy_tag]),
        quality_score,
        channel_category,
        transcript_id,
    ))

    # Step 6: Promote to whiteboard if quality threshold met
    promoted = False
    if quality_score >= promote_threshold:
        wcur.execute("""
            SELECT id FROM intelligence_whiteboard
            WHERE source_type='youtube' AND source_id=%s
        """, (transcript_id,))
        exists = wcur.fetchone()

        if not exists:
            level = 3 if quality_score >= 70 else 2
            wcur.execute("""
                INSERT INTO intelligence_whiteboard
                  (source_type, source_id, title, summary,
                   quality_score, status, level, created_at)
                VALUES ('youtube', %s, %s, %s, %s, 'active', %s, NOW())
                ON CONFLICT DO NOTHING
            """, (
                transcript_id,
                title[:200],
                (summary or "")[:500],
                quality_score,
                level,
            ))
            promoted = True

        # Update promoted flag
        wcur.execute("""
            UPDATE youtube_transcripts
            SET promoted_to_whiteboard = true
            WHERE id = %s AND NOT COALESCE(promoted_to_whiteboard, false)
        """, (transcript_id,))

    conn.commit()
    if close_conn:
        conn.close()

    channel_override = sorted(final_agents_list) != sorted(channel_tags)
    return {
        "ok": True,
        "transcript_id": transcript_id,
        "title": title[:60],
        "final_agents": final_agents_list,
        "strategy_tag": strategy_tag,
        "strategy_confidence": strategy_confidence,
        "quality_score": quality_score,
        "quality_reasons": quality_reasons[:5],
        "promoted": promoted,
        "channel_override": channel_override,
    }


# ═══════════════════════════════════════════════════════
# BATCH TAGGER
# ═══════════════════════════════════════════════════════

def tag_all_transcripts(limit=None, force_retag=False):
    """Tag all transcripts — or just untagged ones."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if force_retag:
        query = "SELECT id FROM youtube_transcripts ORDER BY id"
    else:
        query = """SELECT id FROM youtube_transcripts
            WHERE agent_tags IS NULL OR agent_tags = '[]'::jsonb
            ORDER BY id"""

    if limit:
        query += f" LIMIT {int(limit)}"

    cur.execute(query)
    transcript_ids = [row["id"] for row in cur.fetchall()]
    conn.close()

    print(f"\nTagging {len(transcript_ids)} transcripts...")

    stats = {
        "total": len(transcript_ids),
        "tagged": 0, "promoted": 0, "overridden_channel": 0, "errors": 0,
        "by_strategy": {}, "by_agent": {},
        "quality_distribution": {"80+": 0, "60-79": 0, "40-59": 0, "<40": 0},
    }

    conn = _get_conn()

    for i, tid in enumerate(transcript_ids):
        try:
            result = tag_single_transcript(tid, conn=conn)
            if result["ok"]:
                stats["tagged"] += 1
                if result["promoted"]:
                    stats["promoted"] += 1
                if result["channel_override"]:
                    stats["overridden_channel"] += 1

                strat = result["strategy_tag"]
                stats["by_strategy"][strat] = stats["by_strategy"].get(strat, 0) + 1

                for agent in result["final_agents"]:
                    stats["by_agent"][agent] = stats["by_agent"].get(agent, 0) + 1

                q = result["quality_score"]
                if q >= 80: stats["quality_distribution"]["80+"] += 1
                elif q >= 60: stats["quality_distribution"]["60-79"] += 1
                elif q >= 40: stats["quality_distribution"]["40-59"] += 1
                else: stats["quality_distribution"]["<40"] += 1

                if result["channel_override"]:
                    print(f"  Override [{tid}] {result['title'][:40]}: "
                          f"-> {result['final_agents']}")
            else:
                stats["errors"] += 1
        except Exception as e:
            stats["errors"] += 1
            conn.rollback()
            print(f"  Error on transcript {tid}: {e}")

        if (i + 1) % 50 == 0:
            print(f"  Progress: {i+1}/{len(transcript_ids)} "
                  f"(promoted: {stats['promoted']}, overrides: {stats['overridden_channel']})")

    conn.close()

    print(f"\n{'='*60}")
    print(f"TAGGING COMPLETE")
    print(f"  Total processed:     {stats['total']}")
    print(f"  Successfully tagged: {stats['tagged']}")
    print(f"  Promoted to board:   {stats['promoted']}")
    print(f"  Channel overridden:  {stats['overridden_channel']}")
    print(f"  Errors:              {stats['errors']}")
    print(f"\nStrategy distribution:")
    for strat, count in sorted(stats["by_strategy"].items(), key=lambda x: x[1], reverse=True):
        print(f"  {strat:<30} {count:>4}")
    print(f"\nAgent routing:")
    for agent, count in sorted(stats["by_agent"].items(), key=lambda x: x[1], reverse=True):
        print(f"  {agent:<15} {count:>4} transcripts")
    print(f"\nQuality distribution:")
    for bucket, count in stats["quality_distribution"].items():
        print(f"  Q{bucket:<8} {count:>4}")

    return stats


# ═══════════════════════════════════════════════════════
# INGEST HOOK — called for every new transcript
# ═══════════════════════════════════════════════════════

def tag_new_transcript(transcript_id):
    """Called immediately when a new transcript is inserted.
    Never batched — always immediate.
    """
    result = tag_single_transcript(transcript_id)

    if result["ok"]:
        print(f"  [tagger] {result['title'][:50]} "
              f"-> {result['final_agents']} | {result['strategy_tag']} "
              f"| Q{result['quality_score']}"
              + (" [PROMOTED]" if result["promoted"] else "")
              + (" [OVERRIDE]" if result["channel_override"] else ""))
    else:
        print(f"  [tagger] Failed for transcript {transcript_id}: {result.get('error')}")

    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="YouTube transcript tagger")
    parser.add_argument("--all", action="store_true", help="Tag all untagged transcripts")
    parser.add_argument("--retag-all", action="store_true", help="Force re-tag ALL transcripts")
    parser.add_argument("--id", type=int, help="Tag a single transcript by ID")
    parser.add_argument("--limit", type=int, default=None, help="Limit number to process")
    parser.add_argument("--test", action="store_true", help="Test with first 10, show detail")
    args = parser.parse_args()

    if args.id:
        result = tag_single_transcript(args.id)
        print(json.dumps(result, indent=2))
    elif args.test:
        stats = tag_all_transcripts(limit=10, force_retag=True)
    elif args.retag_all:
        stats = tag_all_transcripts(force_retag=True, limit=args.limit)
    elif args.all:
        stats = tag_all_transcripts(force_retag=False, limit=args.limit)
    else:
        import psycopg2.extras
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT count(*) as total,
                   count(CASE WHEN agent_tags IS NOT NULL AND agent_tags != '[]'::jsonb THEN 1 END) as tagged,
                   count(CASE WHEN promoted_to_whiteboard THEN 1 END) as promoted
            FROM youtube_transcripts
        """)
        row = cur.fetchone()
        conn.close()
        if row:
            rate = int(row["tagged"] / max(row["total"], 1) * 100)
            print(f"Transcripts: {row['total']} total | "
                  f"{row['tagged']} tagged ({rate}%) | "
                  f"{row['promoted']} promoted")
        print("Use --all to tag untagged, --retag-all to force re-tag everything")
