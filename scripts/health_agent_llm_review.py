#!/usr/bin/env python3
"""health_agent_llm_review.py — Nightly LLM-enhanced health review.

Uses local qwen3:14b to analyze the day's health events, errors, and
patterns. Produces an intelligence summary with recommendations.
Stores in llm_intelligence_cache for Command Center display.

This gives the health agent a "brain" — pattern recognition across
errors, trend detection, and proactive recommendations that pure
threshold checks can't provide.

Usage:
    .venv/bin/python scripts/health_agent_llm_review.py
    .venv/bin/python scripts/health_agent_llm_review.py --dry-run

--dry-run runs the same SELECTs on a READ ONLY session, builds the prompt and returns BEFORE the
local-LLM call and both INSERTs are reachable (AGENTS.md §6). A real run writes
data/runtime/health_agent_llm_review_last.json (LaneRunReceipt@v1; ok_at only when the review was
stored) under the persistent state root and exits 1 when no review was stored.
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [health-llm] %(message)s")
log = logging.getLogger("health-llm")
RECEIPT_NAME = "health_agent_llm_review"


def _get_conn():
    from db_adapter import _get_conn as gc
    return gc()


def _collect_daily_health_data(conn):
    """Gather all health events, errors, and agent activity from today."""
    cur = conn.cursor()
    data = {}

    # Health events (last 24h)
    cur.execute("""SELECT component, event_type, severity, message, created_at
                   FROM system_health_events
                   WHERE created_at > NOW() - INTERVAL '24 hours'
                   ORDER BY created_at DESC LIMIT 100""")
    data["health_events"] = [{"component": r[0], "type": r[1], "severity": r[2],
                               "message": (r[3] or "")[:100], "at": str(r[4])}
                              for r in cur.fetchall()]

    # Agent staleness
    cur.execute("""SELECT agent, COUNT(*) as total, MAX(created_at) as latest
                   FROM watchlist_agent_results GROUP BY agent""")
    data["agent_activity"] = [{"agent": r[0], "total": r[1], "latest": str(r[2])}
                               for r in cur.fetchall()]

    # Failed jobs (last 24h)
    cur.execute("""SELECT requested_agent, COUNT(*) as cnt
                   FROM watchlist_agent_jobs
                   WHERE status='failed' AND completed_at > NOW() - INTERVAL '24 hours'
                   GROUP BY requested_agent""")
    data["failed_jobs"] = [{"agent": r[0], "count": r[1]} for r in cur.fetchall()]

    # Pipeline run health
    cur.execute("""SELECT COUNT(*) FILTER (WHERE status='failed') as failed,
                   COUNT(*) as total
                   FROM pipeline_runs WHERE started_at > NOW() - INTERVAL '24 hours'""")
    r = cur.fetchone()
    data["pipeline"] = {"failed": r[0] or 0, "total": r[1] or 0}

    # Claude interventions (last 24h)
    cur.execute("""SELECT component, problem, status, session_log
                   FROM claude_interventions
                   WHERE created_at > NOW() - INTERVAL '24 hours'
                   ORDER BY created_at DESC LIMIT 10""")
    data["claude_interventions"] = [{"component": r[0], "problem": (r[1] or "")[:100],
                                      "status": r[2], "log": (r[3] or "")[:200]}
                                     for r in cur.fetchall()]

    # Open paper trades health
    cur.execute("""SELECT COUNT(*) as total,
                   COUNT(*) FILTER (WHERE stop_order_id IS NULL) as no_stop,
                   COUNT(*) FILTER (WHERE last_synced_at < NOW() - INTERVAL '4 hours' OR last_synced_at IS NULL) as stale_sync
                   FROM paper_trades WHERE status='open'""")
    r = cur.fetchone()
    data["paper_trades"] = {"total": r[0] or 0, "no_stop": r[1] or 0, "stale_sync": r[2] or 0}

    return data


def _call_local_llm(prompt):
    """Call local qwen3:14b via Ollama."""
    import requests
    try:
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": os.getenv("LOCAL_LLM_MODEL", "gemma3:4b"),
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 1000, "temperature": 0.3},
            },
            timeout=120,
        )
        if resp.ok:
            return resp.json().get("response", "")
    except Exception as e:
        log.warning(f"Local LLM call failed: {e}")
    return None


def run_review(dry_run=False):
    """Returns {"status": "dry_run"|"stored"|"no_db"|"no_response"|"store_failed", ...}."""
    conn = _get_conn()
    if not conn:
        log.error("No DB connection")
        return {"status": "no_db"}
    if dry_run:
        from lib.lane_last_receipt import enforce_readonly

        enforce_readonly(conn)

    log.info("Collecting daily health data...")
    data = _collect_daily_health_data(conn)

    # Count issues
    n_health = len(data["health_events"])
    n_failed = sum(j["count"] for j in data["failed_jobs"])
    n_interventions = len(data["claude_interventions"])
    pipeline_fail = data["pipeline"]["failed"]

    prompt = f"""/no_think You are the Trade AI System Health Analyst. Review today's operational data and provide an intelligence briefing.

