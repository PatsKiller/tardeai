# Source Export: scripts/proposal_catalyst_quality.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/proposal_catalyst_quality.py` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `b68baa432e06833633a6baeea2a82ae57a5ee1b4d0e05270b2a6efa6586c9211` |
| **File Size** | 16715 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""proposal_catalyst_quality.py — Assess catalyst quality for paper trade proposals.

Goes beyond catalyst_verified=true to score catalyst type, freshness,
company-specificity, contradictory signals, and expected duration.

Usage:
    .venv/bin/python scripts/proposal_catalyst_quality.py --pending --dry-run
    .venv/bin/python scripts/proposal_catalyst_quality.py --pending --apply
    .venv/bin/python scripts/proposal_catalyst_quality.py --proposal-id 123 --apply
"""
import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from session13_db import get_conn

log = logging.getLogger("catalyst_quality")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

# ---------------------------------------------------------------------------
# Catalyst classification patterns
# ---------------------------------------------------------------------------
CATALYST_PATTERNS = {
    "earnings_beat": [
        r"(?i)eps\s+beat", r"(?i)earnings?\s+beat", r"(?i)beat\s+(estimates?|expectations?|consensus)",
        r"(?i)revenue\s+beat", r"(?i)top[- ]line\s+beat", r"(?i)blowout\s+(quarter|earnings)",
        r"(?i)q[1-4]\s+(beat|surprise)",
    ],
    "guidance_raise": [
        r"(?i)guid(ance|e)\s+(raise|hike|boost|lift|up)",
        r"(?i)raise[ds]?\s+(outlook|forecast|guid)",
        r"(?i)upward\s+revision", r"(?i)full[- ]year\s+(raise|higher)",
    ],
    "fda_approval": [
        r"(?i)fda\s+(approv|clear|grant|accept)", r"(?i)pdufa", r"(?i)nda\s+accept",
        r"(?i)breakthrough\s+therapy", r"(?i)priority\s+review",
    ],
    "contract_win": [
        r"(?i)(win|award|secur|land)[sed]*\s+(contract|deal|order)",
        r"(?i)(government|defense|dod|military)\s+(contract|award)",
        r"(?i)billion[- ]dollar\s+(contract|deal)",
    ],
    "analyst_upgrade": [
        r"(?i)upgrad(e|ed)", r"(?i)price\s+target\s+(raise|hike|boost|increase)",
        r"(?i)initiat\w+\s+(buy|overweight|outperform)",
        r"(?i)reiterate[ds]?\s+(buy|overweight)",
    ],
    "sector_sympathy": [
        r"(?i)sympathy", r"(?i)sector\s+(move|rally|strength|momentum|rotation)",
        r"(?i)peer\s+(rally|strength)", r"(?i)group\s+move",
    ],
    "generic_momentum": [
        r"(?i)momentum", r"(?i)breakout", r"(?i)volume\s+spike",
        r"(?i)technical\s+breakout", r"(?i)relative\s+strength",
    ],
}

COMPANY_SPECIFIC_TYPES = {
    "earnings_beat", "guidance_raise", "fda_approval", "contract_win",
    "analyst_upgrade",
}

DURATION_MAP = {
    "earnings_beat":     "1-3 trading days",
    "guidance_raise":    "1-3 trading days",
    "fda_approval":      "1-2 weeks",
    "contract_win":      "1-2 weeks",
    "analyst_upgrade":   "1-3 trading days",
    "sector_sympathy":   "1-day",
    "generic_momentum":  "1-day",
    "unknown":           "unknown",
}

RISK_MAP = {
    "earnings_beat":     "gap fade if call commentary disappoints",
    "guidance_raise":    "sell-the-news after initial pop",
    "fda_approval":      "clinical or regulatory reversal risk",
    "contract_win":      "execution/margin compression risk on large contract",
    "analyst_upgrade":   "single-analyst risk; may already be priced in",
    "sector_sympathy":   "no company-specific catalyst; fades when sector cools",
    "generic_momentum":  "momentum reversal; no fundamental anchor",
    "unknown":           "unidentified catalyst; cannot assess risk",
}

GRADE_THRESHOLDS = {
    # (min_score, grade)
    80: "STRONG_COMPANY_SPECIFIC",
    60: "MODERATE_COMPANY_SPECIFIC",
    40: "WEAK_GENERIC",
    20: "NO_CATALYST",
    0:  "STALE_CATALYST",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _table_has_column(conn, table, column):
    """Check if a table has a specific column."""
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            LIMIT 1
        """, [table, column])
        return cur.fetchone() is not None
    except Exception:
        return False


