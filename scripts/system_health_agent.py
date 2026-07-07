#!/usr/bin/env python3
"""system_health_agent.py — Execution Integrity Agent.

Continuously monitors every cron job, process, and execution path.
Detects silent failures, lock contention, stale output, abnormal runtimes.
Self-heals with retries. Escalates via central alert router.

Schedule: */5 * * * 1-5 (every 5 min weekdays), */15 * * * 0,6 (every 15 min weekends)

NO bypass_router. NO direct Telegram. ALL alerts through central router.
"""
import argparse, json, logging, os, subprocess, sys, time, uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [health-agent] %(message)s")
log = logging.getLogger("system_health_agent")

# ── Configuration: Every monitored component ─────────────────────────────────
# schedule: cron-style human readable, for display
# log_file: path relative to PROJECT_ROOT/logs
# max_age_min: max minutes since last log output before flagged stale
# max_runtime_sec: max expected runtime before flagged slow
# critical: if True, failure triggers P0 escalation
# retry_cmd: command to retry on failure (relative to PROJECT_ROOT)
# downstream: what breaks if this fails
MONITORED_COMPONENTS = [
    # ── Pipeline Core ──
    {"component": "trade_ai_orchestrator", "display": "Trade AI Orchestrator",
     "schedule": "0 9,10,12,14,16 * * 1-5", "log_file": "screener_pm.log",
     "max_age_min": 180, "max_runtime_sec": 600, "critical": True,
     "retry_cmd": ".venv/bin/python scripts/trade_ai_orchestrator.py --run-label 0900 --no-llm --no-alerts --allow-underfilled",
     "downstream": "strategy_signals, proposals, ATM execution",
     "lock_file": "/tmp/screener_pm.lock"},
    {"component": "auto_proposal_generator", "display": "Auto Proposal Generator",
     "schedule": "*/30 9-16 * * 1-5", "log_file": "auto_proposal.log",
     "max_age_min": 60, "max_runtime_sec": 300, "critical": True,
     "retry_cmd": ".venv/bin/python scripts/auto_proposal_generator.py --today --apply",
     "downstream": "proposals, ATM execution"},
    {"component": "rotation_autopilot", "display": "Rotation Autopilot (IWM/SPY trend switch)",
     "schedule": "*/15 4-16 * * 1-5", "log_file": "rotation_autopilot.log",
     "max_age_min": 45, "max_runtime_sec": 180, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/rotation_autopilot.py --tick --trigger health_retry",
     "downstream": "watchlist, qualified_intelligence, strategy_signals, proposals",
     "lock_file": "/tmp/tradeai_rotation_autopilot.lock"},
    {"component": "incubator_proposal_promoter", "display": "Incubator Promoter",
     "schedule": "0 7-17 * * 1-5", "log_file": "incubator_promoter.log",
     "max_age_min": 180, "max_runtime_sec": 300, "critical": True,
     "retry_cmd": ".venv/bin/python scripts/incubator_proposal_promoter.py --run",
     "downstream": "proposals from incubator",
     "lock_file": "/tmp/incubator_promoter.lock"},
    {"component": "finviz_screener_runner", "display": "Finviz Screener",
     "schedule": "0 8 * * 1-5", "log_file": "finviz_screener.log",
     "max_age_min": 1500, "max_runtime_sec": 600, "critical": True,
     "retry_cmd": ".venv/bin/python scripts/finviz_screener_runner.py --apply",
     "downstream": "scanner input data"},
    {"component": "news_ingestion", "display": "News Ingestion",
     "schedule": ["30 6,12 * * 1-5", "30 18 * * *"], "log_file": "news_ingestion.log",
     "max_age_min": 480, "max_runtime_sec": 600, "critical": True,
     "retry_cmd": ".venv/bin/python scripts/news_ingestion.py --priority",
     "downstream": "catalyst detection, news alerts"},

    # ── Trade Monitoring ──
    {"component": "unified_stop_supervisor", "display": "Stop Supervisor",
     "schedule": "*/3 9-16 * * 1-5", "log_file": "unified_stop_supervisor.log",
     "max_age_min": 10, "max_runtime_sec": 120, "critical": True,
     "retry_cmd": ".venv/bin/python scripts/unified_stop_supervisor.py --apply",
     "downstream": "trailing stops, target exits, stop monitoring"},
    {"component": "holding_protection_advisor", "display": "Stop/Trail Protection Advisor",
     "schedule": "5 17 * * 1-5", "log_file": "protection_advisor.log",
     "max_age_min": 1500, "max_runtime_sec": 900, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/holding_protection_advisor.py",
     "downstream": "stop/trail advisories, Stop Management tab",
     "lock_file": "/tmp/protection_advisor.lock"},
    {"component": "stop_drift_alert", "display": "Stop Drift + Lock-in Alerts",
     "schedule": "35 17 * * 1-5", "log_file": "stop_drift_alert.log",
     "max_age_min": 1500, "max_runtime_sec": 120, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/stop_drift_alert.py --send",
     "downstream": "raise-stop + lock-in Telegram nudges",
     "lock_file": "/tmp/stop_drift_alert.lock"},
    # paper_trade_monitor replaced by unified_stop_supervisor (STOP-V2.2)
    {"component": "alpaca_reconciler", "display": "Alpaca Reconciler",
     "schedule": "5 16 * * 1-5", "log_file": "alpaca_reconciler.log",
     "max_age_min": 1500, "max_runtime_sec": 60, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/alpaca_paper_reconciler.py",
     "downstream": "DB-broker sync"},

    # ── Data Pipeline ──
    {"component": "finviz_enrichment", "display": "Finviz Enrichment",
     "schedule": "10 7 * * 1-5", "log_file": "finviz_enrichment.log",
     "max_age_min": 1500, "max_runtime_sec": 600, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/finviz_enrichment.py",
     "downstream": "enriched scanner data"},
    {"component": "price_db_sync", "display": "Price DB Sync",
     "schedule": "20 7 * * 1-5", "log_file": "price_db_sync.log",
     "max_age_min": 1500, "max_runtime_sec": 600, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/price_db_sync.py",
     "downstream": "price data freshness"},
    {"component": "rag_indexer", "display": "RAG Indexer",
     "schedule": "0 */4 * * *", "log_file": "rag_indexer.log",
     "max_age_min": 300, "max_runtime_sec": 600, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/rag_indexer.py",
     "downstream": "agent context, RAG search"},
    {"component": "indicator_engine", "display": "Indicator Engine",
     "schedule": "0 8 * * 1-5", "log_file": "indicator_engine.log",
     "max_age_min": 1500, "max_runtime_sec": 900, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/indicator_engine.py",
     "downstream": "technical indicators"},

    # ── Agents ──
    {"component": "aegis_morning_brief", "display": "Aegis Morning Brief",
     "schedule": "5 8 * * 1-5", "log_file": "aegis_brief.log",
     "max_age_min": 1500, "max_runtime_sec": 300, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/aegis_morning_brief_delivery.py",
     "downstream": "daily brief delivery"},
    {"component": "telegram_command_handler", "display": "Telegram Bot Daemon",
     "schedule": "*/2 * * * *", "log_file": "telegram_commands.log",
     "max_age_min": 5, "max_runtime_sec": 60, "critical": True,
     "retry_cmd": ".venv/bin/python scripts/telegram_command_handler.py --poll",
     "downstream": "operator commands, approval buttons"},

    # ── Cleanup & Governance ──
    {"component": "cleanup_stale_proposals", "display": "Stale Proposal Cleanup",
     "schedule": "0 10,15 * * 1-5", "log_file": "cleanup_stale_proposals.log",
     "max_age_min": 1500, "max_runtime_sec": 60, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/cleanup_stale_proposals.py --apply",
     "downstream": "proposal hygiene"},
    {"component": "pipeline_watchdog", "display": "Pipeline Watchdog",
     "schedule": "0 */2 * * *", "log_file": "pipeline_watchdog.log",
     "max_age_min": 150, "max_runtime_sec": 300, "critical": True,
     "retry_cmd": ".venv/bin/python scripts/pipeline_watchdog.py",
     "downstream": "pipeline self-healing"},

    # ── TCA ──
    {"component": "tca_analyzer", "display": "TCA Execution Quality",
     "schedule": "30 16 * * 1-5", "log_file": "tca_analyzer.log",
     "max_age_min": 1500, "max_runtime_sec": 60, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/paper_execution_quality_analyzer.py --recent --apply",
     "downstream": "execution quality page"},

    # ── LLM Backtesting (v3.8) ──
    {"component": "trade_close_llm_analyzer", "display": "LLM Close-of-Trade Analysis",
     # script runs weekday 21:00 (structured_eval.log); Sunday 23:00 run is monitored
     # separately by llm_backtest_reviewer. Was pointed at a log path that never existed.
     "schedule": "0 21 * * 1-5", "log_file": "structured_eval.log",
     "max_age_min": 1500, "max_runtime_sec": 300, "critical": False,
     "downstream": "trade_llm_reviews close_analysis, journal learning quality"},
    # NOTE: delayed_trade_llm_reviewer + monthly_grok_meta_review removed 2026-06-06 —
    # no backing script and no cron entry exists (never implemented / aspirational).
    # They produced permanent MISSING false positives. Re-add when the jobs actually exist.

    # ── ATM Position Reconciler ──
    {"component": "atm_position_reconciler", "display": "ATM Position Reconciler",
     "schedule": "*/15 9-16 * * 1-5", "log_file": "atm_position_reconciliation/cron.log",
     "max_age_min": 30, "max_runtime_sec": 120, "critical": False,
     "downstream": "reconciliation health, ghost position detection"},

    # ── Quote Refresh ──
    # ── ATM & Proposals ──
    {"component": "atm_auto_approver", "display": "ATM Auto Approver",
     "schedule": "*/15 7-15 * * 1-5", "log_file": "atm.log",
     "max_age_min": 30, "max_runtime_sec": 60, "critical": True,
     "retry_cmd": ".venv/bin/python scripts/atm_auto_approver.py",
     "downstream": "automated trade approval"},
    {"component": "proposal_enrichment", "display": "Proposal Enrichment",
     "schedule": "*/10 4-19 * * 1-5", "log_file": "proposal_enrichment.log",
     "max_age_min": 30, "max_runtime_sec": 600, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/proposal_enrichment_loop.py --run --limit 5",
     "downstream": "proposal readiness, agent reviews"},
    {"component": "agent_event_router", "display": "Agent Event Router",
     "schedule": "*/30 * * * *", "log_file": "agent_event_router.log",
     "max_age_min": 60, "max_runtime_sec": 300, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/agent_event_router.py",
     "downstream": "event-driven agent triggers"},
    {"component": "paper_execution_sweep", "display": "Paper Execution Sweep",
     "schedule": "*/15 9-16 * * 1-5", "log_file": "paper_execution.log",
     "max_age_min": 30, "max_runtime_sec": 120, "critical": True,
     "retry_cmd": ".venv/bin/python scripts/paper_execution_sweep.py",
     "downstream": "order submission, fill detection"},

    # ── Intelligence ──
    {"component": "alex_daily", "display": "Alex Daily Scan",
     "schedule": "0 5 * * 1-5", "log_file": "alex_daily.log",
     "max_age_min": 1500, "max_runtime_sec": 600, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/run_alex_daily.py --daily",
     "downstream": "CIO intelligence, daily alerts"},
    {"component": "cio_decision_engine", "display": "CIO Decision Engine",
     "schedule": "0 7 * * 1-5", "log_file": "cio_decisions.log",
     "max_age_min": 1500, "max_runtime_sec": 300, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/cio_decision_engine.py --run",
     "downstream": "CIO decisions, portfolio allocation"},
    {"component": "data_gap_resolver", "display": "Data Gap Resolver",
     "schedule": "0 10-16 * * 1-5", "log_file": "data_gap_resolver.log",
     "max_age_min": 1500, "max_runtime_sec": 600, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/data_gap_resolver.py",
     "downstream": "data completeness, enrichment gaps"},
    # NOTE: overnight_batch removed 2026-06-06 — the job was intentionally retired
    # (cron tagged PHASE102-RETIRED; last clean run 2026-05-29). Monitoring a retired
    # job produced a permanent STALE false positive. Its agent_performance scorer was
    # rehomed to update_agent_performance.py (below), re-scheduled weekday 20:00.
    {"component": "update_agent_performance", "display": "Agent Performance Scorer",
     "schedule": "0 20 * * 1-5", "log_file": "update_agent_performance.log",
     "max_age_min": 1500, "max_runtime_sec": 600, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/update_agent_performance.py",
     "downstream": "agent_performance_history, weekly portfolio review"},
    {"component": "auto_enrichment", "display": "Auto Enrichment Runner",
     "schedule": "*/10 4-19 * * 1-5", "log_file": "auto_enrichment.log",
     "max_age_min": 15, "max_runtime_sec": 120, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/auto_enrichment_runner.py",
     "downstream": "symbol enrichment, data quality"},

    # ── Quote Refresh ──
    {"component": "proactive_quote_refresh", "display": "Quote Refresh",
     "schedule": "*/5 9-15 * * 1-5", "log_file": "proactive_quote_refresh_cron.log",
     "max_age_min": 15, "max_runtime_sec": 120, "critical": False,
     "retry_cmd": "bash scripts/run_scheduled_quote_refresh.sh --mode pending --limit 50",
     "downstream": "proposal price freshness"},

    # ── Portfolio live prices (Finviz authoritative — NOT SnapTrade) ──
    {"component": "portfolio_repricer_intraday", "display": "Portfolio Repricer (Finviz intraday)",
     "schedule": ["5 9 * * 1-5", "*/15 9-16 * * 1-5"], "log_file": "portfolio_repricer_intraday.log",
     "max_age_min": 25, "max_runtime_sec": 180, "critical": True,
     "retry_cmd": ".venv/bin/python scripts/portfolio_repricer.py",
     "downstream": "holdings.json prices, finviz_quote_cache, Command Center P/L",
     "lock_file": "/tmp/portfolio_repricer.lock"},
    {"component": "portfolio_repricer_postclose", "display": "Portfolio Repricer (EOD close)",
     "schedule": "10 16 * * 1-5", "log_file": "portfolio_repricer_postclose.log",
     "max_age_min": 1500, "max_runtime_sec": 300, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/portfolio_repricer.py",
     "downstream": "official close capture, holdings reconcile"},
    {"component": "market_quotes_intraday", "display": "Alpaca Market Quotes (intraday backup)",
     "schedule": "*/15 9-16 * * 1-5", "log_file": "market_data.log",
     "max_age_min": 25, "max_runtime_sec": 120, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/external_market_data_ingest.py --quotes",
     "downstream": "market_quotes DB — Fidelity price fallback behind Finviz",
     "lock_file": "/tmp/mkt_quotes_intraday.lock"},
    {"component": "snaptrade_sync", "display": "SnapTrade Holdings Sync (positions/basis only)",
     "schedule": ["50 9 * * 1-5", "0 13 * * 1-5", "35 17 * * 1-5"], "log_file": "snaptrade_sync.log",
     "max_age_min": 480, "max_runtime_sec": 120, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/snaptrade_sync.py --apply",
     "downstream": "Fidelity shares/cost_basis — never authoritative for live quotes"},

    # ── TradeInView / Journal ──
    {"component": "schwab_journal_ingest", "display": "Schwab Journal Ingest",
     "schedule": ["15 18 * * 1-5", "*/15 9-16 * * 1-5"], "log_file": "schwab_ingest.log",
     "max_age_min": 30, "max_runtime_sec": 300, "critical": False,
     # Semantic-failure signatures: the ingest can exit 0 with structurally-valid JSON while actually
     # failing (revoked/absent Schwab token → "no Schwab login token", rows_total:0), which the generic
     # Traceback/ERROR heuristics miss. Flag those so a run-and-fail is not recorded as OK on mtime alone.
     # Operator-action alerting for the token itself is handled by health_agent.collect_broker_token_health.
     "error_signatures": ["invalid_grant", "no Schwab login token", "Refresh token is invalid", "OAuthError"],
     # success markers so a stale error earlier in the log window doesn't flag a since-recovered run
     "success_signatures": ["\"mode\": \"APPLIED\"", "\"inserted\":"],
     "retry_cmd": "flock -n /tmp/schwab_ingest.lock bash -c '.venv/bin/python scripts/schwab_transaction_ingest.py --apply && .venv/bin/python scripts/schwab_journal_builder.py --apply'",
     "downstream": "trade_closed, TradeInView trade log, Schwab round-trips",
     "lock_file": "/tmp/schwab_ingest.lock"},
    {"component": "journal_review_builder", "display": "Journal Review Builder (LLM grades)",
     "schedule": "30 18 * * 1-5", "log_file": "journal_review.log",
     "max_age_min": 1500, "max_runtime_sec": 600, "critical": False,
     "retry_cmd": "flock -n /tmp/journal_review.lock .venv/bin/python scripts/journal_review_builder.py",
     "downstream": "journal_trade_reviews, TradeInView annotations",
     "lock_file": "/tmp/journal_review.lock"},
    {"component": "journal_annotation_reminder", "display": "TradeInView Annotation Reminder",
     "schedule": "30 23 * * 1-5", "log_file": "journal_annotation_reminder.log",
     "max_age_min": 1500, "max_runtime_sec": 120, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/journal_annotation_reminder.py",
     "downstream": "operator annotation coverage nudge"},
    {"component": "journal_tilt_morning_hook", "display": "TradeInView Tilt Morning Hook",
     "schedule": "0 12 * * 1-5", "log_file": "journal_tilt_hook.log",
     "max_age_min": 1500, "max_runtime_sec": 60, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/journal_tilt_morning_hook.py",
     "downstream": "operator_review_queue tilt review item"},

    # ── Recurring Backtesting (v4.0) ──
    {"component": "enterprise_backtester", "display": "Enterprise Backtester",
     "schedule": "0 22 * * 0", "log_file": "enterprise_backtester.log",
     "max_age_min": 10080, "max_runtime_sec": 3600, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/enterprise_backtester.py --replay-trades --apply",
     "downstream": "strategy_backtest_trades, backtest comparison"},
    {"component": "strategy_backtester", "display": "Strategy Backtester (Daily)",
     "schedule": "0 6 * * 1-5", "log_file": "strategy_backtester.log",
     "max_age_min": 1500, "max_runtime_sec": 1800, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/strategy_backtester.py --all-strategies --apply",
     "downstream": "strategy_backtest_trades, active strategy validation"},
    {"component": "llm_backtest_reviewer", "display": "LLM Backtest Trade Reviewer",
     "schedule": "0 23 * * 0", "log_file": "llm_backtest_review.log",
     "max_age_min": 10080, "max_runtime_sec": 7200, "critical": False,
     "retry_cmd": ".venv/bin/python scripts/trade_close_llm_analyzer.py --source backtest --limit 50 --apply --confirm-llm-review-write --allow-local-llm",
     "downstream": "trade_llm_reviews, backtest learning"},
]

