#!/usr/bin/env python3
"""transcript_processor.py — Full hybrid transcript processing pipeline.

Pipeline: raw → clean → extractive pre-filter → abstractive summary → structured JSON → sub-tags → dedup → purge dates

Built for scale (1000+ transcripts). Each step is independent and re-runnable.

Usage:
    python3 scripts/transcript_processor.py --process-all
    python3 scripts/transcript_processor.py --process VIDEO_ID
    python3 scripts/transcript_processor.py --dedup
    python3 scripts/transcript_processor.py --purge-expired
"""
import json, re, sys, hashlib
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# ── Step 1: Filler removal ───────────────────────────────────────────

FILLERS = [
    r'\b(um|uh|uh huh|umm|uhh|hmm|hm|ah|oh|er|like)\b',
    r'\b(you know|i mean|sort of|kind of|basically|actually|literally)\b',
    r'\b(right right|yeah yeah|okay okay)\b',
]
FILLER_PATTERN = re.compile('|'.join(FILLERS), re.IGNORECASE)

# ── Step 4: Sub-tag rules (full investment desk + retirement) ────────

SUB_TAG_RULES = {
    "roth_conversion_ladder": ["roth conversion", "roth ladder", "conversion ladder", "convert ira to roth", "backdoor roth"],
    "ssdi_ira_rules": ["ssdi", "disability.*ira", "disability.*retirement", "social security disability", "disability benefits"],
    "medicaid_trust_planning": ["medicaid", "asset protection trust", "mapt", "medicaid lookback", "medicaid eligibility"],
    "disability_spousal_ira": ["spousal ira", "spousal contribution", "spouse.*ira", "married.*ira"],
    "irmaa_medicare": ["irmaa", "medicare premium", "medicare surcharge", "part b premium", "medicare lookback"],
    "income_gap_strategy": ["income gap", "income target", "retirement income", "passive income", "dividend income.*retirement"],
    "tax_bracket_management": ["tax bracket", "bracket room", "fill.*bracket", "tax efficiency", "tax optimization"],
    "covered_call_income": ["covered call", "option income", "selling calls", "premium income", "wheel strategy"],
    "put_selling_etf": ["put selling", "put etf", "put-write", "put write", "cash secured put", "buffer etf"],
    "inverse_bearish_etf": ["inverse etf", "bear etf", "short etf", "3x inverse", "bearish etf"],
    "dividend_growth": ["dividend growth", "dividend aristocrat", "consecutive.*dividend", "dividend increase", "dgi"],
    "growth_equity": ["growth stock", "growth investing", "earnings growth", "revenue growth", "secular growth"],
    "value_equity": ["value stock", "value investing", "deep value", "margin of safety", "price to book"],
    "small_cap_equity": ["small cap", "small-cap", "microcap", "russell 2000", "smallcap"],
    "bond_ladder": ["bond ladder", "treasury ladder", "fixed income ladder", "i bond", "tips"],
    "fixed_income": ["fixed income", "corporate bond", "municipal bond", "duration", "yield curve", "treasury bond"],
    "macro_multi_asset": ["macro thesis", "multi-asset", "portfolio construction", "investment thesis", "market regime", "cross-asset"],
    "crypto_assets": ["bitcoin", "ethereum", "crypto etf", "spot bitcoin", "digital asset"],
    "commodity_assets": ["commodity", "gold etf", "silver etf", "oil futures", "precious metal"],
    "international_emerging": ["emerging market", "international equity", "developed market", "ex-us", "global equity"],
    "valuation_analysis": ["valuation", "pe ratio", "price to earnings", "dcf", "intrinsic value", "fair value"],
    "rmd_planning": ["required minimum", "rmd", "rmd strategy", "rmd tax", "72t"],
    "401k_rollover": ["401k rollover", "rollover ira", "roll over.*401", "employer plan"],
}


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


# ── Step 1: Clean ────────────────────────────────────────────────────