def _table_exists(conn, table):
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 1 FROM information_schema.tables
            WHERE table_name = %s LIMIT 1
        """, [table])
        return cur.fetchone() is not None
    except Exception:
        return False


def classify_catalyst(text):
    """Return (catalyst_type, evidence_snippets) from free-text catalyst field."""
    if not text:
        return "unknown", []
    evidence = []
    scores = {}
    for ctype, patterns in CATALYST_PATTERNS.items():
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                scores[ctype] = scores.get(ctype, 0) + 1
                evidence.append(m.group(0))
    if not scores:
        return "unknown", [text[:120]] if text else []
    best = max(scores, key=scores.get)
    return best, evidence


def get_news_for_symbol(conn, symbol, hours_back=72):
    """Fetch recent news articles for contradictory-headline analysis."""
    if not _table_exists(conn, "news_articles"):
        return []

    has_sentiment = _table_has_column(conn, "news_articles", "sentiment")
    has_source = _table_has_column(conn, "news_articles", "source")

    cols = ["title", "published_at"]
    if has_sentiment:
        cols.append("sentiment")
    if has_source:
        cols.append("source")

    try:
        cur = conn.cursor()
        cur.execute(f"""
            SELECT {', '.join(cols)} FROM news_articles
            WHERE symbol = %s AND published_at > NOW() - INTERVAL '{int(hours_back)} hours'
            ORDER BY published_at DESC LIMIT 20
        """, [symbol])
        col_names = [d[0] for d in cur.description]
        return [dict(zip(col_names, row)) for row in cur.fetchall()]
    except Exception as e:
        log.warning("news_articles query failed: %s", e)
        conn.rollback()
        return []


def detect_contradictions(articles):
    """Simple heuristic: if sentiments span positive and negative, flag it."""
    sentiments = set()
    for a in articles:
        s = (a.get("sentiment") or "").lower()
        if s in ("positive", "bullish"):
            sentiments.add("positive")
        elif s in ("negative", "bearish"):
            sentiments.add("negative")
    return "positive" in sentiments and "negative" in sentiments


def headline_age_hours(articles):
    """Return age in hours of the most recent headline, or None."""
    if not articles:
        return None
    newest = articles[0].get("published_at")
    if not newest:
        return None
    now = datetime.now(timezone.utc)
    if newest.tzinfo is None:
        newest = newest.replace(tzinfo=timezone.utc)
    delta = (now - newest).total_seconds() / 3600.0
    return round(delta, 1)


def compute_quality_score(catalyst_type, verified, headline_age, contradictions,
                          catalyst_confidence, gap_pct, vs_sector_pct):
    """Compute a 0-100 catalyst quality score."""
    score = 50  # baseline

    # Catalyst type contribution
    type_scores = {
        "earnings_beat": 20, "guidance_raise": 18, "fda_approval": 22,
        "contract_win": 18, "analyst_upgrade": 12, "sector_sympathy": -5,
        "generic_momentum": -10, "unknown": -20,
    }
    score += type_scores.get(catalyst_type, 0)

    # Verification
    if verified:
        score += 10
    else:
        score -= 10

    # Headline freshness (stale = bad)
    if headline_age is not None:
        if headline_age < 4:
            score += 10
        elif headline_age < 12:
            score += 5
        elif headline_age < 24:
            pass  # neutral
        elif headline_age < 48:
            score -= 10
        else:
            score -= 20

    # Contradictory signals
    if contradictions:
        score -= 15

    # Catalyst confidence from scan
    if catalyst_confidence is not None:
        try:
            conf = float(catalyst_confidence)
            if conf >= 0.8:
                score += 8
            elif conf >= 0.5:
                score += 3
            elif conf < 0.3:
                score -= 5
        except (ValueError, TypeError):
            pass

    # Gap fade risk
    if gap_pct is not None:
        try:
            g = abs(float(gap_pct))
            if g > 10:
                score -= 8
            elif g > 5:
                score -= 3
        except (ValueError, TypeError):
            pass

    # Sector relative strength
    if vs_sector_pct is not None:
        try:
            vs = float(vs_sector_pct)
            if vs > 5:
                score += 5
            elif vs < -2:
                score -= 5
        except (ValueError, TypeError):
            pass

    return max(0, min(100, score))


def score_to_grade(score, company_specific):
    """Map score to a grade string."""
    if score >= 80 and company_specific:
        return "STRONG_COMPANY_SPECIFIC"
    if score >= 60 and company_specific:
        return "MODERATE_COMPANY_SPECIFIC"
    if score >= 60 and not company_specific:
        return "WEAK_GENERIC"
    if score >= 40:
        return "WEAK_GENERIC"
    if score >= 20:
        return "NO_CATALYST"
    return "STALE_CATALYST"


# ---------------------------------------------------------------------------
# Core assessment
# ---------------------------------------------------------------------------

def assess_proposal(conn, proposal):
    """Assess catalyst quality for a single proposal dict."""
    pid = proposal["id"]
    symbol = proposal["symbol"]
    catalyst_text = proposal.get("catalyst") or ""
    verified = bool(proposal.get("catalyst_verified"))

    # Classify catalyst type
    catalyst_type, evidence = classify_catalyst(catalyst_text)
    company_specific = catalyst_type in COMPANY_SPECIFIC_TYPES

    # Scan data enrichment
    scan_confidence = proposal.get("catalyst_confidence")
    gap_pct = proposal.get("gap_pct")
    vs_sector_pct = proposal.get("vs_sector_pct")

    # News analysis
    articles = get_news_for_symbol(conn, symbol, hours_back=72)
    contradictions = detect_contradictions(articles)
    age_hours = headline_age_hours(articles)

    # Add news titles to evidence
    for a in articles[:3]:
        title = a.get("title")
        if title and title not in evidence:
            evidence.append(title)

    # Compute score and grade
    score = compute_quality_score(
        catalyst_type, verified, age_hours, contradictions,
        scan_confidence, gap_pct, vs_sector_pct,
    )
    grade = score_to_grade(score, company_specific)

    # Stale override: if headline age > 48h and no strong type, downgrade
    if age_hours is not None and age_hours > 48 and score < 60:
        grade = "STALE_CATALYST"

    return {
        "proposal_id": pid,
        "symbol": symbol,
        "catalyst_quality_score": score,
        "catalyst_grade": grade,
        "catalyst_type": catalyst_type,
        "company_specific": company_specific,
        "verified": verified,
        "headline_age_hours": age_hours,
        "duration_estimate": DURATION_MAP.get(catalyst_type, "unknown"),
        "risk": RISK_MAP.get(catalyst_type, "unidentified catalyst risk"),
        "contradictory_signals": contradictions,
        "evidence": evidence[:5],
    }


# ---------------------------------------------------------------------------
# DB fetch and write
# ---------------------------------------------------------------------------

def fetch_pending_proposals(conn, proposal_id=None, limit=20):
    """Fetch pending proposals with scan data."""
    cur = conn.cursor()
    where_clause = "ptp.status = 'PENDING'"
    params = []

    if proposal_id:
        where_clause = "ptp.id = %s"
        params.append(proposal_id)

    query = f"""
        SELECT ptp.id, ptp.symbol, ptp.strategy_id,
               ptp.catalyst, ptp.catalyst_verified,
               ptp.gap_pct,
               scan.catalyst_confidence, scan.vs_sector_pct,
               scan.sector, scan.industry, scan.change_pct
        FROM paper_trade_proposals ptp
        LEFT JOIN LATERAL (
            SELECT * FROM trade_ai_scans WHERE symbol = ptp.symbol
            ORDER BY scanned_at DESC LIMIT 1
        ) scan ON true
        WHERE {where_clause}
        ORDER BY ptp.created_at DESC
        LIMIT %s
    """
    params.append(limit)

    try:
        cur.execute(query, params)
    except Exception as e:
        log.error("Failed to fetch proposals: %s", e)
        conn.rollback()
        return []

    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _ensure_results_table(conn):
    """Create the catalyst_quality_results table if it doesn't exist."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS catalyst_quality_results (
            id              SERIAL PRIMARY KEY,
            proposal_id     INTEGER NOT NULL,
            symbol          TEXT NOT NULL,
            quality_score   INTEGER,
            grade           TEXT,
            catalyst_type   TEXT,
            company_specific BOOLEAN,
            verified        BOOLEAN,
            headline_age_hours REAL,
            duration_estimate TEXT,
            risk            TEXT,
            contradictory_signals BOOLEAN,
            evidence        JSONB,
            assessed_at     TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    conn.commit()