MAX_RETRIES = 2

# ── safe_flock event log ─────────────────────────────────────────────────────
SAFE_FLOCK_LOG = PROJECT_ROOT / "logs" / "safe_flock_events.jsonl"
SAFE_FLOCK_LOOKBACK_MIN = 30  # window for detecting repeated lock skips

# Components that are critical for repeated-lock-skip escalation
CRITICAL_COMPONENTS = {c["component"] for c in MONITORED_COMPONENTS if c.get("critical")}


def _ingest_safe_flock_events(lookback_min=SAFE_FLOCK_LOOKBACK_MIN):
    """Read recent safe_flock JSONL events. Returns (events, parse_errors)."""
    events = []
    parse_errors = 0
    if not SAFE_FLOCK_LOG.exists():
        return events, parse_errors
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=lookback_min)
        with open(SAFE_FLOCK_LOG, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    # Parse timestamp
                    ts_str = ev.get("ts", "")
                    try:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        else:
                            ts = ts.astimezone(timezone.utc)
                    except Exception:
                        ts = None
                    if ts and ts >= cutoff:
                        ev["_parsed_ts"] = ts
                        events.append(ev)
                except (json.JSONDecodeError, ValueError):
                    parse_errors += 1
    except Exception as e:
        log.warning(f"Failed to read safe_flock log: {e}")
    return events, parse_errors


def _analyze_safe_flock(conn, dry_run=True, verbose=False):
    """Analyze safe_flock events and write health events for anomalies.

    Returns summary dict for inclusion in the health report.
    """
    events, parse_errors = _ingest_safe_flock_events()

    summary = {
        "events_seen": len(events),
        "parse_errors": parse_errors,
        "lock_skips": 0,
        "repeated_lock_skips": [],
        "stale_locks_cleared": 0,
        "command_failures": 0,
    }

    # Bucket events by component
    skips_by_component = {}
    for ev in events:
        et = ev.get("event_type", "")
        comp = ev.get("component", "unknown")

        if et == "lock_skip":
            summary["lock_skips"] += 1
            skips_by_component.setdefault(comp, []).append(ev)

        elif et == "stale_lock_cleared":
            summary["stale_locks_cleared"] += 1
            if conn and not dry_run:
                _log_event(conn, comp, "SAFE_FLOCK_STALE_CLEARED", "WARN",
                           ev.get("message", "Stale lock cleared")[:500])

        elif et == "completed":
            exit_code = ev.get("exit_code")
            if exit_code is not None and exit_code != 0:
                summary["command_failures"] += 1
                if conn and not dry_run:
                    _log_event(conn, comp, "SAFE_FLOCK_CMD_FAILED", "WARN",
                               f"Command exited {exit_code}: {ev.get('command', '')[:200]}")

    # Detect repeated lock skips (2+ in window)
    for comp, skip_list in skips_by_component.items():
        if len(skip_list) >= 2:
            severity = "CRITICAL" if comp in CRITICAL_COMPONENTS else "WARN"
            summary["repeated_lock_skips"].append({
                "component": comp,
                "count": len(skip_list),
                "severity": severity,
            })
            if conn and not dry_run:
                _log_event(conn, comp, "SAFE_FLOCK_REPEATED_SKIP", severity,
                           f"{len(skip_list)} lock skips in {SAFE_FLOCK_LOOKBACK_MIN}min window")

    # Single lock skips (log as INFO)
    for comp, skip_list in skips_by_component.items():
        if len(skip_list) == 1 and conn and not dry_run:
            _log_event(conn, comp, "SAFE_FLOCK_LOCK_SKIP", "INFO",
                       skip_list[0].get("message", "Lock skip")[:500])

    # Repeated parse errors
    if parse_errors >= 5 and conn and not dry_run:
        _log_event(conn, "safe_flock_parser", "SAFE_FLOCK_PARSE_ERRORS", "WARN",
                   f"{parse_errors} malformed JSONL lines in safe_flock log")

    if verbose:
        log.info(f"  safe_flock: {summary['events_seen']} events, "
                 f"{summary['lock_skips']} skips, "
                 f"{len(summary['repeated_lock_skips'])} repeated, "
                 f"{summary['stale_locks_cleared']} stale cleared, "
                 f"{summary['command_failures']} cmd failures")

    return summary


def _get_conn():
    try:
        from db_adapter import _get_conn as _gc
        return _gc()
    except Exception:
        return None


def _log_event(conn, component, event_type, severity, message, action=None, success=None):
    try:
        cur = conn.cursor()
        # Source-side dedup: the */5 agent re-emits the same per-component event ~288x/day,
        # which is the SIEM firehose. Log only state CHANGES (and first occurrences) — if the
        # same (event_type, severity) for this component was logged in the last 25 min, skip.
        cur.execute("""SELECT event_type, severity FROM system_health_events
                       WHERE component = %s AND created_at > NOW() - INTERVAL '25 minutes'
                       ORDER BY created_at DESC LIMIT 1""", [component])
        last = cur.fetchone()
        if last and last[0] == event_type and last[1] == severity:
            conn.commit()  # release the dedup-SELECT txn — leaving it open through a later
            return         # subprocess wait gets the conn idle-in-txn killed at 120s
        cur.execute("""INSERT INTO system_health_events
            (component, event_type, severity, message, action_taken, success)
            VALUES (%s, %s, %s, %s, %s, %s)""",
            [component, event_type, severity, message[:500] if message else None,
             action[:200] if action else None, success])
        conn.commit()
    except Exception as e:
        log.warning(f"Failed to log event: {e}")


def _send_alert(message, urgent=False):
    """Send alert through central router. NEVER bypass."""
    try:
        from telegram_alert import send_telegram
        send_telegram(message)
    except Exception as e:
        log.error(f"Alert send failed: {e}")


def _cron_field_matches(field, value, min_val, max_val):
    """Match a single cron field against `value`. Supports '*', lists, ranges and '/steps'."""
    field = field.strip()
    if field in ("*", "?"):
        return True
    for part in field.split(","):
        base, step = part, 1
        if "/" in part:
            base, step_s = part.split("/", 1)
            try:
                step = int(step_s)
            except ValueError:
                step = 1
        if base in ("*", ""):
            lo, hi = min_val, max_val
        elif "-" in base:
            lo_s, hi_s = base.split("-", 1)
            try:
                lo, hi = int(lo_s), int(hi_s)
            except ValueError:
                continue
        else:
            try:
                if int(base) == value:
                    return True
            except ValueError:
                pass
            continue
        if lo <= value <= hi and (value - lo) % step == 0:
            return True
    return False


def _cron_fires_at(schedule, dt):
    """True if 5-field cron `schedule` fires at the minute-resolution datetime `dt`."""
    parts = schedule.split()
    if len(parts) != 5:
        return False
    minute_f, hour_f, dom_f, month_f, dow_f = parts
    if not _cron_field_matches(minute_f, dt.minute, 0, 59):
        return False
    if not _cron_field_matches(hour_f, dt.hour, 0, 23):
        return False
    if not _cron_field_matches(month_f, dt.month, 1, 12):
        return False
    # Python weekday(): Mon=0..Sun=6  ->  cron: Sun=0..Sat=6 (with 7 also = Sun)
    cron_dow = (dt.weekday() + 1) % 7
    dow_ok = (_cron_field_matches(dow_f, cron_dow, 0, 6)
              or (cron_dow == 0 and _cron_field_matches(dow_f, 7, 0, 7)))
    dom_ok = _cron_field_matches(dom_f, dt.day, 1, 31)
    # Standard cron rule: when both day-of-month and day-of-week are restricted, either matches.
    if dom_f.strip() != "*" and dow_f.strip() != "*":
        return dom_ok or dow_ok
    return dom_ok and dow_ok


def _weekday_only_schedule(schedule):
    """True if the cron string can never fire on a weekend (dow excludes Sat+Sun).

    These are market-day jobs: their crons are wrapped in market_day_gate.sh (or
    equivalent), so on NYSE holidays they are scheduled-but-skipped by design and
    must not be treated as having a scheduled fire that day.
    """
    parts = schedule.split()
    if len(parts) != 5:
        return False
    dow_f = parts[4]
    return not (_cron_field_matches(dow_f, 0, 0, 6)      # Sunday (0)
                or _cron_field_matches(dow_f, 7, 0, 7)    # Sunday (7)
                or _cron_field_matches(dow_f, 6, 0, 6))   # Saturday


def _is_trading_day_cached(dt, _cache={}):
    """market_session.is_trading_day (weekend/NYSE-holiday aware), cached per date.

    Fails OPEN (True = day counts as scheduled) so a broken calendar degrades to the
    old pure-cron behavior instead of silencing staleness detection.
    """
    d = dt.date()
    if d not in _cache:
        try:
            from market_session import is_trading_day
            _cache[d] = bool(is_trading_day(dt))
        except Exception:
            _cache[d] = True
    return _cache[d]


def _prev_scheduled_fire(schedule, now_dt, lookback_days=14):
    """Most recent datetime <= now_dt at which `schedule` would have fired.

    `schedule` may be a single cron string or a list of cron strings (the latest
    fire across all is returned). Returns None if unparseable / no fire in window.

    Trading-calendar aware: weekday-only schedules (dow 1-5) are market-day jobs
    whose crons run under market_day_gate.sh — on NYSE holidays the gate skips them,
    so a holiday is NOT a scheduled fire for those schedules. Without this, the
    2026-07-03 (July-4th observed) skip read as "last fire Friday 16:57" all weekend
    and every gated weekday job paged STALE Sat+Sun despite last output being the
    last real trading day (Thursday). Schedules that can fire on weekends (dow */0/6)
    keep pure cron semantics. Weekday (trading-day) behavior is unchanged.
    """
    schedules = schedule if isinstance(schedule, (list, tuple)) else [schedule]
    schedules = [s for s in schedules if s and len(s.split()) == 5]
    if not schedules:
        return None
    weekday_only = {s: _weekday_only_schedule(s) for s in schedules}
    all_weekday_only = all(weekday_only.values())
    dt = now_dt.replace(second=0, microsecond=0)
    horizon = dt - timedelta(days=lookback_days)
    while dt >= horizon:
        # Fast path: if every schedule is market-day-only and this is not a trading
        # day (weekend/holiday), no fire is possible — skip to the previous day.
        if all_weekday_only and not _is_trading_day_cached(dt):
            dt = dt.replace(hour=23, minute=59) - timedelta(days=1)
            continue
        for s in schedules:
            if _cron_fires_at(s, dt) and (not weekday_only[s] or _is_trading_day_cached(dt)):
                return dt
        dt -= timedelta(minutes=1)
    return None


def _fmt_schedule(schedule):
    """Human-readable form of a schedule that may be a string or list of cron strings."""
    if isinstance(schedule, (list, tuple)):
        return " | ".join(schedule)
    return schedule


def _check_log_freshness(log_file, max_age_min, prev_fire=None, now=None, grace_min=15):
    """Check if log file has recent output.

    When `prev_fire` (the most recent scheduled run time) is supplied, staleness is
    judged against the schedule rather than a blind elapsed-time threshold: the job is
    STALE only if its last output predates the most recent scheduled run (after a grace
    period for that run to complete). This eliminates false positives on days/hours the
    job is not scheduled to run (e.g. weekday-only jobs flagged STALE on weekends).
    Falls back to the fixed `max_age_min` threshold when no schedule context is given.
    """
    log_path = PROJECT_ROOT / "logs" / log_file
    if not log_path.exists():
        return {"status": "MISSING", "age_min": None, "last_line": None}
    try:
        mtime = datetime.fromtimestamp(log_path.stat().st_mtime, tz=timezone.utc)
        age_min = (datetime.now(timezone.utc) - mtime).total_seconds() / 60
        last_line = ""
        with open(log_path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 500))
            last_line = f.read().decode('utf-8', errors='replace').strip().split('\n')[-1][:200]

        if prev_fire is not None and now is not None:
            # The most recent scheduled run hasn't had time to complete yet.
            if now < prev_fire + timedelta(minutes=grace_min):
                return {"status": "OK", "age_min": round(age_min, 1),
                        "last_line": last_line, "note": "within_run_grace"}
            # Stale only if last output is older than the most recent scheduled run.
            if mtime < prev_fire - timedelta(minutes=grace_min):
                return {"status": "STALE", "age_min": round(age_min, 1), "last_line": last_line}
            return {"status": "OK", "age_min": round(age_min, 1), "last_line": last_line}

        # Fallback: fixed-age threshold (event-driven / unparseable schedules).
        if age_min > max_age_min:
            return {"status": "STALE", "age_min": round(age_min, 1), "last_line": last_line}
        return {"status": "OK", "age_min": round(age_min, 1), "last_line": last_line}
    except Exception as e:
        return {"status": "ERROR", "age_min": None, "last_line": str(e)[:100]}