def clean_transcript(raw: str) -> str:
    """Remove filler words and clean up auto-caption text."""
    if not raw:
        return ""
    text = FILLER_PATTERN.sub('', raw)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\.\s+([a-z])', lambda m: '. ' + m.group(1).upper(), text)
    return text.strip()


# ── Step 2: Extractive pre-filter (TextRank via Sumy) ────────────────

def extractive_filter(text: str, ratio: float = 0.35) -> str:
    """Keep top 35% most important sentences using TextRank.
    Reduces noise before sending to LLM for abstractive summary.
    """
    if not text or len(text) < 500:
        return text
    try:
        from sumy.parsers.plaintext import PlaintextParser
        from sumy.nlp.tokenizers import Tokenizer
        from sumy.summarizers.text_rank import TextRankSummarizer

        parser = PlaintextParser.from_string(text, Tokenizer("english"))
        summarizer = TextRankSummarizer()

        # Calculate sentence count to keep
        total_sentences = len(list(parser.document.sentences))
        keep = max(3, int(total_sentences * ratio))

        sentences = summarizer(parser.document, keep)
        return " ".join(str(s) for s in sentences)
    except Exception as e:
        # Fallback: just truncate to first 40% of text
        cutoff = int(len(text) * 0.4)
        return text[:cutoff]


# ── Step 3: Abstractive summary + structured JSON ────────────────────

def generate_structured_summary(title: str, extracted_text: str, channel: str = "",
                                 quality_score: int = 0) -> dict:
    """Generate structured JSON summary using LLM.
    Uses Claude for high-quality transcripts (Q≥70), local for the rest.
    """
    if not extracted_text or len(extracted_text) < 200:
        return {}

    try:
        from llm_router import get_llm_response

        high_impact = quality_score >= 70

        prompt = f"""/no_think You are a full-desk investment research analyst covering equities (growth, value, small-cap), ETFs, bonds/fixed income, options income strategies, commodities, crypto, international markets, and macro. Retirement income and tax planning remain in scope when present.
Analyze this YouTube transcript and output ONLY valid JSON.

Title: {title}
Channel: {channel}

Transcript (key sentences):
{extracted_text[:4000]}

Output ONLY valid JSON with this exact schema (no other text before or after):
{{
  "summary": "150-250 word professional overview focused on investment research implications across asset classes (stocks/ETFs/bonds/options/macro); include retirement/tax angles when relevant",
  "key_points": ["concise factual point 1", "point 2", "point 3"] (5-8 points),
  "action_items": ["actionable recommendation 1", "recommendation 2"] (max 6),
  "tickers_mentioned": ["SCHD", "V", "JEPI"],
  "retirement_relevance": "high" or "medium" or "low",
  "research_relevance": "high" or "medium" or "low",
  "relevance_score": 0-100,
  "main_topics": ["growth_equity", "bond_ladder", "macro_multi_asset", "covered_call_income"],
  "llm_confidence": 0-100
}}

Focus on: equity style (growth/value/small-cap), valuation, ETF structures (covered call, put-write, inverse), fixed income/duration, macro/regime, portfolio construction, commodities/crypto/international, plus retirement topics when present (Roth ladders, SSDI, Medicaid, tax optimization, income gap). Capture specific ticker or ETF mentions."""

        result = get_llm_response(
            "cio_synthesis" if high_impact else "agent_narrative",
            prompt, max_tokens=500, high_impact=high_impact
        )

        if result.get("success"):
            raw = result["response"]
            start = raw.find('{')
            end = raw.rfind('}') + 1
            if start >= 0 and end > start:
                parsed = json.loads(raw[start:end])
                # Validate required keys
                required = ["summary", "key_points", "retirement_relevance"]
                if all(k in parsed for k in required):
                    parsed["_provider"] = result.get("provider", "unknown")
                    return parsed
                # Retry once if missing keys
                result2 = get_llm_response(
                    "cio_synthesis" if high_impact else "agent_narrative",
                    prompt, max_tokens=500, high_impact=high_impact
                )
                if result2.get("success"):
                    raw2 = result2["response"]
                    s2, e2 = raw2.find('{'), raw2.rfind('}') + 1
                    if s2 >= 0 and e2 > s2:
                        parsed2 = json.loads(raw2[s2:e2])
                        parsed2["_provider"] = result2.get("provider", "unknown")
                        parsed2["_retry"] = True
                        return parsed2
    except (json.JSONDecodeError, Exception):
        pass
    return {}


