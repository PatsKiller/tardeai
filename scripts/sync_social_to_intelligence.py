#!/usr/bin/env python3
"""sync_social_to_intelligence.py — fold social sentiment into the scorer's read path.

Watches the gap found in the 2026-08-19 watchlist audit: the producers
(aegis_social_sentiment.py, hermes_social_sentiment.py) write
`social_sentiment_history`, but the watchlist scorer + scope governor read
`intelligence_entities.social_score` / `social_sentiment` — which are NEVER
written (0 of ~8.4k rows had a non-null social_score at audit time).

This bridge reads the latest social_sentiment_history per tracked symbol and
folds it onto intelligence_entities (via the single-writer intelligence_entity_manager)
so `_f_social` in hermes_watchlist_scorer.py and the scope governor actually see it.

Mapping: sentiment_score (-1..1) -> social_score (0..100) = 50 + 50*score;
social_sentiment string from polarity thresholds.

Liveness: report_source('social', ...) on --apply so the health agent can track
it and the source-aware auto-remediation ladder can re-run it on a stale finding.

Usage:
    python3 scripts/sync_social_to_intelligence.py --dry-run
    python3 scripts/sync_social_to_intelligence.py --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Load .env
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k and v and k not in os.environ:
                os.environ[k] = v

MAX_AGE_HOURS = float(os.getenv("SOCIAL_FOLD_MAX_AGE_HOURS", "168"))  # 7 days


def _sentiment_to_social(score: float | None) -> tuple[float, str]:
    """Map social_sentiment_history.sentiment_score (-1..1) -> (social_score 0..100, label)."""
    if score is None:
        return 50.0, "neutral"
    s = float(score)
    social_score = max(0.0, min(100.0, 50.0 + s * 50.0))
    if s >= 0.3:
        label = "bullish"
    elif s >= 0.1:
        label = "positive"
    elif s <= -0.3:
        label = "bearish"
    elif s <= -0.1:
        label = "negative"
    else:
        label = "neutral"
    return round(social_score, 1), label


def resolve_universe() -> list[str]:
    """Tracked symbols (same universe the social producers scan)."""
    try:
        from aegis_nightly_ingestion import resolve_universe as _ru
        return [u["symbol"] for u in _ru()]
    except Exception as e:
        print(f"  [social-fold] universe fallback ({e})")
        return []


def latest_sentiment(conn, symbols: list[str]) -> list[dict]:
    """Latest sentiment row per symbol within the freshness window."""
    if not symbols:
        return []
    cur = conn.cursor()
    cur.execute(
        """SELECT DISTINCT ON (symbol) symbol, sentiment_score, mention_count, observed_at
           FROM social_sentiment_history
           WHERE symbol = ANY(%s)
             AND observed_at > NOW() - (%s * INTERVAL '1 hour')
           ORDER BY symbol, observed_at DESC""",
        (symbols, MAX_AGE_HOURS),
    )
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    cur.close()
    return rows


def main() -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    print(f"[social-fold] folding social_sentiment_history -> intelligence_entities (max_age={MAX_AGE_HOURS:.0f}h)")
    symbols = resolve_universe()
    if not symbols:
        print("  [social-fold] empty universe — nothing to do")
        return {"universe": 0, "folded": 0, "dry_run": not args.apply}

    print(f"  Universe: {len(symbols)} symbols")

    from db_adapter import _get_conn
    conn = _get_conn()
    rows = latest_sentiment(conn, symbols)
    print(f"  Sentiment rows within window: {len(rows)}")

    folded = 0
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        score = r.get("sentiment_score")
        social_score, label = _sentiment_to_social(score)
        fields = {
            "social_score": social_score,
            "social_sentiment": label,
            "social_mentions": r.get("mention_count"),
            "social_updated": r.get("observed_at") or datetime.now(timezone.utc),
        }
        if not args.apply:
            folded += 1
            continue
        try:
            from intelligence_entity_manager import upsert_entity
            if upsert_entity(conn, sym, "market", fields, source="social_sync"):
                folded += 1
        except Exception as e:
            print(f"  [social-fold] {sym} fold error: {e}")

    if args.apply:
        try:
            from lib.data_source_report import report_source
            report_source("social", folded > 0, rows=folded,
                          error=None if folded else "0 symbols folded (no fresh sentiment)")
        except Exception:
            pass

    print(f"  Folded: {folded} symbols")
    print(f"[social-fold] complete (apply={args.apply})")
    return {"universe": len(symbols), "folded": folded, "dry_run": not args.apply}


if __name__ == "__main__":
    main()
