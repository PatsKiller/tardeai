#!/usr/bin/env python3
"""research_watchlist_discovery.py — surface Hermes/social research as watchlist ideas.

Closes the "same sources, curated into ideas" gap (2026-08-19 audit, Gap C): the
watchlist was fed almost exclusively by the Finviz screener, so Hermes forum/web
research and social momentum never became watchlist candidates on their own.

This lane reads the SAME research sources as the day-scalp pipeline
(hermes_research_intelligence = Hermes/SearXNG forum+web; social_sentiment_history =
social) and writes them into watchlist_items as NON-trading research ideas
(status='researched', bucket='research_discovery', source_tier='candidate').

It never auto-promotes to the watchpool or any execution rail — it only surfaces
"here's what's happening in the market for research", exactly like topic_curator's
research_discovery bucket. It is deliberately SEPARATE from the momentum scalp lead
miner (which stages to the incubator + 'active' watchlist for trading).

Usage:
    python3 scripts/research_watchlist_discovery.py --dry-run
    python3 scripts/research_watchlist_discovery.py --apply --max-symbols 60
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SOURCE_KEY = "research_discovery"
HORIZON_DAYS = 7


def _get_conn():
    from db_adapter import _get_conn as _c
    return _c()


def _research_candidates(conn, limit: int) -> list[dict]:
    """Symbols surfaced by Hermes/SearXNG research in the last N days."""
    cur = conn.cursor()
    cur.execute(
        """SELECT symbol, topic, summary, confidence_score, status
           FROM hermes_research_intelligence
           WHERE symbol IS NOT NULL
             AND status IN ('staged', 'promoted', 'reviewed')
             AND created_at > NOW() - (%s * INTERVAL '1 day')
           ORDER BY confidence_score DESC NULLS LAST
           LIMIT %s""",
        (HORIZON_DAYS, limit),
    )
    out = []
    for sym, topic, summary, conf, status in cur.fetchall():
        thesis = (topic or summary or "").strip()[:140]
        out.append({
            "symbol": sym.upper(),
            "origin_system": "hermes_research",
            "provenance_reason": f"Hermes research: {thesis or status}",
            "detail": {"source": "hermes_research", "thesis": thesis,
                       "confidence": float(conf) if conf else None},
        })
    return out


def _social_candidates(conn, limit: int) -> list[dict]:
    """Symbols with unusual social momentum (spike or strong one-sided sentiment)."""
    cur = conn.cursor()
    cur.execute(
        """SELECT symbol, mention_count, sentiment_score, unusual_spike
           FROM social_sentiment_history
           WHERE observed_at > NOW() - (%s * INTERVAL '1 day')
             AND (unusual_spike = true OR ABS(COALESCE(sentiment_score, 0)) >= 0.5)
           ORDER BY observed_at DESC
           LIMIT %s""",
        (HORIZON_DAYS, limit),
    )
    out = []
    for sym, mentions, score, spike in cur.fetchall():
        out.append({
            "symbol": sym.upper(),
            "origin_system": "social_momentum",
            "provenance_reason": f"Social momentum: {mentions} mentions, sentiment {score}",
            "detail": {"source": "social_momentum", "mentions": mentions,
                       "sentiment_score": float(score) if score is not None else None,
                       "unusual_spike": bool(spike)},
        })
    return out


def _insert(conn, cand: dict) -> bool:
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO watchlist_items
               (symbol, source, status, bucket, origin_system, origin_detail,
                source_tier, in_directive_watch, provenance_reason, seen_count,
                first_seen_at, last_seen_at)
           VALUES (%s, %s, 'researched', 'research_discovery', %s, %s::jsonb,
                   'candidate', false, %s, 1, NOW(), NOW())
           ON CONFLICT (symbol, source, COALESCE(bucket, '__none__')) DO NOTHING""",
        (cand["symbol"], SOURCE_KEY, cand["origin_system"],
         json.dumps(cand["detail"], default=str), cand["provenance_reason"]))
    return cur.rowcount > 0


def main() -> dict:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max-symbols", type=int, default=60)
    args = ap.parse_args()

    conn = _get_conn()
    half = max(1, args.max_symbols // 2)

    research = _research_candidates(conn, half)
    social = _social_candidates(conn, half)
    print(f"[research-discovery] Hermes research: {len(research)} | social momentum: {len(social)}")

    # Dedup by symbol (research first, then social); merge provenance if both hit.
    by_symbol: dict[str, dict] = {}
    for c in research + social:
        sym = c["symbol"]
        if sym in by_symbol:
            merged = dict(by_symbol[sym]["detail"])
            merged.update(c["detail"])
            by_symbol[sym]["detail"] = merged
            by_symbol[sym]["origin_system"] = "hermes_research+social"
            by_symbol[sym]["provenance_reason"] = (
                by_symbol[sym]["provenance_reason"] + " | " + c["provenance_reason"])
        else:
            by_symbol[sym] = c

    written = 0
    for sym, cand in by_symbol.items():
        if args.apply:
            try:
                if _insert(conn, cand):
                    written += 1
            except Exception as e:
                print(f"  [research-discovery] {sym} insert error: {e}")
        else:
            written += 1

    if args.apply:
        conn.commit()
        try:
            from lib.data_source_report import report_source
            report_source(SOURCE_KEY, written > 0, rows=written,
                          error=None if written else "0 research candidates")
        except Exception:
            pass

    print(f"[research-discovery] {'would write' if not args.apply else 'wrote'} {written} research ideas")
    conn.close()
    return {"candidates": len(by_symbol), "written": written, "dry_run": not args.apply}


if __name__ == "__main__":
    main()