# ── Step 4: Sub-tags ─────────────────────────────────────────────────

def extract_sub_tags(text: str) -> list:
    """Extract investment-desk sub-tags (all asset classes + retirement) from text."""
    text_lower = (text or "").lower()
    tags = []
    for tag, patterns in SUB_TAG_RULES.items():
        for pat in patterns:
            if re.search(pat, text_lower):
                tags.append(tag)
                break
    return sorted(set(tags))


# ── Step 4b: Timestamped highlights from timed segments ──────────────

HIGHLIGHT_KEYWORDS = [
    # Retirement / disability (kept)
    "roth", "conversion", "ira", "401k", "dividend", "yield", "income",
    "retirement", "medicare", "medicaid", "irmaa", "tax bracket", "ssdi",
    "disability", "stop loss", "rebalance", "covered call", "bond ladder",
    # Equities / valuation
    "growth stock", "value investing", "small cap", "valuation", "earnings growth",
    "free cash flow", "moat", "price target",
    # Bonds / fixed income
    "bond", "treasury", "fixed income", "duration", "yield curve", "tips",
    # Options / ETF structures
    "put selling", "put etf", "put write", "inverse etf", "bear etf",
    "option premium", "wheel strategy",
    # Macro / multi-asset
    "macro", "portfolio construction", "investment thesis", "multi-asset",
    "fomc", "inflation", "interest rate",
    # Crypto / commodities / international
    "bitcoin", "crypto", "commodity", "gold", "emerging market", "international",
]


def extract_timestamped_highlights(timed_segments: list, max_highlights: int = 6) -> list:
    """Find keyword-rich segments and return timestamped highlights."""
    if not timed_segments:
        return []

    # Score each segment window (30-second chunks)
    window_size = 30  # seconds
    windows = []
    i = 0
    while i < len(timed_segments):
        window_text = ""
        start_time = timed_segments[i].get("start", 0)
        end_time = start_time
        j = i
        while j < len(timed_segments) and (timed_segments[j].get("start", 0) - start_time) < window_size:
            window_text += " " + (timed_segments[j].get("text", ""))
            end_time = timed_segments[j].get("start", 0) + timed_segments[j].get("duration", 0)
            j += 1

        # Score this window
        text_lower = window_text.lower()
        score = sum(1 for kw in HIGHLIGHT_KEYWORDS if kw in text_lower)
        if score >= 2:  # At least 2 keyword matches
            # Determine topic from matched keywords
            matched = [kw for kw in HIGHLIGHT_KEYWORDS if kw in text_lower]
            topic = matched[0] if matched else "general"
            # Map to readable topic name
            topic_map = {"roth": "Roth conversion", "conversion": "Roth conversion",
                         "dividend": "Dividend strategy", "yield": "Income yield",
                         "income": "Income strategy", "retirement": "Retirement planning",
                         "medicare": "Medicare/IRMAA", "irmaa": "IRMAA analysis",
                         "tax bracket": "Tax bracket management", "disability": "Disability planning",
                         "covered call": "Covered call income", "bond ladder": "Bond strategy",
                         "growth stock": "Growth equities", "value investing": "Value equities",
                         "small cap": "Small-cap equities", "valuation": "Valuation analysis",
                         "bond": "Fixed income", "treasury": "Treasuries",
                         "fixed income": "Fixed income", "put selling": "Put-selling ETF",
                         "put etf": "Put-selling ETF", "inverse etf": "Inverse/bearish ETF",
                         "macro": "Macro outlook", "portfolio construction": "Portfolio construction",
                         "bitcoin": "Crypto assets", "commodity": "Commodities",
                         "emerging market": "International/emerging"}
            readable_topic = topic_map.get(topic, topic.title())

            def _fmt_time(seconds):
                m, s = divmod(int(seconds), 60)
                h, m = divmod(m, 60)
                return f"{h}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

            windows.append({
                "start": _fmt_time(start_time),
                "end": _fmt_time(end_time),
                "topic": readable_topic,
                "score": score,
                "snippet": window_text.strip()[:80],
            })

        i = j if j > i else i + 1

    # Sort by score descending, take top N
    windows.sort(key=lambda w: w["score"], reverse=True)
    # Remove score + snippet from output (internal only)
    return [{"start": w["start"], "end": w["end"], "topic": w["topic"]} for w in windows[:max_highlights]]


