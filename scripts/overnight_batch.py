#!/usr/bin/env python3
"""overnight_batch.py — Overnight intelligence batch processing.

Runs at 8 PM (after market close). Queues comprehensive analysis for all
portfolio symbols that haven't been analyzed in 7+ days, refreshes stale data,
and records daily performance metrics.

Usage:
    python3 scripts/overnight_batch.py [--telegram]
"""
import json, sys, uuid
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _get_conn():
    import psycopg2
    pw = ""
    for line in (PROJECT_ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def _send_tg(msg: str):
    try:
        from telegram_alert import send_telegram
        send_telegram(msg)
    except Exception:
        pass


def queue_holdings_batch():
    """Tier 1: Every night. All 3 agents. All portfolio holdings that need refresh."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get portfolio symbols from holdings.json
    holdings_file = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
    portfolio_symbols = set()
    try:
        h = json.loads(holdings_file.read_text())
        for pos in h.get("holdings", []):
            sym = pos.get("symbol", "")
            # Skip CASH and fund names with hyphens (401k fund codes)
            if sym and sym != "CASH" and "-" not in sym:
                portfolio_symbols.add(sym)
    except Exception as e:
        print(f"[overnight] Error reading holdings: {e}")
        conn.close()
        return {"tier": 1, "symbols": 0, "total_holdings": 0, "jobs_queued": 0}

    # Filter to symbols not analyzed in last 24h
    if portfolio_symbols:
        cur.execute("""
            SELECT DISTINCT symbol FROM watchlist_agent_results
            WHERE symbol = ANY(%s) AND created_at > NOW() - INTERVAL '24 hours'
        """, (list(portfolio_symbols),))
        recent = {r["symbol"] for r in cur.fetchall()}
        stale_holdings = portfolio_symbols - recent
    else:
        stale_holdings = set()

    # Queue all 3 agents for each stale holding (governed: Flash-first drain, no dupes)
    agents = ["maria", "steph", "risk_agent"]
    queued = 0
    sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))
    from agent_job_enqueue_governance import EnqueueRequest, governed_enqueue
    for symbol in sorted(stale_holdings):
        for agent in agents:
            job_id = f"t1_{symbol.lower()}_{agent}_{uuid.uuid4().hex[:6]}"
            res = governed_enqueue(cur, EnqueueRequest(
                symbol=symbol,
                requested_agent=agent,
                request_type="full_analysis",
                submitted_from="overnight_batch",
                priority=1,
                note="Tier 1: Holdings nightly refresh",
                job_id=job_id,
                universe_tier="T0",
                material=True,
            ))
            if res.action == "INSERT":
                queued += 1

    conn.commit()
    conn.close()
    print(f"[overnight] Tier 1 (holdings): {len(stale_holdings)}/{len(portfolio_symbols)} symbols stale → {queued} jobs queued")
    return {"tier": 1, "symbols": len(stale_holdings), "total_holdings": len(portfolio_symbols), "jobs_queued": queued}


def queue_screener_batch():
    """Tier 2: Mon/Wed/Fri only. Maria only. GO/WAIT screener hits."""
    import psycopg2.extras
    today = datetime.now().weekday()  # 0=Mon, 2=Wed, 4=Fri
    if today not in [0, 2, 4]:
        print(f"[overnight] Tier 2 (screener): skipping — not Mon/Wed/Fri (today={today})")
        return {"tier": 2, "symbols": 0, "jobs_queued": 0, "skipped": True}

    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get portfolio symbols to exclude
    holdings_file = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
    portfolio_symbols = set()
    try:
        h = json.loads(holdings_file.read_text())
        for pos in h.get("holdings", []):
            sym = pos.get("symbol", "")
            if sym and sym != "CASH" and "-" not in sym:
                portfolio_symbols.add(sym)
    except Exception:
        pass

    # Get active screener symbols scored GO/WAIT (>=30) in last 48h
    cur.execute("""
        SELECT DISTINCT wi.symbol
        FROM watchlist_items wi
        WHERE wi.status = 'active'
          AND wi.score >= 30
          AND wi.updated_at > NOW() - INTERVAL '48 hours'
          AND wi.symbol NOT IN (
              SELECT DISTINCT symbol FROM watchlist_agent_results
              WHERE created_at > NOW() - INTERVAL '48 hours'
          )
        ORDER BY wi.symbol
        LIMIT 40
    """)
    screener_symbols = [r["symbol"] for r in cur.fetchall()]
    # Exclude holdings (they're already in Tier 1)
    screener_symbols = [s for s in screener_symbols if s not in portfolio_symbols]

    # Queue Maria only for screener candidates
    queued = 0
    for symbol in screener_symbols:
        job_id = f"t2_{symbol.lower()}_maria_{uuid.uuid4().hex[:6]}"
        cur.execute("""
            INSERT INTO watchlist_agent_jobs (id, symbol, requested_agent, request_type, priority, note, status, submitted_from)
            VALUES (%s, %s, 'maria', 'full_analysis', 2, 'Tier 2: Screener MWF — Maria only', 'queued', 'command_center')
            ON CONFLICT DO NOTHING
        """, (job_id, symbol))
        queued += 1

    conn.commit()
    conn.close()
    print(f"[overnight] Tier 2 (screener): {len(screener_symbols)} symbols → {queued} jobs queued (Maria only, MWF)")
    return {"tier": 2, "symbols": len(screener_symbols), "jobs_queued": queued, "skipped": False}


def _queue_stale_symbols_legacy():
    """LEGACY — Queue agent jobs for symbols not analyzed in 7+ days. Replaced by tiered approach."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        WITH latest_analysis AS (
            SELECT symbol, max(created_at) as last_analyzed
            FROM watchlist_agent_results
            GROUP BY symbol
        )
        SELECT tsc.symbol, tsc.strategy_type, la.last_analyzed
        FROM ticker_strategy_classifications tsc
        LEFT JOIN latest_analysis la ON tsc.symbol = la.symbol
        WHERE tsc.active = TRUE
          AND (la.last_analyzed IS NULL OR la.last_analyzed < NOW() - INTERVAL '5 days')
        ORDER BY la.last_analyzed ASC NULLS FIRST
        LIMIT 20
    """)
    stale = cur.fetchall()

    queued = 0
    agents = ["maria", "steph", "risk_agent"]
    for row in stale:
        symbol = row["symbol"]
        for agent in agents:
            job_id = f"overnight_{symbol.lower()}_{agent}_{uuid.uuid4().hex[:6]}"
            cur.execute("""
                INSERT INTO watchlist_agent_jobs (id, symbol, requested_agent, request_type, priority, note, status)
                VALUES (%s, %s, %s, 'full_analysis', 3, 'Overnight refresh — stale analysis', 'queued')
                ON CONFLICT DO NOTHING
            """, (job_id, symbol, agent))
            queued += 1

    conn.commit()
    conn.close()
    return {"stale_symbols": len(stale), "jobs_queued": queued}


def record_daily_metrics():
    """Record daily system metrics for trending."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Portfolio value
    state_dir = PROJECT_ROOT / "data" / "portfolios" / "state"
    try:
        h = json.loads((state_dir / "holdings.json").read_text())
        portfolio_value = h.get("portfolio_totals", {}).get("total_value", 0)
    except Exception:
        portfolio_value = 0

    # Income
    try:
        div = json.loads((state_dir / "dividend_calendar.json").read_text())
        income = div.get("total_annual", 0)
    except Exception:
        income = 0

    # Agent activity today
    cur.execute("SELECT count(*) as cnt FROM watchlist_agent_results WHERE created_at > CURRENT_DATE")
    agent_jobs_today = cur.fetchone()["cnt"]

    # Alerts today
    cur.execute("SELECT count(*) as cnt FROM portfolio_intelligence_events WHERE created_at > CURRENT_DATE")
    events_today = cur.fetchone()["cnt"]

    # Decisions pending
    cur.execute("SELECT count(*) as cnt FROM cio_decisions WHERE status='proposed'")
    decisions_pending = cur.fetchone()["cnt"]

    # News ingested today
    cur.execute("SELECT count(*) as cnt FROM news_articles WHERE created_at > CURRENT_DATE")
    news_today = cur.fetchone()["cnt"]

    # Store metrics
    metrics = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "portfolio_value": portfolio_value,
        "annual_income": income,
        "income_pct_of_target": round(income / 55000 * 100, 1) if income else 0,
        "agent_jobs_today": agent_jobs_today,
        "events_today": events_today,
        "decisions_pending": decisions_pending,
        "news_today": news_today,
    }

    # Store in performance_daily table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_system_metrics (
            id SERIAL PRIMARY KEY,
            metric_date DATE NOT NULL UNIQUE,
            portfolio_value NUMERIC DEFAULT 0,
            annual_income NUMERIC DEFAULT 0,
            income_pct NUMERIC DEFAULT 0,
            agent_jobs INTEGER DEFAULT 0,
            intel_events INTEGER DEFAULT 0,
            decisions_pending INTEGER DEFAULT 0,
            news_ingested INTEGER DEFAULT 0,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    cur.execute("""
        INSERT INTO daily_system_metrics
            (metric_date, portfolio_value, annual_income, income_pct, agent_jobs, intel_events, decisions_pending, news_ingested)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (metric_date) DO UPDATE SET
            portfolio_value=EXCLUDED.portfolio_value, annual_income=EXCLUDED.annual_income,
            income_pct=EXCLUDED.income_pct, agent_jobs=EXCLUDED.agent_jobs,
            intel_events=EXCLUDED.intel_events, decisions_pending=EXCLUDED.decisions_pending,
            news_ingested=EXCLUDED.news_ingested
    """, (datetime.now().date(), portfolio_value, income, metrics["income_pct_of_target"],
          agent_jobs_today, events_today, decisions_pending, news_today))
    conn.commit()
    conn.close()
    return metrics


