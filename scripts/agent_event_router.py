#!/usr/bin/env python3
"""agent_event_router.py — Level 3 Phase 2: drain agent_event_queue → trigger agent analyses.

Reads pending events from agent_event_queue, creates watchlist_agent_jobs for the
appropriate agents, processes them, and sends Telegram alerts for urgent events.

For SEC_INSIDER_BUY: after agents complete, runs a 3-agent debate. If consensus ≥50%,
auto-queues the symbol for Alex retirement analysis.

Usage:
    python3 scripts/agent_event_router.py            # Drain queue + process
    python3 scripts/agent_event_router.py --dry-run   # Show what would happen
    python3 scripts/agent_event_router.py --status     # Show queue status

Cron: */15 * * * * sleep 120 && cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/agent_event_router.py >> logs/event_router.log 2>&1
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# Agent name normalization: display name → DB agent name
AGENT_DB_NAME = {
    "Maria": "maria",
    "Steph": "steph",
    "Risk": "risk_agent",
    "Tax": "tax_agent",
    "Alex": "alex",
}

BATCH_LIMIT = 20


# ── Helpers ──────────────────────────────────────────────────────────────

def _env(key: str) -> str:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return os.environ.get(key, "")
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get(key, "")


def _get_conn():
    import psycopg2
    return psycopg2.connect(
        host="localhost", dbname="trade_ai",
        user="trade_ai", password=_env("DB_PASSWORD"),
    )


def _log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _send_telegram(msg: str):
    try:
        from telegram_alert import send_telegram
        ok = send_telegram(msg)
        if ok:
            _log("  Telegram sent via alert router")
        else:
            _log("  Telegram suppressed by alert router")
    except Exception as e:
        _log(f"  Telegram failed: {e}")


def _format_trigger_summary(event: dict) -> str:
    """Build a human-readable one-line trigger summary from trigger_data."""
    td = event.get("trigger_data") or {}
    et = event.get("event_type", "")

    if et == "SEC_INSIDER_BUY":
        return f"{td.get('filer_name', '?')} ({td.get('filer_relation', '?')}) bought {td.get('shares', 0):.0f} shares @ ${td.get('price', 0):.2f}"
    elif et == "RSI_EXTREME":
        return f"RSI {td.get('rsi', '?')} ({td.get('direction', '?')}) — threshold {td.get('threshold', '?')}"
    elif et == "FRED_RATE_CHANGE":
        return f"DFF {td.get('previous_rate', '?')}% → {td.get('current_rate', '?')}% ({td.get('direction', '?')} {td.get('change_pct', '?')}%)"
    else:
        return json.dumps(td, default=str)[:120]


# ── Job Creation ─────────────────────────────────────────────────────────

def create_agent_jobs(conn, event: dict, dry_run: bool = False) -> list:
    """Create watchlist_agent_jobs for each agent in agents_to_notify. Returns job IDs."""
    symbol = event.get("symbol")
    agents = event.get("agents_to_notify") or []
    event_type = event.get("event_type", "")
    event_id = event.get("id")
    ts = datetime.now().strftime("%Y%m%d%H%M%S")

    if not symbol:
        _log(f"  Event {event_id} has no symbol — skipping agent jobs (portfolio-level event)")
        return []

    job_ids = []
    cur = conn.cursor()

    for agent_display in agents:
        agent_db = AGENT_DB_NAME.get(agent_display, agent_display.lower())
        job_id = f"event-{event_id}-{symbol.lower()}-{agent_db}-{ts}"

        if dry_run:
            _log(f"  DRY-RUN: would create job {job_id} for {agent_db}")
            job_ids.append(job_id)
            continue

        try:
            # ON CONFLICT (id) only guards a replayed job_id; repeat Level-3 events on
            # the same symbol still stacked identical pending research (2026-07-23
            # queue audit). Skip when this (symbol, agent) already has research pending.
            cur.execute("""
                INSERT INTO watchlist_agent_jobs
                    (id, symbol, requested_agent, request_type, note, status, priority, submitted_from, payload)
                SELECT %s, %s, %s, %s, %s, 'queued', %s, %s, %s
                WHERE NOT EXISTS (
                    SELECT 1 FROM watchlist_agent_jobs w
                    WHERE UPPER(w.symbol) = UPPER(%s) AND w.requested_agent = %s
                      AND w.request_type = 'research'
                      AND w.status IN ('queued', 'pending', 'processing'))
                RETURNING id
            """, (
                job_id, symbol, agent_db, "research",
                f"Level 3 event: {event_type}",
                1 if event.get("priority") == "urgent" else 5,
                "event_router",
                json.dumps({"event_id": event_id, "event_type": event_type,
                            "trigger_data": event.get("trigger_data")}, default=str),
                symbol, agent_db,
            ))
            result = cur.fetchone()
            if result:
                job_ids.append(result[0])
                _log(f"  Created job: {job_id}")
            else:
                _log(f"  Job {job_id} already exists — skipped")
        except Exception as e:
            _log(f"  ERROR creating job for {agent_db}: {e}")
            conn.rollback()

    conn.commit()
    return job_ids


# ── Job Processing ───────────────────────────────────────────────────────

def process_created_jobs(conn, job_ids: list) -> int:
    """Process the jobs we just created by calling process_watchlist_agent_jobs."""
    if not job_ids:
        return 0

    try:
        from process_watchlist_agent_jobs import process_jobs
        completed = process_jobs(limit=len(job_ids))
        _log(f"  Processed {completed} agent jobs")
        return completed
    except Exception as e:
        _log(f"  ERROR processing jobs: {e}")
        return 0


def auto_enrich_research_more(conn, symbol: str) -> bool:
    """If all recent agents returned RESEARCH_MORE, auto-enrich and re-queue."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT agent, recommendation, confidence
                   FROM watchlist_agent_results
                   WHERE symbol=%s AND created_at > NOW() - INTERVAL '2 hours'
                   ORDER BY created_at DESC""", (symbol,))
    recent = cur.fetchall()
    if len(recent) < 2:
        return False
    all_rm = all(r["recommendation"] in ("RESEARCH_MORE", "HOLD") and (r["confidence"] or 0) < 0.5 for r in recent)
    if not all_rm:
        return False

    _log(f"  All agents RESEARCH_MORE for {symbol} — auto-enriching")
    try:
        import subprocess
        subprocess.run([str(PROJECT_ROOT / ".venv/bin/python"),
                        str(PROJECT_ROOT / "scripts/phase2_ticker_enrichment.py"),
                        "--symbol", symbol], capture_output=True, timeout=60,
                       cwd=str(PROJECT_ROOT))
        _log(f"  Enrichment complete for {symbol}")
    except Exception as e:
        _log(f"  Enrichment failed for {symbol}: {e}")

    # Re-queue agent analysis with fresh data
    cur.execute("""INSERT INTO watchlist_agent_jobs
                   (symbol, requested_agent, submitted_from, status, priority)
                   VALUES (%s, 'all', 'auto_enrichment', 'queued', 1)""", (symbol,))
    conn.commit()
    _log(f"  Re-queued agent jobs for {symbol} with fresh data")
    return True


# ── CONTENT_GAP Handler: auto-trigger targeted search + ingestion ────────

def handle_content_gap(conn, event: dict):
    """When agents detect an intelligence gap for a symbol, auto-trigger:
    1. Topic ingestion with targeted search queries
    2. Sentiment scoring on new content
    3. Immediate RAG re-index so agents see it next run
    4. Re-queue agent analysis with fresh context
    """
    symbol = event.get("symbol")
    td = event.get("trigger_data") or {}
    gap_type = td.get("gap_type", "general")
    gap_detail = td.get("detail", "")

    if not symbol:
        _log("  CONTENT_GAP: no symbol — skipping")
        return

    _log(f"  CONTENT_GAP: {symbol} ({gap_type}) — triggering search + ingest loop")
    import subprocess
    venv_py = str(PROJECT_ROOT / ".venv/bin/python3")

    # Step 1: Run targeted topic ingestion (gaps-only mode to be efficient)
    ingested = 0
    try:
        result = subprocess.run(
            [venv_py, str(PROJECT_ROOT / "scripts/topic_ingestion.py"),
             "--gaps-only"],
            capture_output=True, text=True, timeout=180,
            cwd=str(PROJECT_ROOT),
        )
        _log(f"  Topic ingestion (gaps-only): exit={result.returncode}")
        if "ingested" in (result.stdout or "").lower() or "saved" in (result.stdout or "").lower():
            ingested += 1
    except subprocess.TimeoutExpired:
        _log(f"  Topic ingestion timed out (non-fatal)")
    except Exception as e:
        _log(f"  Topic ingestion failed: {e}")

    # Step 2: Try news search for this symbol
    try:
        result = subprocess.run(
            [venv_py, str(PROJECT_ROOT / "scripts/news_ingestion.py"),
             "--symbol", symbol],
            capture_output=True, text=True, timeout=90,
            cwd=str(PROJECT_ROOT),
        )
        _log(f"  News ingestion for {symbol}: exit={result.returncode}")
    except Exception as e:
        _log(f"  News ingestion for {symbol} failed: {e}")

    # Step 3: Score sentiment on any new articles
    try:
        result = subprocess.run(
            [venv_py, str(PROJECT_ROOT / "scripts/sentiment_processor.py")],
            capture_output=True, text=True, timeout=60,
            cwd=str(PROJECT_ROOT),
        )
        _log(f"  Sentiment scoring: {(result.stdout or '').strip()[:80]}")
    except Exception as e:
        _log(f"  Sentiment scoring failed: {e}")

    # Step 4: Immediate RAG re-index (last hour of content, not 8h wait)
    try:
        result = subprocess.run(
            [venv_py, str(PROJECT_ROOT / "scripts/rag_indexer.py"),
             "--source", "news,youtube_transcript,social_post",
             "--hours", "1"],
            capture_output=True, text=True, timeout=120,
            cwd=str(PROJECT_ROOT),
        )
        _log(f"  RAG re-index (1h): exit={result.returncode}")
    except Exception as e:
        _log(f"  RAG re-index failed: {e}")

    # Step 5: Re-queue agent analysis with fresh data
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    job_id = f"gap-fill-{symbol.lower()}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    try:
        cur.execute("""INSERT INTO watchlist_agent_jobs
                       (id, symbol, requested_agent, request_type, note, status, priority, submitted_from)
                       VALUES (%s, %s, 'maria', 'research', %s, 'queued', 2, 'content_gap_handler')
                       ON CONFLICT (id) DO NOTHING""",
                    (job_id, symbol, f"Re-analysis after gap fill: {gap_type} {gap_detail}"))
        conn.commit()
        _log(f"  Re-queued maria research for {symbol}")
    except Exception as e:
        _log(f"  Re-queue failed: {e}")
        conn.rollback()

    # Notify John
    _send_telegram(
        f"Intelligence Gap Filled: {symbol}\n"
        f"Gap: {gap_type}\n"
        f"Actions: topic search + news + sentiment + RAG re-index\n"
        f"Maria re-queued for fresh analysis"
    )


def handle_research_more_demand(conn, symbol: str):
    """When agents output RESEARCH_MORE, trigger targeted content search.
    This closes the loop: agent demand → new search → fresh content → re-analysis.
    """
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Check if agents recently said RESEARCH_MORE
    cur.execute("""SELECT agent, recommendation, confidence, summary
                   FROM watchlist_agent_results
                   WHERE symbol=%s AND created_at > NOW() - INTERVAL '4 hours'
                     AND recommendation = 'RESEARCH_MORE'
                   ORDER BY created_at DESC LIMIT 5""", (symbol,))
    demands = cur.fetchall()

    if not demands:
        return False

    _log(f"  RESEARCH_MORE demand from {len(demands)} agents for {symbol}")

    # Check if we already handled this recently
    cur.execute("""SELECT COUNT(*) as n FROM watchdog_actions
                   WHERE action_type='gap_fill' AND target=%s
                     AND created_at > NOW() - INTERVAL '4 hours'""", (symbol,))
    if (cur.fetchone()["n"] or 0) > 0:
        _log(f"  Already gap-filled {symbol} recently — skipping")
        return False

    # Fire a synthetic CONTENT_GAP event
    gap_reasons = "; ".join(
        f"{d['agent']}: {(d.get('summary') or '')[:60]}" for d in demands[:3]
    )
    handle_content_gap(conn, {
        "symbol": symbol,
        "event_type": "CONTENT_GAP",
        "trigger_data": {
            "gap_type": "agent_demand",
            "detail": gap_reasons,
            "demanding_agents": [d["agent"] for d in demands],
        },
    })

    # Log the action to prevent re-triggering
    try:
        cur.execute("""INSERT INTO watchdog_actions
                       (action_type, target, reason, success, result, created_at)
                       VALUES ('gap_fill', %s, %s, true, 'triggered', NOW())""",
                    (symbol, f"RESEARCH_MORE from {len(demands)} agents"))
        conn.commit()
    except Exception:
        conn.rollback()

    return True


# ── SEC Insider Buy: Debate + Alex Queue ─────────────────────────────────

def handle_sec_debate(conn, event: dict):
    """For SEC_INSIDER_BUY: run 3-agent debate, auto-queue Alex if consensus ≥50%."""
    symbol = event.get("symbol")
    if not symbol:
        return

    td = event.get("trigger_data") or {}
    trigger_title = f"SEC Insider Purchase: {td.get('filer_name', '?')} bought {td.get('shares', 0):.0f} shares of {symbol}"

    try:
        from agent_watchlist_engine import run_agent_debate
        result = run_agent_debate(symbol, trigger_title, trigger_source="sec_insider_buy")

        consensus_score = result.get("consensus_score", 0)
        consensus_rec = result.get("consensus_recommendation", "HOLD")
        _log(f"  Debate for {symbol}: {consensus_rec} at {consensus_score}% consensus")

        if consensus_score >= 50 and consensus_rec in ("BUY", "ADD", "RESEARCH_MORE"):
            # Auto-queue for Alex retirement analysis
            cur = conn.cursor()
            job_id = f"event-alex-{symbol.lower()}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            cur.execute("""
                INSERT INTO watchlist_agent_jobs
                    (id, symbol, requested_agent, request_type, note, status, priority, submitted_from)
                VALUES (%s, %s, 'alex', 'allocation', %s, 'queued', 1, 'event_router')
                ON CONFLICT (id) DO NOTHING
            """, (job_id, symbol,
                  f"Auto-queued: debate consensus {consensus_score}% ({consensus_rec}) on SEC insider buy"))
            conn.commit()
            _log(f"  Auto-queued Alex analysis for {symbol} (debate {consensus_score}% {consensus_rec})")
    except Exception as e:
        _log(f"  Debate error for {symbol}: {e}")


# ── Main Queue Drain ─────────────────────────────────────────────────────

def drain_queue(dry_run: bool = False) -> int:
    """Read pending events, create agent jobs, process them, send alerts.

    Improvement #5: After collecting the batch, checks for sector correlation.
    If 3+ events share a sector (e.g. 4 defense stops), fires a
    SECTOR_CORRELATION_ALERT before individual analyses so Maria investigates
    the macro cause first.

    Improvement #6: Market session context is injected into Telegram alerts
    so you know whether to act immediately or wait for market confirmation.
    """
    import psycopg2.extras
    from intel_query import get_market_session_context

    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT * FROM agent_event_queue
        WHERE status = 'pending'
        ORDER BY
            CASE priority WHEN 'urgent' THEN 0 ELSE 1 END,
            created_at ASC
        LIMIT %s
    """, (BATCH_LIMIT,))
    events = cur.fetchall()

    if not events:
        _log("No pending events in queue.")
        conn.close()
        return 0

    _log(f"Draining {len(events)} pending events...")

    # ── Improvement #5: Sector correlation check ─────────────────────
    # Before processing individual events, check if 3+ share a sector.
    # If yes, insert a SECTOR_CORRELATION_ALERT at the front of the queue.
    all_symbols = [e.get("symbol") for e in events if e.get("symbol")]
    if len(all_symbols) >= 3 and not dry_run:
        try:
            from agent_watchlist_engine import detect_sector_correlation, insert_sector_correlation_event
            correlation = detect_sector_correlation(all_symbols)
            if correlation:
                _log(f"  SECTOR CORRELATION DETECTED: {correlation['sector_label']} "
                     f"({correlation['count']} symbols: {', '.join(correlation['symbols'])})")
                insert_sector_correlation_event(correlation)
                # Send Telegram alert for the correlation
                session_ctx = get_market_session_context()
                tg_msg = (
                    f"🔗 SECTOR CORRELATION — {correlation['sector_label'].upper()}\n"
                    f"Symbols: {', '.join(correlation['symbols'])}\n"
                    f"Note: {correlation['note']}\n"
                    f"{session_ctx}"
                )
                _send_telegram(tg_msg)
        except Exception as e:
            _log(f"  Sector correlation check failed: {e}")

    # ── Improvement #6: Get session context once for the whole batch ──
    try:
        session_ctx = get_market_session_context()
    except Exception:
        session_ctx = ""

    processed = 0

    for event in events:
        eid = event["id"]
        etype = event["event_type"]
        symbol = event.get("symbol") or "—"
        priority = event.get("priority", "normal")
        agents = event.get("agents_to_notify") or []

        _log(f"Event #{eid}: {etype} {symbol} [{priority}] → {agents}")

        # Mark processing
        if not dry_run:
            cur2 = conn.cursor()
            cur2.execute("UPDATE agent_event_queue SET status='processing' WHERE id=%s", (eid,))
            conn.commit()

        # Send Telegram alert for urgent events — include session context (#6)
        if priority == "urgent" and not dry_run:
            trigger_summary = _format_trigger_summary(event)
            tg_msg = (
                f"🚨 {etype} — {symbol}\n"
                f"Trigger: {trigger_summary}\n"
                f"Agents notified: {', '.join(agents)}\n"
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"{session_ctx}"
            )
            _send_telegram(tg_msg)

        # Create agent jobs
        job_ids = create_agent_jobs(conn, event, dry_run)

        # Process jobs (call the actual agent functions)
        if not dry_run and job_ids:
            process_created_jobs(conn, job_ids)

        # CONTENT_GAP: auto-trigger targeted search + ingestion + RAG + re-analysis
        if etype == "CONTENT_GAP" and symbol and symbol != "—" and not dry_run:
            try:
                handle_content_gap(conn, event)
            except Exception as e:
                _log(f"  Content gap handler error for {symbol}: {e}")

        # SEC_INSIDER_BUY: run debate after agent analyses
        elif etype == "SEC_INSIDER_BUY" and symbol != "—" and not dry_run:
            handle_sec_debate(conn, event)

        # Any event + all agents RESEARCH_MORE: auto-search + enrich + re-queue
        if symbol and symbol != "\u2014" and not dry_run:
            try:
                # First try demand-driven search (RESEARCH_MORE → new content)
                if not handle_research_more_demand(conn, symbol):
                    # Fallback to ticker enrichment only
                    auto_enrich_research_more(conn, symbol)
            except Exception as e:
                _log(f"  Auto-enrich/search error for {symbol}: {e}")

        # Mark done
        if not dry_run:
            cur2 = conn.cursor()
            cur2.execute(
                "UPDATE agent_event_queue SET status='done', processed_at=NOW() WHERE id=%s",
                (eid,),
            )
            conn.commit()
            _log(f"  Event #{eid} → done")
        else:
            _log(f"  DRY-RUN: would mark #{eid} done")

        processed += 1

    conn.close()
    return processed


