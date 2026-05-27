#!/usr/bin/env python3
"""system_health_agent.py — Execution Integrity Agent.

Continuously monitors every cron job, process, and execution path.
Detects silent failures, lock contention, stale output, abnormal runtimes.
Self-heals with retries. Escalates via central alert router.

Schedule: */5 * * * 1-5 (every 5 min weekdays), */15 * * * 0,6 (every 15 min weekends)

NO bypass_router. NO direct Telegram. ALL alerts through central router.
"""
import argparse, json, logging, os, subprocess, sys, time
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
     "schedule": "0 6,12,18 * * *", "log_file": "news_ingestion.log",
     "max_age_min": 480, "max_runtime_sec": 600, "critical": True,
     "retry_cmd": ".venv/bin/python scripts/news_ingestion.py --priority",
     "downstream": "catalyst detection, news alerts"},

    # ── Trade Monitoring ──
    {"component": "unified_stop_supervisor", "display": "Stop Supervisor",
     "schedule": "*/3 9-16 * * 1-5", "log_file": "unified_stop_supervisor.log",
     "max_age_min": 10, "max_runtime_sec": 120, "critical": True,
     "retry_cmd": ".venv/bin/python scripts/unified_stop_supervisor.py --apply",
     "downstream": "trailing stops, target exits, stop monitoring"},
    # paper_trade_monitor replaced by unified_stop_supervisor (STOP-V2.2)
    {"component": "alpaca_reconciler", "display": "Alpaca Reconciler",
     "schedule": "5 16 * * 1-5", "log_file": "alpaca_reconciler.log",
     "max_age_min": 1500, "max_runtime_sec": 60, "critical": False,
     "downstream": "DB-broker sync"},

    # ── Data Pipeline ──
    {"component": "finviz_enrichment", "display": "Finviz Enrichment",
     "schedule": "10 7 * * 1-5", "log_file": "finviz_enrichment.log",
     "max_age_min": 1500, "max_runtime_sec": 600, "critical": False,
     "downstream": "enriched scanner data"},
    {"component": "price_db_sync", "display": "Price DB Sync",
     "schedule": "20 7 * * 1-5", "log_file": "price_db_sync.log",
     "max_age_min": 1500, "max_runtime_sec": 600, "critical": False,
     "downstream": "price data freshness"},
    {"component": "rag_indexer", "display": "RAG Indexer",
     "schedule": "0 */4 * * *", "log_file": "rag_indexer.log",
     "max_age_min": 300, "max_runtime_sec": 600, "critical": False,
     "downstream": "agent context, RAG search"},
    {"component": "indicator_engine", "display": "Indicator Engine",
     "schedule": "0 8 * * 1-5", "log_file": "indicator_engine.log",
     "max_age_min": 1500, "max_runtime_sec": 900, "critical": False,
     "downstream": "technical indicators"},

    # ── Agents ──
    {"component": "aegis_morning_brief", "display": "Aegis Morning Brief",
     "schedule": "5 8 * * 1-5", "log_file": "aegis_brief.log",
     "max_age_min": 1500, "max_runtime_sec": 300, "critical": False,
     "downstream": "daily brief delivery"},
    {"component": "telegram_command_handler", "display": "Telegram Bot Daemon",
     "schedule": "*/2 * * * *", "log_file": "telegram_commands.log",
     "max_age_min": 5, "max_runtime_sec": 60, "critical": True,
     "downstream": "operator commands, approval buttons"},

    # ── Cleanup & Governance ──
    {"component": "cleanup_stale_proposals", "display": "Stale Proposal Cleanup",
     "schedule": "0 10,15 * * 1-5", "log_file": "cleanup_stale_proposals.log",
     "max_age_min": 1500, "max_runtime_sec": 60, "critical": False,
     "downstream": "proposal hygiene"},
    {"component": "pipeline_watchdog", "display": "Pipeline Watchdog",
     "schedule": "0 */2 * * *", "log_file": "pipeline_watchdog.log",
     "max_age_min": 150, "max_runtime_sec": 300, "critical": True,
     "downstream": "pipeline self-healing"},

    # ── TCA ──
    {"component": "tca_analyzer", "display": "TCA Execution Quality",
     "schedule": "30 16 * * 1-5", "log_file": "tca_analyzer.log",
     "max_age_min": 1500, "max_runtime_sec": 60, "critical": False,
     "downstream": "execution quality page"},

    # ── Quote Refresh ──
    {"component": "proactive_quote_refresh", "display": "Quote Refresh",
     "schedule": "*/5 9-15 * * 1-5", "log_file": "proactive_quote_refresh_cron.log",
     "max_age_min": 15, "max_runtime_sec": 120, "critical": False,
     "downstream": "proposal price freshness"},
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


