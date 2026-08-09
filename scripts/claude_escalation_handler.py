#!/usr/bin/env python3
"""claude_escalation_handler.py — Process health agent escalations.

Processes escalation queue with 3-tier approach:
  1. Safe retry_cmd direct execution (allowlisted, logged, timeboxed)
  2. Local LLM diagnosis for fixable items
  3. Claude Code CLI for unresolved problems

Usage:
    .venv/bin/python scripts/claude_escalation_handler.py
    .venv/bin/python scripts/claude_escalation_handler.py --dry-run
    .venv/bin/python scripts/claude_escalation_handler.py --dry-run --tier1-only
    .venv/bin/python scripts/claude_escalation_handler.py --no-llm   # tier1 only, apply retries

Hang note: without --tier1-only / --no-llm, Tier 2 (Ollama) + Tier 3a (llama.cpp 600s)
can look stuck with little stdout — check logs/claude_escalation.log.
"""
import hashlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from lib.live_project_root import get_live_project_root   # noqa: E402
PROJECT_ROOT = get_live_project_root()

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

QUEUE_FILE = PROJECT_ROOT / "logs" / "claude_escalation_queue.json"
STALENESS_QUEUE_FILE = PROJECT_ROOT / "data" / "runtime" / "staleness_escalation_queue.json"
RETRY_LOG = PROJECT_ROOT / "logs" / "claude_escalation_retry_cmd.jsonl"
ALLOWLIST_FILE = PROJECT_ROOT / "config" / "claude_escalation_allowlist.yaml"
LOG_DIR = PROJECT_ROOT / "logs"


def _safe_write_queue(path, items):
    """Write *items* to *path* using flock-guarded atomic write when available."""
    try:
        from lib.queue_file import write_items
        write_items(path, items)
    except Exception:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(items, indent=2) if items else "[]")
        except Exception:
            pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [claude-escalation] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "claude_escalation.log"),
    ]
)
log = logging.getLogger("claude-escalation")


# ── Allowlist ────────────────────────────────────────────────────────────

def _load_allowlist():
    """Load retry command allowlist from YAML config."""
    try:
        import yaml
        with open(ALLOWLIST_FILE) as f:
            return yaml.safe_load(f)
    except ImportError:
        # Fallback: parse YAML manually for simple structure
        try:
            text = ALLOWLIST_FILE.read_text()
            config = {"allowed_script_patterns": [], "blocked_patterns": [],
                      "max_runtime_seconds": 120, "environment_guards": {}}
            section = None
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("allowed_script_patterns"):
                    section = "allowed"
                elif line.startswith("blocked_patterns"):
                    section = "blocked"
                elif line.startswith("max_runtime_seconds"):
                    config["max_runtime_seconds"] = int(line.split(":")[1].strip())
                elif line.startswith("environment_guards"):
                    section = "env"
                elif line.startswith("- ") and section:
                    val = line[2:].strip().strip('"').strip("'")
                    if section == "allowed":
                        config["allowed_script_patterns"].append(val)
                    elif section == "blocked":
                        config["blocked_patterns"].append(val)
                elif ":" in line and section == "env" and not line.startswith("#"):
                    k, v = line.split(":", 1)
                    config["environment_guards"][k.strip()] = v.strip().strip('"').strip("'")
            return config
        except Exception:
            return None
    except Exception:
        return None


def _check_allowlist(cmd, allowlist):
    """Check if a command is allowed, blocked, or needs manual review.
    Returns (allowed: bool, reason: str)."""
    if not allowlist:
        return False, "no_allowlist_config"
    if not cmd:
        return False, "empty_command"

    cmd_lower = cmd.lower()

    # Check blocked patterns first (hard deny).
    # Use word-boundary matching so a blocked pattern like "submit_order" doesn't
    # also block benign flags like "--submit-validation".  The old substring match
    # ("submit" blocked every --submit-* flag for days — 2026-08-07 incident).
    for pattern in allowlist.get("blocked_patterns", []):
        pl = pattern.lower()
        # Match as a whole word/token: preceded by start-of-string, whitespace,
        # or a path/flag delimiter; followed by end-of-string, whitespace, or
        # a flag delimiter.  This correctly blocks "submit_order --symbol X"
        # while allowing "--submit-validation --symbol X".
        if re.search(rf'(?<![\w/-]){re.escape(pl)}(?![\w-])', cmd_lower):
            return False, f"blocked_pattern: {pattern}"

    # Check environment guards
    for env_key, expected in allowlist.get("environment_guards", {}).items():
        actual = os.getenv(env_key, "")
        if actual != expected:
            return False, f"env_guard_failed: {env_key}={actual}, expected={expected}"

    # Check allowed script patterns
    for pattern in allowlist.get("allowed_script_patterns", []):
        if pattern in cmd:
            return True, f"allowed_pattern: {pattern}"

    return False, "not_in_allowlist"