def show_status():
    """Show current queue status."""
    import psycopg2.extras
    conn = _get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        SELECT status, COUNT(*) as cnt
        FROM agent_event_queue
        GROUP BY status ORDER BY cnt DESC
    """)
    rows = cur.fetchall()

    _log("Queue status:")
    for r in rows:
        _log(f"  {r['status']:12} {r['cnt']}")

    cur.execute("""
        SELECT id, event_type, symbol, priority, status, created_at, processed_at
        FROM agent_event_queue
        ORDER BY created_at DESC LIMIT 10
    """)
    recent = cur.fetchall()
    if recent:
        _log("Recent events:")
        for r in recent:
            _log(f"  #{r['id']} {r['event_type']:20} {r.get('symbol') or '—':8} {r['priority']:8} {r['status']:12} {str(r['created_at'])[:19]}")

    conn.close()


# ── Entry Point ──────────────────────────────────────────────────────────

def main():
    dry_run = "--dry-run" in sys.argv
    status_only = "--status" in sys.argv

    (PROJECT_ROOT / "logs").mkdir(exist_ok=True)

    _log("=" * 60)
    _log("Agent Event Router — Level 3 Phase 2")
    _log(f"Mode: {'STATUS' if status_only else 'DRY RUN' if dry_run else 'LIVE'}")
    _log("=" * 60)

    if status_only:
        show_status()
        return

    try:
        processed = drain_queue(dry_run)
        _log(f"Processed {processed} events.")
    except Exception as e:
        _log(f"FATAL: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    _log("")


if __name__ == "__main__":
    main()