def _check_lock_contention(lock_file):
    """Check if a lock file exists and if the holding process is alive."""
    if not lock_file:
        return {"status": "NO_LOCK", "pid": None, "alive": None}
    pid_file = f"{lock_file}.pid"
    if not os.path.exists(pid_file):
        return {"status": "FREE", "pid": None, "alive": None}
    try:
        pid = int(open(pid_file).read().strip())
        alive = os.path.exists(f"/proc/{pid}")
        if alive:
            # Check how long it's been running
            try:
                stat = os.stat(f"/proc/{pid}")
                start_time = datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc)
                runtime = (datetime.now(timezone.utc) - start_time).total_seconds()
                return {"status": "LOCKED", "pid": pid, "alive": True, "runtime_sec": round(runtime)}
            except Exception:
                return {"status": "LOCKED", "pid": pid, "alive": True}
        else:
            return {"status": "STALE_LOCK", "pid": pid, "alive": False}
    except Exception:
        return {"status": "UNKNOWN", "pid": None, "alive": None}


def _check_output_validity(component, log_file, error_signatures=None, success_signatures=None):
    """Check if the last run produced meaningful output (not just errors).

    error_signatures: component-declared substrings that mean the run FAILED even if it exited 0 with
    structurally-valid output (e.g. Schwab `invalid_grant` / `no Schwab login token` — a clean JSON
    failure the generic Traceback/ERROR heuristics miss). This closes the "log is fresh so it's OK"
    blind spot for API-dependent crons that can run-and-fail silently.
    success_signatures: markers of a good run; a failure signature is only honored when it is MORE RECENT
    than the last success marker, so a stale error earlier in the log window doesn't flag a run that has
    since recovered."""
    log_path = PROJECT_ROOT / "logs" / log_file
    if not log_path.exists():
        return {"valid": False, "reason": "log_missing"}
    try:
        with open(log_path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 4000))
            tail = f.read().decode('utf-8', errors='replace')
        # Component-declared failure signatures FIRST — catches semantic failures that exit 0 with
        # valid-looking output (no Traceback, low ERROR count). Recency-gated by success markers.
        _last_ok = max((tail.rfind(s) for s in (success_signatures or [])), default=-1)
        for sig in (error_signatures or []):
            pos = tail.rfind(sig)
            if pos >= 0 and pos > _last_ok:
                return {"valid": False, "reason": f"error_signature:{sig[:40]}"}
        # Check for common failure patterns
        if "Usage:" in tail and "error:" in tail.lower():
            return {"valid": False, "reason": "usage_error_likely_misconfigured"}
        if "Traceback" in tail and "Error" in tail:
            return {"valid": False, "reason": "python_exception"}
        if tail.count("ERROR") > 5:
            return {"valid": False, "reason": "excessive_errors"}
        return {"valid": True, "reason": "ok"}
    except Exception:
        return {"valid": False, "reason": "read_error"}