def record_agent_performance():
    """Record weekly agent performance metrics."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Only run on Sundays or if forced
    if datetime.now().weekday() != 6 and "--force" not in sys.argv:
        conn.close()
        return {}

    cur.execute("""
        SELECT agent,
               count(*) as total,
               avg(confidence) as avg_conf,
               count(CASE WHEN recommendation IN ('BUY','ADD') THEN 1 END) as buys,
               count(CASE WHEN recommendation IN ('SELL','TRIM') THEN 1 END) as sells,
               count(CASE WHEN recommendation = 'HOLD' THEN 1 END) as holds
        FROM watchlist_agent_results
        WHERE created_at > NOW() - INTERVAL '7 days'
        GROUP BY agent
    """)
    agents = cur.fetchall()

    for a in agents:
        cur.execute("""
            INSERT INTO agent_performance_history
                (agent, period_start, period_end, total_recommendations, avg_confidence, accuracy_pct)
            VALUES (%s, %s, %s, %s, %s, 0)
        """, (a["agent"], datetime.now() - timedelta(days=7), datetime.now(),
              a["total"], float(a["avg_conf"] or 0)))

    conn.commit()
    conn.close()
    return {"agents": len(agents)}



    # ── Sunday 9 AM — Journal annotation reminder ──────────────────────────
    if now.weekday() == 6 and now.hour == 9 and now.minute < 5:
        print("[cron] Running journal reminder...")
        send_journal_reminder()

# End of reminder

def run(send_telegram: bool = False):
    """Run the full overnight batch."""
    print(f"[overnight] {datetime.now().isoformat()} — Starting overnight batch")

    # 1. Record today's metrics
    metrics = record_daily_metrics()
    print(f"[overnight] Metrics recorded: portfolio=${metrics['portfolio_value']:,.0f}, income=${metrics['annual_income']:,.0f} ({metrics['income_pct_of_target']}%)")

    # 2. Queue agent jobs — tiered approach
    tier1 = queue_holdings_batch()
    tier2 = queue_screener_batch()
    total_queued = tier1["jobs_queued"] + tier2["jobs_queued"]
    print(f"[overnight] Tier1={tier1['jobs_queued']} (holdings/nightly) Tier2={tier2['jobs_queued']} (screener/MWF) Total={total_queued}")

    # 3. Record agent performance (weekly)
    perf = record_agent_performance()
    if perf:
        print(f"[overnight] Agent performance recorded for {perf['agents']} agents")

    # 4. Telegram summary
    if send_telegram:
        divider = "\u2501" * 24
        msg = (
            f"\U0001F319 *Overnight Batch Complete*\n"
            f"{divider}\n\n"
            f"\U0001F4CA *Daily Metrics:*\n"
            f"  Portfolio: ${metrics['portfolio_value']/1e6:.2f}M\n"
            f"  Income: ${metrics['annual_income']:,.0f}/yr ({metrics['income_pct_of_target']}% of target)\n"
            f"  Agent jobs today: {metrics['agent_jobs_today']}\n"
            f"  Intel events: {metrics['events_today']}\n"
            f"  News ingested: {metrics['news_today']}\n\n"
            f"\U0001F504 *Refresh Queue:*\n"
            f"  Tier 1 (holdings): {tier1['symbols']}/{tier1['total_holdings']} stale → {tier1['jobs_queued']} jobs\n"
            f"  Tier 2 (screener): {tier2['symbols']} symbols → {tier2['jobs_queued']} jobs {'(MWF only)' if not tier2.get('skipped') else '(skipped — not MWF)'}\n"
            f"  Total: {total_queued} jobs queued\n"
            f"  (will process over next 1-2 hours)\n\n"
            f"{divider}\n"
            f"_Next: Alex daily scan at 5:00 AM_"
        )
        _send_tg(msg)

    # 4. Write daily portfolio snapshot for performance tracking
    try:
        snap_dir = PROJECT_ROOT / "data" / "portfolios" / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        snap_file = snap_dir / f"{today}.json"
        snap_file.write_text(json.dumps({
            "date": today,
            "portfolio_value": metrics["portfolio_value"],
            "annual_income": metrics["annual_income"],
            "income_pct": metrics["income_pct_of_target"],
            "agent_jobs": metrics["agent_jobs_today"],
        }, indent=2))
        print(f"[overnight] Snapshot: {snap_file.name}")
    except Exception as e:
        print(f"[overnight] Snapshot error: {e}")

    # 5. Populate watchlist price levels from support/resistance data
    try:
        from watchlist_price_levels import populate_price_levels
        import psycopg2
        pw = ""
        for line in (PROJECT_ROOT / ".env").read_text().splitlines():
            if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
        pconn = psycopg2.connect(host='localhost', dbname='trade_ai', user='trade_ai', password=pw)
        price_count = populate_price_levels(pconn)
        pconn.close()
        print(f"[overnight] Price levels populated: {price_count} symbols")
    except Exception as e:
        print(f"[overnight] Price levels (non-fatal): {e}")

    # 6. Overnight trade review (gemma3:27b — deeper analysis of today's closed trades)
    try:
        from multi_tier_trade_reviewer import run_tier
        review_result = run_tier("overnight")
        print(f"[overnight] Trade reviews: {review_result.get('trades_reviewed', 0)} trades reviewed by gemma3:27b")
    except Exception as e:
        print(f"[overnight] Trade review (non-fatal): {e}")

    print(f"[overnight] Done")
    return {"metrics": metrics, "tier1": tier1, "tier2": tier2}


def evaluate_past_decisions() -> dict:
    """Score past decisions at 7d/30d/90d and extract top lessons for future prompts."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    updated = 0

    # Fill in 7-day prices for decisions made 7+ days ago
    cur.execute("""
        SELECT d.id, d.symbol, d.price_at_decision, d.recommendation, d.created_at
        FROM decision_outcomes d
        WHERE d.price_7d IS NULL AND d.created_at < NOW() - INTERVAL '7 days'
        LIMIT 50
    """)
    for row in cur.fetchall():
        try:
            cur2 = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur2.execute("SELECT price FROM market_quotes WHERE symbol=%s ORDER BY fetched_at DESC LIMIT 1", (row["symbol"],))
            q = cur2.fetchone()
            if q:
                price_now = float(q["price"])
                p0 = float(row["price_at_decision"] or 0)
                if p0 > 0:
                    chg = ((price_now / p0) - 1) * 100
                    rec = row["recommendation"] or ""
                    correct = (rec in ("BUY", "ADD") and chg > 0) or (rec in ("SELL", "TRIM") and chg < 0) or (rec in ("HOLD",) and abs(chg) < 10)
                    score = 1.0 if correct else -0.5 if abs(chg) > 5 else 0
                    cur2.execute("""UPDATE decision_outcomes SET price_7d=%s, outcome_score=%s, evaluated_at=NOW()
                        WHERE id=%s""", (price_now, score, row["id"]))
                    updated += 1
        except Exception:
            pass

    conn.commit()

    # Extract top 3 lessons from recent outcomes
    cur.execute("""
        SELECT symbol, recommendation, price_at_decision, price_7d, outcome_score,
               created_at, evaluated_at
        FROM decision_outcomes
        WHERE outcome_score IS NOT NULL AND evaluated_at > NOW() - INTERVAL '30 days'
        ORDER BY ABS(outcome_score) DESC LIMIT 5
    """)
    lessons = []
    for r in cur.fetchall():
        p0 = float(r.get("price_at_decision") or 0)
        p7 = float(r.get("price_7d") or 0)
        chg = ((p7 / p0) - 1) * 100 if p0 > 0 and p7 > 0 else 0
        label = "CORRECT" if r["outcome_score"] > 0 else "WRONG"
        lessons.append(f"{r['symbol']}: {r['recommendation']} at ${p0:.2f} → ${p7:.2f} ({chg:+.1f}%) [{label}]")

    # Store lessons in agent_intelligence_rules for prompt injection
    if lessons:
        lesson_text = "\n".join(lessons[:7])
        ucur = conn.cursor()
        ucur.execute("""INSERT INTO agent_intelligence_rules (rule_type, rule_key, config, changed_by, updated_at)
            VALUES ('outcome_lessons', 'latest', %s, 'outcome_eval', NOW())
            ON CONFLICT (rule_type, rule_key) DO UPDATE SET config=EXCLUDED.config, updated_at=NOW()""",
            (json.dumps({"lessons": lessons[:7], "text": lesson_text, "evaluated_at": datetime.now().isoformat()}),))
        conn.commit()

    conn.close()
    print(f"[outcomes] Updated {updated} decisions, {len(lessons)} lessons extracted")
    return {"updated": updated, "lessons": lessons}


