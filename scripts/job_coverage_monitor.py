#!/usr/bin/env python3
"""Job coverage / heartbeat monitor.

Data-freshness checks (check_data_product_freshness.py) verify OUTPUTS, but they
can't catch two failure modes that bit us 2026-06-03:
  1. A job that was never scheduled at all (holdings_llm_refresh — built, run once,
     never crontab'd → silently froze).
  2. A job that IS scheduled but crashes/produces nothing (topic_ingestion.py --all —
     invalid arg, errored every run).

This monitor keeps a REGISTRY of jobs that are SUPPOSED to run, and for each checks:
  - SCHEDULED?  — does its script appear (uncommented) in the active crontab?
  - PRODUCING?  — has it emitted a fresh heartbeat (log mtime or DB timestamp) within
                  its expected cadence?
Status: NOT_SCHEDULED / STALE / NO_SIGNAL (warn) / OK.

Usage:
    python3 scripts/job_coverage_monitor.py            # human-readable
    python3 scripts/job_coverage_monitor.py --json     # JSON
Exit code: number of FAILs (NOT_SCHEDULED + STALE), capped at 250.
"""
import json
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOGS = PROJECT_ROOT / "logs"

# ── Registry: jobs that must run. cadence_h = max hours between heartbeats.
#   signal: ("log", filename) → use log mtime;  ("db", sql) → MAX(timestamp) from DB.
#   schedule_match: substring that must appear (uncommented) in crontab.
REGISTRY = [
    {"name": "holdings_llm_refresh", "schedule_match": "holdings_llm_refresh.py", "cadence_h": 30,
     "signal": ("db", "SELECT MAX(holdings_llm_at) FROM watchlist_items WHERE source='portfolio'")},
    {"name": "catalyst_momentum_engine", "schedule_match": "catalyst_momentum_engine.py", "cadence_h": 30,
     "signal": ("db", "SELECT MAX(created_at) FROM hermes_research_intelligence WHERE research_type='momentum_catalyst'")},
    {"name": "hermes_coordinator", "schedule_match": "hermes_coordinator.py", "cadence_h": 1,
     "signal": ("log", "hermes_coordinator.log")},
    {"name": "iterate_research_topics", "schedule_match": "iterate_research_topics.py", "cadence_h": 30,
     "signal": ("log", "research_iterate.log")},
    {"name": "topic_ingestion", "schedule_match": "topic_ingestion.py", "cadence_h": 96,
     "signal": ("log", "topic_ingestion.log")},
    {"name": "process_watchlist_agent_jobs", "schedule_match": "process_watchlist_agent_jobs.py", "cadence_h": 3,
     "signal": ("db", "SELECT MAX(created_at) FROM watchlist_agent_jobs WHERE status='completed'")},
    {"name": "aegis_overnight", "schedule_match": "aegis_overnight.py", "cadence_h": 30,
     "signal": ("db", "SELECT MAX(observed_at) FROM aegis_portfolio_briefs")},
    {"name": "portfolio_server_watchdog", "schedule_match": "portfolio_server_watchdog.sh", "cadence_h": 1,
     "signal": ("log", ".portfolio_watchdog_heartbeat")},
    {"name": "drive_sync", "schedule_match": "sync-docs-to-drive.sh", "cadence_h": 26,
     "signal": ("log", "drive-sync.log")},
    {"name": "news_ingestion", "schedule_match": "news_ingestion.py", "cadence_h": 12,
     "signal": ("db", "SELECT MAX(created_at) FROM news_articles")},
    {"name": "rag_embeddings", "schedule_match": "embedding", "cadence_h": 72,
     "signal": ("db", "SELECT MAX(created_at) FROM content_embeddings")},
    {"name": "transcript_discovery", "schedule_match": "aegis_transcript_discovery.py", "cadence_h": 240,
     "signal": ("db", "SELECT MAX(ingested_at) FROM youtube_transcripts")},
    {"name": "iris_proposal_curator", "schedule_match": "iris_proposal_curator.py", "cadence_h": 30,
     "signal": ("log", "iris_proposal_curator.log")},
    {"name": "hermes_youtube_discovery", "schedule_match": "hermes_youtube_discovery.py", "cadence_h": 30,
     "signal": ("log", "hermes_youtube_discovery.log")},
    {"name": "options_monitor", "schedule_match": "run_options_monitor", "cadence_h": 1,
     "signal": ("log", "options_monitor.log")},
    {"name": "options_paper_lifecycle", "schedule_match": "run_options_paper_position_monitor",
     "cadence_h": 1, "signal": ("log", "options_paper_monitor.log")},
    {"name": "alpaca_paper_options_reconcile", "schedule_match": "reconcile_alpaca_paper_options",
     "cadence_h": 2, "signal": ("log", "alpaca_paper_options_reconcile.log")},
    {"name": "options_iv_snapshot", "schedule_match": "options_iv_snapshot.py", "cadence_h": 30,
     "signal": ("db", "SELECT MAX(captured_at) FROM options_iv_history")},
    {"name": "atm_auto_approver", "schedule_match": "atm_auto_approver.py", "cadence_h": 1,
     "signal": ("log", "atm.log")},
    {"name": "protection_pipeline", "schedule_match": "run_protection_pipeline.sh", "cadence_h": 2,
     "signal": ("log", "protection_pipeline_cron.log")},
    {"name": "watchlist_proposal_bridge", "schedule_match": "watchlist_proposal_bridge.py", "cadence_h": 1,
     "signal": ("log", "watchlist_proposal_bridge.log")},
    {"name": "pullback_macd_screener", "schedule_match": "run_pullback_macd_screener.sh", "cadence_h": 30,
     "signal": ("log", "pullback_macd_screener.log")},
    {"name": "auto_proposal_generator", "schedule_match": "auto_proposal_generator.py", "cadence_h": 2,
     "signal": ("log", "auto_proposal.log")},
    {"name": "proposal_enrichment", "schedule_match": "proposal_enrichment_loop.py", "cadence_h": 1,
     "signal": ("log", "proposal_enrichment.log")},
    {"name": "strategy_audits", "schedule_match": "run_scheduled_strategy_audits.sh", "cadence_h": 30,
     "signal": ("log", "strategy_audits.log")},
    {"name": "schwab_journal_ingest", "schedule_match": "schwab_journal_builder.py", "cadence_h": 1,
     "signal": ("log", "schwab_ingest.log")},
    {"name": "journal_review_builder", "schedule_match": "journal_review_builder.py", "cadence_h": 30,
     "signal": ("log", "journal_review.log")},
    {"name": "journal_annotation_reminder", "schedule_match": "journal_annotation_reminder.py", "cadence_h": 30,
     "signal": ("log", "journal_annotation_reminder.log")},
    {"name": "journal_tilt_morning_hook", "schedule_match": "journal_tilt_morning_hook.py", "cadence_h": 30,
     "signal": ("log", "journal_tilt_hook.log")},
    # Hermes analyst-coverage LLM research — weekday-daily; 80h cadence tolerates
    # the weekend gap. Was silently deferred every day pre-2026-07-30 (guard
    # window bug), so this monitor exists specifically to catch a recurrence.
    {"name": "hermes_analyst_coverage", "schedule_match": "hermes_analyst_coverage.py", "cadence_h": 80,
     "signal": ("log", "hermes_analyst_coverage.log")},
    # Analyst-signal discovery feeder — every ~3h.
    {"name": "hermes_analyst_signal_discovery", "schedule_match": "hermes_analyst_signal_discovery.py",
     "cadence_h": 5, "signal": ("log", "hermes_analyst_signal.log")},
    # Industry/sector novelty discovery — daily.
    {"name": "hermes_industry_novelty_discovery", "schedule_match": "hermes_industry_novelty_discovery.py",
     "cadence_h": 30, "signal": ("log", "hermes_industry_novelty.log")},
]


