#!/usr/bin/env python3
"""signal_fusion.py — Fuse catalyst, news, social, sentiment into unified signal scores.

Strategy-aware weighting. Classification-first.

Usage:
    python3 scripts/signal_fusion.py --full [--json] [--dry-run]
    python3 scripts/signal_fusion.py --active [--json] [--dry-run]
    python3 scripts/signal_fusion.py --symbol SCHD [--json] [--dry-run]

Refactor wave 2 (cron -> n8n, 2026-10-10; cron:L409 --full, cron:L411 --active):
- The connection comes from db_adapter (the shared credential loader), not an inline parse of
  PROJECT_ROOT/.env for DB_PASSWORD. The old reader opened a fresh connection per symbol with a
  password read from the release .env; logs/signal_fusion.log carries 66 intermittent
  "password authentication failed" tracebacks. One connection per run, commit per symbol as before.
- ``--dry-run`` computes every fused score on a READ ONLY session through ``compute_fused`` (SELECTs
  only) and returns before ``_persist`` (the two INSERTs) is reachable; it reports the rows it would
  have written. No receipt.
- A real --full / --active run writes data/runtime/signal_fusion_{full,active}_last.json
  (LaneRunReceipt@v1, ok_at only on success) and exits 1 when the symbol query fails, or when the
  per-symbol error rate exceeds ERROR_RATE_FAIL (a run that fused nothing did no work).
"""
import json, os, sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

ERROR_RATE_FAIL = 0.05  # more than 5% of symbols failing = the run failed (one transient miss is not)

# Strategy-aware fusion weights
_STRATEGY_FUSION = {
    "dividend_growth_compounder": {"catalyst": 0.40, "news": 0.35, "social": 0.10, "sentiment": 0.15},
    "covered_call_income":        {"catalyst": 0.35, "news": 0.35, "social": 0.10, "sentiment": 0.20},
    "high_yield_income_bdc":      {"catalyst": 0.40, "news": 0.30, "social": 0.10, "sentiment": 0.20},
    "bond_income":                {"catalyst": 0.30, "news": 0.40, "social": 0.05, "sentiment": 0.25},
    "core_growth_compounder":     {"catalyst": 0.35, "news": 0.30, "social": 0.15, "sentiment": 0.20},
    "defense_thesis":             {"catalyst": 0.45, "news": 0.35, "social": 0.05, "sentiment": 0.15},
    "speculative_growth":         {"catalyst": 0.30, "news": 0.20, "social": 0.30, "sentiment": 0.20},
    "swing_trade":                {"catalyst": 0.25, "news": 0.20, "social": 0.30, "sentiment": 0.25},
}
_DEFAULT_WEIGHTS = {"catalyst": 0.35, "news": 0.30, "social": 0.20, "sentiment": 0.15}


def _get_conn():
    # Shared loader (env_bootstrap / .env, connect_timeout, lock/statement timeouts) -- no inline password.
    from db_adapter import _get_conn as _adapter_conn

    return _adapter_conn()


def _dict_cursor(conn):
    import psycopg2.extras

    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def fuse_signals(symbol: str, window_hours: int = 24, *, conn=None, dry_run: bool = False) -> dict:
    """Compute fused signal for a symbol; persist it unless ``dry_run``.

    ``conn`` lets a batch reuse one connection (the caller owns it). Standalone calls open and close
    their own, as before. A dry run never calls ``_persist``.
    """
    own = conn is None
    if own:
        conn = _get_conn()
        if dry_run:
            from lib.lane_last_receipt import enforce_readonly

            enforce_readonly(conn)
    try:
        cur = _dict_cursor(conn)
        result, catalysts = compute_fused(cur, symbol, window_hours)
        if dry_run:
            conn.rollback()
            return result
        _persist(cur, result, catalysts)
        conn.commit()
        return result
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        if own:
            conn.close()