## SYSTEM ARCHITECTURE REFERENCE (what healthy looks like)
- 17 cron components run on schedule (orchestrator, screener, promoter, news, stops, reconciler, enrichment, price sync, RAG, indicators, aegis, telegram, cleanup, watchdog, TCA, quote refresh)
- 8 agents (maria, steph, risk_agent, tax_agent, alex, aegis, iris, maria_research) process analysis jobs via watchlist_agent_jobs queue
- Healthy: maria/steph/risk run daily, tax/iris/maria_research run weekly, aegis runs overnight, alex runs at 5AM
- Pipeline: screener→orchestrator→signals→proposals→enrichment→ATM approval→Alpaca execution
- Paper trades: 3-6 open positions, all must have stop_order_id on Alpaca, synced within 4h
- LLM routing: local qwen3:14b → grok → claude → openai (budget $1.50/day)
- Agent confidence threshold: 0.55 auto-route, 0.35 needs review, 0.80 high-impact
- Health agent runs every 5 min during market hours, retries stale components (max 2/day), escalates to Telegram then Claude Code
- Target: 0 STALE components, 0 stuck jobs, all agents within freshness thresholds

## Today's Health Data

### Health Events ({n_health} in 24h)
{json.dumps(data['health_events'][:20], indent=2)}

### Agent Activity
{json.dumps(data['agent_activity'], indent=2)}

### Failed Jobs ({n_failed} in 24h)
{json.dumps(data['failed_jobs'], indent=2)}

### Pipeline Health
{json.dumps(data['pipeline'], indent=2)}

### Claude Interventions ({n_interventions})
{json.dumps(data['claude_interventions'], indent=2)}

### Paper Trades
{json.dumps(data['paper_trades'], indent=2)}

## Your Analysis (respond in this exact format)

HEALTH GRADE: [A/B/C/D/F]

TOP ISSUES:
1. [most critical issue and why]
2. [second issue]
3. [third issue]

PATTERNS DETECTED:
- [any recurring failures or trends]

RECOMMENDATIONS:
1. [specific actionable recommendation]
2. [second recommendation]

RISK FORECAST:
- [what might break tomorrow based on today's patterns]
"""

    log.info(f"Sending to local LLM ({n_health} events, {n_failed} failed jobs, {pipeline_fail} pipeline failures)...")

    counts = {"health_events": n_health, "failed_jobs": n_failed,
              "interventions": n_interventions, "pipeline_failed": pipeline_fail}
    if dry_run:
        log.info(f"[DRY RUN] Would send prompt ({len(prompt)} chars) to "
                 f"{os.getenv('LOCAL_LLM_MODEL', 'gemma3:4b')} and upsert llm_intelligence_cache"
                 f"(section='health_review') + 1 system_health_events row")
        return {"status": "dry_run", "prompt_chars": len(prompt), **counts}

    response = _call_local_llm(prompt)
    if not response:
        log.warning("LLM returned no response — skipping")
        return {"status": "no_response", **counts}

    log.info(f"LLM response: {response[:200]}...")

    # Store in llm_intelligence_cache
    try:
        cur = conn.cursor()
        cur.execute("""INSERT INTO llm_intelligence_cache (section, content, generated_at)
                       VALUES ('health_review', %s, NOW())
                       ON CONFLICT (section) DO UPDATE SET content=%s, generated_at=NOW()""",
                    [response[:3000], response[:3000]])
        conn.commit()
        log.info("Stored health review in llm_intelligence_cache")
        stored = True
    except Exception as e:
        log.warning(f"Failed to store review: {e}")
        stored = False

    # Also store as a system health event for the log
    try:
        cur = conn.cursor()
        cur.execute("""INSERT INTO system_health_events
            (component, event_type, severity, message)
            VALUES ('health_llm_review', 'NIGHTLY_REVIEW', 'INFO', %s)""",
            [response[:500]])
        conn.commit()
    except Exception:
        pass

    conn.close()
    log.info("Nightly health review complete")
    return {"status": "stored" if stored else "store_failed", "response_chars": len(response), **counts}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.dry_run:
        res = run_review(dry_run=True)
        return 0 if res.get("status") == "dry_run" else 1
    from lib.lane_last_receipt import now_iso, write_receipt

    started = now_iso()
    try:
        res = run_review(dry_run=False)
    except Exception as exc:  # noqa: BLE001 -- recorded in the receipt, then a non-zero exit
        write_receipt(RECEIPT_NAME, ok=False, error=f"{type(exc).__name__}: {exc}", started_at=started)
        log.error(f"health review FAILED: {type(exc).__name__}: {exc}")
        return 1
    ok = res.get("status") == "stored"
    write_receipt(RECEIPT_NAME, ok=ok, summary=res, started_at=started,
                  error=None if ok else res.get("status"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