def proactive_intel_scan() -> dict:
    """Scan qualified_intelligence for high-conf items with ticker-level throttling.

    Ticker throttle gate (v2.49):
      - Only run full agent chain if:
        1. New qualified_intelligence Q≥70 for this ticker in last 24h
        2. User ran `research SYMBOL` (requested_by='telegram')
        3. Ticker is in portfolio AND last_analyzed > 48h ago
      - All others: skip, log reason, use cached embeddings
    """
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Find recent high-quality qualified intel not yet acted on
    cur.execute("""
        SELECT qi.symbol, qi.title, qi.quality_score, qi.source_type, qi.retirement_relevance, qi.id
        FROM qualified_intelligence qi
        WHERE qi.quality_score >= 70
          AND qi.discovered_at > NOW() - INTERVAL '24 hours'
          AND qi.symbol IS NOT NULL
          AND qi.symbol NOT IN (SELECT symbol FROM watchlist_agent_jobs WHERE created_at > NOW() - INTERVAL '24 hours')
        ORDER BY qi.quality_score DESC LIMIT 10
    """)
    hot_items = cur.fetchall()

    # Load portfolio symbols for priority check
    portfolio_syms = set()
    try:
        h = json.loads((PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text())
        portfolio_syms = {p.get("symbol", "") for p in h.get("holdings", []) if p.get("symbol")}
    except Exception:
        pass

    queued = 0
    debated = 0
    skipped = 0

    for item in hot_items:
        sym = item["symbol"]

        # Ticker-level throttle gate
        should_analyze = False
        throttle_reason = ""

        # Gate 1: New high-Q intel in last 24h (already filtered by query, but check Q≥70)
        if item["quality_score"] >= 70:
            should_analyze = True
            throttle_reason = f"new_intel Q:{item['quality_score']}"

        # Gate 2: Portfolio symbol not analyzed in 48h
        if sym in portfolio_syms:
            cur.execute("SELECT MAX(created_at) FROM watchlist_agent_results WHERE symbol=%s", (sym,))
            last = cur.fetchone()
            last_dt = last[0] if last and last[0] else None
            if last_dt:
                from datetime import timezone
                age_h = (datetime.now(timezone.utc) - last_dt.astimezone(timezone.utc)).total_seconds() / 3600
                if age_h > 48:
                    should_analyze = True
                    throttle_reason = f"portfolio_stale ({int(age_h)}h > 48h)"
                elif not should_analyze:
                    should_analyze = False
                    throttle_reason = f"portfolio_fresh ({int(age_h)}h < 48h)"
            else:
                should_analyze = True
                throttle_reason = "portfolio_never_analyzed"

        if not should_analyze:
            skipped += 1
            print(f"  [throttle] Skipped {sym}: {throttle_reason}")
            continue

        # Run multi-agent debate before queuing
        try:
            from agent_watchlist_engine import run_agent_debate
            debate = run_agent_debate(sym, item["title"][:100], trigger_source=item["source_type"])
            if debate.get("confidence", 0) >= 0.5:
                debated += 1
            else:
                print(f"  [throttle] {sym}: debate consensus too low ({debate.get('confidence',0):.0%}), skipping")
                skipped += 1
                continue
        except Exception as e:
            print(f"  [proactive] {sym}: debate error ({e}), queuing anyway")

        try:
            ucur = conn.cursor()
            ucur.execute("""INSERT INTO watchlist_agent_jobs
                (symbol, agent, request_type, status, requested_by, priority, note)
                VALUES (%s, 'full_chain', 'analysis', 'queued', 'proactive_scan', 'high', %s)""",
                (sym, f"Auto: Q:{item['quality_score']} {item['source_type']} — {throttle_reason} — {item['title'][:80]}"))
            queued += 1
            print(f"  [proactive] Queued {sym} (Q:{item['quality_score']}, {throttle_reason}) after debate")
        except Exception:
            pass

    conn.commit()

    # Retry failed event-triggered jobs from the last 24h
    retried = 0
    try:
        cur.execute("""
            UPDATE watchlist_agent_jobs
            SET status = 'queued', started_at = NULL, completed_at = NULL
            WHERE status = 'failed'
              AND submitted_from = 'event_router'
              AND created_at > NOW() - INTERVAL '24 hours'
            RETURNING id, symbol, requested_agent
        """)
        retry_rows = cur.fetchall()
        retried = len(retry_rows)
        if retried > 0:
            conn.commit()
            for r in retry_rows:
                print(f"  [proactive] Retried event job: {r['symbol']} → {r['requested_agent']}")
            print(f"  [proactive] Re-queued {retried} failed event-triggered jobs from last 24h")
    except Exception as e:
        print(f"  [proactive] Event retry error: {e}")
        conn.rollback()

    conn.close()
    print(f"[proactive] Scanned {len(hot_items)}, debated {debated}, queued {queued}, throttled {skipped}, event-retries {retried}")
    return {"scanned": len(hot_items), "debated": debated, "queued": queued, "throttled": skipped, "event_retries": retried}


def refresh_research_topics() -> dict:
    """Weekly re-analysis of persistent research topics with new embeddings + FRED + lessons."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""SELECT id, topic, latest_findings, research_count
        FROM user_research_topics
        WHERE status='active' AND (last_researched_at IS NULL OR last_researched_at < NOW() - INTERVAL '7 days')
        ORDER BY priority DESC, updated_at DESC LIMIT 5""")
    topics = cur.fetchall()
    refreshed = 0

    for t in topics:
        topic = t["topic"]
        try:
            # Get fresh context
            extra = ""
            try:
                from external_market_data_ingest import get_macro_context
                mc = get_macro_context()
                if mc: extra += mc + "\n"
            except Exception:
                pass
            try:
                from intel_query import get_intel_summary
                intel = get_intel_summary(agent="Alex", max_chars=400)
                if intel: extra += intel[:400] + "\n"
            except Exception:
                pass

            from llm_router import get_llm_response
            prompt = (f"/no_think Re-analyze this research topic with latest data:\n\nTOPIC: {topic}\n\n"
                      f"PREVIOUS FINDINGS: {(t.get('latest_findings') or 'None')[:300]}\n\n"
                      f"LATEST CONTEXT:\n{extra}\n\n"
                      f"Provide updated analysis (under 200 words). What's new? Any actionable changes?")
            result = get_llm_response("agent_narrative", prompt, max_tokens=400)
            if result.get("success"):
                ucur = conn.cursor()
                ucur.execute("""UPDATE user_research_topics
                    SET latest_findings=%s, latest_finding_at=NOW(), research_count=research_count+1, last_researched_at=NOW()
                    WHERE id=%s""", (result["response"][:2000], t["id"]))
                refreshed += 1
                print(f"  [research] Refreshed: {topic[:40]} via {result.get('provider')}")
        except Exception as e:
            print(f"  [research] Error on '{topic[:30]}': {e}")

    conn.commit()
    conn.close()
    print(f"[research] Refreshed {refreshed}/{len(topics)} topics")
    return {"refreshed": refreshed, "total": len(topics)}