def _crontab_lines():
    try:
        out = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return []
    return [ln for ln in out.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def _is_scheduled(match, cron_lines):
    return any(match in ln for ln in cron_lines)


def _log_age_h(fname):
    # Logs live in either the project logs/ or the operator's ~/logs.
    for base in (LOGS, Path.home() / "logs"):
        p = base / fname
        if p.exists():
            return round((time.time() - p.stat().st_mtime) / 3600, 1)
    return None


def _db_age_h(sql):
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from db_adapter import get_connection
        conn = get_connection(); cur = conn.cursor()
        cur.execute(sql); row = cur.fetchone(); conn.close()
        if not row or not row[0]:
            return None
        from datetime import datetime
        ts = row[0]
        dt = ts.replace(tzinfo=None) if hasattr(ts, "replace") else datetime.fromisoformat(str(ts))
        return round((datetime.now() - dt).total_seconds() / 3600, 1)
    except Exception:
        return None


def evaluate():
    cron_lines = _crontab_lines()
    results = []
    for job in REGISTRY:
        scheduled = _is_scheduled(job["schedule_match"], cron_lines)
        kind, arg = job["signal"]
        age = _log_age_h(arg) if kind == "log" else _db_age_h(arg)
        if not scheduled:
            status, detail = "NOT_SCHEDULED", f"not in crontab (last signal {age}h ago)" if age is not None else "not in crontab, no heartbeat"
        elif age is None:
            status, detail = "NO_SIGNAL", "scheduled but no heartbeat found yet"
        elif age > job["cadence_h"]:
            status, detail = "STALE", f"{age}h since last run (max {job['cadence_h']}h)"
        else:
            status, detail = "OK", f"{age}h ago (max {job['cadence_h']}h)"
        results.append({"job": job["name"], "status": status, "detail": detail,
                        "age_hours": age, "cadence_hours": job["cadence_h"], "scheduled": scheduled})
    return results


def main():
    results = evaluate()
    fails = [r for r in results if r["status"] in ("NOT_SCHEDULED", "STALE")]
    if "--json" in sys.argv:
        print(json.dumps({"results": results,
                          "summary": {"total": len(results), "fail": len(fails),
                                      "ok": sum(1 for r in results if r["status"] == "OK")}}, indent=2, default=str))
    else:
        icon = {"OK": "✅", "STALE": "🔴", "NOT_SCHEDULED": "⛔", "NO_SIGNAL": "🟡"}
        print("Job coverage / heartbeat:")
        for r in sorted(results, key=lambda x: x["status"]):
            print(f"  {icon.get(r['status'],'?')} [{r['status']:13}] {r['job']:28} {r['detail']}")
        print(f"\n{len(fails)} FAIL ({sum(1 for r in results if r['status']=='OK')}/{len(results)} OK)")
    return min(len(fails), 250)


if __name__ == "__main__":
    sys.exit(main())