def write_result(conn, result):
    """Insert an assessment result into the database."""
    _ensure_results_table(conn)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO catalyst_quality_results
            (proposal_id, symbol, quality_score, grade, catalyst_type,
             company_specific, verified, headline_age_hours, duration_estimate,
             risk, contradictory_signals, evidence)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, [
        result["proposal_id"], result["symbol"],
        result["catalyst_quality_score"], result["catalyst_grade"],
        result["catalyst_type"], result["company_specific"],
        result["verified"], result["headline_age_hours"],
        result["duration_estimate"], result["risk"],
        result["contradictory_signals"],
        json.dumps(result["evidence"]),
    ])
    conn.commit()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Assess catalyst quality for proposals")
    parser.add_argument("--pending", action="store_true", help="Assess all pending proposals")
    parser.add_argument("--proposal-id", type=int, help="Assess a specific proposal")
    parser.add_argument("--dry-run", action="store_true", help="Print results without writing to DB")
    parser.add_argument("--apply", action="store_true", help="Write results to DB")
    parser.add_argument("--limit", type=int, default=20, help="Max proposals to assess")
    args = parser.parse_args()

    if not args.pending and not args.proposal_id:
        parser.error("Specify --pending or --proposal-id")

    if not args.dry_run and not args.apply:
        parser.error("Specify --dry-run or --apply")

    conn = get_conn()
    try:
        proposals = fetch_pending_proposals(
            conn,
            proposal_id=args.proposal_id,
            limit=args.limit,
        )

        if not proposals:
            log.info("No proposals found to assess.")
            return

        log.info("Assessing %d proposal(s)...", len(proposals))

        results = []
        for p in proposals:
            result = assess_proposal(conn, p)
            results.append(result)

            log.info(
                "[%s] %s score=%d grade=%s type=%s age=%s",
                result["symbol"], "APPLY" if args.apply else "DRY-RUN",
                result["catalyst_quality_score"], result["catalyst_grade"],
                result["catalyst_type"],
                f"{result['headline_age_hours']}h" if result["headline_age_hours"] else "N/A",
            )

            if args.apply:
                write_result(conn, result)
                log.info("  -> Written to catalyst_quality_results")

        # Summary output
        print(json.dumps(results, indent=2, default=str))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
```