def send_journal_reminder():
    """Weekly reminder: unannotated trade count via Telegram."""
    try:
        import psycopg2, os
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(
            host=os.getenv('DB_HOST','localhost'), port=int(os.getenv('DB_PORT',5432)),
            dbname=os.getenv('DB_NAME','trade_ai'), user=os.getenv('DB_USER',''),
            password=os.getenv('DB_PASSWORD','')
        )
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*) FROM trade_closed t
            LEFT JOIN journal_trade_reviews r ON r.trade_key = t.trade_key
            WHERE r.id IS NULL
        """)
        unannotated = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM trade_closed")
        total = cur.fetchone()[0]
        conn.close()

        if unannotated > 0:
            pct = round((total - unannotated) / total * 100, 1) if total else 0
            msg = (
                f"📓 *Weekly Journal Reminder*\n\n"
                f"*{unannotated} trades* still need annotation ({total} total).\n"
                f"Coverage: {pct}% complete\n\n"
                f"Unannotated trades have no setup type, entry reason, or lessons.\n"
                f"👉 https://ms01-openclaw.tail163d14.ts.net/v3/journal"
            )
            _send_tg(msg)
            try:
                from lib.comms import CommunicationEvent, publish_communication
                publish_communication(CommunicationEvent(
                    direction="OUTBOUND", event_type="alert", message_class="ops",
                    producer="overnight_batch", subject_key="ops:journal_reminder",
                    retention_class="operational", severity="info",
                    sanitized_body=msg[:500], short_summary=msg[:120],
                ))
            except Exception:
                # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
                pass
            print(f"[journal_reminder] Sent: {unannotated} unannotated trades")
        else:
            print("[journal_reminder] All trades annotated — no reminder sent")
    except Exception as e:
        print(f"[journal_reminder] Error: {e}")


def run_tax_sweep():
    """Queue tax_agent for holdings with loss > $500 + SSDI-impacted proposals."""
    conn = _get_conn()
    cur = conn.cursor()
    jobs_queued = 0

    # 1. Holdings with unrealized loss > $500 not analyzed by tax_agent in 24h
    holdings_file = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
    if holdings_file.exists():
        data = json.loads(holdings_file.read_text())
        loss_symbols = [
            h["symbol"] for h in data.get("holdings", [])
            if h.get("gain_loss") is not None and h["gain_loss"] < -500 and h.get("symbol")
        ]
        if loss_symbols:
            # Exclude symbols already analyzed by tax_agent in last 24h
            cur.execute("""SELECT DISTINCT symbol FROM watchlist_agent_results
                          WHERE agent = 'tax_agent' AND created_at > NOW() - INTERVAL '24 hours'""")
            recent = {r[0] for r in cur.fetchall()}
            for sym in loss_symbols[:10]:
                if sym not in recent:
                    cur.execute("""INSERT INTO watchlist_agent_jobs
                        (id, symbol, requested_agent, request_type, note, status, priority, submitted_from, created_at)
                        VALUES (%s, %s, 'tax_agent', 'full_analysis', 'tax harvest review — loss > $500', 'pending', 1, 'tax_sweep', NOW())
                    """, (str(uuid.uuid4()), sym))
                    jobs_queued += 1

    # 2. Proposals with SSDI impact not yet reviewed by tax_agent
    cur.execute("""SELECT id, symbol FROM watchlist_proposals
                   WHERE ssdi_impact IS NOT NULL AND ssdi_impact != 'none' AND status = 'proposed' LIMIT 5""")
    ssdi_proposals = cur.fetchall()
    for pid, sym in ssdi_proposals:
        cur.execute("""INSERT INTO watchlist_agent_jobs
            (id, symbol, requested_agent, request_type, note, status, priority, submitted_from, created_at)
            VALUES (%s, %s, 'tax_agent', 'full_analysis', %s, 'pending', 1, 'tax_sweep', NOW())
            ON CONFLICT DO NOTHING
        """, (str(uuid.uuid4()), sym, f"SSDI-impacted proposal #{pid}"))
        jobs_queued += 1

    conn.commit()
    cur.close()
    conn.close()
    print(f"[tax-sweep] Queued {jobs_queued} jobs for tax_agent")
    return jobs_queued


if __name__ == "__main__":
    tg = "--telegram" in sys.argv

    # Determine mode for pipeline registry
    if "--outcomes" in sys.argv:
        _mode = 'overnight_batch_outcomes'
    elif "--proactive" in sys.argv:
        _mode = 'overnight_batch_proactive'
    elif "--research" in sys.argv:
        _mode = 'overnight_batch_research'
    elif "--index-embeddings" in sys.argv:
        _mode = 'overnight_batch_embeddings'
    elif "--tax-sweep" in sys.argv:
        _mode = 'overnight_batch_tax'
    else:
        _mode = 'overnight_batch'

    _run_id = None
    try:
        from pipeline_registry import run_start, run_complete, run_fail
        _run_id = run_start(_mode)
    except Exception:
        pass

    try:
        if "--outcomes" in sys.argv:
            _result = evaluate_past_decisions()
            _count = _result.get('scored', 0) if isinstance(_result, dict) else 0
        elif "--proactive" in sys.argv:
            _result = proactive_intel_scan()
            _count = _result.get('queued', 0) if isinstance(_result, dict) else 0
        elif "--research" in sys.argv:
            _result = refresh_research_topics()
            _count = _result.get('refreshed', 0) if isinstance(_result, dict) else 0
        elif "--index-embeddings" in sys.argv:
            sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
            from content_scoring import batch_index_all
            batch_index_all(batch_size=100)
            _count = 0
        elif "--tax-sweep" in sys.argv:
            run_tax_sweep()
            _count = 0
        else:
            run(send_telegram=tg)
            _count = 0

        try:
            if _run_id: run_complete(_run_id, rows_processed=_count)
        except Exception:
            pass
    except Exception as _e:
        try:
            if _run_id: run_fail(_run_id, str(_e))
        except Exception:
            pass
        raise