# ── Step 5: Cross-channel deduplication ──────────────────────────────

def _text_fingerprint(text: str, n: int = 5) -> set:
    """Create a set of n-gram fingerprints for similarity comparison."""
    words = re.findall(r'\w+', text.lower())
    if len(words) < n:
        return set()
    return set(tuple(words[i:i+n]) for i in range(len(words) - n + 1))


def find_duplicates(threshold: float = 0.4) -> list:
    """Find duplicate/near-duplicate transcripts across channels.
    Uses Jaccard similarity on word n-gram fingerprints.
    """
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, video_id, title, channel_name, LEFT(cleaned_text, 2000) as text FROM youtube_transcripts WHERE cleaned_text IS NOT NULL")
    rows = cur.fetchall()
    conn.close()

    fingerprints = []
    for r in rows:
        fp = _text_fingerprint(r.get("text", ""))
        fingerprints.append({"id": r["id"], "video_id": r["video_id"], "title": r["title"],
                             "channel": r["channel_name"], "fp": fp})

    duplicates = []
    for i in range(len(fingerprints)):
        for j in range(i + 1, len(fingerprints)):
            a, b = fingerprints[i], fingerprints[j]
            if not a["fp"] or not b["fp"]:
                continue
            # Skip same channel (expected overlap)
            if a["channel"] == b["channel"]:
                continue
            intersection = len(a["fp"] & b["fp"])
            union = len(a["fp"] | b["fp"])
            similarity = intersection / union if union > 0 else 0
            if similarity > threshold:
                duplicates.append({
                    "a": f"{a['channel']}: {a['title'][:40]}",
                    "b": f"{b['channel']}: {b['title'][:40]}",
                    "similarity": round(similarity, 2),
                })

    return duplicates


# ── Step 6: Purge dates ──────────────────────────────────────────────