def _log_retry(item, cmd, allowed, reason, status, exit_code=None,
               stdout="", stderr="", duration=0, verify_exit=None):
    """Append retry execution log to JSONL."""
    try:
        RETRY_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": item.get("component", "unknown"),
            "fixable": item.get("fixable", False),
            "retry_cmd": cmd,
            "retry_cmd_hash": hashlib.sha256(cmd.encode()).hexdigest()[:12] if cmd else "",
            "allowlist_result": "allowed" if allowed else "blocked",
            "blocked_reason": reason if not allowed else "",
            "status": status,
            "exit_code": exit_code,
            "stdout_tail": stdout[-500:] if stdout else "",
            "stderr_tail": stderr[-500:] if stderr else "",
            "duration_seconds": round(duration, 1),
            "verify_exit_code": verify_exit,
            "env_alpaca_mode": os.getenv("ALPACA_MODE", ""),
            "env_llm_disable": os.getenv("LLM_DISABLE_LIVE_EXECUTION", ""),
        }
        with open(RETRY_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _finding_type_from_component(component: str) -> str:
    """health:category:type → type (handles multi-colon types like agent::x)."""
    if not component or not str(component).startswith("health:"):
        return ""
    parts = str(component).split(":", 2)
    return parts[2] if len(parts) >= 3 else ""


# Must match health_agent / lib.watchlist_priority (decision-feeding SLA types).
_TIME_SENSITIVE_REQUEST_TYPES = (
    "proposal_review", "full_analysis", "research_gap", "event", "go_signal_review",
)


def _db_verify(sql: str, params=None) -> tuple[bool, object, str]:
    """Run a verify query with rollback on error so the connection stays usable.

    Returns (ok, scalar_or_none, note). ok=False means verify failed (do NOT mark fixed).
    """
    conn = _get_conn()
    if not conn:
        return False, None, "no_db"
    cur = None
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        row = cur.fetchone()
        conn.commit()
        return True, (row[0] if row else None), "ok"
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return False, None, f"verify_error:{e}"
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass


def _verify_remediation(item) -> tuple[bool, str]:
    """Post-retry verify: only mark fixed when the issue is actually clear.

    Returns (cleared, note). On verify SQL/IO errors return cleared=False (fail closed)
    so exit-0 thrash cannot mark 'fixed' while the finding is still active.
    Unknown types return (True, 'no_verify') for legacy allowlisted producers.
    """
    ftype = _finding_type_from_component(item.get("component", ""))
    if not ftype:
        return True, "no_verify_unknown_component"

    # Paper stuck: zero APPROVED_FOR_PAPER_TEST rows remaining
    if ftype == "approved_paper_test_stuck":
        ok, n, note = _db_verify(
            "SELECT COUNT(*) FROM paper_trade_proposals WHERE status = 'APPROVED_FOR_PAPER_TEST'"
        )
        if not ok:
            return False, note
        n = int(n or 0)
        if n == 0:
            return True, "paper_stuck_cleared"
        return False, f"paper_stuck_still_{n}"

    # Backups: newest full dump < 26h and ≥ 500MB
    if ftype in ("backup_cadence_stale", "db_dump_stale", "db_dump_missing"):
        try:
            import glob
            import time as _t
            min_b = 500 * 1024 * 1024
            dumps = []
            for p in glob.glob(str(Path.home() / "db_backups" / "trade_ai_*.sql.gz")):
                st = Path(p).stat()
                if st.st_size >= min_b:
                    dumps.append(st.st_mtime)
            if not dumps:
                return False, "no_full_dump"
            age_h = (_t.time() - max(dumps)) / 3600
            if age_h <= 26:
                return True, f"dump_age_{age_h:.1f}h"
            return False, f"dump_still_stale_{age_h:.1f}h"
        except Exception as e:
            return False, f"verify_error:{e}"

    # Indicators: max(computed_at) within 48h
    if ftype in ("indicator_snapshot_stale", "indicator_snapshots_stale"):
        ok, age, note = _db_verify(
            "SELECT EXTRACT(EPOCH FROM (now() - MAX(computed_at)))/3600 "
            "FROM indicator_signal_history"
        )
        if not ok:
            return False, note
        age_f = float(age) if age is not None else 9999.0
        if age_f <= 48:
            return True, f"indicator_age_{age_f:.1f}h"
        return False, f"indicator_still_{age_f:.1f}h"

    # Scalp GO dark: at least 1 GO in 3d window after retry — else ineffective.
    # Product-regime hold (low_max_score_regime recorded in root-cause memory with
    # hold_until in the future) is treated as verified "accepted" so we do not thrash
    # exit-0 scanner retries every 10m while max_score stays below GO_THRESHOLD.
    if ftype == "scalp_catalyst_verification_dead":
        ok, n, note = _db_verify("""
            SELECT COUNT(*) FROM scalp_scan_results
            WHERE scanned_at > now() - interval '3 days'
              AND decision = 'GO'
        """)
        if not ok:
            return False, note
        n = int(n or 0)
        if n > 0:
            return True, f"scalp_go_{n}"
        try:
            from lib import health_root_cause_memory as _rcmem
            mem = _rcmem.summary_for("scalp_catalyst_verification_dead")
            hold_until = mem.get("hold_until")
            rc = mem.get("last_root_cause") or ""
            if hold_until and rc in ("low_max_score_regime", "news_or_social_feed_dead"):
                from datetime import datetime, timezone
                hu = datetime.fromisoformat(str(hold_until).replace("Z", "+00:00"))
                if datetime.now(timezone.utc) < hu:
                    return True, f"scalp_hold_accepted rc={rc} until={hold_until}"
        except Exception:
            pass
        return False, "scalp_go_still_zero"

    # SETUPS session: run_date == today ET
    if ftype in ("trade_ai_session_stale", "trade_ai_session_missing", "orchestrator_setups_stale"):
        try:
            from zoneinfo import ZoneInfo
            today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        except Exception:
            today = datetime.now().date().isoformat()
        for p in (
            PROJECT_ROOT / "data" / "runtime" / "trade_ai_cache.json",
            Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT/data/runtime/trade_ai_cache.json"),
        ):
            try:
                if p.exists():
                    rd = str(json.loads(p.read_text()).get("run_date") or "")[:10]
                    if rd == today:
                        return True, f"session_run_date_{rd}"
                    return False, f"session_still_{rd}_want_{today}"
            except Exception as e:
                return False, f"verify_error:{e}"
        return False, "session_cache_missing"

    # pipeline_failures: unrecovered real pipeline_runs (not just job backlog)
    if ftype == "pipeline_failures":
        ok, n, note = _db_verify(
            """
            SELECT COUNT(*) FROM pipeline_runs f
            WHERE f.status='failed'
              AND f.started_at > now() - interval '24 hours'
              AND (f.summary IS NULL OR f.summary::text NOT LIKE '%%zombie run cleared%%')
              AND NOT EXISTS (
                SELECT 1 FROM pipeline_runs s
                WHERE s.pipeline_key = f.pipeline_key
                  AND s.status = 'success'
                  AND s.started_at > f.started_at
              )
            """
        )
        if not ok:
            return False, note
        n = int(n or 0)
        # Also require SLA backlog under floor
        ok2, n2, note2 = _db_verify(
            """
            SELECT COUNT(*) FROM watchlist_agent_jobs
            WHERE status IN ('queued', 'pending')
              AND created_at < now() - interval '2 hours'
              AND request_type = ANY(%s)
            """,
            (list(_TIME_SENSITIVE_REQUEST_TYPES),),
        )
        if not ok2:
            return False, note2
        n2 = int(n2 or 0)
        if n == 0 and n2 < 10:
            return True, f"pipeline_ok unrecovered=0 sla={n2}"
        return False, f"pipeline_still unrecovered={n} sla={n2}"

    # Agent jobs backlog: decision-feeding (SLA) types only — matches health_agent
    if ftype in ("agent_jobs_stuck", "agent_jobs_stale"):
        ok, n, note = _db_verify(
            """
            SELECT COUNT(*) FROM watchlist_agent_jobs
            WHERE status IN ('queued', 'pending')
              AND created_at < now() - interval '2 hours'
              AND request_type = ANY(%s)
            """,
            (list(_TIME_SENSITIVE_REQUEST_TYPES),),
        )
        if not ok:
            return False, note
        n = int(n or 0)
        # Progress counts: cleared only when under health warning floor
        if n < 10:
            return True, f"jobs_sla_backlog_{n}"
        return False, f"jobs_sla_backlog_still_{n}"

    return True, "no_verify"


def _cmd_timeout_seconds(cmd: str, allowlist: dict | None) -> int:
    """Per-command timeouts so one long ingest cannot stall the whole tier1 batch."""
    base = int((allowlist or {}).get("max_runtime_seconds", 120) or 120)
    c = (cmd or "").lower()
    if "process_watchlist_agent_jobs" in c:
        return max(base, 300)  # drain batches need wall time
    if "run_pg_backup" in c or "pg_dump" in c:
        return max(base, 900)  # full dump can take 10–15m
    if "external_market_data_ingest" in c:
        return min(base, 90)  # fail fast; health will re-arm — don't block 5m
    if "social_scalp_scanner" in c:
        return min(base, 120)
    if "heal_trade_ai_session" in c or "cleanup_stale_proposals" in c:
        return min(base, 60)
    return base


def _execute_retry_cmd(item, allowlist, dry_run=False):
    """Execute an allowlisted retry command with full logging.
    Returns (executed: bool, success: bool, output: str)."""
    cmd = item.get("retry_cmd", "")
    if not cmd:
        return False, False, "no_retry_cmd"

    # P0 fail-closed containment (issue #283 / PR #284 Gate 4)
    try:
        from lib.agent_jobs_containment import guard_agent_jobs_execution
        g = guard_agent_jobs_execution(cmd, source="claude_escalation_handler")
    except Exception as _cex:
        if "process_watchlist_agent_jobs" in str(cmd).lower():
            status = "CONTAINMENT_CHECK_FAILED"
            log.info(f"  ⛔ retry_cmd {status} (import/eval): {cmd[:80]}")
            _log_retry(item, cmd, False, status, "containment_check_failed")
            return False, False, status
        g = {"blocked": False}
    if g.get("blocked"):
        status = g.get("remediation_status") or g.get("status") or "CONTAINMENT_CHECK_FAILED"
        log.info(f"  ⛔ retry_cmd {status} (P0 agent_jobs): {cmd[:80]}")
        _log_retry(item, cmd, False, status, "contained_p0")
        return False, False, status

    allowed, reason = _check_allowlist(cmd, allowlist)

    if not allowed:
        log.info(f"  ⛔ retry_cmd blocked: {reason} — {cmd[:80]}")
        _log_retry(item, cmd, False, reason, "blocked")
        return False, False, f"blocked: {reason}"

    if dry_run:
        log.info(f"  🔍 [DRY RUN] Would execute: {cmd[:100]}")
        _log_retry(item, cmd, True, reason, "dry_run")
        return False, False, "dry_run"

    # Resolve .venv/bin/python to the dev venv (release dir has no .venv)
    from lib.live_project_root import DEV_VENV_PYTHON
    original_cmd = cmd
    cmd = cmd.replace(".venv/bin/python", str(DEV_VENV_PYTHON))
    if cmd != original_cmd:
        log.info(f"  🔀 Resolved venv: using {DEV_VENV_PYTHON}")

    # Execute
    log.info(f"  🔧 Executing retry_cmd: {cmd[:100]}")
    timeout = _cmd_timeout_seconds(cmd, allowlist)
    log.info(f"  ⏳ timeout budget {timeout}s for this command")
    t0 = time.time()
    # Run in a NEW SESSION (own process group) so a timeout kills the WHOLE tree, not just the
    # shell wrapper. The old subprocess.run(timeout=) only SIGKILLed the `/bin/sh -c`, leaving the
    # python grandchild (e.g. a --limit 15 processor) orphaned to keep loading Ollama for minutes —
    # the 2026-06-25 thundering-herd. killpg on timeout closes that leak.
    proc = None
    try:
        proc = subprocess.Popen(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=str(PROJECT_ROOT), start_new_session=True,
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            duration = time.time() - t0
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGTERM)
                try:
                    proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(pgid, signal.SIGKILL)
                    proc.communicate(timeout=5)
            except Exception as kex:
                log.warning(f"  ⏱️ retry_cmd timeout cleanup error: {kex}")
            log.warning(f"  ⏱️ retry_cmd timeout ({timeout}s) — process group killed")
            _log_retry(item, cmd, True, reason, "retry_cmd_timeout", duration=duration)
            return True, False, f"timeout after {timeout}s"
        duration = time.time() - t0
        rc = proc.returncode
        if rc == 0:
            log.info(f"  ✅ retry_cmd succeeded ({duration:.1f}s)")
            _log_retry(item, cmd, True, reason, "retry_cmd_succeeded",
                       rc, stdout, stderr, duration)
            return True, True, (stdout or "")[-500:]
        elif rc in (69, 99):
            # rc=69/99 = flock lock held by another process — NOT a failure, just contention
            stderr_tail = (stderr or "")[-200:]
            log.info(f"  🔒 retry_cmd skipped — lock held by another process (rc={rc}): {stderr_tail[:100]}")
            _log_retry(item, cmd, False, reason, "flock_contention",
                       rc, stdout, stderr, duration)
            return False, False, f"flock_contention rc={rc}"
        else:
            log.warning(f"  ❌ retry_cmd failed (rc={rc}, {duration:.1f}s)")
            _log_retry(item, cmd, True, reason, "retry_cmd_failed",
                       rc, stdout, stderr, duration)
            return True, False, f"exit_code={rc}: {(stderr or '')[-200:]}"
    except Exception as e:
        duration = time.time() - t0
        log.error(f"  💥 retry_cmd error: {e}")
        _log_retry(item, cmd, True, reason, "retry_cmd_error",
                   stderr=str(e), duration=duration)
        return True, False, str(e)


# ── DB / Notification helpers ────────────────────────────────────────────

def _get_conn():
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from db_adapter import _get_conn as gc
        return gc()
    except Exception:
        return None


def _log_intervention(conn, component, problem, diagnosis="", solution="",
                      files_changed=None, status="investigating", session_log=""):
    """Write to claude_interventions table."""
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO claude_interventions
                (component, problem, diagnosis, solution, files_changed, status, session_log,
                 resolved_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, [
            component, problem[:500], (diagnosis or "")[:2000], (solution or "")[:2000],
            files_changed or [], status,
            (session_log or "")[:5000],
            datetime.now(timezone.utc) if status in ("fixed", "failed", "deferred") else None,
        ])
        conn.commit()
        row = cur.fetchone()
        return row[0] if row else None
    except Exception as e:
        log.error(f"Failed to log intervention: {e}")
        return None


def _notify(message):
    """Send Telegram notification."""
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from telegram_alert import send_telegram
        send_telegram(message)
    except Exception:
        pass


# ── Main processing ─────────────────────────────────────────────────────

def _clear_queues():
    """Write empty arrays to both escalation queue files."""
    try:
        from lib.queue_file import write_items
        write_items(QUEUE_FILE, [])
        write_items(STALENESS_QUEUE_FILE, [])
    except Exception:
        # Fallback: direct write
        try:
            QUEUE_FILE.write_text("[]")
        except Exception:
            pass
        try:
            STALENESS_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STALENESS_QUEUE_FILE.write_text("[]")
        except Exception:
            pass


def process_queue(dry_run=False, tier1_only=False, no_llm=False):
    """Process escalation queues: direct retry → LLM diagnosis → deep LLM.

    tier1_only / no_llm: skip Tier 2 and Tier 3 (no Ollama / llama.cpp) — use for
    path/CWD checks and when isolating hangs (Tier 3a alone can wait 600s).
    """
    skip_llm = bool(tier1_only or no_llm)
    print(
        f"[claude-escalation] start dry_run={dry_run} tier1_only={tier1_only} "
        f"no_llm={no_llm} skip_llm={skip_llm} root={PROJECT_ROOT}",
        flush=True,
    )
    # Collect items from both queues (flock-guarded reads)
    items = []
    try:
        from lib.queue_file import read_items
        items.extend(read_items(QUEUE_FILE))
        items.extend(read_items(STALENESS_QUEUE_FILE))
    except Exception:
        # Fallback: direct reads
        if QUEUE_FILE.exists():
            try:
                items.extend(json.loads(QUEUE_FILE.read_text()))
            except Exception:
                pass
        if STALENESS_QUEUE_FILE.exists():
            try:
                items.extend(json.loads(STALENESS_QUEUE_FILE.read_text()))
            except Exception:
                pass

    if not items:
        log.info("Escalation queue empty")
        print("[claude-escalation] queue empty — exit", flush=True)
        return

    # Deduplicate by component
    seen = set()
    unique_items = []
    for item in items:
        key = f"{item.get('component')}:{item.get('detail', item.get('status', ''))}"
        if key not in seen:
            seen.add(key)
            unique_items.append(item)

    # Filter to actionable items (skip portfolio_risk — those are informational)
    actionable = [i for i in unique_items if i.get("component") != "portfolio_risk"]

    if not actionable:
        log.info(f"Queue has {len(unique_items)} items but none are actionable (all portfolio_risk)")
        # Only remove portfolio_risk items — never blind-wipe both queues
        non_risk = [i for i in unique_items if i.get("component") != "portfolio_risk"]
        _safe_write_queue(QUEUE_FILE, non_risk)
        # Leave staleness queue untouched
        print("[claude-escalation] no actionable items — exit", flush=True)
        return

    tier3_max = max(1, int(os.getenv("ESCALATION_TIER3_MAX_BATCH", "20")))
    tier2_max = max(1, int(os.getenv("ESCALATION_TIER2_MAX_BATCH", "8")))
    MAX_RETRIES = int(os.getenv("ESCALATION_MAX_RETRIES", "4"))
    # Backoff schedule (attempt index -> cooldown minutes before next retry)
    BACKOFF_MINUTES = [0, 5, 15, 30]
    # Interval between consecutive Tier 1 command executions (seconds) — prevents thundering-herd
    TIER1_INTER_CMD_DELAY_SEC = float(os.getenv("ESCALATION_TIER1_INTER_CMD_DELAY", "2.0"))

    log.info(
        f"Processing {len(actionable)} escalation(s) (tier3 cap {tier3_max}"
        f"{', LLM SKIPPED' if skip_llm else ''})"
    )
    print(
        f"[claude-escalation] processing {len(actionable)} actionable "
        f"(of {len(unique_items)} unique)",
        flush=True,
    )
    allowlist = _load_allowlist()
    conn = _get_conn()
    now_ts = time.time()

    # Drop pure operator-only items (no retry_cmd) — they are not auto-fixable and
    # must not burn retries / pollute the autonomous queue.
    _OPERATOR_COMPONENTS = (
        "unprotected_positions", "siem_p0p1", "schwab_token_revoked",
        "finviz_cookie_expired", "audit_ledger", "kill_switch",
        "release_manifest", "proposal_link_rate", "catalyst_type_quality",
        "agent::test_", "agent_staleness",  # no retry_cmd, never auto-fixable
    )
    cleaned = []
    for item in actionable:
        comp = str(item.get("component") or "")
        if not item.get("fixable") and not item.get("retry_cmd") and not item.get("needs_code_fix"):
            if any(k in comp for k in _OPERATOR_COMPONENTS) or comp.startswith("health:"):
                # Keep code_fix; drop review-only noise from autonomous queue
                if not item.get("needs_code_fix"):
                    log.info(f"  🗑 Drop operator/review-only from queue: {comp}")
                    continue
        cleaned.append(item)
    actionable = cleaned

    # ── Retry tracking: apply backoff and increment attempt counts ──
    # Autonomous re-arm: after EXHAUST_RESET_SEC, clear exhaustion and escalate strategy
    # (higher job limit) so the agent keeps fixing without human requeue.
    EXHAUST_RESET_SEC = float(os.getenv("ESCALATION_EXHAUST_RESET_SEC", "1800"))  # 30m
    # Persistent-exhaust: findings that can never self-resolve (e.g. scalp GO dark in a
    # low-max-score regime).  Never re-arm; log at most once per 24h to avoid storm loops.
    PERSISTENT_EXHAUST = set(
        (os.getenv("ESCALATION_PERSISTENT_EXHAUST_COMPONENTS", "") or
         "health:intelligence_quality:scalp_catalyst_verification_dead").split(",")
    )
    _last_persistent_log = 0.0
    for item in actionable:
        attempts = item.get("_attempts", 0)
        last_at = item.get("_last_attempt_ts", 0)
        comp = item.get("component", "")
        # Persistent-exhaust: leave exhausted forever — log once per 24h max
        if item.get("_exhausted") and comp in PERSISTENT_EXHAUST:
            if (now_ts - _last_persistent_log) >= 86400:
                log.info(f"  🔒 Persistent-exhaust: {comp} — NOT re-arming (market/regime gated)")
                _last_persistent_log = now_ts
            continue
        # Auto re-arm exhausted fixable items after cooldown with strategy upgrade
        if item.get("_exhausted") and item.get("fixable") and item.get("retry_cmd"):
            if last_at and (now_ts - float(last_at)) >= EXHAUST_RESET_SEC:
                log.info(f"  ♻️ Re-arm exhausted {comp} after {EXHAUST_RESET_SEC:.0f}s")
                item.pop("_exhausted", None)
                item["_attempts"] = 0
                attempts = 0
                cmd = item.get("retry_cmd") or ""
                # Escalate throughput for job drain on re-arm
                if "process_watchlist_agent_jobs.py" in cmd and "--limit" in cmd:
                    import re as _re
                    item["retry_cmd"] = _re.sub(
                        r"--limit\s+\d+", "--limit 40", cmd
                    )
                    item["_strategy"] = "limit_40_rearm"
        item["_attempts"] = attempts + 1
        item["_last_attempt_ts"] = now_ts

        if attempts >= MAX_RETRIES:
            item["_exhausted"] = True
            log.warning(f"{item.get('component')}: exhausted after {attempts} attempts — will re-arm in {EXHAUST_RESET_SEC:.0f}s")
            try:
                _notify(
                    f"⚠️ AUTO-RETRY PAUSED (will re-arm): {item.get('component')}\n"
                    f"{item.get('detail', '')[:200]}\n"
                    f"After {attempts} retries; autonomous re-arm in {int(EXHAUST_RESET_SEC/60)}m."
                )
            except Exception:
                pass
            continue

        # Apply backoff: skip if cooldown hasn't elapsed
        idx = min(attempts - 1, len(BACKOFF_MINUTES) - 1)
        cooldown_sec = BACKOFF_MINUTES[idx] * 60 if idx >= 0 else 0
        elapsed = now_ts - last_at
        if last_at > 0 and elapsed < cooldown_sec:
            item["_cooling_down"] = True
            item["_cooldown_remaining_sec"] = cooldown_sec - elapsed

    # ── Tier 1: Direct retry_cmd execution for fixable items ──
    fixable = [i for i in actionable if i.get("fixable") and i.get("retry_cmd")]
    resolved_by_retry = set()

    if fixable:
        log.info(f"Tier 1: {len(fixable)} fixable item(s) with retry_cmd")
        print(f"[claude-escalation] Tier 1: {len(fixable)} fixable with retry_cmd", flush=True)

        # Deduplicate by retry_cmd hash to prevent multiple items from fighting over
        # the same flock (e.g. agent_jobs_stuck + pipeline_failures both use the same lock)
        seen_cmds = {}
        deduped_fixable = []
        for item in fixable:
            cmd_hash = hashlib.sha256((item.get("retry_cmd") or "").encode()).hexdigest()[:12]
            if cmd_hash in seen_cmds:
                log.info(f"  🔗 Merged {item.get('component')} → same retry_cmd as "
                         f"{seen_cmds[cmd_hash]}")
                continue
            seen_cmds[cmd_hash] = item.get("component")
            deduped_fixable.append(item)
        fixable = deduped_fixable

        for idx, item in enumerate(fixable):
            if item.get("_exhausted"):
                log.info(f"  ⏭ Skipping {item.get('component')}: retries exhausted")
                continue
            if item.get("_cooling_down"):
                remaining_cd = item.get("_cooldown_remaining_sec", 0)
                log.info(f"  ⏳ Skipping {item.get('component')}: cooling down ({remaining_cd:.0f}s remaining)")
                continue
            print(
                f"[claude-escalation]   Tier1 [{idx+1}/{len(fixable)}] "
                f"{item.get('component')}: {(item.get('retry_cmd') or '')[:80]}",
                flush=True,
            )
            executed, success, output = _execute_retry_cmd(item, allowlist, dry_run)
            if success:
                cleared, vnote = _verify_remediation(item)
                # Durable root-cause memory: record verify result for iterative next strategy
                try:
                    from lib import health_root_cause_memory as _rcmem
                    _ft = _finding_type_from_component(item.get("component", ""))
                    if _ft in ("scalp_catalyst_verification_dead", "pipeline_failures"):
                        if cleared:
                            _rcmem.record_outcome(
                                _ft, strategy_id=item.get("_strategy") or "escalation_tier1",
                                ok=True, note=vnote, cmd=item.get("retry_cmd"),
                            )
                        else:
                            _rcmem.record_error(
                                _ft,
                                (item.get("detail") or "")[:400],
                                how_to_fix=f"verify failed after retry: {vnote}",
                            )
                            _rcmem.record_outcome(
                                _ft, strategy_id=item.get("_strategy") or "escalation_tier1",
                                ok=False, note=vnote, cmd=item.get("retry_cmd"),
                            )
                            # Escalate strategy on re-arm: prefer iterative remediator if bare cmd thrashing
                            cmd = item.get("retry_cmd") or ""
                            if _ft == "scalp_catalyst_verification_dead" and "remediate_scalp_go_dark" not in cmd:
                                item["retry_cmd"] = (
                                    ".venv/bin/python scripts/remediate_scalp_go_dark.py"
                                )
                                item["_strategy"] = "iterative_scalp_rc"
                            if _ft == "pipeline_failures" and "remediate_pipeline_failures" not in cmd:
                                item["retry_cmd"] = (
                                    ".venv/bin/python scripts/remediate_pipeline_failures.py"
                                )
                                item["_strategy"] = "iterative_pipeline_rc"
                except Exception as _rcx:
                    log.debug(f"root-cause memory skip: {_rcx}")
                if cleared:
                    resolved_by_retry.add(id(item))
                    if conn:
                        _log_intervention(conn, item.get("component", "unknown"),
                                          item.get("detail", "")[:500],
                                          solution=f"retry_cmd succeeded+verified: {output[:160]} [{vnote}]",
                                          status="fixed",
                                          session_log=(
                                              f"retry_cmd: {item.get('retry_cmd', '')}\n"
                                              f"output: {output[:800]}\nverify: {vnote}"
                                          ))
                    log.info(f"  ✅ verified clear ({vnote})")
                else:
                    # Exit 0 but issue still present — do NOT mark fixed; keep for strategy escalate
                    item["retry_output"] = output
                    item["_ineffective_verify"] = vnote
                    if conn:
                        _log_intervention(conn, item.get("component", "unknown"),
                                          item.get("detail", "")[:500],
                                          solution=f"retry exit 0 but verify failed: {vnote}",
                                          status="failed",
                                          session_log=(
                                              f"retry_cmd: {item.get('retry_cmd', '')}\n"
                                              f"output: {output[:800]}\nverify: {vnote}"
                                          ))
                    log.warning(f"  ⚠️ retry exit 0 but still active ({vnote}) — not marking fixed")
            elif executed and not success:
                # Attach retry output to item for Claude diagnosis
                item["retry_output"] = output
            elif not executed:
                # Flock contention — don't count as attempt, don't attach failure output
                item["_attempts"] = item.get("_attempts", 1) - 1  # undo the increment
                item["_flock_contention"] = True
            # Brief delay between commands to prevent thundering-herd on LLM/DB resources
            if TIER1_INTER_CMD_DELAY_SEC > 0:
                time.sleep(TIER1_INTER_CMD_DELAY_SEC)

    # Remove resolved items from actionable
    remaining = [i for i in actionable if id(i) not in resolved_by_retry]
    if resolved_by_retry:
        log.info(f"  Tier 1 resolved {len(resolved_by_retry)}/{len(fixable)} items")

    if not remaining:
        log.info("All items resolved by direct retry_cmd")
        if not dry_run:
            # Only wipe the main queue (resolved) — staleness queue is separate
            _safe_write_queue(QUEUE_FILE, [])
        if resolved_by_retry and not dry_run:
            _notify(f"✅ Auto-recovery: {len(resolved_by_retry)} escalation(s) resolved by retry_cmd")
        print(
            f"[claude-escalation] done: all resolved by Tier1 "
            f"(resolved={len(resolved_by_retry)} dry_run={dry_run})",
            flush=True,
        )
        return

    # ── Optional early exit: no LLM tiers ──
    if skip_llm:
        log.info(
            f"Skipping Tier 2/3 LLM ({len(remaining)} remaining) — "
            f"{'--tier1-only' if tier1_only else '--no-llm'}"
        )
        print(
            f"[claude-escalation] SKIP Tier2/3 LLM — {len(remaining)} remaining unfixed; "
            f"Tier1 resolved={len(resolved_by_retry)} dry_run={dry_run}",
            flush=True,
        )
        # Leave queue intact when dry-run or when items remain unfixed
        if not dry_run and resolved_by_retry:
            # Drop only resolved; rewrite queues with remaining
            try:
                _safe_write_queue(QUEUE_FILE, remaining)
            except Exception:
                pass
        print("[claude-escalation] done (tier1-only path)", flush=True)
        return

    # ── Tier 2: Local LLM diagnosis for remaining fixable items (capped per run) ──
    # Skip on dry-run: dry-run should not call Ollama (was the "hang with no output" cause)
    remaining_fixable = [i for i in remaining if i.get("fixable")]
    if remaining_fixable and not dry_run:
        tier2_batch = remaining_fixable[:tier2_max]
        if len(remaining_fixable) > tier2_max:
            log.info(f"Tier 2: diagnosing {tier2_max}/{len(remaining_fixable)} fixable item(s) this run")
        else:
            log.info(f"Tier 2: LLM diagnosis for {len(tier2_batch)} remaining fixable item(s)")
        for item in tier2_batch:
            try:
                _detail = item.get("detail", "")
                _retry_output = item.get("retry_output", "")
                _log_content = ""
                for _logname in ["auto_enrichment.log", "proposal_enrichment.log",
                                 "auto_proposal.log", "screener_pm.log"]:
                    _lp = PROJECT_ROOT / "logs" / _logname
                    if _lp.exists():
                        _log_content = _lp.read_text()[-2000:]
                        break

                import requests
                _llm_resp = requests.post("http://localhost:11434/api/generate", json={
                    "model": os.getenv("LOCAL_LLM_MODEL", "gemma3:4b"),
                    "prompt": (f"/no_think Diagnose this Trade AI error and suggest a fix:\n\n"
                               f"Alert: {_detail}\n"
                               + (f"Retry output: {_retry_output}\n" if _retry_output else "")
                               + f"Recent log:\n{_log_content}\n\n"
                               f"Respond with: DIAGNOSIS: (what broke) FIX: (what to do)"),
                    "stream": False,
                    "options": {"num_predict": 300, "temperature": 0.2},
                }, timeout=90)
                if _llm_resp.ok:
                    _diagnosis = _llm_resp.json().get("response", "")[:500]
                    log.info(f"  LLM diagnosis: {_diagnosis[:200]}")
                    item["llm_diagnosis"] = _diagnosis
                    if conn:
                        _log_intervention(conn, item.get("component", "unknown"),
                                          item.get("detail", "")[:500],
                                          diagnosis=_diagnosis,
                                          status="investigating",
                                          session_log=f"local_llm_diagnosis: {_diagnosis}")
            except Exception as e:
                log.warning(f"  Local LLM diagnosis failed: {e}")
    elif remaining_fixable and dry_run:
        log.info(f"Tier 2: SKIPPED on --dry-run ({len(remaining_fixable)} would use Ollama)")
        print(
            f"[claude-escalation] Tier 2 skipped on dry-run "
            f"({len(remaining_fixable)} would call Ollama)",
            flush=True,
        )

    # ── Tier 3: Local LLM deep analysis (batched — defer overflow to next cron tick) ──
    # Items skipped due to cooldown or exhaustion are preserved for next run
    cooldown_items = [i for i in remaining if i.get("_cooling_down")]
    exhausted_items = [i for i in remaining if i.get("_exhausted")]
    # Exhausted items: log once and remove from queue (they've been notified)
    for ex in exhausted_items:
        log.info(f"  Removing exhausted item from queue: {ex.get('component')} "
                 f"({ex.get('_attempts', '?')} attempts)")
    # Keep cooldown items for next run; exclude exhausted
    remaining = [i for i in remaining if not i.get("_exhausted") and not i.get("_cooling_down")]
    deferred = remaining[tier3_max:] + cooldown_items
    remaining = remaining[:tier3_max]
    if deferred:
        cd_n = len(cooldown_items)
        pure_deferred = len(deferred) - cd_n
        log.info(f"Tier 3: deferring {pure_deferred} escalation(s) + {cd_n} cooldown(s) to next handler run")
        if exhausted_items:
            log.info(f"  Exhausted (removing): {len(exhausted_items)} item(s) after {MAX_RETRIES} retries")
    print(
        f"[claude-escalation] Tier 3 prep: analyze={len(remaining)} deferred={len(deferred)} "
        f"dry_run={dry_run}",
        flush=True,
    )

    problems = []
    for item in remaining:
        comp = item.get("component", "unknown")
        detail = item.get("detail", "")
        status = item.get("status", "")
        error = item.get("last_error", "")
        retry_cmd = item.get("retry_cmd", "")
        retry_out = item.get("retry_output", "")
        llm_diag = item.get("llm_diagnosis", "")
        problems.append(
            f"- Component: {comp}\n"
            f"  Status: {status}\n"
            f"  Detail: {detail}\n"
            f"  Last error: {error}\n"
            f"  Retry command: {retry_cmd}"
            + (f"\n  Retry output: {retry_out}" if retry_out else "")
            + (f"\n  LLM Diagnosis: {llm_diag}" if llm_diag else "")
        )

    analysis_prompt = (
        f"You are the Trade AI system health analyst. "
        f"{len(remaining)} problem(s) were not resolved by automatic retries.\n\n"
        f"For each problem, provide:\n"
        f"1. ROOT CAUSE: What specifically failed and why\n"
        f"2. IMPACT: What is affected (proposals, trades, data quality)\n"
        f"3. FIX: Exact steps or commands to resolve\n"
        f"4. PREVENTION: How to prevent recurrence\n\n"
        f"Problems:\n" + "\n".join(problems)
    )

    # Read relevant log tails for context
    _context_logs = ""
    for _logname in ["auto_enrichment.log", "proposal_enrichment.log",
                     "auto_proposal.log", "screener_pm.log", "system_health_agent.log"]:
        _lp = PROJECT_ROOT / "logs" / _logname
        if _lp.exists():
            _tail = _lp.read_text()[-1000:]
            _context_logs += f"\n--- {_logname} (tail) ---\n{_tail}\n"
    if _context_logs:
        analysis_prompt += f"\n\nRecent system logs for context:\n{_context_logs[-3000:]}"

    if dry_run:
        log.info(f"[DRY RUN] Tier 3: Would analyze {len(remaining)} item(s) via local LLM:\n{analysis_prompt[:500]}...")
        if conn:
            for item in remaining:
                _log_intervention(conn, item.get("component", "unknown"),
                                  json.dumps(item, default=str)[:500],
                                  status="deferred",
                                  session_log="dry_run — not invoked")
        # Separate staleness items from main queue items for staleness queue
        stale_items = [i for i in (deferred or []) if i.get("source") == "hermes_health_inspector"]
        non_stale = [i for i in (deferred or []) if i.get("source") != "hermes_health_inspector"]
        _safe_write_queue(QUEUE_FILE, non_stale)
        _safe_write_queue(STALENESS_QUEUE_FILE, stale_items)
        return

    log.info(f"Tier 3: Deep LLM analysis for {len(remaining)} item(s)...")
    intervention_ids = []
    if conn:
        for item in remaining:
            iid = _log_intervention(conn, item.get("component", "unknown"),
                                    json.dumps(item, default=str)[:500],
                                    status="investigating")
            if iid:
                intervention_ids.append(iid)

    _notify(f"🔍 Investigating {len(remaining)} escalation(s) via local LLM:\n" +
            "\n".join(f"• {i.get('component')}: {i.get('detail', i.get('status', ''))[:60]}"
                      for i in remaining[:5]))

    session_log = ""
    success = False
    _tier_used = ""

    # ── Tier 3a: gemma4:31b via llama.cpp (best quality) ──
    LLAMACPP_URL = os.getenv("LLAMACPP_URL", "http://127.0.0.1:8081")
    LLAMACPP_GGUF = Path.home() / "llama-cpp-vulkan" / "gemma4-31b-hf.gguf"
    LLAMACPP_BIN = Path.home() / "llama-cpp-vulkan" / "llama-b9405" / "llama-server"

    # LOAD/PRIORITY GUARD (2026-06-29 outage fix): gemma4:31b burns ~3 CPU cores via CPU-spilling
    # Vulkan on this box. When health-agent escalations spike during contention, spawning 31B
    # investigations starved the single-threaded dashboard server → more endpoint timeouts → more
    # findings → more escalations → a runaway feedback loop (dashboard ERR_CONNECTION_RESET, load 8+).
    # Skip the 31B tier (fall through to the lighter local/cloud tiers) during the market window or
    # under high load, so escalation investigation never amplifies an outage it is reporting.
    _skip_31b = False
    try:
        _load1 = os.getloadavg()[0]
        _load_cap = float(os.getenv("ESCALATION_31B_LOAD_CAP", "4.0"))
        try:
            from zoneinfo import ZoneInfo as _ZI
            _et = datetime.now(_ZI("America/New_York"))
        except Exception:
            _et = datetime.now()
        _in_market = _et.weekday() < 5 and 6 <= _et.hour < 12
        if os.getenv("DISABLE_GEMMA4_31B_ESCALATION") == "1" or _in_market or _load1 > _load_cap:
            _skip_31b = True
            log.info(f"  Tier 3a SKIPPED (gemma4:31b) — priority guard: market_window={_in_market} "
                     f"load1={_load1:.1f} cap={_load_cap} — using a lighter lane so escalation work "
                     f"does not starve the dashboard")
    except Exception:
        pass

    if not _skip_31b and LLAMACPP_GGUF.exists() and LLAMACPP_BIN.exists():
        log.info("  Tier 3a: Attempting gemma4:31b via llama.cpp...")
        _llama_proc = None
        try:
            import requests as _req
            # Check if llama-server is already running
            try:
                _req.get(f"{LLAMACPP_URL}/health", timeout=3)
                _llama_running = True
            except Exception:
                _llama_running = False

            # Start llama-server if not running (unload ALL Ollama models first)
            if not _llama_running:
                log.info("  Starting llama-server for gemma4:31b...")
                # Unload ALL Ollama models to free VRAM
                try:
                    _ps = _req.get("http://localhost:11434/api/ps", timeout=5).json()
                    for _m in _ps.get("models", []):
                        _mname = _m.get("name", "")
                        log.info(f"  Unloading Ollama model: {_mname}")
                        try:
                            _req.post("http://localhost:11434/api/chat",
                                      json={"model": _mname, "keep_alive": 0,
                                            "messages": [{"role": "user", "content": ""}]},
                                      timeout=15)
                        except Exception:
                            pass
                    time.sleep(5)
                    # Verify VRAM is free
                    _ps2 = _req.get("http://localhost:11434/api/ps", timeout=5).json()
                    _still = [m["name"] for m in _ps2.get("models", [])]
                    if _still:
                        log.warning(f"  Models still loaded after unload: {_still}")
                    else:
                        log.info("  All Ollama models unloaded, VRAM free")
                except Exception as _ue:
                    log.warning(f"  Ollama unload failed: {_ue}")
                time.sleep(3)

                _lib_dir = str(LLAMACPP_BIN.parent)
                _llama_log = PROJECT_ROOT / "logs" / "llama_server_escalation.log"
                _llama_logf = open(_llama_log, "a")
                _llama_proc = subprocess.Popen(
                    [str(LLAMACPP_BIN), "--model", str(LLAMACPP_GGUF),
                     "--port", "8081", "--host", "127.0.0.1",
                     "--ctx-size", "2048", "--n-gpu-layers", "25", "--threads", "6"],
                    stdout=_llama_logf, stderr=_llama_logf,
                    env={**os.environ, "LD_LIBRARY_PATH": _lib_dir},
                )
                # Wait for startup — gemma4:31b takes 60-90s to load on hybrid GPU/CPU
                _server_ready = False
                for _wait in range(60):
                    time.sleep(3)
                    try:
                        if _req.get(f"{LLAMACPP_URL}/health", timeout=3).ok:
                            _server_ready = True
                            log.info(f"  llama-server ready after {(_wait+1)*3}s")
                            break
                    except Exception:
                        pass
                if not _server_ready:
                    log.warning("  llama-server did not become ready in 180s")
                    raise TimeoutError("llama-server startup timeout")

            # Call gemma4:31b — allow 10 min for deep analysis on hybrid CPU/GPU
            _resp = _req.post(f"{LLAMACPP_URL}/v1/chat/completions", json={
                "model": "gemma4-31b",
                "messages": [
                    {"role": "system", "content": "You are a Trade AI system health analyst. Provide detailed structured root cause analysis."},
                    {"role": "user", "content": analysis_prompt},
                ],
                "temperature": 0.2, "max_tokens": 2048,
            }, timeout=600)
            if _resp.ok:
                _analysis = _resp.json()["choices"][0]["message"]["content"].strip()
                if _analysis and len(_analysis) > 100:
                    session_log = f"GEMMA4_31B (llama.cpp):\n{_analysis}"
                    success = True
                    _tier_used = "3a_gemma4_31b"
                    log.info(f"  ✅ Tier 3a: gemma4:31b analysis complete ({len(_analysis)} chars)")
        except Exception as e:
            log.warning(f"  Tier 3a gemma4:31b failed: {e}")
        finally:
            # Stop llama-server if we started it
            if _llama_proc:
                _llama_proc.terminate()
                try:
                    _llama_proc.wait(timeout=10)
                except Exception:
                    _llama_proc.kill()
                log.info("  Stopped llama-server")

    # ── Tier 3b: Ollama — prefer gemma3:4b during market hours / multi-item batches ──
    if not success:
        import requests as _req

        def _ollama_analyze(model: str, *, timeout: int, num_predict: int) -> tuple[str, str]:
            _resp = _req.post("http://localhost:11434/api/chat", json={
                "model": model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": "You are a Trade AI system health analyst. Provide structured root cause analysis."},
                    {"role": "user", "content": analysis_prompt[:12000]},
                ],
                "options": {"temperature": 0.2, "num_predict": num_predict, "num_ctx": 4096},
            }, timeout=timeout)
            if not _resp.ok:
                return "", f"HTTP {_resp.status_code}"
            _analysis = _resp.json().get("message", {}).get("content", "").strip()
            if _analysis and len(_analysis) > 50:
                return _analysis, ""
            return _analysis or "", f"insufficient ({len(_analysis)} chars)"

        try:
            _small = os.getenv("ESCALATION_LLM_MODEL_SMALL", "gemma3:4b")
            _default = os.getenv("ESCALATION_LLM_MODEL", "gemma3:12b")
            try:
                from zoneinfo import ZoneInfo as _ZI
                _et = datetime.now(_ZI("America/New_York"))
            except Exception:
                _et = datetime.now()
            _in_market = _et.weekday() < 5 and 9 <= _et.hour < 16
            _load1 = os.getloadavg()[0]
            _load_cap = float(os.getenv("ESCALATION_TIER3_LOAD_CAP", "3.5"))
            _ps_resp = _req.get("http://localhost:11434/api/ps", timeout=5).json()
            _loaded = [m["name"] for m in _ps_resp.get("models", []) if "embed" not in m["name"].lower()]

            if _in_market or len(remaining) >= 2 or _load1 > _load_cap:
                _model = _small
            else:
                _model = _loaded[0] if _loaded else _default
            _timeout = min(300, max(180, 90 + 25 * len(remaining)))
            _predict = 512 if len(remaining) >= 2 else 1024
            log.info(f"  Tier 3b: {_model} via Ollama · batch {len(remaining)} · timeout {_timeout}s "
                     f"(market={_in_market} load={_load1:.1f})")
            _analysis, _err = _ollama_analyze(_model, timeout=_timeout, num_predict=_predict)
            if _analysis:
                session_log = f"{_model} (Ollama):\n{_analysis}"
                success = True
                _tier_used = f"3b_{_model.replace(':', '_')}"
                log.info(f"  ✅ Tier 3b: {_model} analysis complete ({len(_analysis)} chars)")
            elif _model != _small:
                log.warning(f"  Tier 3b: {_model} failed ({_err}) — retrying {_small}")
                _analysis, _err2 = _ollama_analyze(_small, timeout=240, num_predict=512)
                if _analysis:
                    session_log = f"{_small} (Ollama fallback):\n{_analysis}"
                    success = True
                    _tier_used = f"3b_{_small.replace(':', '_')}_fallback"
                    log.info(f"  ✅ Tier 3b fallback: {_small} ({len(_analysis)} chars)")
                else:
                    session_log = f"{_model} error: {_err}; {_small} fallback: {_err2}"
            else:
                session_log = f"{_model} error: {_err}"
        except Exception as e:
            log.warning(f"  Tier 3b: Ollama failed: {e}")
            session_log = f"Ollama error: {e}"

    # ── Tier 3c: Claude Code CLI (optional, requires API credits) ──
    if not success and os.getenv("ESCALATION_USE_CLAUDE_CLI", "").lower() in ("1", "true"):
        log.info("  Tier 3c: Falling back to Claude Code CLI...")
        try:
            result = subprocess.run(
                ["claude", "-p", "\n".join(problems), "--output-format", "text"],
                capture_output=True, text=True, timeout=300,
                cwd=str(PROJECT_ROOT),
                env={**os.environ, "CLAUDE_NO_INTERACTIVE": "1"},
            )
            if result.returncode == 0:
                session_log = f"CLAUDE_CLI:\n{result.stdout[-3000:]}"
                success = True
                _tier_used = "3c_claude_cli"
            else:
                _combined = f"{result.stdout or ''} {result.stderr or ''}"
                if "credit balance" in _combined.lower():
                    log.error("  Tier 3c: Claude CLI credit balance too low")
                session_log += f"\nCLAUDE_CLI: exit {result.returncode}: {_combined[-500:]}"
        except Exception as e:
            session_log += f"\nCLAUDE_CLI error: {e}"

    final_status = "fixed" if success else "failed"
    if conn:
        cur = conn.cursor()
        for iid in intervention_ids:
            try:
                cur.execute("""UPDATE claude_interventions
                    SET status=%s, session_log=%s, resolved_at=NOW()
                    WHERE id=%s""",
                    [final_status, session_log[:5000], iid])
            except Exception:
                pass
        conn.commit()

    resolved_count = len(resolved_by_retry)
    defer_note = f"\nDeferred: {len(deferred)} queued for next run" if deferred else ""
    _notify(f"{'✅' if success else '❌'} Escalation analysis {'complete' if success else 'failed'}\n"
            f"Tier 1 (retry_cmd): {resolved_count} resolved\n"
            f"Tier 3 (local LLM): {len(remaining)} analyzed → {final_status}{defer_note}\n"
            f"Analysis: {session_log[:200]}")

    _safe_write_queue(QUEUE_FILE, deferred)
    log.info(
        f"Queue: {resolved_count} retried, {len(remaining)} tier3 → {final_status}, "
        f"{len(deferred)} deferred"
    )


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(
        description="Process health escalations: Tier1 retry_cmd → Tier2 Ollama → Tier3 deep LLM"
    )
    ap.add_argument("--dry-run", action="store_true", help="Do not execute retries; skip Tier2 Ollama")
    ap.add_argument(
        "--tier1-only",
        action="store_true",
        help="Only allowlisted retry_cmd (no Tier2/Tier3 LLM) — use to isolate hangs",
    )
    ap.add_argument(
        "--no-llm",
        action="store_true",
        help="Same as --tier1-only: skip all LLM tiers",
    )
    args = ap.parse_args()
    process_queue(
        dry_run=args.dry_run,
        tier1_only=args.tier1_only,
        no_llm=args.no_llm,
    )