def compute_fused(cur, symbol: str, window_hours: int = 24):
    """READ ONLY: every statement here is a SELECT. Returns (result, catalysts)."""
    sym = symbol.upper()
    cutoff = datetime.now() - timedelta(hours=window_hours)

    # Classification
    cur.execute("SELECT strategy_type FROM ticker_strategy_classifications WHERE symbol=%s AND active=TRUE", (sym,))
    cls = cur.fetchone()
    strategy_type = cls["strategy_type"] if cls else None
    weights = _STRATEGY_FUSION.get(strategy_type, _DEFAULT_WEIGHTS)

    # Recent catalysts
    cur.execute("SELECT catalyst_type, confidence, impact_score, severity FROM catalyst_events WHERE symbol=%s AND created_at > %s ORDER BY created_at DESC LIMIT 5", (sym, cutoff))
    catalysts = cur.fetchall()
    catalyst_score = 0
    if catalysts:
        scores = [float(c.get("confidence", 0.5) or 0.5) * float(c.get("impact_score", 0.5) or 0.5) for c in catalysts]
        catalyst_score = min(1.0, sum(scores) / len(scores))

    # Recent news
    cur.execute("SELECT relevance_score, sentiment_score FROM news_articles WHERE symbol=%s AND created_at > %s ORDER BY created_at DESC LIMIT 10", (sym, cutoff))
    news = cur.fetchall()
    news_score = 0
    if news:
        scores = [float(n.get("relevance_score", 0.5) or 0.5) for n in news]
        news_score = min(1.0, sum(scores) / len(scores))

    # Recent social (may be empty if no social monitoring)
    cur.execute("SELECT sentiment_score, engagement_score FROM social_mentions WHERE symbol=%s AND created_at > %s ORDER BY created_at DESC LIMIT 10", (sym, cutoff))
    social = cur.fetchall()
    social_score = 0
    if social:
        scores = [float(s.get("engagement_score", 0.5) or 0.5) for s in social]
        social_score = min(1.0, sum(scores) / len(scores))

    # Sentiment lane (2026-06-04): repointed from catalyst_sentiment_analysis (NO producer — always
    # empty, so sentiment_score was stuck at the 0.5 default) to sentiment_observations, which carries
    # the same overall_sentiment/confidence columns and now flows again (news_ingestion + sentiment_processor).
    cur.execute("SELECT overall_sentiment, confidence FROM sentiment_observations WHERE symbol=%s AND created_at > %s ORDER BY created_at DESC LIMIT 3", (sym, cutoff))
    sentiments = cur.fetchall()
    sentiment_score = 0.5  # neutral default
    if sentiments:
        # Map sentiment to score
        sent_map = {"very_positive": 0.9, "positive": 0.7, "neutral": 0.5, "negative": 0.3, "very_negative": 0.1}
        scores = [sent_map.get(s.get("overall_sentiment", "neutral"), 0.5) for s in sentiments]
        sentiment_score = sum(scores) / len(scores)

    # Research insights (structured thesis data)
    cur.execute("""
        SELECT thesis_type, confidence, time_horizon, structured_thesis, id
        FROM research_insights WHERE symbol=%s AND created_at > %s AND active=TRUE
        ORDER BY created_at DESC LIMIT 5
    """, (sym, cutoff))
    research = cur.fetchall()
    research_score = 0
    research_insight_ids = []
    if research:
        # Score: bullish insights increase, bearish decrease, confidence-weighted
        thesis_map = {"bullish": 0.8, "neutral": 0.5, "bearish": 0.2, "mixed": 0.4}
        r_scores = [thesis_map.get(r.get("thesis_type", "neutral"), 0.5) * float(r.get("confidence", 0.5) or 0.5) for r in research]
        research_score = min(1.0, sum(r_scores) / len(r_scores))
        research_insight_ids = [r["id"] for r in research if r.get("id")]

    # Multi-source confirmation: research + news/catalyst alignment boosts confidence
    confirmation_bonus = 0
    if research_score > 0.5 and (catalyst_score > 0.5 or news_score > 0.5):
        confirmation_bonus = 0.05  # Small boost for multi-source alignment
    elif research_score < 0.3 and (catalyst_score > 0.5 or news_score > 0.5):
        confirmation_bonus = -0.03  # Research contradicts other sources

    # Fuse with research (reweight: research gets ~10% from social which is often empty)
    r_weight = min(0.15, weights.get("social", 0.20))  # Take from social weight
    s_weight = max(0.05, weights.get("social", 0.20) - r_weight)
    fused = (
        weights["catalyst"] * catalyst_score +
        weights["news"] * news_score +
        s_weight * social_score +
        weights["sentiment"] * sentiment_score +
        r_weight * research_score +
        confirmation_bonus
    )
    fused = round(max(0, min(1.0, fused)), 3)

    # Signal decay: reduce score for older signals
    # (cutoff already handles window, but we could age-weight within window)

    # Contradiction detection
    contradictions = []
    if news_score > 0.6 and social_score < 0.3:
        contradictions.append("positive_news_negative_social")
    if social_score > 0.7 and news_score < 0.3:
        contradictions.append("high_social_no_news_retail_risk")
    if catalyst_score > 0.7 and sentiment_score < 0.3:
        contradictions.append("strong_catalyst_negative_sentiment")
    if research_score > 0.6 and catalyst_score < 0.3:
        contradictions.append("positive_research_no_catalyst")
    if research_score < 0.3 and catalyst_score > 0.6:
        contradictions.append("negative_research_positive_catalyst")

    # Severity
    severity = "low"
    if fused > 0.7: severity = "high"
    elif fused > 0.5: severity = "medium"
    if any(c.get("severity") == "critical" for c in catalysts): severity = "critical"

    result = {
        "symbol": sym,
        "strategy_type": strategy_type,
        "fused_score": fused,
        "catalyst_score": catalyst_score,
        "news_score": news_score,
        "social_score": social_score,
        "sentiment_score": sentiment_score,
        "severity": severity,
        "contradictions": contradictions,
        "human_review": len(contradictions) > 0,
        "research_score": research_score,
        "research_insight_ids": research_insight_ids,
        "confirmation_bonus": confirmation_bonus,
        "input_counts": {"catalysts": len(catalysts), "news": len(news), "social": len(social), "sentiments": len(sentiments), "research": len(research)},
    }
    return result, catalysts


