#!/usr/bin/env python3
"""
candidate_discovery_orchestrator.py — Multi-source candidate discovery with degraded mode.

If Finviz fails, falls back to alternate sources instead of going blind.

Usage:
    python candidate_discovery_orchestrator.py --dry-run
    python candidate_discovery_orchestrator.py --apply
    python candidate_discovery_orchestrator.py --simulate-finviz-failure --dry-run
"""
import argparse, json, os, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

def _env(key, default=""):
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.strip().startswith(key + "="):
                return line.split("=", 1)[1].strip().strip('"')
    return os.getenv(key, default)

def _get_conn():
    import psycopg2
    return psycopg2.connect(host="localhost", dbname="trade_ai",
                            user="trade_ai", password=_env("DB_PASSWORD"))


def check_finviz(simulate_failure=False):
    """Check Finviz and return candidates or None on failure."""
    if simulate_failure:
        print("  [discovery] SIMULATING Finviz failure")
        return None, "simulated_failure"
    try:
        from finviz_health_check import check
        result = check()
        if result["status"] == "healthy" and result.get("row_count", 0) > 0:
            return result, None
        return None, result.get("error", "zero rows")
    except Exception as e:
        return None, str(e)


def get_incubator_candidates(conn, limit=50):
    """Fallback: active incubator symbols."""
    cur = conn.cursor()
    cur.execute("""
        SELECT symbol, latest_score, strategy_id, status
        FROM incubator_universe WHERE status='ACTIVE'
        ORDER BY latest_score DESC NULLS LAST LIMIT %s
    """, (limit,))
    candidates = []
    for row in cur.fetchall():
        candidates.append({
            "symbol": row[0], "source_key": "incubator",
            "source_confidence": 0.7,
            "reason": f"Active incubator, score={row[1]}, strategy={row[2]}",
            "normalized_payload": {"score": float(row[1]) if row[1] else 0, "strategy": row[2]},
        })
    return candidates


def get_news_catalyst_candidates(conn, limit=30):
    """Fallback: symbols with recent high-relevance news."""
    cur = conn.cursor()
    cur.execute("""
        SELECT symbol, COUNT(*) as article_count, MAX(relevance_score) as max_rel
        FROM news_articles
        WHERE created_at > NOW() - INTERVAL '48 hours'
        AND relevance_score >= 0.5 AND symbol IS NOT NULL
        AND LENGTH(symbol) BETWEEN 1 AND 6
        GROUP BY symbol ORDER BY article_count DESC, max_rel DESC LIMIT %s
    """, (limit,))
    candidates = []
    for row in cur.fetchall():
        candidates.append({
            "symbol": row[0], "source_key": "news_catalyst",
            "source_confidence": 0.5,
            "reason": f"{row[1]} articles in 48h, max relevance {row[2]:.2f}",
            "normalized_payload": {"article_count": row[1], "max_relevance": float(row[2] or 0)},
        })
    return candidates


def get_watchlist_candidates(conn, limit=30):
    """Fallback: active watchlist symbols needing refresh."""
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT symbol FROM watchlist_agent_results
        WHERE created_at > NOW() - INTERVAL '7 days'
        ORDER BY symbol LIMIT %s
    """, (limit,))
    candidates = []
    for row in cur.fetchall():
        candidates.append({
            "symbol": row[0], "source_key": "watchlist_refresh",
            "source_confidence": 0.6,
            "reason": "Active watchlist symbol needing refresh",
            "normalized_payload": {},
        })
    return candidates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--simulate-finviz-failure", action="store_true")
    parser.add_argument("--max-candidates", type=int, default=100)
    args = parser.parse_args()

    conn = _get_conn()

    # Check Finviz
    finviz_result, finviz_error = check_finviz(args.simulate_finviz_failure)

    if finviz_result:
        mode = "normal"
        print(f"  [discovery] Mode: NORMAL (Finviz healthy, {finviz_result.get('row_count',0)} rows)")
        candidates_by_source = {"finviz": finviz_result.get("row_count", 0)}
    else:
        mode = "degraded"
        print(f"  [discovery] Mode: DEGRADED (Finviz failed: {finviz_error})")
        print(f"  [discovery] Activating fallback sources...")

        candidates = []
        # Fallback 1: incubator
        inc = get_incubator_candidates(conn, limit=50)
        candidates.extend(inc)
        print(f"  [fallback] Incubator: {len(inc)} candidates")

        # Fallback 2: news catalysts
        news = get_news_catalyst_candidates(conn, limit=30)
        candidates.extend(news)
        print(f"  [fallback] News catalyst: {len(news)} candidates")

        # Fallback 3: watchlist refresh
        wl = get_watchlist_candidates(conn, limit=30)
        candidates.extend(wl)
        print(f"  [fallback] Watchlist: {len(wl)} candidates")

        # Dedup by symbol
        seen = set()
        unique = []
        for c in candidates:
            if c["symbol"] not in seen:
                seen.add(c["symbol"])
                unique.append(c)
        candidates = unique[:args.max_candidates]

        candidates_by_source = {
            "incubator": len(inc), "news_catalyst": len(news),
            "watchlist_refresh": len(wl), "total_unique": len(candidates),
        }

        if not args.dry_run and args.apply:
            cur = conn.cursor()
            for c in candidates:
                event_id = f"disc_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"
                cur.execute("""
                    INSERT INTO candidate_discovery_events
                        (event_id, source_key, symbol, source_confidence,
                         normalized_payload, degraded, reason)
                    VALUES (%s, %s, %s, %s, %s, true, %s)
                    ON CONFLICT (event_id) DO NOTHING
                """, (event_id, c["source_key"], c["symbol"],
                      c.get("source_confidence", 0.5),
                      json.dumps(c.get("normalized_payload", {})),
                      c.get("reason", "")))
            conn.commit()
            print(f"  [discovery] Recorded {len(candidates)} degraded candidates to DB")

    summary = {
        "mode": mode,
        "finviz_status": "healthy" if finviz_result else "failed",
        "finviz_error": finviz_error,
        "candidates_by_source": candidates_by_source,
        "total_candidates": sum(candidates_by_source.values()) if mode == "normal" else candidates_by_source.get("total_unique", 0),
        "warnings": [f"Finviz failed: {finviz_error}"] if mode == "degraded" else [],
    }

    print(f"\n  Summary: {json.dumps(summary, indent=2)}")
    conn.close()
    return summary


if __name__ == "__main__":
    os.chdir(str(PROJECT_ROOT))
    main()
