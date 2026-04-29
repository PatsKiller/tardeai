#!/usr/bin/env python3
"""transcript_processor.py — Clean, summarize, and sub-tag YouTube transcripts.

Takes raw auto-caption text and produces:
1. cleaned_text: filler words removed, basic sentence structure
2. summary: 150-300 word summary via LLM
3. sub_tags: retirement-specific subtopics

Usage:
    python3 scripts/transcript_processor.py --process-all
    python3 scripts/transcript_processor.py --process VIDEO_ID
"""
import json, re, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Filler words to remove from auto-captions
FILLERS = [
    r'\b(um|uh|uh huh|umm|uhh|hmm|hm|ah|oh|er|like)\b',
    r'\b(you know|i mean|sort of|kind of|basically|actually|literally)\b',
    r'\b(right right|yeah yeah|okay okay)\b',
]
FILLER_PATTERN = re.compile('|'.join(FILLERS), re.IGNORECASE)

# Retirement-specific sub-tags
SUB_TAG_RULES = {
    "roth_conversion_ladder": ["roth conversion", "roth ladder", "conversion ladder", "convert ira to roth", "backdoor roth"],
    "ssdi_ira_rules": ["ssdi", "disability.*ira", "disability.*retirement", "social security disability", "disability benefits"],
    "medicaid_trust_planning": ["medicaid", "asset protection trust", "mapt", "medicaid lookback", "medicaid eligibility"],
    "disability_spousal_ira": ["spousal ira", "spousal contribution", "spouse.*ira", "married.*ira"],
    "irmaa_medicare": ["irmaa", "medicare premium", "medicare surcharge", "part b premium", "medicare lookback"],
    "income_gap_strategy": ["income gap", "income target", "retirement income", "passive income", "dividend income.*retirement"],
    "tax_bracket_management": ["tax bracket", "bracket room", "fill.*bracket", "tax efficiency", "tax optimization"],
    "covered_call_income": ["covered call", "option income", "selling calls", "premium income", "wheel strategy"],
    "dividend_growth": ["dividend growth", "dividend aristocrat", "consecutive.*dividend", "dividend increase", "dgi"],
    "rmd_planning": ["required minimum", "rmd", "rmd strategy", "rmd tax", "72t"],
    "401k_rollover": ["401k rollover", "rollover ira", "roll over.*401", "employer plan"],
    "bond_ladder": ["bond ladder", "treasury ladder", "fixed income ladder", "i bond", "tips"],
}


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def clean_transcript(raw: str) -> str:
    """Remove filler words and clean up auto-caption text."""
    if not raw:
        return ""
    text = raw

    # Remove filler words
    text = FILLER_PATTERN.sub('', text)

    # Collapse multiple spaces
    text = re.sub(r'\s+', ' ', text)

    # Basic sentence detection — capitalize after periods
    text = re.sub(r'\.\s+([a-z])', lambda m: '. ' + m.group(1).upper(), text)

    # Remove leading/trailing whitespace per line
    text = '\n'.join(line.strip() for line in text.split('\n') if line.strip())

    return text.strip()


def extract_sub_tags(text: str) -> list:
    """Extract retirement-specific sub-tags from transcript text."""
    text_lower = (text or "").lower()
    tags = []
    for tag, patterns in SUB_TAG_RULES.items():
        for pat in patterns:
            if re.search(pat, text_lower):
                tags.append(tag)
                break
    return sorted(set(tags))


def generate_summary(title: str, text: str, channel: str = "") -> str:
    """Generate a 150-300 word summary using local LLM."""
    if not text or len(text) < 200:
        return ""

    try:
        from llm_router import get_llm_response
        prompt = f"""/no_think Summarize this YouTube video transcript in 150-200 words. Focus on actionable investment insights, retirement planning advice, and specific recommendations mentioned.

Title: {title}
Channel: {channel}

Transcript (first 3000 chars):
{text[:3000]}

Provide a concise summary with:
1. Main topic (1 sentence)
2. Key insights (3-4 bullet points)
3. Actionable takeaway (1 sentence)"""

        result = get_llm_response("agent_narrative", prompt, max_tokens=300)
        if result.get("success"):
            return result["response"][:1000]
    except Exception:
        pass
    return ""


def set_purge_dates():
    """Set purge_after dates based on quality tier."""
    from datetime import datetime, timedelta
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("SELECT id, quality_score, validation_status, ingested_at FROM youtube_transcripts WHERE purge_after IS NULL")
    rows = cur.fetchall()
    ucur = conn.cursor()

    for r in rows:
        q = r.get("quality_score", 0)
        ingested = r.get("ingested_at") or datetime.now()
        if q >= 75:
            purge = None  # Keep forever
        elif q >= 50:
            purge = ingested + timedelta(days=365)  # 12 months
        else:
            purge = ingested + timedelta(days=90)  # 90 days

        if purge:
            ucur.execute("UPDATE youtube_transcripts SET purge_after=%s WHERE id=%s", (purge.date(), r["id"]))

    conn.commit()
    conn.close()
    return len(rows)


def process_transcript(video_id: str = None, process_all: bool = False):
    """Clean, summarize, and sub-tag transcripts."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    if video_id:
        cur.execute("SELECT id, video_id, title, channel_name, transcript_text FROM youtube_transcripts WHERE video_id=%s", (video_id,))
    elif process_all:
        cur.execute("SELECT id, video_id, title, channel_name, transcript_text FROM youtube_transcripts WHERE cleaned_text IS NULL OR summary IS NULL")
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

        # 1. Clean
        cleaned = clean_transcript(raw)

        # 2. Sub-tags
        sub_tags = extract_sub_tags(f"{title} {cleaned}")

        # 3. Summary (LLM — only for transcripts with enough content)
        summary = ""
        if len(cleaned) > 500:
            summary = generate_summary(title, cleaned, channel)
            if summary:
                print(f"  [{r['video_id'][:8]}] {channel:20} summary: {len(summary)} chars, sub_tags: {sub_tags}")
            else:
                print(f"  [{r['video_id'][:8]}] {channel:20} cleaned only (LLM failed), sub_tags: {sub_tags}")
        else:
            print(f"  [{r['video_id'][:8]}] {channel:20} too short for summary ({len(cleaned)} chars), sub_tags: {sub_tags}")

        ucur.execute("""
            UPDATE youtube_transcripts
            SET cleaned_text=%s, summary=%s, sub_tags=%s
            WHERE id=%s
        """, (cleaned[:50000], summary[:2000] if summary else None,
              json.dumps(sub_tags), r["id"]))
        processed += 1

    conn.commit()
    conn.close()
    return processed


if __name__ == "__main__":
    if "--process-all" in sys.argv:
        print(f"Processing all unprocessed transcripts...")
        n = process_transcript(process_all=True)
        print(f"Processed: {n}")
        print(f"Setting purge dates...")
        p = set_purge_dates()
        print(f"Purge dates set: {p}")
    elif "--process" in sys.argv:
        idx = sys.argv.index("--process")
        if idx + 1 < len(sys.argv):
            process_transcript(video_id=sys.argv[idx + 1])
        else:
            print("Usage: --process VIDEO_ID")
    else:
        print("Usage: --process-all | --process VIDEO_ID")
