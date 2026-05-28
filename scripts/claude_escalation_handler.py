#!/usr/bin/env python3
"""claude_escalation_handler.py — Process health agent escalations via Claude Code.

Called by cron every 15 minutes. Reads claude_escalation_queue.json,
bundles problems, invokes Claude Code CLI to investigate and fix.
Logs results to claude_interventions table and clears the queue.

Usage:
    .venv/bin/python scripts/claude_escalation_handler.py
    .venv/bin/python scripts/claude_escalation_handler.py --dry-run
"""
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
QUEUE_FILE = PROJECT_ROOT / "logs" / "claude_escalation_queue.json"
LOG_DIR = PROJECT_ROOT / "logs"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [claude-escalation] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "claude_escalation.log"),
    ]
)
log = logging.getLogger("claude-escalation")


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


def process_queue(dry_run=False):
    """Read escalation queue, invoke Claude Code, log results."""
    if not QUEUE_FILE.exists():
        log.info("No escalation queue file — nothing to process")
        return

    try:
        items = json.loads(QUEUE_FILE.read_text())
    except Exception:
        items = []

    if not items:
        log.info("Escalation queue empty")
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
        # Clear queue
        QUEUE_FILE.write_text("[]")
        return

    log.info(f"Processing {len(actionable)} escalation(s)")

    conn = _get_conn()

    # Try local LLM first for quick diagnosis of fixable items
    fixable = [i for i in actionable if i.get("fixable")]
    if fixable:
        log.info(f"Attempting local LLM diagnosis for {len(fixable)} fixable item(s)")
        for item in fixable:
            try:
                # Read the relevant log tail for context
                _detail = item.get("detail", "")
                _log_content = ""
                for _logname in ["auto_proposal.log", "screener_pm.log", "incubator_promoter.log"]:
                    _lp = PROJECT_ROOT / "logs" / _logname
                    if _lp.exists() and _logname.split(".")[0] in _detail.lower().replace("_", ""):
                        _log_content = _lp.read_text()[-2000:]
                        break
                if not _log_content:
                    # Generic: read the log mentioned in the detail
                    for _logname in ["auto_proposal.log", "screener_pm.log"]:
                        _lp = PROJECT_ROOT / "logs" / _logname
                        if _lp.exists():
                            _log_content = _lp.read_text()[-2000:]
                            break

                import requests
                _llm_resp = requests.post("http://localhost:11434/api/generate", json={
                    "model": "qwen3:14b",
                    "prompt": f"/no_think Diagnose this Trade AI error and suggest a fix:\n\nAlert: {_detail}\n\nRecent log:\n{_log_content}\n\nRespond with: DIAGNOSIS: (what broke) FIX: (what to do)",
                    "stream": False,
                    "options": {"num_predict": 300, "temperature": 0.2},
                }, timeout=60)
                if _llm_resp.ok:
                    _diagnosis = _llm_resp.json().get("response", "")[:500]
                    log.info(f"  LLM diagnosis: {_diagnosis[:200]}")
                    item["llm_diagnosis"] = _diagnosis
                    # Log to interventions table
                    if conn:
                        _log_intervention(conn, item.get("component", "unknown"),
                                          item.get("detail", "")[:500],
                                          diagnosis=_diagnosis,
                                          status="investigating",
                                          session_log=f"local_llm_diagnosis: {_diagnosis}")
            except Exception as e:
                log.warning(f"  Local LLM diagnosis failed: {e}")

    # Build the prompt for Claude Code
    problems = []
    for item in actionable:
        comp = item.get("component", "unknown")
        detail = item.get("detail", "")
        status = item.get("status", "")
        error = item.get("last_error", "")
        retry_cmd = item.get("retry_cmd", "")
        llm_diag = item.get("llm_diagnosis", "")
        problems.append(
            f"- Component: {comp}\n"
            f"  Status: {status}\n"
            f"  Detail: {detail}\n"
            f"  Last error: {error}\n"
            f"  Retry command: {retry_cmd}"
            + (f"\n  LLM Diagnosis: {llm_diag}" if llm_diag else "")
        )

    prompt = (
        f"The Trade AI health agent has escalated {len(actionable)} problem(s) that "
        f"automatic retries could not fix. Investigate each, diagnose the root cause, "
        f"and fix if possible. For each problem, report what you found and what you did.\n\n"
        f"Problems:\n" + "\n".join(problems) + "\n\n"
        f"Working directory: {PROJECT_ROOT}\n"
        f"After investigating, write a brief summary of findings and actions taken."
    )

    if dry_run:
        log.info(f"[DRY RUN] Would invoke Claude Code with:\n{prompt[:500]}...")
        if conn:
            for item in actionable:
                _log_intervention(conn, item.get("component", "unknown"),
                                  json.dumps(item, default=str)[:500],
                                  status="deferred",
                                  session_log="dry_run — not invoked")
        QUEUE_FILE.write_text("[]")
        return

    # Log investigating status
    intervention_ids = []
    if conn:
        for item in actionable:
            iid = _log_intervention(conn, item.get("component", "unknown"),
                                    json.dumps(item, default=str)[:500],
                                    status="investigating")
            if iid:
                intervention_ids.append(iid)

    # Notify operator that Claude is investigating
    _notify(f"🤖 Claude Code investigating {len(actionable)} escalation(s):\n" +
            "\n".join(f"• {i.get('component')}: {i.get('detail', i.get('status', ''))[:60]}"
                      for i in actionable[:5]))

    # Invoke Claude Code CLI
    log.info(f"Invoking Claude Code CLI...")
    session_log = ""
    success = False
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True, text=True, timeout=300,
            cwd=str(PROJECT_ROOT),
            env={**os.environ, "CLAUDE_NO_INTERACTIVE": "1"},
        )
        session_log = result.stdout[-3000:] if result.stdout else ""
        if result.returncode == 0:
            success = True
            log.info(f"Claude Code completed successfully")
            log.info(f"Output: {session_log[:500]}")
        else:
            session_log = f"EXIT CODE {result.returncode}\nSTDERR: {result.stderr[-1000:]}\nSTDOUT: {result.stdout[-1000:]}"
            log.warning(f"Claude Code exited with code {result.returncode}")
    except subprocess.TimeoutExpired:
        session_log = "TIMEOUT: Claude Code did not complete within 5 minutes"
        log.warning("Claude Code timed out after 5 minutes")
    except FileNotFoundError:
        session_log = "Claude Code CLI not found — install with: npm i -g @anthropic-ai/claude-code"
        log.error("Claude Code CLI not found")
    except Exception as e:
        session_log = f"ERROR: {str(e)}"
        log.error(f"Claude Code invocation failed: {e}")

    # Update intervention records
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

    # Notify result
    _notify(f"{'✅' if success else '❌'} Claude Code escalation {'resolved' if success else 'failed'}\n"
            f"{len(actionable)} problem(s) investigated\n"
            f"Status: {final_status}\n"
            f"Log: {session_log[:200]}")

    # Clear queue
    QUEUE_FILE.write_text("[]")
    log.info(f"Queue cleared. {len(actionable)} items processed → {final_status}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    process_queue(dry_run=args.dry_run)
