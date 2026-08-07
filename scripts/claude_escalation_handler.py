#!/usr/bin/env python3
"""claude_escalation_handler.py — Process health agent escalations.

Processes escalation queue with 3-tier approach:
  1. Safe retry_cmd direct execution (allowlisted, logged, timeboxed)
  2. Local LLM diagnosis for fixable items
  3. Claude Code CLI for unresolved problems

Usage:
    .venv/bin/python scripts/claude_escalation_handler.py
    .venv/bin/python scripts/claude_escalation_handler.py --dry-run
"""
import hashlib
import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

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

    # Check blocked patterns first (hard deny)
    for pattern in allowlist.get("blocked_patterns", []):
        if pattern.lower() in cmd_lower:
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

    # Execute
    log.info(f"  🔧 Executing retry_cmd: {cmd[:100]}")
    timeout = allowlist.get("max_runtime_seconds", 120) if allowlist else 120
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
        QUEUE_FILE.write_text("[]")
    except Exception:
        pass
    try:
        STALENESS_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STALENESS_QUEUE_FILE.write_text("[]")
    except Exception:
        pass


def process_queue(dry_run=False):
    """Process escalation queues: direct retry → LLM diagnosis → Claude Code CLI.
    Reads from both claude_escalation_queue.json AND staleness_escalation_queue.json."""
    # Collect items from both queues
    items = []

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
        _clear_queues()
        return

    tier3_max = max(1, int(os.getenv("ESCALATION_TIER3_MAX_BATCH", "5")))
    tier2_max = max(1, int(os.getenv("ESCALATION_TIER2_MAX_BATCH", "3")))

    log.info(f"Processing {len(actionable)} escalation(s) (tier3 cap {tier3_max})")
    allowlist = _load_allowlist()
    conn = _get_conn()

    # ── Tier 1: Direct retry_cmd execution for fixable items ──
    fixable = [i for i in actionable if i.get("fixable") and i.get("retry_cmd")]
    resolved_by_retry = set()

    if fixable:
        log.info(f"Tier 1: {len(fixable)} fixable item(s) with retry_cmd")
        for idx, item in enumerate(fixable):
            executed, success, output = _execute_retry_cmd(item, allowlist, dry_run)
            if success:
                resolved_by_retry.add(id(item))
                if conn:
                    _log_intervention(conn, item.get("component", "unknown"),
                                      item.get("detail", "")[:500],
                                      solution=f"retry_cmd succeeded: {output[:200]}",
                                      status="fixed",
                                      session_log=f"retry_cmd: {item.get('retry_cmd', '')}\noutput: {output[:1000]}")
            elif executed and not success:
                # Attach retry output to item for Claude diagnosis
                item["retry_output"] = output

    # Remove resolved items from actionable
    remaining = [i for i in actionable if id(i) not in resolved_by_retry]
    if resolved_by_retry:
        log.info(f"  Tier 1 resolved {len(resolved_by_retry)}/{len(fixable)} items")

    if not remaining:
        log.info("All items resolved by direct retry_cmd")
        _clear_queues()
        if resolved_by_retry:
            _notify(f"✅ Auto-recovery: {len(resolved_by_retry)} escalation(s) resolved by retry_cmd")
        return

    # ── Tier 2: Local LLM diagnosis for remaining fixable items (capped per run) ──
    remaining_fixable = [i for i in remaining if i.get("fixable")]
    if remaining_fixable:
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

    # ── Tier 3: Local LLM deep analysis (batched — defer overflow to next cron tick) ──
    deferred = remaining[tier3_max:]
    remaining = remaining[:tier3_max]
    if deferred:
        log.info(f"Tier 3: deferring {len(deferred)} escalation(s) to next handler run")

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
        QUEUE_FILE.write_text(json.dumps(deferred, indent=2) if deferred else "[]")
        # Separate staleness items from main queue items for staleness queue
        stale_items = [i for i in (deferred or []) if i.get("source") == "hermes_health_inspector"]
        non_stale = [i for i in (deferred or []) if i.get("source") != "hermes_health_inspector"]
        QUEUE_FILE.write_text(json.dumps(non_stale, indent=2) if non_stale else "[]")
        try:
            STALENESS_QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STALENESS_QUEUE_FILE.write_text(json.dumps(stale_items, indent=2) if stale_items else "[]")
        except Exception:
            pass
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

    QUEUE_FILE.write_text(json.dumps(deferred, indent=2) if deferred else "[]")
    log.info(
        f"Queue: {resolved_count} retried, {len(remaining)} tier3 → {final_status}, "
        f"{len(deferred)} deferred"
    )


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    process_queue(dry_run=args.dry_run)