def _check_log_freshness(log_file, max_age_min):
    """Check if log file has recent output."""
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


def _check_output_validity(component, log_file):
    """Check if the last run produced meaningful output (not just errors)."""
    log_path = PROJECT_ROOT / "logs" / log_file
    if not log_path.exists():
        return {"valid": False, "reason": "log_missing"}
    try:
        with open(log_path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 2000))
            tail = f.read().decode('utf-8', errors='replace')
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
        if retries_today >= MAX_RETRIES:
            _log_event(conn, component, "RETRY_EXHAUSTED", "CRITICAL",
                       f"Max retries ({MAX_RETRIES}) exhausted today", success=False)
            return False
    except Exception:
        pass

    # Clear stale lock if present
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

    log.info(f"[retry] {component} — attempt {retries_today + 1}/{MAX_RETRIES}")
    try:
        result = subprocess.run(
            cmd, shell=True, timeout=comp.get("max_runtime_sec", 300),
            capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        success = result.returncode == 0
        _log_event(conn, component, "RETRY", "INFO" if success else "WARN",
                   f"exit={result.returncode} stdout={result.stdout[-200:]}" if success
                   else f"exit={result.returncode} stderr={result.stderr[-200:]}",
                   action=cmd[:100], success=success)
        return success
    except subprocess.TimeoutExpired:
        _log_event(conn, component, "RETRY_TIMEOUT", "WARN",
                   f"Retry timed out after {comp.get('max_runtime_sec', 300)}s",
                   action=cmd[:100], success=False)
        return False
    except Exception as e:
        _log_event(conn, component, "RETRY_ERROR", "WARN", str(e)[:200],
                   action=cmd[:100], success=False)
        return False


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
        f"Expected: {comp.get('schedule', 'unknown')}",
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

    for comp in MONITORED_COMPONENTS:
        component = comp["component"]
        log_file = comp.get("log_file", "")

        # 1. Check log freshness
        freshness = _check_log_freshness(log_file, comp.get("max_age_min", 60))

        # 2. Check lock contention
        lock_info = _check_lock_contention(comp.get("lock_file"))

        # 3. Check output validity
        output_check = _check_output_validity(component, log_file)

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
                ["cron_health", component, check["status"], comp.get("schedule"),
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
                            # Find a symbol to analyze (most recent holding)
                            cur.execute("""SELECT DISTINCT symbol FROM watchlist_agent_results
                                WHERE agent=%s ORDER BY created_at DESC LIMIT 3""", [agent])
                            _syms = [r[0] for r in cur.fetchall()]
                            for _sym in _syms[:2]:
                                cur.execute("""INSERT INTO watchlist_agent_jobs
                                    (symbol, requested_agent, request_type, status, priority, submitted_from)
                                    VALUES (%s, %s, 'full_analysis', 'queued', 1, 'health_agent_remediation')""",
                                    [_sym, agent])
                            conn.commit()
                            if _syms:
                                log.info(f"  🔧 Auto-queued {len(_syms[:2])} jobs for stale {agent}")
                    except Exception as _qe:
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

    conn.close()
    return report


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