def _persist(cur, result: dict, catalysts) -> None:
    """The ONLY writes: one fused_signals row, plus an intelligence event for high/critical."""
    sym = result["symbol"]
    strategy_type = result["strategy_type"]
    fused = result["fused_score"]
    catalyst_score = result["catalyst_score"]
    news_score = result["news_score"]
    social_score = result["social_score"]
    sentiment_score = result["sentiment_score"]
    research_score = result["research_score"]
    research_insight_ids = result["research_insight_ids"]
    severity = result["severity"]
    contradictions = result["contradictions"]
    cur.execute("""
        INSERT INTO fused_signals (symbol, strategy_type, fused_score, catalyst_score, news_score,
                                   social_score, sentiment_score, research_score, research_insight_ids,
                                   severity, confidence, contradictions, reason_codes, human_review)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (sym, strategy_type, fused, catalyst_score, news_score, social_score, sentiment_score,
          research_score, research_insight_ids if research_insight_ids else None,
          severity, fused,
          json.dumps(contradictions), [], len(contradictions) > 0))

    # Intelligence event for high-severity signals
    if severity in ("high", "critical"):
        cur.execute("""
            INSERT INTO portfolio_intelligence_events (symbol, strategy_type, event_type, severity, source, payload)
            VALUES (%s, %s, 'fused_signal', %s, 'signal_fusion.py', %s)
        """, (sym, strategy_type, severity,
              json.dumps({"fused_score": fused, "catalyst_score": catalyst_score,
                          "news_score": news_score, "contradictions": contradictions}, default=str)))


_FULL_SQL = "SELECT symbol FROM ticker_strategy_classifications WHERE active=TRUE"
_PRIORITY_SQL = ("SELECT symbol FROM ticker_strategy_classifications WHERE active=TRUE AND symbol IN "
                 "(SELECT DISTINCT symbol FROM watchlist_items WHERE source='portfolio' AND status<>'removed')")
_ACTIVE_SQL = """
        SELECT DISTINCT symbol FROM (
            SELECT symbol FROM trade_ai_scans WHERE run_date >= CURRENT_DATE AND decision IN ('GO','WAIT')
            UNION SELECT symbol FROM paper_trade_proposals WHERE status IN ('PENDING','APPROVED')
            UNION SELECT symbol FROM paper_trades WHERE lower(status) = 'open'
            UNION SELECT symbol FROM watchlist_items WHERE status = 'active'
        ) u WHERE symbol IS NOT NULL
    """


def _fuse_set(sql: str, *, dry_run: bool = False, stats: dict | None = None) -> list:
    """Fuse every symbol ``sql`` returns on ONE connection. ``stats`` (if given) gets attempted/errors."""
    conn = _get_conn()
    if dry_run:
        from lib.lane_last_receipt import enforce_readonly

        enforce_readonly(conn)  # the server refuses any write, whatever is reached (AGENTS.md §6)
    try:
        cur = _dict_cursor(conn)
        cur.execute(sql)
        symbols = [r["symbol"] for r in cur.fetchall()]
        conn.rollback()  # end the read transaction (db_adapter connections are not autocommit)
        results, errors = [], 0
        for sym in symbols:
            try:
                results.append(fuse_signals(sym, conn=conn, dry_run=dry_run))
            except Exception as e:
                errors += 1
                print(f"  [fusion] {sym}: error — {e}")
                if getattr(conn, "closed", 0):  # lost connection: reopen (the old code connected per symbol)
                    conn = _get_conn()
                    if dry_run:
                        from lib.lane_last_receipt import enforce_readonly

                        enforce_readonly(conn)
        if stats is not None:
            stats.update(attempted=len(symbols), errors=errors)
        return results
    finally:
        try:
            conn.close()
        except Exception:
            pass


def fuse_all(priority_only: bool = False, *, dry_run: bool = False, stats: dict | None = None) -> list:
    return _fuse_set(_PRIORITY_SQL if priority_only else _FULL_SQL, dry_run=dry_run, stats=stats)


def fuse_active(*, dry_run: bool = False, stats: dict | None = None) -> list:
    """Intraday cadence (audit gate): fuse only the active DECISION set — today's GO/WAIT scalp candidates,
    open proposals, open paper trades, and active watchlist — so those names have fresh fusion before
    proposal/alert decisions, without re-fusing the full ~2700-symbol universe. Fast (~tens of symbols).
    (Reads paper_trades / paper_trade_proposals as a symbol list only; writes nothing there.)"""
    return _fuse_set(_ACTIVE_SQL, dry_run=dry_run, stats=stats)


def _batch(mode: str, argv: list) -> int:
    """--full / --active. Dry run: report, no receipt. Real run: receipt + honest exit code."""
    dry = "--dry-run" in argv
    as_json = "--json" in argv
    fn = fuse_all if mode == "full" else fuse_active
    stats: dict = {}
    if dry:
        results = fn(dry_run=True, stats=stats)
        high = [r["symbol"] for r in results if r["severity"] in ("high", "critical")]
        print(json.dumps({
            "mode": "dry_run", "set": mode, "symbols": stats.get("attempted", 0), "computed": len(results),
            "errors": stats.get("errors", 0),
            "would_write": {"fused_signals": len(results), "portfolio_intelligence_events": len(high)},
            "high_or_critical": high[:50],
        }, indent=2, default=str))
        if as_json:
            print(json.dumps(results, indent=2, default=str))
        return 0

    from lib.lane_last_receipt import now_iso, write_receipt

    name = f"signal_fusion_{mode}"
    started_at = now_iso()
    try:
        results = fn(stats=stats)
    except Exception as exc:
        write_receipt(name, ok=False, started_at=started_at, error=f"{type(exc).__name__}: {exc}")
        raise
    label = "active-set symbols (intraday cadence)" if mode == "active" else "symbols"
    print(f"[fusion] Fused {len(results)} {label}")
    high = [r for r in results if r["severity"] in ("high", "critical")]
    if high:
        print(f"  High/critical signals: {[r['symbol'] for r in high]}")
    if as_json:
        print(json.dumps(results, indent=2, default=str))
    attempted, errors = stats.get("attempted", 0), stats.get("errors", 0)
    # An empty set is a finding (nothing to fuse), not a failure; a run whose symbols mostly errored is.
    ok = errors == 0 or (len(results) > 0 and errors / max(attempted, 1) <= ERROR_RATE_FAIL)
    write_receipt(name, ok=ok, started_at=started_at,
                  summary={"symbols": attempted, "fused": len(results), "errors": errors,
                           "high_or_critical": len(high)},
                  error=None if ok else f"{errors}/{attempted} symbols failed")
    if not ok:
        print(f"[fusion] FAILED: {errors}/{attempted} symbols errored", file=sys.stderr)
    return 0 if ok else 1


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--symbol" in argv:
        sym = argv[argv.index("--symbol") + 1].upper()
        r = fuse_signals(sym, dry_run="--dry-run" in argv)
        if "--json" in argv:
            print(json.dumps(r, indent=2, default=str))
        else:
            tag = " (dry-run: not written)" if "--dry-run" in argv else ""
            print(f"  {r['symbol']}: fused={r['fused_score']:.3f} cat={r['catalyst_score']:.2f} news={r['news_score']:.2f} social={r['social_score']:.2f} sent={r['sentiment_score']:.2f} [{r['severity']}]{tag}")
        return 0
    if "--active" in argv:
        return _batch("active", argv)
    if "--full" in argv:
        return _batch("full", argv)
    print("Usage: --symbol SCHD [--json] [--dry-run] | --active [--json] [--dry-run] | --full [--json] [--dry-run]")
    return 2


if __name__ == "__main__":
    sys.exit(main())
