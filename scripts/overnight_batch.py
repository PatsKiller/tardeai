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


def queue_stale_symbols():
    """Queue agent jobs for symbols not analyzed in 7+ days."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Find portfolio symbols with stale or missing analysis (7+ days old)
    # Queue up to 20 per night — overnight processor handles 25/5min = 300/hour
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


def run(send_telegram: bool = False):
    """Run the full overnight batch."""
    print(f"[overnight] {datetime.now().isoformat()} — Starting overnight batch")

    # 1. Record today's metrics
    metrics = record_daily_metrics()
    print(f"[overnight] Metrics recorded: portfolio=${metrics['portfolio_value']:,.0f}, income=${metrics['annual_income']:,.0f} ({metrics['income_pct_of_target']}%)")

    # 2. Queue stale symbols for refresh
    stale = queue_stale_symbols()
    print(f"[overnight] Queued {stale['jobs_queued']} jobs for {stale['stale_symbols']} stale symbols")

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
            f"  {stale['stale_symbols']} stale symbols re-queued\n"
            f"  {stale['jobs_queued']} agent jobs created\n"
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

    print(f"[overnight] Done")
    return {"metrics": metrics, "stale": stale}


if __name__ == "__main__":
    tg = "--telegram" in sys.argv
    run(send_telegram=tg)