def _attempt_retry(comp, conn):
    """Attempt automatic retry of a failed component. Max 2 retries per day."""
    cmd = comp.get("retry_cmd")
    if not cmd:
        return False
    component = comp["component"]

    # Check retry count today
    try:
        cur = conn.cursor()
        cur.execute("""SELECT COUNT(*) FROM system_health_events
            WHERE component=%s AND event_type='RETRY' AND created_at > NOW() - INTERVAL '24 hours'""",
            [component])
        retries_today = cur.fetchone()[0] or 0
        # Release the read txn NOW — the retry subprocess below blocks for up to max_runtime_sec
        # (300s+) while db_adapter kills idle-in-transaction at 120s, taking this shared conn with it
        # (the agent was logging idle-txn kills it caused itself, 1-2 per */15 run).
        conn.commit()
        if retries_today >= MAX_RETRIES:
            _log_event(conn, component, "RETRY_EXHAUSTED", "CRITICAL",
                       f"Max retries ({MAX_RETRIES}) exhausted today", success=False)
            return False
    except Exception:
        try:
            conn.rollback()  # an aborted txn held through the subprocess dies the same way
        except Exception:
            pass

    # Clear stale lock ONLY when the PID is genuinely dead. (Do NOT pre-clear before running — that
    # defeated the lock and let every cycle spawn another heavy orchestrator: the 2026-06-25 pile-up
    # of 3+ concurrent trade_ai_orchestrator --run-label 0900 runs that starved the single-threaded
    # API server.)
    lock_file = comp.get("lock_file")
    if lock_file:
        lock_info = _check_lock_contention(lock_file)
        if lock_info["status"] == "STALE_LOCK":
            try:
                os.remove(f"{lock_file}.pid")
                _log_event(conn, component, "LOCK_CLEARED", "WARN",
                           f"Cleared stale lock {lock_file} (dead PID {lock_info['pid']})",
                           action="rm stale .pid", success=True)
            except Exception:
                pass

    # SINGLE-FLIGHT the retry through the SAME safe_flock.sh the cron uses, so a remediation can never
    # stack on the cron run or on a prior still-running remediation. If the lock is held, safe_flock
    # exits without running — exactly what we want (it's already running; don't pile on).
    run_cmd = cmd
    if lock_file:
        run_cmd = f"bash {PROJECT_ROOT}/scripts/safe_flock.sh {lock_file} {cmd}"

    log.info(f"[retry] {component} — attempt {retries_today + 1}/{MAX_RETRIES}")
    timeout_s = comp.get("max_runtime_sec", 300)
    proc = None
    try:
        # new session so a timeout kills the WHOLE tree (heavy orchestrator child included), not just
        # the shell — the old subprocess.run(timeout) orphaned the python child to keep loading the host.
        proc = subprocess.Popen(
            run_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=str(PROJECT_ROOT), start_new_session=True)
        try:
            out, err = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            try:
                import signal as _sig
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, _sig.SIGTERM)
                try:
                    proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(pgid, _sig.SIGKILL)
                    proc.communicate(timeout=5)
            except Exception:
                pass
            _log_event(conn, component, "RETRY_TIMEOUT", "WARN",
                       f"Retry timed out after {timeout_s}s — process group killed",
                       action=cmd[:100], success=False)
            return False
        success = proc.returncode == 0
        _log_event(conn, component, "RETRY", "INFO" if success else "WARN",
                   f"exit={proc.returncode} stdout={(out or '')[-200:]}" if success
                   else f"exit={proc.returncode} stderr={(err or '')[-200:]}",
                   action=cmd[:100], success=success)
        return success
    except Exception as e:
        _log_event(conn, component, "RETRY_ERROR", "WARN", str(e)[:200],
                   action=cmd[:100], success=False)
        return False