def set_purge_dates():
    """Set purge_after dates based on quality tier."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id, quality_score, ingested_at FROM youtube_transcripts WHERE purge_after IS NULL")
    rows = cur.fetchall()
    ucur = conn.cursor()
    for r in rows:
        q = r.get("quality_score", 0)
        ingested = r.get("ingested_at") or datetime.now()
        if q >= 75:
            purge = None
        elif q >= 50:
            purge = ingested + timedelta(days=365)
        else:
            purge = ingested + timedelta(days=90)
        if purge:
            ucur.execute("UPDATE youtube_transcripts SET purge_after=%s WHERE id=%s", (purge.date(), r["id"]))
    conn.commit()
    conn.close()
    return len(rows)


def purge_expired():
    """Delete transcripts past their purge date."""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM youtube_transcripts WHERE purge_after IS NOT NULL AND purge_after < CURRENT_DATE")
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    print(f"[purge] Deleted {deleted} expired transcripts")
    return deleted


# ── Main pipeline ────────────────────────────────────────────────────

def process_transcript(video_id: str = None, process_all: bool = False):
    """Full hybrid pipeline: clean → extract → summarize → sub-tag → structured JSON."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if video_id:
        cur.execute("SELECT id, video_id, title, channel_name, transcript_text, quality_score, timed_segments FROM youtube_transcripts WHERE video_id=%s", (video_id,))
    elif process_all:
        cur.execute("SELECT id, video_id, title, channel_name, transcript_text, quality_score, timed_segments FROM youtube_transcripts WHERE summary IS NULL OR structured_json IS NULL")
    else:
        conn.close()
        return 0

    rows = cur.fetchall()
    ucur = conn.cursor()
    processed = 0

    for r in rows:
        raw = r.get("transcript_text", "")
        title = r.get("title", "")
        channel = r.get("channel_name", "")
        quality = r.get("quality_score", 0)
        vid = r.get("video_id", "?")[:8]

        # Step 1: Clean
        cleaned = clean_transcript(raw)

        # Step 2: Extractive pre-filter (TextRank — keep top 35%)
        extracted = extractive_filter(cleaned)
        reduction = f"{len(cleaned)}→{len(extracted)} chars ({int(len(extracted)/max(len(cleaned),1)*100)}%)"

        # Step 3: Abstractive structured summary
        structured = {}
        summary = ""
        if len(extracted) > 300:
            structured = generate_structured_summary(title, extracted, channel, quality)
            summary = structured.get("summary", "")
            provider = structured.get("_provider", "?")
            kp = len(structured.get("key_points", []))
            ai = len(structured.get("action_items", []))
            rel = structured.get("retirement_relevance", "?")
            print(f"  [{vid}] {channel:25} {kp}pts {ai}acts rel={rel} via={provider} extract={reduction}")
        else:
            print(f"  [{vid}] {channel:25} too short ({len(extracted)} chars), extract={reduction}")

        # Step 4: Sub-tags
        sub_tags = extract_sub_tags(f"{title} {cleaned}")

        # Step 4b: Timestamped highlights
        timed = r.get("timed_segments")
        if isinstance(timed, str):
            try: timed = json.loads(timed)
            except: timed = None
        if timed and isinstance(timed, list):
            highlights = extract_timestamped_highlights(timed)
            if highlights and structured:
                structured["timestamped_highlights"] = highlights
                print(f"    → {len(highlights)} timestamped highlights extracted")

        # Store everything
        ucur.execute("""
            UPDATE youtube_transcripts
            SET cleaned_text=%s, summary=%s, structured_json=%s, sub_tags=%s
            WHERE id=%s
        """, (cleaned[:50000],
              summary[:2000] if summary else None,
              json.dumps(structured) if structured else None,
              json.dumps(sub_tags),
              r["id"]))
        processed += 1

    conn.commit()
    conn.close()
    return processed


if __name__ == "__main__":
    if "--process-all" in sys.argv:
        print("Processing all transcripts (full hybrid pipeline)...")
        n = process_transcript(process_all=True)
        print(f"Processed: {n}")
        print("Setting purge dates...")
        p = set_purge_dates()
        print(f"Purge dates set: {p}")
    elif "--process" in sys.argv:
        idx = sys.argv.index("--process")
        if idx + 1 < len(sys.argv):
            process_transcript(video_id=sys.argv[idx + 1])
    elif "--dedup" in sys.argv:
        print("Checking for cross-channel duplicates...")
        dupes = find_duplicates()
        if dupes:
            print(f"Found {len(dupes)} potential duplicates:")
            for d in dupes:
                print(f"  {d['similarity']:.0%} similar: {d['a']} ↔ {d['b']}")
        else:
            print("No duplicates found.")
    elif "--purge-expired" in sys.argv:
        purge_expired()
    else:
        print("Usage:")
        print("  --process-all         Full pipeline on all unprocessed transcripts")
        print("  --process VIDEO_ID    Process a single transcript")
        print("  --dedup               Find cross-channel duplicate transcripts")
        print("  --purge-expired       Delete transcripts past purge_after date")