def _is_portfolio_market_hours(now_et) -> bool:
    """Weekday 9:30 AM – 4:00 PM ET — when intraday Finviz repricing must be live."""
    if now_et.weekday() >= 5:
        return False
    mins = now_et.hour * 60 + now_et.minute
    return 570 <= mins <= 960


def _parse_et_timestamp(ts_str: str):
    """Parse 'YYYY-MM-DD HH:MM:SS ET' (or ISO) to aware UTC datetime."""
    if not ts_str:
        return None
    s = str(ts_str).strip().replace(" ET", "").replace("ET", "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            naive = datetime.strptime(s[:19], fmt)
            import pytz as _ptz_et
            return _ptz_et.timezone("US/Eastern").localize(naive).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _portfolio_price_freshness_alerts(now_et, max_age_min: float = 25.0) -> list[str]:
    """Finviz cache + holdings repriced timestamps — authoritative portfolio quote layer."""
    if not _is_portfolio_market_hours(now_et):
        return []
    alerts = []
    state_dir = PROJECT_ROOT / "data" / "portfolios" / "state"
    now_utc = datetime.now(timezone.utc)

    # finviz_quote_cache.json _meta.last_fetched
    cache_path = state_dir / "finviz_quote_cache.json"
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            meta = cache.get("_meta") or {}
            lf = _parse_et_timestamp(meta.get("last_fetched") or meta.get("last_updated") or "")
            if lf:
                age = (now_utc - lf).total_seconds() / 60.0
                if age > max_age_min:
                    alerts.append(
                        f"🚨 Finviz quote cache stale {age:.0f}m (>{max_age_min:.0f}m) — "
                        f"portfolio cards may show wrong P/L")
            else:
                alerts.append("⚠️ Finviz quote cache missing last_fetched timestamp")
        except Exception as e:
            alerts.append(f"⚠️ Finviz quote cache unreadable: {str(e)[:80]}")
    else:
        alerts.append("🚨 finviz_quote_cache.json missing")

    # holdings.json last_repriced (not file mtime — SnapTrade sync can mask staleness)
    holdings_path = state_dir / "holdings.json"
    if holdings_path.exists():
        try:
            hp = json.loads(holdings_path.read_text(encoding="utf-8"))
            lr = _parse_et_timestamp(hp.get("last_repriced") or "")
            if lr:
                age = (now_utc - lr).total_seconds() / 60.0
                if age > max_age_min:
                    alerts.append(
                        f"🚨 Portfolio last_repriced stale {age:.0f}m (>{max_age_min:.0f}m) — "
                        f"run portfolio_repricer.py")
            else:
                alerts.append("⚠️ holdings.json missing last_repriced")
        except Exception as e:
            alerts.append(f"⚠️ holdings.json repriced check failed: {str(e)[:80]}")

    return alerts


def _escalate(comp, check_result, conn):
    """Escalate a failure to operator via central alert router. Dedup: max 1 per component per 2 hours."""
    component = comp["component"]
    severity = "CRITICAL" if comp.get("critical") else "WARN"

    # Dedup: don't spam same escalation within 2 hours
    try:
        cur = conn.cursor()
        cur.execute("""SELECT COUNT(*) FROM system_health_events
            WHERE component=%s AND event_type='ESCALATION'
            AND created_at > NOW() - INTERVAL '2 hours'""", [component])
        if (cur.fetchone()[0] or 0) > 0:
            _log_event(conn, component, "ESCALATION_DEDUPED", severity,
                       f"Suppressed duplicate escalation (2h window)", success=True)
            return
    except Exception:
        pass

    msg_lines = [
        f"{'🚨' if severity == 'CRITICAL' else '⚠️'} SYSTEM HEALTH: {comp['display']} — {check_result['status']}",
        "",
        f"Component: {component}",
        f"Expected: {_fmt_schedule(comp.get('schedule', 'unknown'))}",
        f"Last output: {check_result.get('age_min', '?')} min ago",
        f"Status: {check_result['status']}",
    ]
    if check_result.get("last_error"):
        msg_lines.append(f"Error: {check_result['last_error'][:150]}")
    if comp.get("downstream"):
        msg_lines.append(f"Impact: {comp['downstream']}")
    if check_result.get("action_taken"):
        msg_lines.append(f"Action: {check_result['action_taken']}")
    # Add actionable fix instruction
    if comp.get("retry_cmd"):
        msg_lines.append(f"Fix: {comp['retry_cmd'][:100]}")
    else:
        msg_lines.append("Fix: Check logs and restart manually")

    msg = "\n".join(msg_lines)
    _send_alert(msg)
    _log_event(conn, component, "ESCALATION", severity, msg[:500],
               action="telegram_alert", success=True)


def run_health_check(dry_run=True, verbose=False):
    """Run all health checks. Returns full report."""
    conn = _get_conn()
    if not conn:
        log.error("No DB connection")
        return {"error": "no_db"}

    now = datetime.now(timezone.utc)
    report = {
        "timestamp": now.isoformat(),
        "mode": "dry_run" if dry_run else "active",
        "checks": [],
        "summary": {"ok": 0, "stale": 0, "missing": 0, "failed": 0,
                     "locked": 0, "retried": 0, "escalated": 0},
    }

    # Determine if we're in market hours (ET)
    import pytz as _ptz
    _et = _ptz.timezone("US/Eastern")
    _now_et = now.astimezone(_et)
    _current_hour = _now_et.hour
    _is_weekday = _now_et.weekday() < 5

    for comp in MONITORED_COMPONENTS:
        component = comp["component"]
        log_file = comp.get("log_file", "")

        # Schedule-aware staleness: judge freshness against the component's actual cron
        # schedule (day-of-week + hours), not a blind elapsed-time threshold. This is what
        # prevents weekday-only jobs (1-5) from being flagged STALE on weekends, and jobs
        # from being flagged before their first scheduled run of the day.
        _sched = comp.get("schedule", "")
        _prev_fire = None
        if _sched and _sched != "event-driven":
            _prev_fire = _prev_scheduled_fire(_sched, _now_et)
        _grace_min = max(comp.get("max_runtime_sec", 600) / 60.0, 5) + 10

        # 1. Check log freshness (schedule-aware when a scheduled fire time is known)
        freshness = _check_log_freshness(
            log_file, comp.get("max_age_min", 60),
            prev_fire=_prev_fire, now=_now_et, grace_min=_grace_min,
        )

        # 2. Check lock contention
        lock_info = _check_lock_contention(comp.get("lock_file"))

        # 3. Check output validity
        output_check = _check_output_validity(component, log_file, comp.get("error_signatures"),
                                              comp.get("success_signatures"))

        # Build check result
        check = {
            "component": component,
            "display": comp.get("display", component),
            "critical": comp.get("critical", False),
            "schedule": comp.get("schedule", ""),
            "status": freshness["status"],
            "age_min": freshness.get("age_min"),
            "last_line": (freshness.get("last_line") or "")[:100],
            "lock": lock_info["status"],
            "lock_pid": lock_info.get("pid"),
            "lock_runtime": lock_info.get("runtime_sec"),
            "output_valid": output_check.get("valid", True),
            "output_reason": output_check.get("reason", ""),
            "downstream": comp.get("downstream", ""),
            "action_taken": None,
            "last_error": None,
        }

        # 4. Determine action
        needs_action = False
        if freshness["status"] in ("STALE", "MISSING"):
            needs_action = True
            report["summary"]["stale" if freshness["status"] == "STALE" else "missing"] += 1
        elif not output_check.get("valid", True):
            needs_action = True
            check["status"] = "OUTPUT_INVALID"
            check["last_error"] = output_check.get("reason", "unknown")
            report["summary"]["failed"] += 1
        elif lock_info["status"] == "STALE_LOCK":
            needs_action = True
            check["status"] = "STALE_LOCK"
            report["summary"]["locked"] += 1
        elif lock_info["status"] == "LOCKED" and lock_info.get("runtime_sec", 0) > comp.get("max_runtime_sec", 600):
            needs_action = True
            check["status"] = "LOCK_TIMEOUT"
            check["last_error"] = f"Process {lock_info['pid']} running {lock_info['runtime_sec']}s (max {comp.get('max_runtime_sec')}s)"
            report["summary"]["locked"] += 1
        else:
            report["summary"]["ok"] += 1

        # 5. Self-heal
        if needs_action and not dry_run:
            # Try retry first
            if comp.get("retry_cmd"):
                success = _attempt_retry(comp, conn)
                check["action_taken"] = "retry_success" if success else "retry_failed"
                report["summary"]["retried"] += 1
                if success:
                    check["status"] = "RECOVERED"
                    _log_event(conn, component, "RECOVERED", "INFO",
                               f"Self-healed via retry", action=comp["retry_cmd"][:100], success=True)
                else:
                    # Escalate
                    if comp.get("critical"):
                        _escalate(comp, check, conn)
                        check["action_taken"] = "retry_failed_escalated"
                        report["summary"]["escalated"] += 1
            elif comp.get("critical"):
                # No retry cmd but critical — escalate immediately
                _escalate(comp, check, conn)
                check["action_taken"] = "escalated_no_retry"
                report["summary"]["escalated"] += 1

        # 6. Persist check result
        try:
            cur = conn.cursor()
            cur.execute("""INSERT INTO system_health_checks
                (check_type, component, status, expected_schedule, last_success_at,
                 last_failure_at, last_run_duration_sec, expected_max_duration_sec,
                 failure_count, retry_count, last_error, last_action, downstream_impact, severity)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                ["cron_health", component, check["status"], _fmt_schedule(comp.get("schedule")),
                 now if check["status"] == "OK" else None,
                 now if check["status"] not in ("OK", "RECOVERED") else None,
                 None, comp.get("max_runtime_sec"),
                 1 if check["status"] not in ("OK", "RECOVERED") else 0,
                 1 if (check.get("action_taken") or "").startswith("retry") else 0,
                 check.get("last_error"), check.get("action_taken"),
                 comp.get("downstream"),
                 "CRITICAL" if comp.get("critical") and needs_action else "INFO"])
            conn.commit()
        except Exception as e:
            log.warning(f"Failed to persist check for {component}: {e}")

        if verbose:
            icon = "✅" if check["status"] == "OK" else "🔄" if check["status"] == "RECOVERED" else "❌"
            log.info(f"  {icon} {comp['display']:30s} status={check['status']:15s} age={check.get('age_min', '?')}min lock={check['lock']}")

        report["checks"].append(check)

    # ── safe_flock event analysis ──
    sf_summary = _analyze_safe_flock(conn, dry_run=dry_run, verbose=verbose)
    report["safe_flock"] = sf_summary

    # ── Agent staleness check ──
    AGENT_MAX_AGE_DAYS = {
        "maria": 1, "steph": 1, "risk_agent": 1,
        "aegis": 3, "alex": 3, "tax_agent": 7,
        "iris": 7, "maria_research": 7,
    }
    try:
        cur = conn.cursor()
        # Check watchlist_agent_results for most agents
        cur.execute("""SELECT agent, MAX(created_at) as latest
                       FROM watchlist_agent_results GROUP BY agent""")
        agent_latest = {r[0]: r[1] for r in cur.fetchall()}
        # Check agent-specific home tables
        for tbl, col, agent_name in [("aegis_portfolio_briefs", "observed_at", "aegis"),
                                      ("cio_decisions", "created_at", "alex")]:
            try:
                cur.execute(f"SELECT MAX({col}) FROM {tbl}")
                r = cur.fetchone()
                if r and r[0] and (agent_name not in agent_latest or r[0] > agent_latest.get(agent_name, now)):
                    agent_latest[agent_name] = r[0]
            except Exception:
                pass
        stale_agents = []
        for agent, latest in agent_latest.items():
            max_days = AGENT_MAX_AGE_DAYS.get(agent, 7)
            if latest:
                age_days = (now - latest).total_seconds() / 86400
                if age_days > max_days:
                    stale_agents.append(f"{agent}: {age_days:.0f}d stale (max {max_days}d)")
                    if verbose:
                        log.warning(f"  ⚠️  Agent {agent} stale: last ran {age_days:.0f}d ago (max {max_days}d)")
        if stale_agents and not dry_run:
            # Dedup: only alert once per 4 hours per agent set
            _stale_key = ",".join(sorted(stale_agents))
            _dedup_ok = True
            try:
                cur.execute("""SELECT COUNT(*) FROM system_health_events
                    WHERE component='agent_staleness' AND event_type='STALENESS_ALERT'
                    AND created_at > NOW() - INTERVAL '4 hours'""")
                if (cur.fetchone()[0] or 0) > 0:
                    _dedup_ok = False
            except Exception:
                pass
            if _dedup_ok:
                try:
                    from telegram_alert import send_telegram
                    send_telegram("⚠️ AGENT STALENESS\n" + "\n".join(stale_agents))
                    _log_event(conn, "agent_staleness", "STALENESS_ALERT", "WARN",
                               "\n".join(stale_agents), success=True)
                except Exception:
                    pass
            # Auto-remediate: queue jobs for stale agents that process via watchlist_agent_jobs
            _QUEUE_REMEDIATE = {"tax_agent", "iris", "maria_research"}
            for agent, latest in agent_latest.items():
                max_days = AGENT_MAX_AGE_DAYS.get(agent, 7)
                if latest and (now - latest).total_seconds() / 86400 > max_days and agent in _QUEUE_REMEDIATE:
                    try:
                        # Queue a refresh job if none pending
                        cur.execute("""SELECT COUNT(*) FROM watchlist_agent_jobs
                            WHERE requested_agent=%s AND status IN ('queued','pending','processing')""", [agent])
                        if (cur.fetchone()[0] or 0) == 0:
                            # Find a symbol to analyze (most recently analyzed per symbol)
                            cur.execute("""SELECT symbol, MAX(created_at) AS latest
                                FROM watchlist_agent_results
                                WHERE agent=%s GROUP BY symbol ORDER BY latest DESC LIMIT 2""", [agent])
                            _syms = [r[0] for r in cur.fetchall()]
                            for _sym in _syms:
                                cur.execute("""INSERT INTO watchlist_agent_jobs
                                    (id, symbol, requested_agent, request_type, status, priority, submitted_from)
                                    VALUES (%s, %s, %s, 'full_analysis', 'queued', 1, 'health_agent_remediation')""",
                                    [str(uuid.uuid4()), _sym, agent])
                            conn.commit()
                            if _syms:
                                log.info(f"  🔧 Auto-queued {len(_syms)} jobs for stale {agent}")
                    except Exception as _qe:
                        try:
                            conn.rollback()
                        except Exception:
                            pass
                        log.warning(f"  Auto-queue for {agent} failed: {_qe}")
        report["stale_agents"] = stale_agents
    except Exception as e:
        log.warning(f"Agent staleness check failed: {e}")

    # ── Auto-expire stale queue jobs and proposals ──
    try:
        cur = conn.cursor()
        cur.execute("""UPDATE watchlist_agent_jobs SET status='expired', completed_at=NOW()
                       WHERE status IN ('queued','pending') AND created_at < NOW() - INTERVAL '7 days'""")
        expired_jobs = cur.rowcount
        cur.execute("""UPDATE watchlist_agent_jobs SET status='failed', completed_at=NOW()
                       WHERE status='processing' AND started_at < NOW() - INTERVAL '6 hours'""")
        stuck_jobs = cur.rowcount
        cur.execute("""UPDATE watchlist_proposals SET status='expired'
                       WHERE status IN ('proposed','pending') AND created_at < NOW() - INTERVAL '14 days'""")
        expired_proposals = cur.rowcount
        conn.commit()
        if expired_jobs or stuck_jobs or expired_proposals:
            log.info(f"  🧹 Queue cleanup: {expired_jobs} expired jobs, {stuck_jobs} stuck jobs, {expired_proposals} stale proposals")
    except Exception as e:
        log.warning(f"Queue cleanup failed: {e}")

    # ── Proposal lifecycle: enrich-before-reject ──
    # Step 1: Find PENDING proposals that are unenriched for >30 min.
    #         Trigger enrichment instead of rejecting immediately.
    # Step 2: Only reject after enrichment has been attempted 3+ times and failed,
    #         OR after 6 hours regardless.
    try:
        cur = conn.cursor()
        import psycopg2.extras
        rcur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Step 1: Trigger enrichment for stuck proposals (>30 min, <3 attempts)
        rcur.execute("""SELECT id, symbol, enrichment_attempt_count, enrichment_status, packet_state
            FROM paper_trade_proposals
            WHERE status='PENDING'
              AND created_at < NOW() - INTERVAL '30 minutes'
              AND packet_state IN ('MISSING_DATA', 'NEW', 'ENRICHING')
              AND COALESCE(enrichment_attempt_count, 0) < 3
            ORDER BY created_at ASC LIMIT 10""")
        _needs_enrichment = [dict(r) for r in rcur.fetchall()]

        if _needs_enrichment:
            log.info(f"  🔧 Auto-enrichment: {len(_needs_enrichment)} stuck proposals need enrichment")
            try:
                import subprocess
                _enrich_result = subprocess.run(
                    [sys.executable, str(PROJECT_ROOT / "scripts" / "auto_enrichment_runner.py"),
                     "--force-all", "--limit", str(len(_needs_enrichment))],
                    capture_output=True, text=True, timeout=300,
                    cwd=str(PROJECT_ROOT)
                )
                log.info(f"  🔧 Auto-enrichment triggered (rc={_enrich_result.returncode})")
                if _enrich_result.returncode != 0:
                    log.warning(f"  Auto-enrichment stderr: {_enrich_result.stderr[:200]}")

                # Increment attempt counter for proposals we tried
                for p in _needs_enrichment:
                    cur.execute("""UPDATE paper_trade_proposals
                        SET enrichment_attempt_count = COALESCE(enrichment_attempt_count, 0) + 1,
                            enrichment_last_attempt_at = NOW(), updated_at = NOW()
                        WHERE id = %s""", [p["id"]])
                conn.commit()
            except Exception as _ee:
                log.warning(f"  Auto-enrichment trigger failed: {_ee}")

        # Step 2: Reject proposals that have been enrichment-attempted 3+ times and still stuck
        cur.execute("""UPDATE paper_trade_proposals
            SET status='REJECTED', rejection_reason='auto_enrichment_failed_3x',
                rejected_at=NOW(), updated_at=NOW()
            WHERE status='PENDING' AND created_at < NOW() - INTERVAL '2 hours'
            AND (approval_allowed IS NULL OR approval_allowed = false)
            AND packet_state IN ('MISSING_DATA', 'NEW', 'ENRICHING')
            AND COALESCE(enrichment_attempt_count, 0) >= 3""")
        _stuck_proposals = cur.rowcount

        # Step 3: Hard reject after 6 hours regardless (safety net)
        cur.execute("""UPDATE paper_trade_proposals
            SET status='REJECTED', rejection_reason='auto_stale_6h',
                rejected_at=NOW(), updated_at=NOW()
            WHERE status='PENDING' AND created_at < NOW() - INTERVAL '6 hours'""")
        _stale_proposals = cur.rowcount
        conn.commit()
        if _stuck_proposals or _stale_proposals:
            log.info(f"  🧹 Proposal cleanup: {_stuck_proposals} enrichment-failed-3x, {_stale_proposals} stale >6h")
    except Exception as e:
        log.warning(f"Proposal lifecycle cleanup failed: {e}")

    # ── Pipeline output monitoring (detect running-but-broken components) ──
    pipeline_alerts = []
    try:
        cur = conn.cursor()
        import pytz as _ptz_pipe
        _et_pipe = _ptz_pipe.timezone("US/Eastern")
        _now_et_pipe = now.astimezone(_et_pipe)
        _h = _now_et_pipe.hour
        _is_market = 9 <= _h <= 16 and _now_et_pipe.weekday() < 5

        if _is_market and not dry_run:
            # 1. Log error content scanning — detect Python crashes in key logs
            _ERROR_PATTERNS = ["Traceback", "NameError", "RISK_GATE_ERROR", "CRITICAL", "FATAL"]
            _SCAN_LOGS = ["auto_proposal.log", "screener_pm.log", "incubator_promoter.log",
                          "paper_execution.log", "unified_stop_supervisor.log"]
            for _logname in _SCAN_LOGS:
                _logpath = PROJECT_ROOT / "logs" / _logname
                if _logpath.exists():
                    try:
                        _tail = _logpath.read_text()[-3000:]
                        _err_count = sum(_tail.count(p) for p in _ERROR_PATTERNS)
                        if _err_count >= 3:
                            pipeline_alerts.append(f"🔴 {_logname}: {_err_count} errors in recent output")
                    except Exception:
                        pass

            # 2. Proposal creation rate — 0 proposals during market hours for >2h
            cur.execute("""SELECT COUNT(*) FROM paper_trade_proposals
                WHERE created_at > NOW() - INTERVAL '3 hours' AND created_at::date = CURRENT_DATE""")
            _recent_proposals = cur.fetchone()[0] or 0
            if _recent_proposals == 0 and _h >= 10:
                pipeline_alerts.append(f"⚠️ 0 proposals created in last 3 hours (market open)")

            # 3. Signal generation — 0 signals today after 10 AM.
            # Include universe size so the cause is attributable: a thin universe points upstream
            # (screener/Finviz), NOT the orchestrator. Root cause (e.g. 429) is carried by check #9.
            cur.execute("SELECT COUNT(*) FROM strategy_signals WHERE fired_at::date = CURRENT_DATE")
            _today_signals = cur.fetchone()[0] or 0
            if _today_signals == 0 and _h >= 10:
                cur.execute("SELECT COUNT(DISTINCT symbol) FROM trade_ai_scans WHERE scanned_at::date = CURRENT_DATE")
                _uni_today = cur.fetchone()[0] or 0
                pipeline_alerts.append(
                    f"⚠️ 0 signals generated today (universe={_uni_today} symbols) — "
                    f"check Finviz 429/screener if universe is thin, else orchestrator scoring")

            # 4. Trade execution rate — ATM active but 0 trades after 10 AM
            cur.execute("SELECT mode FROM atm_state WHERE id=1")
            _atm_row = cur.fetchone()
            _atm_mode = _atm_row[0] if _atm_row else "unknown"
            if _atm_mode == "active":
                cur.execute("""SELECT COUNT(*) FROM paper_trades
                    WHERE entry_time::date = CURRENT_DATE AND status != 'cancelled'""")
                _today_trades = cur.fetchone()[0] or 0
                if _today_trades == 0 and _h >= 11:
                    pipeline_alerts.append(f"⚠️ ATM=active but 0 trades today (check proposal pipeline)")

            # 5. Alpaca position sync — DB vs broker divergence
            cur.execute("SELECT COUNT(*) FROM paper_trades WHERE status='open' AND (last_synced_at IS NULL OR last_synced_at < NOW() - INTERVAL '4 hours')")
            _unsync = cur.fetchone()[0] or 0
            if _unsync > 0:
                pipeline_alerts.append(f"📊 {_unsync} open trade(s) not synced with broker in 4h+")

            # 6. Screener data quality
            cur.execute("""SELECT COUNT(*) FROM trade_ai_scans
                WHERE scanned_at::date = CURRENT_DATE AND (float_m IS NULL OR float_m = 0)""")
            _zero_float = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM trade_ai_scans WHERE scanned_at::date = CURRENT_DATE")
            _total_scans = cur.fetchone()[0] or 0
            if _total_scans > 0 and _zero_float / _total_scans > 0.5:
                pipeline_alerts.append(f"⚠️ Screener data quality: {_zero_float}/{_total_scans} scans have zero float")

            # 7. Open trade agent coverage — detect trades with no recent agent analysis
            try:
                cur.execute("""SELECT pt.symbol FROM paper_trades pt
                    WHERE pt.status = 'open'
                    AND NOT EXISTS (
                        SELECT 1 FROM watchlist_agent_results war
                        WHERE war.symbol = pt.symbol
                        AND war.created_at > NOW() - INTERVAL '3 days'
                    )""")
                _uncovered = [r[0] for r in cur.fetchall()]
                if _uncovered:
                    pipeline_alerts.append(
                        f"⚠️ {len(_uncovered)} open trade(s) with no agent analysis in 3 days: {', '.join(_uncovered[:5])}"
                    )
            except Exception:
                pass

            # 8. Pre-promotion gate blocking — detect if ALL proposals are being blocked
            try:
                import pathlib as _pl
                _olog = _pl.Path(PROJECT_ROOT / "logs" / "screener_pm.log")
                if _olog.exists():
                    _tail = _olog.read_text()[-5000:]
                    _blocked = _tail.count("BLOCKED by pre-promotion gate")
                    _created = _tail.count("CREATED proposal")
                    if _blocked > 0 and _created > 0 and _blocked >= _created:
                        # Check for floating point R:R false blocks
                        _rr_blocks = _tail.count("rr_below_minimum")
                        if _rr_blocks > 0:
                            pipeline_alerts.append(
                                f"⚠️ Pre-promotion gate blocking {_blocked}/{_created} proposals "
                                f"({_rr_blocks} R:R blocks — check floating point tolerance)"
                            )
                        else:
                            pipeline_alerts.append(
                                f"⚠️ Pre-promotion gate blocking {_blocked}/{_created} proposals"
                            )
            except Exception:
                pass

            # 9. Finviz rate-limiting — ROOT CAUSE of a starved universe → 0 GO/A+ → 0 signals
            # (added 2026-06-22 after a 429 storm collapsed the universe to ~40-70 symbols and
            # produced 0 signals for every strategy, which earlier looked like a fib-specific bug).
            # Detects the cause directly so the alert is actionable instead of "orchestrator broken".
            try:
                _fv_log = PROJECT_ROOT / "logs" / "finviz_screener.log"
                _fv_429_thresh = int(os.getenv("HEALTH_FINVIZ_429_THRESHOLD", "100"))
                if _fv_log.exists():
                    _fv_tail = _fv_log.read_text()[-40000:]
                    _fv_429 = _fv_tail.count("Too Many Requests")
                    if _fv_429 >= _fv_429_thresh:
                        pipeline_alerts.append(
                            f"🔴 Finviz rate-limited (HTTP 429 ×{_fv_429} in recent log) — screener "
                            f"universe starved; signal generation will be thin/zero until it clears")
            except Exception:
                pass

        if pipeline_alerts:
            report["pipeline_alerts"] = pipeline_alerts
            log.info(f"  Pipeline issues: {len(pipeline_alerts)}")
            for _pa in pipeline_alerts:
                log.info(f"    {_pa}")
            # Alert (dedup: max 1 per 2 hours)
            _pipe_dedup_ok = True
            try:
                cur.execute("""SELECT COUNT(*) FROM system_health_events
                    WHERE component='pipeline_output' AND event_type='PIPELINE_ALERT'
                    AND created_at > NOW() - INTERVAL '2 hours'""")
                if (cur.fetchone()[0] or 0) > 0:
                    _pipe_dedup_ok = False
            except Exception:
                pass
            if _pipe_dedup_ok:
                try:
                    from telegram_alert import send_telegram
                    send_telegram("🔴 PIPELINE HEALTH\n" + "\n".join(pipeline_alerts))
                    _log_event(conn, "pipeline_output", "PIPELINE_ALERT", "WARN",
                               "\n".join(pipeline_alerts), success=True)
                except Exception:
                    pass
    except Exception as e:
        log.warning(f"Pipeline output monitoring failed: {e}")

    # ── Portfolio risk checks (5 conditions from Command Center) ──
    portfolio_alerts = []
    try:
        _state_dir = PROJECT_ROOT / "data" / "portfolios" / "state"
        _rm = {}
        _rm_path = _state_dir / "risk_management.json"
        if _rm_path.exists():
            import json as _json_rm
            _rm = _json_rm.loads(_rm_path.read_text())

        # 1. Triggered stops
        _STOP_EXEMPT = {"fidelity_401k", "schwab_rollover_ira", "schwab_roth_ira", "schwab_roth", "schwab_taxable"}
        _triggered = [p for p in _rm.get("positions", [])
                      if p.get("status") == "TRIGGERED"
                      and (p.get("account", "") or "").lower() not in _STOP_EXEMPT]
        if _triggered:
            _syms = ", ".join(p.get("symbol", "?") for p in _triggered[:5])
            portfolio_alerts.append(f"🚨 {len(_triggered)} stop(s) triggered: {_syms}")

        # 2. Portfolio heat
        _heat = _rm.get("portfolio_heat_pct", 0)
        if _heat > 5:
            portfolio_alerts.append(f"⚠️ Portfolio heat {_heat:.1f}% — above 5% threshold")

        # 3. No-stop positions
        _no_stop = sum(1 for p in _rm.get("positions", [])
                       if p.get("status") == "NO STOP"
                       and (p.get("account", "") or "").lower() not in _STOP_EXEMPT)
        if _no_stop > 5:
            portfolio_alerts.append(f"⚠️ {_no_stop} positions without stops")

        # 4. CIO critical decisions
        _cio = _db_query("""SELECT COUNT(*) as cnt FROM cio_decisions
            WHERE priority IN ('critical','high')
            AND status NOT IN ('completed','dismissed')
            AND created_at > NOW() - INTERVAL '7 days'""", fetch="one") if not dry_run else {}
        _cio_cnt = (_cio or {}).get("cnt", 0)
        if _cio_cnt > 0:
            portfolio_alerts.append(f"⚡ {_cio_cnt} CIO critical/high decisions pending")

        # 5. Paper trade drift (open trades with no recent price sync)
        _stale_trades = _db_query("""SELECT COUNT(*) as cnt FROM paper_trades
            WHERE status='open' AND (last_synced_at IS NULL OR last_synced_at < NOW() - INTERVAL '4 hours')""",
            fetch="one") if not dry_run else {}
        _stale_trade_cnt = (_stale_trades or {}).get("cnt", 0)
        if _stale_trade_cnt > 0:
            portfolio_alerts.append(f"📊 {_stale_trade_cnt} paper trade(s) not synced in 4h+")

        # 6. Portfolio live prices (Finviz repricer — not SnapTrade, not holdings file mtime)
        portfolio_alerts.extend(_portfolio_price_freshness_alerts(_now_et))

        if portfolio_alerts:
            report["portfolio_alerts"] = portfolio_alerts
            log.info(f"  Portfolio risks: {len(portfolio_alerts)}")
            for _pa in portfolio_alerts:
                log.info(f"    {_pa}")
    except Exception as e:
        log.warning(f"Portfolio risk check failed: {e}")

    # ── Stop monitoring health (lifecycle orphans, naked, stale advisories) ──
    stop_monitoring_alerts = []
    try:
        from lib.stop_monitoring_health import run_stop_monitoring_health
        _sm = run_stop_monitoring_health(conn, apply=not dry_run)
        report["stop_monitoring"] = _sm
        stop_monitoring_alerts = _sm.get("alerts") or []
        _sm_issues = (_sm.get("diagnosis") or {}).get("issues") or []
        if _sm_issues:
            log.info(f"  Stop monitoring: {len(_sm_issues)} issue(s)")
            for _sa in stop_monitoring_alerts[:8]:
                log.info(f"    {_sa}")
        if stop_monitoring_alerts:
            portfolio_alerts.extend(stop_monitoring_alerts)
            report["portfolio_alerts"] = portfolio_alerts
    except Exception as e:
        log.warning(f"Stop monitoring health failed: {e}")

    # ── Claude Code escalation queue ──
    # Write unresolved problems to escalation file for Claude Code to pick up
    _escalation_items = []
    # Collect failed retries
    for check in report.get("checks", []):
        if check.get("action_taken") in ("retry_failed_escalated", "escalated_no_retry"):
            _escalation_items.append({
                "component": check.get("component"),
                "status": check.get("status"),
                "age_min": check.get("age_min"),
                "last_error": check.get("last_error"),
                "retry_cmd": check.get("retry_cmd"),
            })
    # Add stale agents that auto-remediation couldn't fix
    for sa in report.get("stale_agents", []):
        _escalation_items.append({"component": "agent_staleness", "detail": sa})
    # Add portfolio alerts (informational)
    for pa in portfolio_alerts:
        _escalation_items.append({"component": "portfolio_risk", "detail": pa})
    # Add pipeline alerts — these ARE fixable by Claude Code (log errors, broken scripts)
    for pa in pipeline_alerts:
        _escalation_items.append({"component": "pipeline_output", "detail": pa, "fixable": True})
    # Add enrichment-failed proposals that exhausted auto-remediation attempts
    try:
        _ecur = conn.cursor()
        _ecur.execute("""SELECT id, symbol, enrichment_attempt_count, created_at
            FROM paper_trade_proposals
            WHERE status='PENDING' AND packet_state IN ('NEW', 'MISSING_DATA', 'ENRICHING')
            AND COALESCE(enrichment_attempt_count, 0) >= 2
            AND created_at < NOW() - INTERVAL '1 hour'""")
        for _er in _ecur.fetchall():
            _escalation_items.append({
                "component": "proposal_enrichment_stuck",
                "detail": f"Proposal #{_er[0]} {_er[1]} stuck after {_er[2]} enrichment attempts (created {_er[3]})",
                "fixable": True,
                "retry_cmd": f".venv/bin/python scripts/auto_enrichment_runner.py --force-all --limit 5",
            })
    except Exception:
        pass

    if _escalation_items and not dry_run:
        try:
            import json as _esc_json
            _esc_file = PROJECT_ROOT / "logs" / "claude_escalation_queue.json"
            _existing = []
            if _esc_file.exists():
                try:
                    _existing = _esc_json.loads(_esc_file.read_text())
                except Exception:
                    _existing = []
            # Append new items with timestamp
            for item in _escalation_items:
                item["escalated_at"] = now.isoformat()
                item["source"] = "system_health_agent"
            _existing.extend(_escalation_items)
            # Keep only last 50 items
            _existing = _existing[-50:]
            _esc_file.write_text(_esc_json.dumps(_existing, indent=2, default=str))
            log.info(f"  📋 {len(_escalation_items)} items written to claude_escalation_queue.json")
        except Exception as e:
            log.warning(f"Claude escalation queue write failed: {e}")

    report["portfolio_alerts"] = portfolio_alerts
    conn.close()
    return report


# Helper for portfolio risk DB queries
def _db_query(sql, params=None, fetch="all"):
    try:
        from db_adapter import _get_conn as _gq_conn
        _c = _gq_conn()
        _cur = _c.cursor()
        _cur.execute(sql, params)
        if fetch == "one":
            _cols = [d[0] for d in _cur.description]
            _row = _cur.fetchone()
            _c.close()
            return dict(zip(_cols, _row)) if _row else {}
        _cols = [d[0] for d in _cur.description]
        _rows = [dict(zip(_cols, r)) for r in _cur.fetchall()]
        _c.close()
        return _rows
    except Exception:
        return {} if fetch == "one" else []


def main():
    p = argparse.ArgumentParser(description="System Health Execution Integrity Agent")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--output-json", type=str)
    args = p.parse_args()
    if args.apply:
        args.dry_run = False

    report = run_health_check(dry_run=args.dry_run, verbose=args.verbose)

    s = report.get("summary", {})
    mode = "DRY RUN" if args.dry_run else "ACTIVE"
    total = sum(s.values())
    log.info(f"[{mode}] Health check complete: {s['ok']}/{total} OK, "
             f"{s['stale']} stale, {s['missing']} missing, {s['failed']} failed, "
             f"{s['locked']} locked, {s['retried']} retried, {s['escalated']} escalated")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))

    # Return non-zero if any critical component is down
    critical_down = [c for c in report.get("checks", [])
                     if c.get("critical") and c.get("status") not in ("OK", "RECOVERED")]
    if critical_down and not args.dry_run:
        sys.exit(1)


if __name__ == "__main__":
    main()
