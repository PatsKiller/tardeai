#!/usr/bin/env python3
"""health_agent.py — Centralized, proactive Health Agent for Trade AI v12.

This is the SCORING + TREND + ROUTING brain that sits ON TOP of the existing fragmented monitors
(system_health_agent execution-integrity, pipeline_watchdog, stop/protection monitors, freshness
monitors, claude_escalation_handler). It does NOT duplicate their per-component polling; it aggregates
their signals into:

  • a single Health Score (0-100) with a breakdown by category
        Data Quality · Execution Health · Intelligence Quality · Risk Protection · Retirement Planning
  • proactive TREND detection (score declining over N runs → escalate before it breaks)
  • bounded, audited routing of findings into the EXISTING escalation queue
        (claude_escalation_handler drains it: safe retry → local LLM → Claude Code;
         code-level findings are tagged needs_code_fix so coder_dispatch routes them to an AI coder)

Outputs (always):
  • DB table  health_agent_snapshots   (append-only history, powers trends + the dashboard)
  • state JSON data/portfolios/state/health_agent_status.json   (latest snapshot, fast read)
  • logs/health_agent.jsonl            (audit trail of every decision + reasoning)

Safety: advisory by default. Never raises. Free-lane LLM only for the optional narrative summary.

Usage:
    .venv/bin/python scripts/health_agent.py                 # compute + persist + alert
    .venv/bin/python scripts/health_agent.py --no-enqueue    # score only, do not touch escalation queue
    .venv/bin/python scripts/health_agent.py --json          # print snapshot json
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time as _time_module
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib.live_project_root import (  # noqa: E402
    get_live_project_root,
    DEV_ROOT,
    DEV_VENV_PYTHON,
)
PROJECT_ROOT = get_live_project_root()
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
# Prefer DEV scripts on sys.path when live stamp is missing newer modules
if DEV_ROOT != PROJECT_ROOT and (DEV_ROOT / "scripts").is_dir():
    sys.path.insert(0, str(DEV_ROOT / "scripts"))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    if DEV_ROOT != PROJECT_ROOT:
        load_dotenv(DEV_ROOT / ".env", override=False)
except Exception:
    pass

STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
LOG_DIR = PROJECT_ROOT / "logs"
POLICY_FILE = PROJECT_ROOT / "config" / "health_agent_policy.json"
# Fallback policy from DEV when live stamp lags (cron often runs health_agent from DEV tree
# but PROJECT_ROOT resolves to CURRENT release).
if not POLICY_FILE.is_file() and (DEV_ROOT / "config" / "health_agent_policy.json").is_file():
    POLICY_FILE = DEV_ROOT / "config" / "health_agent_policy.json"


def _resolve_remediation_python() -> str:
    """Absolute python for producer remediations — live stamp often has no .venv (exit 127)."""
    candidates = [
        str(DEV_VENV_PYTHON) if DEV_VENV_PYTHON.is_file() else "",
        str(DEV_ROOT / ".venv" / "bin" / "python3"),
        sys.executable or "",
        str(PROJECT_ROOT / ".venv" / "bin" / "python"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return sys.executable or "python3"


def _rewrite_remediation_cmd(cmd: str) -> str:
    """Rewrite relative .venv/bin/python → absolute dev venv; prefer DEV scripts cwd later."""
    import re
    if not cmd or not isinstance(cmd, str):
        return cmd or ""
    py = _resolve_remediation_python()
    return re.sub(r"(?:\.?/?\.?venv/bin/python3?)\b", py, cmd)


# Source keys that external_market_data_ingest.py --quotes actually refreshes (and whose
# data_source_health markers it updates). The generic data_source_stale retry is only
# correct for these; every other source needs an explicit data_source_remediation entry.
_QUOTE_SOURCE_KEYS = {"yahoo_finance", "finviz", "alpaca"}


def _data_source_retry_cmd(policy: dict, ftype: str, finding: dict) -> str | None:
    """Resolve the allowlisted retry command for a finding, source-aware for data_source_stale.

    The generic `data_source_stale` remediation points at
    `external_market_data_ingest.py --quotes`, which only refreshes quote data
    (Alpaca/Finviz/yfinance). A stale non-quote source (finnhub news, sec, social, …)
    would otherwise be retried against the wrong producer forever — a no-op loop that
    can never clear the finding. Prefer a per-source override from
    `policy.data_source_remediation` (keyed by source_key) when present, and skip auto-retry
    (return None → escalate) for non-quote sources that have no explicit producer.
    """
    rmap = policy.get("remediation_map") or {}
    cmd = rmap.get(ftype)
    if ftype == "data_source_stale":
        src = (finding.get("source") or "").lower()
        src_map = policy.get("data_source_remediation") or {}
        if src and isinstance(src_map, dict):
            override = src_map.get(src)
            if isinstance(override, str) and override.strip():
                return override
        # The generic entry runs the market-quote ingest, which only refreshes quote
        # sources. Non-quote sources have no producer in that script, so auto-retrying
        # is a no-op loop — skip auto (escalate) rather than run the wrong producer.
        if src and src not in _QUOTE_SOURCE_KEYS:
            return None
    return cmd if isinstance(cmd, str) else None


def _remediation_cwd() -> Path:
    """Cwd with scripts/ + .env. Prefer DEV (has venv + full scripts); fall back to live."""
    if (DEV_ROOT / "scripts").is_dir() and (DEV_ROOT / ".env").is_file():
        return DEV_ROOT
    if (PROJECT_ROOT / "scripts").is_dir():
        return PROJECT_ROOT
    return DEV_ROOT
STATUS_FILE = STATE_DIR / "health_agent_status.json"
AUDIT_JSONL = LOG_DIR / "health_agent.jsonl"
QUEUE_FILE = LOG_DIR / "claude_escalation_queue.json"

SEV_ORDER = {"critical": 3, "warning": 2, "info": 1, "ok": 0}


# ── config + db ─────────────────────────────────────────────────────────────────────────────────────

def load_policy() -> dict:
    try:
        from config_db_loader import get_config
        cfg = get_config("health_agent_policy", fallback_path="config/health_agent_policy.json")
        if cfg:
            return cfg
    except Exception:
        pass
    try:
        return json.loads(POLICY_FILE.read_text())
    except Exception:
        return {}


def _db(sql, params=None, fetch="one"):
    try:
        from db_adapter import _execute, USE_DB
        if not USE_DB:
            return None
        return _execute(sql, params, fetch=fetch)
    except Exception:
        return None


def _file_age_h(path: Path):
    if not path.exists():
        return None
    return round((datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds() / 3600, 1)


def _is_portfolio_market_hours() -> bool:
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = datetime.now()
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return 570 <= mins <= 960


def _parse_et_ts_minutes(ts_str: str) -> float | None:
    """Age in minutes for 'YYYY-MM-DD HH:MM:SS ET' timestamps."""
    if not ts_str:
        return None
    s = str(ts_str).strip().replace(" ET", "").replace("ET", "").strip()[:19]
    try:
        from zoneinfo import ZoneInfo
        naive = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        et = naive.replace(tzinfo=ZoneInfo("America/New_York"))
        return round((datetime.now(ZoneInfo("America/New_York")) - et).total_seconds() / 60.0, 1)
    except Exception:
        return None


def _db_age_h(sql):
    r = _db(sql, fetch="one")
    if not r:
        return None
    ts = list(r.values())[0]
    if not ts:
        return None
    try:
        dt = ts.replace(tzinfo=None) if hasattr(ts, "replace") else datetime.fromisoformat(str(ts))
        return round((datetime.now() - dt).total_seconds() / 3600, 1)
    except Exception:
        return None


_IS_WEEKEND = datetime.now().weekday() >= 5


def _f(category, ftype, severity, message, **extra):
    """Build a finding."""
    return {"category": category, "type": ftype, "severity": severity, "message": message, **extra}


def _check_portfolio_totals_drift(hp: dict, pcfg: dict) -> list[dict]:
    """Detect holdings.json total_value diverging from sum(position MV) — root cause of header vs
    Portfolio page mismatch after SnapTrade sync without portfolio_repricer _recalc_totals."""
    out = []
    min_drift = float(pcfg.get("totals_drift_min_dollars", 5000))
    min_pct = float(pcfg.get("totals_drift_min_pct", 0.5))
    holdings = hp.get("holdings") or []
    derived = round(sum(float(p.get("market_value") or 0) for p in holdings), 2)
    canonical = float((hp.get("portfolio_totals") or {}).get("total_value") or 0)
    if derived <= 0 or canonical <= 0:
        return out
    drift = round(abs(derived - canonical), 2)
    drift_pct = drift / canonical * 100 if canonical else 0
    if drift >= min_drift or drift_pct >= min_pct:
        sev = "critical" if drift >= min_drift * 3 or drift_pct >= min_pct * 4 else "warning"
        out.append(_f("data_quality", "portfolio_totals_drift", sev,
                      f"portfolio_totals ${canonical:,.0f} vs holdings sum ${derived:,.0f} "
                      f"(drift ${drift:,.0f} / {drift_pct:.2f}%) — run portfolio_repricer",
                      derived_total=derived, canonical_total=canonical, drift_dollars=drift,
                      drift_pct=round(drift_pct, 3)))
    # Per-account: stale manual/reported totals (Fidelity rollover after SnapTrade position merge).
    for acct_key, acct in (hp.get("account_summaries") or {}).items():
        if not isinstance(acct, dict):
            continue
        ah = [p for p in holdings if p.get("account") == acct_key and not p.get("is_loan")]
        acct_derived = round(sum(float(p.get("market_value") or 0) for p in ah), 2)
        acct_stored = float(acct.get("total_value") or 0)
        if acct_derived <= 0 or acct_stored <= 0:
            continue
        adrift = round(abs(acct_derived - acct_stored), 2)
        if adrift >= min_drift:
            sev = "critical" if adrift >= min_drift * 2 else "warning"
            out.append(_f("data_quality", "account_summary_drift", sev,
                          f"{acct_key}: account_summary ${acct_stored:,.0f} vs holdings "
                          f"${acct_derived:,.0f} (drift ${adrift:,.0f})",
                          account=acct_key, derived_total=acct_derived, stored_total=acct_stored,
                          drift_dollars=adrift))
    return out


def _check_snaptrade_cash_stale(hp: dict, pcfg: dict) -> list[dict]:
    """Fidelity/SnapTrade: SPAXX position units lag after stock buys; cash must use buying_power."""
    out = []
    min_gap = float(pcfg.get("snaptrade_cash_gap_min_dollars", 5000))
    for acct in (pcfg.get("snaptrade_accounts") or ["fidelity_rollover_ira"]):
        rows = [p for p in (hp.get("holdings") or []) if p.get("account") == acct]
        if not rows:
            continue
        cash_rows = [p for p in rows if p.get("is_cash") or str(p.get("symbol") or "").upper()
                     in ("SPAXX", "FDRXX", "FZFXX", "SPRXX")]
        equity_mv = round(sum(float(p.get("market_value") or 0) for p in rows if p not in cash_rows), 2)
        if not cash_rows or equity_mv < min_gap:
            continue
        spaxx = max(cash_rows, key=lambda p: float(p.get("market_value") or 0))
        cash_mv = float(spaxx.get("market_value") or 0)
        src = str(spaxx.get("cash_source") or spaxx.get("position_source") or "")
        if src == "snaptrade_buying_power":
            continue
        # Stale: position-unit cash with large equity book (post-deploy pattern)
        if cash_mv > equity_mv * 0.8 and src in ("snaptrade_position_units", "snaptrade", ""):
            out.append(_f("data_quality", "snaptrade_cash_stale", "warning",
                          f"{acct}: SPAXX ${cash_mv:,.0f} looks stale vs ${equity_mv:,.0f} "
                          f"equity — re-sync with balances.buying_power",
                          account=acct, spaxx_mv=cash_mv, equity_mv=equity_mv, cash_source=src))
    return out


REMEDIATION_STATE = STATE_DIR / "health_agent_remediation_state.json"
REMEDIATION_LOG = LOG_DIR / "health_agent_remediation.jsonl"


# Safe script basename substrings permitted for immediate auto-remediation (no broker submit).
def _load_safe_remediation_scripts() -> tuple:
    """Return the set of script basenames allowed for immediate auto-remediation.

    Loads from the canonical YAML allowlist (single source of truth).  Falls back to
    a hardcoded tuple only if the YAML is unreadable — in that case a loud warning is
    printed so the operator knows the safety net is degraded.
    """
    allowlist_path = PROJECT_ROOT / "config" / "claude_escalation_allowlist.yaml"
    try:
        # Hand-parse the YAML (no pyyaml dependency — the handler uses the same pattern)
        lines = allowlist_path.read_text().splitlines()
        in_allowed = False
        scripts = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("allowed_script_patterns:"):
                in_allowed = True
                continue
            if in_allowed:
                if stripped.startswith("blocked_patterns:") or stripped.startswith("max_runtime"):
                    break
                # Extract basename from quoted string like '- "scripts/foo.py"'
                if stripped.startswith("- ") and "." in stripped:
                    script = stripped.split('"')[1] if '"' in stripped else stripped.split("'")[1] if "'" in stripped else stripped[3:].strip()
                    basename = script.rsplit("/", 1)[-1]
                    if basename and "." in basename:
                        scripts.append(basename)
        if scripts:
            return tuple(scripts)
    except Exception:
        pass

    # Fallback — hardcoded safety net (must be kept in sync with the YAML manually)
    import sys as _sys
    print("WARNING: health_agent failed to load allowlist from YAML — using hardcoded fallback", file=_sys.stderr)
    return (
        "portfolio_repricer.py", "external_market_data_ingest.py", "snaptrade_sync.py",
        "run_finviz_momentum_scalp_scan.py", "social_scalp_scanner.py",
        "run_sec_form4_momentum_context.py", "reset_stuck_agent_jobs.py",
        "fix_strategy_registry_null_ids.py", "remediate_proposal_trade_plans.py",
        "auto_enrichment_runner.py", "cleanup_stale_proposals.py",
        "remediate_watchlist_news_guard.py", "hermes_scope_governor.py",
        "cio_decision_engine.py", "schwab_journal_builder.py",
        "schwab_transaction_ingest.py", "trade_ai_orchestrator.py",
        "shadow_batch_generator.py", "finviz_screener_runner.py", "news_ingestion.py",
        "indicator_cache_refresh.py", "build_symbol_profiles.py", "pro_analyst_fetch.py",
        "sector_momentum_engine.py", "rotation_autopilot.py", "unified_stop_supervisor.py",
        "fred_data_ingest.py", "sec_data_ingest.py", "social_ingest.py",
        "youtube_transcript_ingest.py", "process_watchlist_agent_jobs.py",
        "run_pg_backup.sh", "run_options_monitor.py", "data_gap_resolver.py",
        "hermes_coordinator.py", "hermes_embedding_enqueue.py",
        "hermes_embedding_worker.py", "backtest_results_aggregator.py",
        "proposal_backtest_engine.py", "enrich_proposal_technicals.py",
        "journal_review_builder.py", "paper_trade_monitor.py",
        "paper_trade_statistics.py", "heal_trade_ai_session_cache.py",
        "remediate_scalp_go_dark.py", "remediate_pipeline_failures.py",
    )


_SAFE_REMEDIATION_SCRIPTS = _load_safe_remediation_scripts()


def run_auto_remediation(policy: dict, findings: list[dict]) -> list[dict]:
    """Execute allowlisted fix scripts immediately (no escalation wait).
    Cooldown per finding-type prevents storms. Python path always rewritten to DEV venv
    so live-stamp CWD without .venv does not exit 127.

    For scalp_catalyst_verification_dead and pipeline_failures the map points at iterative
    remediators that diagnose root cause, record how-to-fix in health_root_cause_memory,
    and advance a strategy ladder so the same thrashing command is not re-run forever.
    """
    cfg = policy.get("auto_remediate") or {}
    # Entries awaiting a verdict from the post-batch re-check.
    _pending: list[dict] = []
    if not cfg.get("enabled", True):
        return []
    never = set(policy.get("never_auto_remediate") or cfg.get("never_auto_remediate") or [])
    types = set(cfg.get("finding_types") or [
        "portfolio_totals_drift", "account_summary_drift", "snaptrade_cash_stale",
        "portfolio_repricer_stale", "finviz_quote_cache_stale", "market_quotes_stale",
    ])
    cooldown_m = float(cfg.get("cooldown_minutes", 10))
    # Circuit breaker: if a remediation keeps "succeeding" (exit 0) yet the SAME finding fires again
    # within ineffective_window_minutes, the fix isn't actually fixing it — stop the futile loop and
    # the false "✅ Auto-fixed" pings after max_ineffective_attempts; escalate for operator/code review.
    # Iterative ladder remediations (scalp/pipeline) manage their own strategy advance + hold windows
    # via health_root_cause_memory — they use a higher ineffective ceiling so the ladder can walk.
    max_ineffective = int(cfg.get("max_ineffective_attempts", 3))
    max_ineffective_ladder = int(cfg.get("max_ineffective_ladder_attempts", 12))
    ineff_window_m = float(cfg.get("ineffective_window_minutes", 60))
    rmap = policy.get("remediation_map") or {}
    ladder_types = {
        "scalp_catalyst_verification_dead",
        "pipeline_failures",
    }
    # Always auto session heal even if severity was demoted; SETUPS header is user-visible.
    session_force = {"trade_ai_session_stale", "trade_ai_session_missing"}
    actionable = [f for f in findings
                  if (
                      (f.get("severity") in ("warning", "critical") and f.get("type") in types)
                      or f.get("type") in session_force
                  )
                  and f.get("type") not in never
                  and f.get("type") in types
                  and not f.get("held")]  # root-cause hold: skip thrash
    if not actionable:
        return []
    try:
        state = json.loads(REMEDIATION_STATE.read_text()) if REMEDIATION_STATE.exists() else {}
    except Exception:
        state = {}
    now = datetime.now(timezone.utc)
    results = []
    ran_cmds: set[str] = set()
    run_cwd = _remediation_cwd()

    def _st(ftype):  # normalize legacy str-timestamp state → dict
        s = state.get(ftype)
        if isinstance(s, str):
            return {"last_success": s, "ineffective_streak": 0}
        return s if isinstance(s, dict) else {"last_success": None, "ineffective_streak": 0}

    def _record_rc_memory(ftype: str, f: dict, entry: dict) -> None:
        """Best-effort: push error/outcome into durable root-cause memory."""
        try:
            from lib import health_root_cause_memory as rcmem
            if not entry.get("ok") or entry.get("ineffective"):
                rcmem.record_error(
                    ftype,
                    (f.get("message") or entry.get("note") or entry.get("trigger") or "")[:500],
                    root_cause=entry.get("root_cause"),
                    how_to_fix=entry.get("how_to_fix"),
                )
            # Iterative scripts already record outcomes themselves; only log bare map cmds here
            if ftype not in ladder_types and entry.get("cmd"):
                rcmem.record_outcome(
                    ftype,
                    strategy_id="remediation_map",
                    ok=bool(entry.get("ok")) and not entry.get("ineffective"),
                    note=(entry.get("note") or entry.get("trigger") or "")[:300],
                    cmd=entry.get("cmd"),
                    exit_code=entry.get("exit_code"),
                )
        except Exception:
            pass

    for f in actionable:
        ftype = f.get("type")
        raw_cmd = _data_source_retry_cmd(policy, ftype, f)
        # Only string commands are executable (skip agent_hung dict etc.)
        if not isinstance(raw_cmd, str) or not raw_cmd.strip():
            continue
        cmd = _rewrite_remediation_cmd(raw_cmd)
        if cmd in ran_cmds:
            continue
        st = _st(ftype)
        last = st.get("last_success")
        ceiling = max_ineffective_ladder if ftype in ladder_types else max_ineffective
        if last:
            try:
                last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                gap = (now - last_dt).total_seconds()
                if gap < cooldown_m * 60:
                    continue  # cooldown — too soon to retry
                # Recurred within the ineffective window despite a recent "successful" fix → it didn't hold.
                st["ineffective_streak"] = st.get("ineffective_streak", 0) + 1 if gap < ineff_window_m * 60 else 0
            except Exception:
                pass
        # Circuit broken: don't re-run; record an ineffective result so the alert escalates (not "fixed").
        if st.get("ineffective_streak", 0) >= ceiling:
            entry = {"at": now.isoformat(), "type": ftype, "cmd": cmd, "ok": False, "ineffective": True,
                     "streak": st["ineffective_streak"],
                     "note": f"remediation ineffective {st['ineffective_streak']}x within {int(ineff_window_m)}m "
                             f"— not re-running; needs operator/code review",
                     "trigger": f.get("message", "")[:200]}
            # Ladder types: reset streak + advance memory strategy so next window tries next fix
            if ftype in ladder_types:
                try:
                    from lib import health_root_cause_memory as rcmem
                    rcmem.advance_strategy(ftype)
                    entry["note"] += " (ladder advanced)"
                    st["ineffective_streak"] = 0
                except Exception:
                    pass
            results.append(entry)
            with open(REMEDIATION_LOG, "a") as fh:
                fh.write(json.dumps(entry) + "\n")
            state[ftype] = st
            _record_rc_memory(ftype, f, entry)
            continue
        if not any(s in cmd for s in _SAFE_REMEDIATION_SCRIPTS):
            continue
        try:
            # P0 agent_jobs containment (same guard as escalation handler)
            try:
                from lib.agent_jobs_containment import guard_agent_jobs_execution
                g = guard_agent_jobs_execution(cmd, source="health_agent_auto_remediate")
                if g.get("blocked"):
                    results.append({
                        "at": now.isoformat(), "type": ftype, "cmd": cmd, "ok": False,
                        "contained": True, "note": g.get("remediation_status") or "CONTAINED",
                        "trigger": f.get("message", "")[:200],
                    })
                    continue
            except Exception:
                pass
            # Iterative ladder remediations: pipeline spawns orchestrator detached (fast);
            # scalp may rescan+ingest (~few minutes).
            if "remediate_pipeline_failures" in cmd:
                timeout = 180
            elif "trade_ai_orchestrator" in cmd:
                timeout = 120  # should be detached via remediate_*; legacy map only
            elif "remediate_scalp_go_dark" in cmd or "social_scalp" in cmd:
                timeout = 420
            elif "run_pg_backup" in cmd:
                timeout = 600
            else:
                timeout = 180
            # Run in a NEW SESSION (own process group) so a timeout kills the WHOLE tree,
            # not just the shell wrapper.  The old subprocess.run(timeout=) only SIGKILLed
            # the `/bin/sh -c`, leaving the python grandchild orphaned — the 2026-06-25
            # thundering-herd class.  killpg on timeout closes that leak.
            proc = None
            stdout = ""
            stderr = ""
            t0 = _time_module.time()
            try:
                proc = subprocess.Popen(
                    cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, cwd=str(run_cwd), start_new_session=True,
                )
                try:
                    stdout, stderr = proc.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    duration = _time_module.time() - t0
                    try:
                        pgid = os.getpgid(proc.pid)
                        os.killpg(pgid, signal.SIGTERM)
                        try:
                            proc.communicate(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(pgid, signal.SIGKILL)
                            proc.communicate(timeout=5)
                    except Exception:
                        pass  # process already exited — best-effort cleanup
                    entry = {
                        "at": now.isoformat(), "type": ftype, "cmd": cmd, "ok": False,
                        "exit_code": -1, "cwd": str(run_cwd),
                        "stdout_tail": (stdout or "")[-400:],
                        "stderr_tail": (stderr or "")[-400:],
                        "ineffective_streak": st.get("ineffective_streak", 0),
                        "trigger": f.get("message", "")[:200],
                        "error": f"timeout after {timeout}s",
                    }
                    results.append(entry)
                    REMEDIATION_LOG.parent.mkdir(parents=True, exist_ok=True)
                    with open(REMEDIATION_LOG, "a") as fh:
                        fh.write(json.dumps(entry) + "\n")
                    _record_rc_memory(ftype, f, entry)
                    continue  # next finding — don't fall through to normal rc/parse handling
                duration = _time_module.time() - t0
                rc = proc.returncode
            except Exception as exc:
                duration = _time_module.time() - t0
                entry = {
                    "at": now.isoformat(), "type": ftype, "cmd": cmd, "ok": False,
                    "exit_code": -1, "cwd": str(run_cwd),
                    "stdout_tail": (stdout or "")[-400:],
                    "stderr_tail": (stderr or "")[-400:],
                    "ineffective_streak": st.get("ineffective_streak", 0),
                    "trigger": f.get("message", "")[:200],
                    "error": str(exc)[:200],
                }
                results.append(entry)
                REMEDIATION_LOG.parent.mkdir(parents=True, exist_ok=True)
                with open(REMEDIATION_LOG, "a") as fh:
                    fh.write(json.dumps(entry) + "\n")
                _record_rc_memory(ftype, f, entry)
                continue  # next finding — don't fall through to normal rc/parse handling
            # flock contention (rc 69/99) is not a hard failure — leave for next tick.
            # PROVISIONAL ONLY. The exit code says the command ran, never that the
            # condition cleared -- the 2026-08-26 repricer exited 0 for 24h while the
            # served numbers stayed stale. The real verdict is decided below, after
            # the originating check is re-run. `ok` is overwritten there.
            ok = False
            entry = {
                "at": now.isoformat(), "type": ftype, "cmd": cmd, "ok": ok,
                "exit_code": rc,
                "cwd": str(run_cwd),
                "stdout_tail": (stdout or "")[-400:],
                "stderr_tail": (stderr or "")[-400:],
                "ineffective_streak": st.get("ineffective_streak", 0),
                "trigger": f.get("message", "")[:200],
            }
            # Parse iterative remediator JSON stdout for root_cause / how_to_fix.
            # The old txt.find("{") + json.loads broke on trailing prose/log lines
            # after the JSON object — iterate { positions from the END and raw_decode.
            if ftype in ladder_types and stdout:
                try:
                    txt = stdout.strip()
                    decoder = json.JSONDecoder()
                    # Find the LAST valid JSON object (skip trailing log lines)
                    for i in range(len(txt) - 1, -1, -1):
                        if txt[i] == "{":
                            try:
                                parsed, _ = decoder.raw_decode(txt[i:])
                                if isinstance(parsed, dict):
                                    entry["root_cause"] = parsed.get("root_cause")
                                    entry["how_to_fix"] = parsed.get("how_to_fix")
                                    entry["strategy_id"] = parsed.get("strategy_id")
                                    entry["held"] = parsed.get("held")
                                    if parsed.get("note"):
                                        entry["note"] = str(parsed.get("note"))[:300]
                                break  # found and parsed — stop
                            except json.JSONDecodeError:
                                continue  # try next { from the end
                except Exception:
                    pass
            if rc in (69, 99):
                entry["ok"] = False
                entry["flock_contention"] = True
            # Queue for the re-check pass. Until then this entry claims nothing.
            entry["_pending_verification"] = True
            entry["_before_finding"] = {k: f.get(k) for k in
                                        ("type", "severity", "message", "age_hours",
                                         "age_seconds", "count", "drift_pct")}
            _pending.append(entry)
            results.append(entry)
            # The attempt is recorded now; the VERDICT is appended by the re-check
            # pass as a second row (record: "verdict"). This row claims nothing.
            REMEDIATION_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(REMEDIATION_LOG, "a") as fh:
                fh.write(json.dumps({**entry, "record": "attempt"}) + "\n")
            # Dedupe on the command having RUN, not on it having worked -- this
            # used to sit inside `if ok:`, so deferring the verdict would have let
            # the same command run once per finding in a single batch.
            ran_cmds.add(cmd)
            if entry.get("held"):
                st["ineffective_streak"] = 0
            state[ftype] = st
            _record_rc_memory(ftype, f, entry)
        except Exception as ex:
            results.append({"at": now.isoformat(), "type": ftype, "cmd": cmd, "ok": False,
                            "error": str(ex)[:200], "trigger": f.get("message", "")[:200]})
    # ── Verdict pass: re-run the originating check and compare ──────────────
    # Nothing above this point is entitled to say a condition was fixed. A
    # subprocess exit code proves the command ran; only re-observing the finding
    # proves anything about the condition. This is one extra compute() for the
    # whole batch, not one per finding.
    if _pending:
        try:
            from scripts.lib.health_remediation_outcome import (
                WORSENED, classify, diagnose, escalation_payload, should_stop_retrying,
            )
            try:
                _, _, _, after_cat = compute(policy)
                after_findings = [x for fs in after_cat.values() for x in fs]
                recheck_ok = True
            except Exception:
                # Could not re-observe. Refuse to claim success rather than fall
                # back to the exit code -- that fallback is the original defect.
                after_findings, recheck_ok = [], False

            breaker = int(cfg.get("max_ineffective_attempts_verified", 2))
            for entry in _pending:
                ftype = entry.get("type")
                before = entry.pop("_before_finding", {}) or {}
                entry.pop("_pending_verification", None)
                if not recheck_ok:
                    entry["ok"] = False
                    entry["outcome"] = "UNVERIFIED"
                    entry["note"] = "post-remediation re-check unavailable; no success claimed"
                    continue

                verdict = classify(
                    finding_type=ftype, before=before, after_findings=after_findings,
                    exit_code=entry.get("exit_code"),
                    timed_out=bool(entry.get("error", "").startswith("timeout")),
                )
                entry["ok"] = verdict["ok"]
                entry["outcome"] = verdict["outcome"]
                entry["verified_by_recheck"] = verdict["verified_by_recheck"]
                entry["metric_before"] = verdict["metric_before"]
                entry["metric_after"] = verdict["metric_after"]

                st2 = state.get(ftype) or _st(ftype)
                streak = int(st2.get("ineffective_streak", 0))
                if verdict["outcome"] == "CLEARED":
                    st2["last_success"] = now.isoformat()
                    st2["ineffective_streak"] = 0
                else:
                    # A non-CLEARED verdict must never stamp last_success. Stamping
                    # it is what let a failing fix look recently-healthy.
                    if verdict["outcome"] in ("INEFFECTIVE", WORSENED):
                        streak += 1
                        st2["ineffective_streak"] = streak
                        cause = diagnose(verdict, evidence={
                            "wrote_path": entry.get("wrote_path"),
                            "read_path": entry.get("read_path"),
                        })
                        entry["root_cause"] = cause
                        stop, reason = should_stop_retrying(verdict, streak, breaker=breaker)
                        if stop:
                            entry["escalate"] = escalation_payload(
                                verdict, root_cause=cause,
                                command=entry.get("cmd") or "", reason=reason)
                            entry["ineffective"] = True
                            entry["note"] = (
                                f"{verdict['outcome']} — {cause}; not re-running. "
                                f"{entry['escalate']['metric_trend']}")
                        try:
                            from lib import health_root_cause_memory as rcmem
                            rcmem.record_error(ftype, entry.get("note") or entry.get("trigger") or "",
                                               root_cause=cause)
                        except Exception:
                            pass
                state[ftype] = st2

                try:
                    REMEDIATION_LOG.parent.mkdir(parents=True, exist_ok=True)
                    with open(REMEDIATION_LOG, "a") as fh:
                        fh.write(json.dumps({**entry, "record": "verdict"}) + "\n")
                except Exception:
                    pass
        except Exception:
            for entry in _pending:
                entry.setdefault("ok", False)
                entry.setdefault("outcome", "UNVERIFIED")

    if state:
        try:
            REMEDIATION_STATE.parent.mkdir(parents=True, exist_ok=True)
            REMEDIATION_STATE.write_text(json.dumps(state, indent=2))
        except Exception:
            pass
    return results


# ── category collectors (each returns a list of findings; never raises) ──────────────────────────────

def collect_data_quality() -> list[dict]:
    out = []
    try:
        wk = 48 if _IS_WEEKEND else None
        checks = [
            ("holdings", _file_age_h(STATE_DIR / "holdings.json"), wk or 24, True),
            ("risk_management", _file_age_h(STATE_DIR / "risk_management.json"), wk or 24, True),
            ("dividend_calendar", _file_age_h(STATE_DIR / "dividend_calendar.json"), wk or 48, True),
            ("news", _db_age_h("SELECT MAX(created_at) FROM news_articles"), wk or 6, False),
            ("cio_advisory_cases", _file_age_h(PROJECT_ROOT / "data" / "cio" / "cio_production_cases.jsonl"), wk or 48, True),
            ("agent_jobs", _db_age_h("SELECT MAX(created_at) FROM watchlist_agent_jobs WHERE status='completed'"), wk or 4, False),
            # indicator_signal_history last wrote 2026-05-04; producer is retired.
            # Do not emit critical / auto-retry indicator_cache_refresh against a dead table.
            # ("indicator_snapshots", ... retired)
            ("symbol_profiles", _db_age_h("SELECT MAX(updated_at) FROM symbol_profiles"), wk or 48, True),
            ("analyst_rollups", _db_age_h("SELECT MAX(created_at) FROM analyst_consensus_history"), wk or 48, True),
            ("sector_momentum", _db_age_h("SELECT MAX(created_at) FROM sector_momentum_state"), wk or 48, True),
            ("rotation_summary", _db_age_h("SELECT MAX(created_at) FROM strategy_rotation_signals"), wk or 48, True),
            ("stops", _db_age_h("SELECT MAX(snapshot_at) FROM stop_lifecycle WHERE lifecycle != 'orphaned'"), wk or 48, True),
            ("fred_data", _db_age_h("SELECT MAX(fetched_at) FROM fred_economic_series"), wk or 168, True),
            ("sec_data", _db_age_h("SELECT MAX(created_at) FROM sec_form4"), wk or 168, True),
            ("social_data", _db_age_h("SELECT MAX(observed_at) FROM social_sentiment_history"), wk or 48, True),
            ("youtube", _db_age_h("SELECT MAX(ingested_at) FROM youtube_transcripts"), wk or 168, True),
            ("orchestrator_setups", _file_age_h(LOG_DIR / "screener_pm.log"), wk or 24, True),
            ("shadow_batch", _file_age_h(LOG_DIR / "shadow_batch_manual.log"), wk or 24, True),
        ]
        out.append(_f(
            "data_quality",
            "indicator_snapshots_retired",
            "info",
            "indicator_signal_history producer retired (last row 2026-05-04); "
            "not the canonical live indicator product",
        ))
        for name, age, maxh, weekend_ok in checks:
            if age is None:
                out.append(_f("data_quality", f"{name}_unknown", "info", f"{name} freshness unknown", age_hours=None))
            elif age > maxh:
                weekend_excused = _IS_WEEKEND and weekend_ok
                sev = "info" if weekend_excused else ("critical" if age > maxh * 3 else "warning")
                ft = "news_stale" if name == "news" else f"{name}_stale"
                out.append(_f("data_quality", ft, sev,
                              f"{name} stale: {age}h (max {maxh}h)" + (" [weekend]" if weekend_excused else ""),
                              age_hours=age, max_hours=maxh))
        gaps = _db("SELECT COUNT(*) AS c FROM data_gap_registry WHERE status='open'", fetch="one")
        if gaps and gaps.get("c", 0) > 0:
            n = gaps["c"]
            out.append(_f("data_quality", "data_gaps_open", "warning" if n < 10 else "critical",
                          f"{n} open data gaps", count=n))

        # Portfolio live prices — Finviz repricer is authoritative (SnapTrade touches holdings mtime)
        pcfg = (load_policy().get("portfolio_price_freshness") or {})
        if pcfg.get("enabled", True) and _is_portfolio_market_hours():
            max_m = float(pcfg.get("max_age_minutes", 25))
            fv_path = STATE_DIR / "finviz_quote_cache.json"
            if fv_path.exists():
                try:
                    meta = (json.loads(fv_path.read_text(encoding="utf-8")).get("_meta") or {})
                    age_m = _parse_et_ts_minutes(meta.get("last_fetched") or meta.get("last_updated") or "")
                    if age_m is None:
                        out.append(_f("data_quality", "finviz_quote_cache_unknown", "warning",
                                      "finviz_quote_cache missing last_fetched"))
                    elif age_m > max_m:
                        sev = "critical" if age_m > max_m * 2 else "warning"
                        out.append(_f("data_quality", "finviz_quote_cache_stale", sev,
                                      f"Finviz quote cache stale {age_m:.0f}m (max {max_m:.0f}m)",
                                      age_minutes=age_m))
                except Exception as ex:
                    out.append(_f("data_quality", "finviz_quote_cache_error", "warning",
                                  f"finviz_quote_cache read error: {ex}"))
            else:
                out.append(_f("data_quality", "finviz_quote_cache_missing", "critical",
                              "finviz_quote_cache.json missing"))

            hp = STATE_DIR / "holdings.json"
            if hp.exists():
                try:
                    hp_data = json.loads(hp.read_text(encoding="utf-8"))
                    age_m = _parse_et_ts_minutes(hp_data.get("last_repriced") or "")
                    if age_m is None:
                        out.append(_f("data_quality", "portfolio_repriced_unknown", "warning",
                                      "holdings.json missing last_repriced"))
                    elif age_m > max_m:
                        sev = "critical" if age_m > max_m * 2 else "warning"
                        out.append(_f("data_quality", "portfolio_repricer_stale", sev,
                                      f"Portfolio last_repriced stale {age_m:.0f}m (max {max_m:.0f}m)",
                                      age_minutes=age_m))
                    out.extend(_check_portfolio_totals_drift(hp_data, pcfg))
                    out.extend(_check_snaptrade_cash_stale(hp_data, pcfg))
                except Exception as ex:
                    out.append(_f("data_quality", "portfolio_repriced_error", "warning",
                                  f"holdings last_repriced check error: {ex}"))

            mq = _db("""SELECT EXTRACT(EPOCH FROM (NOW() - MAX(fetched_at)))/60.0 AS age_m
                        FROM market_quotes""", fetch="one")
            if mq and mq.get("age_m") is not None:
                mq_age = float(mq["age_m"])
                mq_max = float(pcfg.get("market_quotes_max_age_minutes", max_m))
                if mq_age > mq_max:
                    out.append(_f("data_quality", "market_quotes_stale", "warning",
                                  f"market_quotes DB stale {mq_age:.0f}m (max {mq_max:.0f}m)",
                                  age_minutes=mq_age))
    except Exception as e:
        out.append(_f("data_quality", "collector_error", "info", f"data_quality check error: {e}"))

    # ── Agent Liveness Check ──
    # Ignore test_*/fixture agents — they burn critical score without a safe auto-restart.
    try:
        rows = _db("""
            SELECT agent_id, last_seen, status,
                   EXTRACT(EPOCH FROM (now() - last_seen))/60 as minutes_since_seen
            FROM agent_heartbeat
            WHERE last_seen < now() - interval '5 minutes'
              AND status != 'DEAD'
              AND agent_id NOT ILIKE 'test\\_%'
              AND agent_id NOT ILIKE 'fixture\\_%'
              AND agent_id NOT ILIKE 'dummy\\_%'
        """, fetch="all")
        if rows:
            for row in rows:
                agent_id = row["agent_id"]
                last_seen = row["last_seen"]
                status = row["status"]
                mins = float(row["minutes_since_seen"])
                severity = "P0" if mins > 30 else ("P1" if mins > 10 else "P2")
                problem_label = "HUNG" if mins > 30 else "LATE"
                out.append({
                    "category": "data_quality",
                    "type": f"agent::{agent_id}",
                    "severity": "critical" if severity == "P0" else ("warning" if severity == "P1" else "info"),
                    "message": f"Agent {agent_id} ({status}) last seen {mins:.0f}min ago",
                    "producer": f"agent::{agent_id}",
                    "problem": problem_label,
                    "description": f"Agent {agent_id} ({status}) last seen {mins:.0f}min ago",
                    "latest_reading": str(last_seen),
                    "needs_restart": mins > 15,
                    "auto_retry": f"agent_restart::{agent_id}" if mins > 15 else None,
                })
    except Exception:
        pass  # graceful if table doesn't exist yet

    return out


def _count_real_pipeline_failures(hours: int = 24) -> int:
    """Count failed pipeline runs with substantive errors that have NOT since recovered.

    Recovery-aware: a pipeline that failed earlier but has a later successful run for the same
    pipeline_key is healthy now — counting those stale failures kept execution_health pinned low
    for a full 24h after a transient blip (e.g. a morning 'connection already closed' burst that
    recovered by 08:18). We only count failures with no same-key success at a later started_at.
    Still excludes zombie rows and failed-with-empty-errors bookkeeping."""
    row = _db(
        f"""SELECT COUNT(*) AS c FROM pipeline_runs f
            WHERE f.status='failed'
              AND f.started_at > now() - interval '{int(hours)} hours'
              AND (f.summary IS NULL OR f.summary::text NOT LIKE '%%zombie run cleared%%')
              AND NOT (
                f.summary IS NOT NULL AND (
                  f.summary::text ~ '"errors"\\s*:\\s*\\[\\s*\\]'
                  OR COALESCE(f.summary::jsonb->>'errors', 'x') IN ('', '[]')
                  OR (jsonb_typeof(f.summary::jsonb->'errors') = 'array'
                      AND jsonb_array_length(f.summary::jsonb->'errors') = 0)
                )
              )
              AND NOT EXISTS (
                SELECT 1 FROM pipeline_runs s
                WHERE s.pipeline_key = f.pipeline_key
                  AND s.status = 'success'
                  AND s.started_at > f.started_at
              )""",
        fetch="one",
    )
    return int((row or {}).get("c") or 0)


def collect_execution_health() -> list[dict]:
    out = []
    try:
        # recent pipeline failures — exclude zombie rows and failed-with-empty-errors bookkeeping
        pf_count = _count_real_pipeline_failures(24)
        if pf_count > 0:
            rc_note = ""
            try:
                from lib import health_root_cause_memory as _rcmem
                mem = _rcmem.summary_for("pipeline_failures")
                if mem.get("last_root_cause"):
                    rc_note = (
                        f" [rc={mem.get('last_root_cause')}; "
                        f"fix={str(mem.get('last_how_to_fix') or '')[:120]}; "
                        f"strategy={mem.get('last_strategy_id')}]"
                    )
            except Exception:
                pass
            out.append(_f("execution_health", "pipeline_failures", "warning" if pf_count <= 5 else "critical",
                          f"{pf_count} pipeline run failures in 24h{rc_note}", count=pf_count))
        # stuck queued agent jobs — distinguish DECISION-FEEDING jobs (have an SLA) from the rolling
        # background research/discovery queue (no SLA; drained by priority, intentionally backloggy).
        # Penalizing execution_health for a research backlog was a false signal — only time-sensitive
        # jobs starved >2h are an execution defect; the rolling backlog is reported as info.
        from lib.watchlist_priority import TIME_SENSITIVE_REQUEST_TYPES as _TIME_SENSITIVE
        qt = _db("""SELECT COUNT(*) AS c FROM watchlist_agent_jobs
                    WHERE status='queued' AND created_at < now() - interval '2 hours'
                      AND request_type = ANY(%s)""", (list(_TIME_SENSITIVE),), fetch="one")
        if qt and qt.get("c", 0) > 0:
            n = qt["c"]
            out.append(_f("execution_health", "agent_jobs_stuck", "warning" if n < 40 else "critical",
                          f"{n} decision-feeding agent jobs queued >2h", count=n))
        qr = _db("""SELECT COUNT(*) AS c FROM watchlist_agent_jobs
                    WHERE status='queued' AND created_at < now() - interval '2 hours'
                      AND request_type <> ALL(%s)""", (list(_TIME_SENSITIVE),), fetch="one")
        if qr and qr.get("c", 0) >= 150:
            out.append(_f("execution_health", "research_backlog", "info",
                          f"{qr['c']} background research/discovery jobs queued >2h (no SLA, priority-drained)",
                          count=qr["c"]))
        # execution-integrity escalation queue depth (system_health_agent output)
        try:
            items = json.loads(QUEUE_FILE.read_text()) if QUEUE_FILE.exists() else []
        except Exception:
            items = []
        # Only count non-health_agent escalations (system_health_agent, etc.) — health_agent must not
        # count its own enqueued findings or the execution_escalations meta-type (feedback loop).
        _META = frozenset({"health:execution_health:execution_escalations"})
        crit = [i for i in items
                if (i.get("severity") in ("CRITICAL", "critical") or i.get("critical"))
                and i.get("component") not in _META
                and (i.get("source") or "") not in ("health_agent", "health_agent_meta")]
        if crit:
            out.append(_f("execution_health", "execution_escalations", "critical",
                          f"{len(crit)} critical execution escalations open",
                          components=[i.get("component") for i in crit[:6]]))
        # orphaned protective stops
        orph = _db("SELECT COUNT(*) AS c FROM stop_lifecycle WHERE lifecycle='orphaned'", fetch="one")
        if orph and orph.get("c", 0) > 0:
            out.append(_f("execution_health", "orphaned_stops", "warning",
                          f"{orph['c']} orphaned stop orders", count=orph["c"]))
        # pending rows with wrong lifecycle (phantom false-positive source)
        lc_mis = _db("""SELECT COUNT(*) AS c FROM paper_trades
                        WHERE status='pending' AND lifecycle_state='open'
                          AND COALESCE(broker_order_id,'')=''""", fetch="one")
        if lc_mis and lc_mis.get("c", 0) > 0:
            out.append(_f("execution_health", "pending_lifecycle_mismatch", "critical",
                          f"{lc_mis['c']} pending trade(s) with lifecycle_state=open (phantom risk)",
                          count=lc_mis["c"], kind="code"))
        # stale never-submitted trades (should be auto-cancelled by monitor/submitter)
        stale_ns = _db("""SELECT COUNT(*) AS c FROM paper_trades
                          WHERE status IN ('pending','open')
                            AND COALESCE(broker_order_id,'')='' AND filled_at IS NULL
                            AND created_at < now() - interval '20 minutes'""", fetch="one")
        if stale_ns and stale_ns.get("c", 0) > 0:
            out.append(_f("execution_health", "never_submitted_stale", "warning",
                          f"{stale_ns['c']} trade(s) pending >20m without broker order",
                          count=stale_ns["c"]))
        # ATM-bypass guard: every executed/automated trade must trace back to a proposal that was
        # PRESENTED in the queue (account-agnostic). A trade with no source_proposal_id/proposal_id
        # skipped the proposal review — flag it (operator requirement: any ATM trade → Proposals).
        byp = _db("""SELECT COUNT(*) AS c FROM paper_trades
                     WHERE status IN ('open','closed') AND created_at > now() - interval '7 days'
                       AND (source_proposal_id IS NULL OR source_proposal_id='') AND proposal_id IS NULL""",
                  fetch="one")
        if byp and byp.get("c", 0) > 0:
            out.append(_f("execution_health", "atm_proposal_bypass", "warning",
                          f"{byp['c']} executed trade(s) in 7d not linked to a proposal — every ATM trade "
                          f"must be presented in Proposals first",
                          count=byp["c"]))
    except Exception as e:
        out.append(_f("execution_health", "collector_error", "info", f"execution check error: {e}"))
    return out


def collect_intelligence_quality() -> list[dict]:
    out = []
    try:
        # local LLM reachable?
        import urllib.request
        base = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:11434")
        up = False
        try:
            with urllib.request.urlopen(base.rstrip("/") + "/api/tags", timeout=5) as r:
                up = r.status == 200
        except Exception:
            up = False
        if not up:
            out.append(_f("intelligence_quality", "local_llm_down", "critical",
                          "Local LLM (Ollama) not reachable", base_url=base, kind="code"))
        # ensemble failures
        ef = _db("SELECT COUNT(*) AS c FROM inference_ensemble_jobs WHERE status='failed' AND requested_at > now() - interval '24 hours'", fetch="one")
        if ef and ef.get("c", 0) > 0:
            out.append(_f("intelligence_quality", "ensemble_failures", "warning",
                          f"{ef['c']} ensemble jobs failed in 24h", count=ef["c"]))
        # stale research backlog
        aged = _db("SELECT MAX(EXTRACT(DAY FROM now()-created_at)) AS d FROM hermes_research_intelligence WHERE status='staged'", fetch="one")
        if aged and aged.get("d") and float(aged["d"]) > 14:
            out.append(_f("intelligence_quality", "research_stale", "warning",
                          f"oldest staged research is {int(float(aged['d']))}d old", days=int(float(aged["d"]))))
        # Hermes → RAG pipeline (promoted research must reach content_embeddings)
        promoted = int((_db("SELECT COUNT(*) AS c FROM hermes_research_intelligence WHERE status='promoted'", fetch="one") or {}).get("c", 0))
        embedded = int((_db("SELECT COUNT(*) AS c FROM content_embeddings WHERE source_type='hermes_research'", fetch="one") or {}).get("c", 0))
        pending = int((_db("SELECT COUNT(*) AS c FROM hermes_embedding_queue WHERE embedding_status='pending'", fetch="one") or {}).get("c", 0))
        failed = int((_db("SELECT COUNT(*) AS c FROM hermes_embedding_queue WHERE embedding_status='failed'", fetch="one") or {}).get("c", 0))
        if promoted >= 50:
            cov = embedded / max(promoted, 1)
            if cov < 0.10:
                out.append(_f("intelligence_quality", "hermes_rag_gap", "critical",
                              f"Hermes RAG coverage {cov * 100:.1f}% ({embedded}/{promoted} embedded)",
                              promoted=promoted, embedded=embedded, coverage_pct=round(cov * 100, 1)))
            elif cov < 0.50:
                out.append(_f("intelligence_quality", "hermes_rag_gap", "warning",
                              f"Hermes RAG coverage {cov * 100:.1f}% ({embedded}/{promoted} embedded)",
                              promoted=promoted, embedded=embedded, coverage_pct=round(cov * 100, 1)))
        # Gate-aware: the RAG embedding worker is operator-gated (curator approved 2026-06-02, RAG write
        # still gated → hermes_embedding_worker defaults dry-run + has no scheduled --apply run). When
        # gated, a pending backlog is BY DESIGN, not a quality defect — surface as info, don't penalize.
        rag_gated = True
        try:
            import subprocess as _sp
            _cr = _sp.run(["crontab", "-l"], capture_output=True, text=True, timeout=5).stdout
            rag_gated = not any("hermes_embedding_worker" in ln and "--apply" in ln for ln in _cr.splitlines())
        except Exception:
            rag_gated = True
        _gate_note = " (RAG worker gated by design — not a defect)" if rag_gated else " in queue"
        if pending >= 2000:
            out.append(_f("intelligence_quality", "hermes_embed_backlog", "info" if rag_gated else "critical",
                          f"{pending} Hermes embeddings pending{_gate_note}", count=pending, rag_gated=rag_gated))
        elif pending >= 200:
            out.append(_f("intelligence_quality", "hermes_embed_backlog", "info" if rag_gated else "warning",
                          f"{pending} Hermes embeddings pending{_gate_note}", count=pending, rag_gated=rag_gated))
        if failed >= 10:
            out.append(_f("intelligence_quality", "hermes_embed_failures", "warning",
                          f"{failed} Hermes embedding jobs failed", count=failed))
        elif failed > 0:
            out.append(_f("intelligence_quality", "hermes_embed_failures", "info",
                          f"{failed} Hermes embedding jobs failed", count=failed))
        # Coordinator tick freshness (cron */15m)
        coord = _db("""SELECT EXTRACT(EPOCH FROM (now() - created_at))/60 AS age_min
                       FROM hermes_memory_events
                       WHERE hermes_agent_name='chief_hermes_coordinator' AND event_type='agent_state_change'
                       ORDER BY created_at DESC LIMIT 1""", fetch="one")
        age_min = float((coord or {}).get("age_min") or 999)
        # llm_priority_guard DEFERS coordinator ticks 06:00-12:00 ET weekdays (market-critical GPU
        # window) — in-window silence is by design and fired a false critical every morning
        # (2026-07-06 audit: last tick 05:45 flagged at 09:22). Judge only the pre-window portion
        # of the age: a coordinator that was already stale before 06:00 still alerts.
        _now = datetime.now()
        _in_guard = _now.weekday() < 5 and 6 <= _now.hour < 12
        if _in_guard:
            age_min -= (_now - _now.replace(hour=6, minute=0, second=0, microsecond=0)).total_seconds() / 60
        _note = " (guard-window adjusted)" if _in_guard else ""
        if age_min > 60:
            out.append(_f("intelligence_quality", "hermes_coordinator_stale", "critical",
                          f"Hermes coordinator last tick {int(age_min)}m ago{_note}", age_min=int(age_min)))
        elif age_min > 30:
            out.append(_f("intelligence_quality", "hermes_coordinator_stale", "warning",
                          f"Hermes coordinator last tick {int(age_min)}m ago{_note}", age_min=int(age_min)))
    except Exception as e:
        out.append(_f("intelligence_quality", "collector_error", "info", f"intelligence check error: {e}"))
    return out


def collect_hermes_scope_governor_health() -> list[dict]:
    """Hermes Scope Governor + event feeder cron liveness (not silent flock -n skips)."""
    out: list[dict] = []
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))
        from lib.hermes_scope_governor.health import check_scope_governor_health
        conn = None
        try:
            from db_adapter import _get_conn, USE_DB
            if USE_DB:
                conn = _get_conn()
        except Exception:
            conn = None
        for f in check_scope_governor_health(conn):
            extra = {k: v for k, v in f.items() if k not in ("type", "severity", "message")}
            out.append(_f("intelligence_quality", f["type"], f["severity"], f["message"], **extra))
    except Exception as e:
        out.append(_f("intelligence_quality", "hermes_scope_governor_monitor_error", "info",
                      f"scope governor health check failed: {str(e)[:80]}"))
    return out


def collect_risk_protection() -> list[dict]:
    out = []
    try:
        # open paper positions with no stop recorded
        unp = _db("""SELECT COUNT(*) AS c FROM paper_trades
                     WHERE status='open' AND (stop_loss IS NULL OR stop_loss=0)""", fetch="one")
        if unp and unp.get("c", 0) > 0:
            out.append(_f("risk_protection", "unprotected_positions", "critical",
                          f"{unp['c']} open positions without a stop", count=unp["c"]))
        # stop lifecycle alerts — but a rejected NATIVE stop is NOT unprotected if an armed SYNTHETIC stop
        # covers the same symbol/account (Schwab rejects fractional STOPs by design → synthetic takes over).
        # Cross-reference synthetic_stops so fractional positions don't trip a false 'unprotected' alert.
        al = _db("""SELECT COUNT(*) AS c FROM stop_lifecycle sl
                    WHERE sl.health='alert'
                      AND NOT EXISTS (SELECT 1 FROM synthetic_stops ss
                                      WHERE ss.symbol = sl.symbol AND ss.account = sl.account
                                        AND ss.status = 'armed')""", fetch="one")
        if al and al.get("c", 0) > 0:
            out.append(_f("risk_protection", "stop_alerts", "warning",
                          f"{al['c']} stops in alert state (no synthetic coverage)", count=al["c"]))
        try:
            import sys as _sysc
            from pathlib import Path as _P
            _root = _P(__file__).resolve().parent.parent
            _sysc.path.insert(0, str(_root / "scripts" / "lib"))
            from stop_consensus_check import detect_conflicts
            _soc = detect_conflicts(project_root=_root)
            if _soc:
                syms = ", ".join(c["symbol"] for c in _soc[:5])
                out.append(_f("risk_protection", "stop_over_consensus", "warning",
                              f"{len(_soc)} stop(s) above Street mean ({syms})", count=len(_soc)))
        except Exception:
            pass
        # recent P0/P1 protection SIEM events — count DISTINCT unresolved issues, not duplicate
        # re-alert rows. The log scraper (and others) can emit the same underlying error every cycle;
        # counting raw rows let one stale-but-fixed traceback read as "26 P0/P1 alerts" and pinned
        # risk_protection critical. We dedup by raw_text and exclude already-resolved alerts so the
        # score reflects distinct open problems. (log_error_scraper now also offset-tails to stop the
        # re-alert source at the root.)
        p = _db("""SELECT COUNT(DISTINCT COALESCE(NULLIF(raw_text,''), alert_uid::text, id::text)) AS c
                   FROM alert_events
                   WHERE severity IN ('critical','urgent')
                     AND created_at > now() - interval '24 hours'
                     AND COALESCE(lifecycle_state,'active') NOT IN ('resolved','acknowledged')""",
                fetch="one")
        if p and p.get("c", 0) > 0:
            out.append(_f("risk_protection", "siem_p0p1", "warning" if p["c"] < 5 else "critical",
                          f"{p['c']} distinct P0/P1 SIEM issues open (24h)", count=p["c"]))
    except Exception as e:
        out.append(_f("risk_protection", "collector_error", "info", f"risk check error: {e}"))
    return out


def collect_retirement_planning() -> list[dict]:
    out = []
    try:
        div = {}
        dpath = STATE_DIR / "dividend_calendar.json"
        if dpath.exists():
            try:
                div = json.loads(dpath.read_text()) or {}
            except Exception:
                div = {}
        # Canonical retirement state — same source the /api/v2/retirement endpoint reads.
        rr = {}
        rrpath = STATE_DIR / "retirement_roadmap.json"
        if rrpath.exists():
            try:
                rr = json.loads(rrpath.read_text()) or {}
            except Exception:
                rr = {}
        gw = rr.get("golden_window")
        if not gw:
            out.append(_f("retirement_planning", "golden_window_missing", "warning",
                          "golden_window not present in retirement state"))
        total = div.get("total_annual") or div.get("annual_income")
        if total in (None, 0):
            out.append(_f("retirement_planning", "dividend_income_zero", "warning",
                          "dividend annual income is 0/missing — likely a data inconsistency"))
        age = _file_age_h(dpath)
        if age is None:
            out.append(_f("retirement_planning", "dividend_calendar_missing", "warning",
                          "dividend_calendar.json missing"))
    except Exception as e:
        out.append(_f("retirement_planning", "collector_error", "info", f"retirement check error: {e}"))
    return out


# policy made available to arg-less collectors (set by compute() before the collectors run)
_POLICY: dict = {}


def collect_strategy_output() -> list[dict]:
    """Catch 'silent zero' strategy failures: an active, tilt-weighted strategy that graded 0 signals
    today even though the pipeline ran fine. This is the FIB-style gap (verify_fib_proposals.py) —
    generalized to every strategy. Gated to avoid morning false-positives: only on trading days, only
    after the configured hour, and only for strategies with a recent baseline (fired in prior days)."""
    out = []
    cfg = (_POLICY.get("strategy_output") or {})
    if not cfg.get("enabled", True):
        return out
    try:
        try:
            from market_session import is_trading_day
            if not is_trading_day():
                return out  # no signals expected off-session
        except Exception:
            pass
        check_after = int(cfg.get("check_after_hour", 11))  # server clock is ET
        if datetime.now().hour < check_after:
            return out  # too early to judge "zero today"
        tilt_min = float(cfg.get("tilt_min", 1.0))
        rows = _db("""SELECT strategy_id,
                        COUNT(*) FILTER (WHERE fired_at::date = CURRENT_DATE) AS today,
                        COUNT(*) FILTER (WHERE fired_at::date < CURRENT_DATE) AS prior
                      FROM strategy_signals
                      WHERE fired_at > now() - interval '7 days'
                      GROUP BY strategy_id""", fetch="all") or []
        try:
            import strategy_tilt as _st
        except Exception:
            _st = None
        for r in rows:
            sid = r.get("strategy_id")
            if r.get("today", 0) != 0 or r.get("prior", 0) <= 0:
                continue  # produced today, or no baseline → not a silent zero
            try:
                tilt = float(_st.get_tilt(sid)) if _st else 1.0
            except Exception:
                tilt = 1.0
            if tilt < tilt_min:
                continue
            out.append(_f("execution_health", "strategy_zero_output",
                          "warning" if tilt >= 1.5 else "info",
                          f"{sid}: 0 signals today (tilt {tilt}, {r['prior']} fired in prior 7d)",
                          strategy=sid, tilt=tilt, prior_7d=r["prior"]))
    except Exception as e:
        out.append(_f("execution_health", "collector_error", "info", f"strategy_output check error: {e}"))
    return out


def collect_proposal_maturity() -> list[dict]:
    """Monitor proposal volume/quality across Options, Trades, Watchlist, Rotation."""
    out = []
    cfg = (_POLICY.get("proposal_maturity") or {})
    if not cfg.get("enabled", True):
        return out
    try:
        import options_engine as oe
        metrics = oe.get_proposal_health_metrics()
        opt = metrics.get("options") or {}
        count = int(opt.get("proposal_count") or 0)
        age_min = opt.get("cache_age_min")
        stale_h = float(cfg.get("options_stale_hours", 4)) * 60
        min_count = int(cfg.get("options_min_count", 1))
        if age_min is not None and age_min > stale_h:
            out.append(_f("execution_health", "options_proposals_stale", "warning",
                          f"Options cache {int(age_min)}m old (>{int(stale_h)}m)",
                          count=count, age_min=age_min))
        try:
            from market_session import is_trading_day
            trading = is_trading_day()
        except Exception:
            trading = datetime.now().weekday() < 5
        check_after = int(cfg.get("check_after_hour", 10))
        if trading and datetime.now().hour >= check_after and count < min_count:
            out.append(_f("execution_health", "options_zero_proposals", "warning",
                          f"No options proposals ({count}) — desk empty after {check_after}:00",
                          count=count, kind="code"))
        pending = (metrics.get("trades") or {}).get("pending_proposals")
        if pending is not None and pending >= int(cfg.get("trade_pending_warn", 25)):
            out.append(_f("execution_health", "trade_proposals_backlog", "warning",
                          f"{pending} pending trade proposals awaiting review", count=pending))
        wl_stale = (metrics.get("watchlist") or {}).get("stale_active_7d")
        if wl_stale is not None and wl_stale >= int(cfg.get("watchlist_stale_warn", 15)):
            out.append(_f("intelligence_quality", "watchlist_stale", "warning",
                          f"{wl_stale} active watchlist items stale >7d", count=wl_stale))
        rot = (metrics.get("rotation") or {}).get("pending_recommendations")
        if rot is not None and rot == 0 and trading and datetime.now().hour >= 14:
            out.append(_f("intelligence_quality", "rotation_empty", "info",
                          "No pending rotation recommendations", count=0))
        try:
            import market_rotation_signals as mrs
            rot_sig = mrs.detect_small_cap_rotation()
            cov = mrs.coverage_gap(rot_sig)
            if cov.get("has_market_signal") and cov.get("gaps"):
                out.append(_f("intelligence_quality", "small_cap_signal_gap", "warning",
                              f"Small-cap outperformance detected but system gaps: {', '.join(cov['gaps'])}",
                              rs_20d=rot_sig.get("rs_20d"), rs_1d=rot_sig.get("rs_1d"),
                              gaps=cov.get("gaps"), news_count=cov.get("news_count"),
                              proposal_count=cov.get("proposal_count"),
                              watchlist_count=cov.get("watchlist_count")))
        except Exception:
            pass
        # Proposal → manual execution conversion + tagging (closed-loop monitor)
        track = metrics.get("execution_tracking") or {}
        if track:
            tag_pct = float(track.get("tagging_rate_pct") or 100)
            conv_pct = float(track.get("proposal_conversion_pct") or 0)
            untagged = int(track.get("untagged_manual") or 0)
            opt_active = int(track.get("options_proposals_active") or 0)
            opt_logged = int(track.get("options_executions_logged") or 0)
            if untagged >= 3 and tag_pct < 70:
                out.append(_f("execution_health", "manual_tagging_failing", "warning",
                              f"{untagged} manual executions untagged ({tag_pct:.0f}% tagging rate)",
                              untagged=untagged, tagging_rate_pct=tag_pct))
            pending_broker = int(track.get("broker_proposals_pending_7d") or 0)
            if pending_broker >= 5 and conv_pct < 15:
                out.append(_f("execution_health", "proposal_conversion_low", "warning",
                              f"Only {conv_pct:.0f}% broker proposals logged as executed ({pending_broker} pending)",
                              conversion_pct=conv_pct, pending=pending_broker))
            if opt_active >= 4 and opt_logged == 0 and trading:
                out.append(_f("execution_health", "options_proposals_ignored", "info",
                              f"{opt_active} quality options proposals — none logged as manually executed",
                              options_active=opt_active, options_logged=opt_logged))
        # Broker queue conversion: approved broker-route proposals stuck without live_submit_path
        try:
            from proposal_execution_readiness import collect_execution_readiness
            readiness = collect_execution_readiness(since_days=7)
            unrouted = int(readiness.get("broker_unrouted_48h") or 0)
            link_pct = float(readiness.get("link_rate_pct") or 0)
            target_link = float(readiness.get("target_link_rate_pct") or 15)
            unrouted_warn = int(cfg.get("broker_unrouted_warn", 3))
            unrouted_crit = int(cfg.get("broker_unrouted_critical", 8))
            link_warn = float(cfg.get("link_rate_warn_pct", 5))
            if unrouted >= unrouted_warn:
                sev = "critical" if unrouted >= unrouted_crit else "warning"
                out.append(_f("execution_health", "broker_proposals_unrouted", sev,
                              f"{unrouted} broker-route proposals >48h without submit tag — conversion stalled",
                              count=unrouted, link_rate_pct=link_pct))
            if link_pct < link_warn and int(readiness.get("created") or 0) >= 10:
                out.append(_f("execution_health", "proposal_link_rate_low", "warning",
                              f"Execution link rate {link_pct:.1f}% (target {target_link:.0f}%)",
                              link_rate_pct=link_pct, created=readiness.get("created")))
        except Exception:
            pass
    except Exception as e:
        out.append(_f("execution_health", "collector_error", "info",
                      f"proposal_maturity check error: {e}"))
    return out


def collect_log_errors() -> list[dict]:
    """Scan key component logs for ERROR/Traceback/CRITICAL spikes (content, not just staleness).
    Only recently-modified logs are considered, so old errors don't re-alarm."""
    import re as _re
    import time as _t
    out = []
    cfg = (_POLICY.get("log_errors") or {})
    if not cfg.get("enabled", True):
        return out
    watch = cfg.get("watch") or [
        "auto_proposal.log", "screener_pm.log", "news_ingestion.log", "paper_execution.log",
        "unified_stop_supervisor.log", "pipeline_watchdog.log", "atm.log", "cio_decisions.log",
        "data_gap_resolver.log", "rag_indexer.log", "health_agent_cron.log", "coder_dispatch_cron.log",
        "hermes_scope_governor.log", "hermes_event_feeder.log",
    ]
    window_h = float(cfg.get("window_hours", 3))
    threshold = int(cfg.get("error_threshold", 5))
    tail = int(cfg.get("tail_lines", 400))
    # Case-SENSITIVE: match real log-level tokens / error markers, NOT domain words like the
    # severity label "high/critical" in a normal summary line (that caused false positives).
    pat = _re.compile(r"\bERROR\b|\bCRITICAL\b|\bFATAL\b|Traceback \(most recent call last\)"
                      r"|\bException\b|[A-Za-z]*error:|[A-Za-z]*exception:"
                      # "Error:" with the colon — e.g. "[email] Error: [Errno 2] ... 'gog'" (the dead
                      # email lane was invisible to this scraper, 2026-07-06 audit); the colon keeps
                      # prose like "HTTP Error 404" from matching
                      r"|\bError:")
    now = _t.time()
    try:
        for name in watch:
            p = LOG_DIR / name
            if not p.exists():
                continue
            if now - p.stat().st_mtime > window_h * 3600:
                continue  # not recently active → not a current spike
            try:
                lines = p.read_text(errors="ignore").splitlines()[-tail:]
            except Exception:
                continue
            # Timestamp window (2026-07-17): only count error lines DATED inside window_hours.
            # The old tail-400 + mtime gate pinned quiet logs critical for DAYS after an
            # incident — the error lines stayed inside the 400-line tail while unrelated
            # writes kept mtime fresh (three logs held execution_health at 0 all day on
            # morning-incident lines). Undated lines (traceback frames, continuation output)
            # inherit the previous dated line's time; a log with no timestamps at all keeps
            # the old mtime-gated behavior rather than going blind.
            _ts_pat = _re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})")
            _cutoff = datetime.now() - timedelta(hours=window_h)
            # Pre-first-timestamp fragments in a log that HAS timestamps are by construction
            # the OLDEST content in the tail — counting them under the no-timestamp fallback
            # pinned the 09:00 slot-exhaustion FATALs as "recent" all afternoon (2026-07-17).
            # The fallback now applies ONLY to logs with no timestamps anywhere in the tail.
            _has_any_ts = any(_ts_pat.search(ln) for ln in lines)
            _last_ts = None
            errs = []
            for ln in lines:
                _m = _ts_pat.search(ln)
                if _m:
                    try:
                        _last_ts = datetime.strptime(f"{_m.group(1)} {_m.group(2)}", "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        pass
                if not pat.search(ln):
                    continue
                if _last_ts is not None:
                    if _last_ts >= _cutoff:
                        errs.append(ln)
                elif not _has_any_ts:
                    errs.append(ln)
            if len(errs) >= threshold:
                out.append(_f("execution_health", "log_errors",
                              "critical" if len(errs) >= threshold * 3 else "warning",
                              f"{name}: {len(errs)} error lines in last {tail} (recent)",
                              log=name, count=len(errs), sample=(errs[-1][:160] if errs else ""),
                              kind="code"))
    except Exception as e:
        out.append(_f("execution_health", "collector_error", "info", f"log_errors check error: {e}"))
    return out


# ── Actionability: why each finding matters + what to do about it ────────────────────────────────────
# Makes every finding self-justifying (impact) and actionable (recommended fix). The "what was actually
# DONE + who/when" is attached at read time by the API from claude_interventions + coder_dispatch_audit.
WHY = {
    "log_errors": "A component log is throwing repeated errors — a job is failing/looping and silently dropping work.",
    "strategy_zero_output": "An active, tilt-weighted strategy produced nothing today — missed setups/proposals for that edge.",
    "pipeline_failures": "Failed pipeline runs mean downstream signals, proposals or decisions may be missing/stale.",
    "agent_jobs_stuck": "Decision-feeding agent jobs (proposal/full-analysis/research-gap) aren't draining within SLA — proposals and reviews are going stale.",
    "research_backlog": "Background research/discovery queue is large but has no SLA — drained by priority; informational unless it never shrinks.",
    "proposal_thesis_broken": "A PENDING proposal's live price has passed its target or fallen to its stop — there is no valid live R:R; verify it's expiring/recalibrating and not displaying a stale favorable R:R.",
    "atm_proposal_bypass": "An executed/automated trade isn't linked to a proposal — it skipped the Proposals queue review. Every ATM trade must be presented in Proposals first (account-agnostic).",
    "execution_escalations": "Critical execution escalations are unresolved failures already flagged by the integrity agent.",
    "orphaned_stops": "Orphaned stop orders may not actually protect a live position — real risk exposure.",
    "unprotected_positions": "Open positions with no stop = unbounded downside risk.",
    "stop_alerts": "Stops in alert state may be mispriced or near trigger and need review.",
    "siem_p0p1": "High-severity (P0/P1) protection/execution SIEM events are open and need review.",
    "local_llm_down": "The local LLM is the free-lane analysis brain; down means degraded intelligence or metered fallback.",
    "ensemble_failures": "Ensemble validation failures weaken proposal/decision confidence.",
    "research_stale": "Hermes research backlog isn't being promoted/refreshed.",
    "hermes_rag_gap": "Promoted Hermes research isn't in RAG — agents read stale/missing context.",
    "hermes_embed_backlog": "Hermes embedding queue is backing up — RAG won't catch up until drained.",
    "hermes_embed_failures": "Ollama embedding failures — check nomic-embed-text and retry worker.",
    "hermes_coordinator_stale": "Hermes coordinator hasn't ticked — auto-promote and fleet agents may be stalled.",
    "hermes_scope_governor_stale": "Scope governor hasn't run — Hot/Warm/Cold tier ledger is stale; Hermes may score the wrong universe.",
    "hermes_scope_governor_cron_missing": "Scope governor is not scheduled — scope_tier will never update.",
    "hermes_scope_governor_cron_unobservable": "Scope governor uses flock -n — skipped runs are invisible until tiers go stale.",
    "hermes_scope_governor_lock_skips": "Scope governor runs are being skipped because a prior run is still holding the lock (wedged or too slow).",
    "hermes_scope_governor_underrunning": "Scope governor is firing far fewer than 48 runs/day — cron skips or crashes.",
    "hermes_event_feeder_stale": "Score event feeder hasn't run — archived (S3) symbols won't reactivate on catalyst/news.",
    "hermes_event_feeder_cron_missing": "Event feeder is not scheduled — the event lane is off.",
    "hermes_governed_universe_stale": "Governed universe JSON feed is old — Hermes consumers read outdated Hot/Warm/Cold scope.",
    "options_zero_proposals": "Options desk produced zero proposals — income/CC opportunities may be invisible in Command Center.",
    "options_proposals_stale": "Options proposal cache is stale — UI may show outdated or empty ideas.",
    "options_snapshot_retention_stale": "options_chain_snapshots isn't being pruned — the vol-surface table grows unbounded (retention regression).",
    "options_snapshot_table_bloat": "options_chain_snapshots row count is high — confirm the daily retention sweep is running.",
    "options_approval_backlog": "Desk approval queue is backing up — pending options proposals aren't being reviewed/approved, blocking the live path.",
    "options_approval_blocked_pileup": "Many options proposals are auto-blocked (illiquid/gated) — not an operator-review lag, but the desk universe or liquidity gates may need a look.",
    "proposal_creation_burst": "A burst of new proposals each trigger local+cloud LLM oversight — bulk creation can overload the single-threaded server (the 2026-06-26 load incident). Throttle the producing screener/bridge.",
    "pullback_macd_scan_stale": "The daily S&P 500 pullback/MACD screener hasn't run recently — the dip-buy candidate list is going stale.",
    "pullback_macd_no_runs": "The pullback/MACD screener has never recorded a run — cron may not be installed yet.",
    "pullback_macd_universe_thin": "The S&P 500 constituent table is under-populated — the weekly universe refresh may be failing, shrinking screener coverage.",
    "options_approval_expired_pending": "Pending options approvals have passed their 24h expiry without review — the queue isn't being cleaned.",
    "trade_proposals_backlog": "Many trade proposals are pending — approval queue may be clogged.",
    "enrichment_pipeline_failure": "Proposal enrichment/readiness is failing (often import or readiness API) — both paper ATM and live 2FA lanes stall without fresh readiness data.",
    "enrichment_failures_high": "Many PENDING proposals have repeated enrichment failures — ATM auto-approve and manual review queues see stale cards.",
    "approved_paper_test_stuck": "Paper-lane proposals are stuck in APPROVED_FOR_PAPER_TEST after revalidation drift or submit — no new paper trades until lifecycle is normalized.",
    "enrichment_status_in_progress_stale": "enrichment_status=IN_PROGRESS is wedged on terminal or long-idle rows — enrichment cron skips them until cleared.",
    "news_symbol_mismatch": "Yahoo RSS mis-tagged catalyst headlines on CIO-rated watchlist symbols (e.g. wrong company on thin tickers) — cards show stale/wrong news for HOLD/AVOID as well as BUY.",
    "watchlist_stale": "Watchlist items haven't been refreshed — rotation/options synergy may be weak.",
    "rotation_empty": "No rotation recommendations staged — capital redeployment signals may be missing.",
    "small_cap_signal_gap": "IWM/Russell 2000 is outperforming SPY in the market, but news curation, proposals, or watchlist lack small-cap coverage.",
    "golden_window_missing": "Retirement Golden Window drives Roth-conversion guidance; missing = a planning gap.",
    "dividend_income_zero": "Zero dividend income is almost certainly a data inconsistency, not reality.",
    "data_gaps_open": "Some symbols lack required enrichment until these gaps are resolved.",
    "finviz_quote_cache_stale": "Finviz quote cache is the authoritative portfolio price layer — stale cache = wrong Command Center P/L.",
    "portfolio_repricer_stale": "portfolio_repricer.py has not run — holdings prices lag Finviz/broker reality.",
    "portfolio_totals_drift": "Header portfolio_value disagrees with sum of position market values — Command Center shows two different totals.",
    "account_summary_drift": "An account_summary total is stale vs its holdings rows (common after SnapTrade sync without repricer).",
    "snaptrade_cash_stale": "Fidelity SPAXX cash is stale (SnapTrade position units); should use balances.buying_power (~Fidelity core MM).",
    "market_quotes_stale": "Alpaca market_quotes backup feed is stale — Fidelity fallback prices may be wrong.",
    "schwab_journal_ingest_stale": "Schwab journal ingest hasn't run recently — TradeInView trade log and round-trips lag broker reality.",
    "schwab_journal_ingest_missing": "Schwab journal ingest has no log — trade_closed may never have been populated from Schwab.",
    "journal_annotation_low": "Most closed trades lack journal annotations — behavioral analytics, pivot grid, and lessons are unreliable.",
    "journal_mfe_coverage_low": "MFE/profit-capture rows are sparse — Exit Intel and capture-ratio analytics are incomplete.",
    "trade_closed_stale": "trade_closed has no recent closes — TradeInView may show an outdated trade history.",
}


_CTA_BY_TYPE = {
    "portfolio_repricer_stale": {"label": "System → Pipeline", "route": "/v3/system?tab=pipeline"},
    "finviz_quote_cache_stale": {"label": "System → Admin", "route": "/v3/system?tab=admin"},
    "agent_jobs_processing_stuck": {"label": "System → Jobs", "route": "/v3/system?tab=jobs"},
    "trade_proposals_backlog": {"label": "Trading → Proposals", "route": "/v3/trading?tab=Proposals"},
    "enrichment_pipeline_failure": {"label": "Trading → Proposals", "route": "/v3/trading?tab=Proposals"},
    "enrichment_failures_high": {"label": "Trading → Proposals", "route": "/v3/trading?tab=Proposals"},
    "approved_paper_test_stuck": {"label": "Trading → Proposals", "route": "/v3/trading?tab=Proposals"},
    "enrichment_status_in_progress_stale": {"label": "Trading → Proposals", "route": "/v3/trading?tab=Proposals"},
    "news_symbol_mismatch": {"label": "Watch → Watchlist", "route": "/v3/watch?tab=watchlist"},
    "watchlist_stale": {"label": "Watch → Watchlist", "route": "/v3/watch?tab=watchlist"},
    "rotation_empty": {"label": "Rotation desk", "route": "/v3/rotation"},
}
_CTA_BY_CATEGORY = {
    "execution_health": {"label": "Trading → Proposals", "route": "/v3/trading?tab=Proposals"},
    "risk_protection": {"label": "Risk → Exposure", "route": "/v3/risk"},
    "pipeline_freshness": {"label": "System → Pipeline", "route": "/v3/system?tab=pipeline"},
    "intelligence_quality": {"label": "Hermes", "route": "/v3/hermes"},
    "retirement_planning": {"label": "Retirement", "route": "/v3/retirement"},
    "data_quality": {"label": "Health Agent", "route": "/v3/health"},
}


def _attach_cta(f: dict):
    """One-click operator route for CC v3 UI (Health, Home alert rail, MetricStrip)."""
    t = f.get("type", "")
    cta = _CTA_BY_TYPE.get(t) or _CTA_BY_CATEGORY.get(f.get("category", "")) or {
        "label": "Health Agent", "route": "/v3/health",
    }
    f["cta"] = cta


# Hard operator-only: never claim auto-retry; never enqueue producer scripts.
_NEVER_AUTO_DEFAULT = frozenset({
    "unprotected_positions", "siem_p0p1", "schwab_token_revoked",
    "finviz_cookie_expired", "audit_ledger_coverage_warn",
    "audit_ledger_coverage_fail", "audit_ledger_chain_break",
    "kill_switch_active",
})


def _annotate(f: dict, rmap: dict):
    """Attach why-it-matters + recommended action + actionability to a finding (write-time)."""
    t = f.get("type", "")
    never = set(_POLICY.get("never_auto_remediate") or []) | set(_NEVER_AUTO_DEFAULT)
    f["why"] = WHY.get(t) or ("Stale data product — dependent pages/decisions use old numbers."
                              if t.endswith("_stale") else f"{f.get('category','')} signal needs review.")
    cmd = rmap.get(t)
    if t in never or f.get("operator_action"):
        f["action_type"] = "operator"
        f["recommended_action"] = (
            f.get("reauth_cmd")
            or "Operator action required (risk/credential/SIEM/ledger — never auto)."
        )
        f["actionable"] = True
        f["never_auto"] = True
    elif isinstance(cmd, str) and cmd.strip():
        f["action_type"] = "auto_retry"
        f["recommended_action"] = f"Auto-retry (allowlisted): {cmd}"
        f["actionable"] = True
    elif f.get("kind") in ("code", "single_file", "multi_file", "schema"):
        f["action_type"] = "code_fix"
        f["recommended_action"] = f"Route to AI coder ({f.get('kind')}) → worktree → verify → diff/PR"
        f["actionable"] = True
    elif t.endswith("_stale") or t in ("news_stale",):
        f["action_type"] = "refresh"
        f["recommended_action"] = "Re-run the producing job to refresh this data product."
        f["actionable"] = True
    elif f.get("severity") == "info":
        f["action_type"] = "monitor"
        f["recommended_action"] = "Monitor — informational, no action required yet."
        f["actionable"] = False
    else:
        f["action_type"] = "review"
        f["recommended_action"] = "Operator review."
        f["actionable"] = True
    _attach_cta(f)


def collect_strategy_registry_integrity() -> list[dict]:
    """Strategy Weekly Review data integrity (2026-07-05 incident):
    (a) strategy_registry rows with NULL/empty strategy_id — created by an old config-loader
        upsert that omitted the column; the weekly review rendered them as 'None (UNVALIDATED)'.
        Auto-remediable: fix_strategy_registry_null_ids.py backfills strategy_id = strategy_type
        (they are real YAML strategies, not orphans — backfill, never delete) with a JSONL audit.
    (b) the weekly review's real-trade join returning 0 rows while the schwab journal
        (trade_closed) has ≥1 closed trade — the join is broken. Needs-operator alert only;
        never auto-rewrite joins."""
    out = []
    try:
        rows = _db("""SELECT strategy_type FROM strategy_registry
                      WHERE strategy_id IS NULL OR BTRIM(strategy_id) = ''""", fetch="all") or []
        if rows:
            names = sorted(str(r.get("strategy_type")) for r in rows)
            shown = ", ".join(names[:6]) + ("…" if len(names) > 6 else "")
            out.append(_f("data_quality", "strategy_registry_null_ids", "warning",
                          f"{len(rows)} strategy_registry rows have NULL/empty strategy_id ({shown}) — "
                          f"weekly review renders them as 'None (UNVALIDATED)'; backfilling "
                          f"strategy_id = strategy_type",
                          count=len(rows), strategy_types=names))
    except Exception as e:
        out.append(_f("data_quality", "collector_error", "info",
                      f"strategy_registry null-id check error: {e}"))
    try:
        st_file = STATE_DIR / "strategy_weekly_review_latest.json"
        if st_file.exists():
            age_h = _file_age_h(st_file)
            if age_h is not None and age_h <= 8 * 24:  # only judge a recent review run
                st = json.loads(st_file.read_text())
                r = _db("SELECT COUNT(*) AS n FROM trade_closed", fetch="one") or {}
                journal_n = int(r.get("n") or 0)
                seen = int(st.get("real_rows_attributed") or 0) + int(st.get("real_rows_unattributed") or 0)
                if journal_n >= 1 and seen == 0:
                    out.append(_f("data_quality", "weekly_review_real_join_zero", "critical",
                                  f"strategy weekly review saw 0 real trades but the schwab journal "
                                  f"(trade_closed) has {journal_n} closed trades — real-trade join "
                                  f"broken; needs operator review (joins are never auto-rewritten)",
                                  journal_closed=journal_n,
                                  review_generated_at=st.get("generated_at"),
                                  action_type="review"))
    except Exception as e:
        out.append(_f("data_quality", "collector_error", "info",
                      f"weekly_review real-join check error: {e}"))
    return out


CATEGORIES = ["data_quality", "execution_health", "intelligence_quality",
              "risk_protection", "retirement_planning", "pipeline_freshness"]

def collect_pipeline_freshness() -> list[dict]:
    """OUTPUT-freshness of key data pipelines — the blind spot that let ticker_snapshot_daily,
    setup_advisory, agent_performance etc. rot for weeks while their crons logged false success.
    The health agent aggregates; this is the missing prober. Stale findings are tagged kind='code'
    so a feeder that's stale despite its cron firing gets routed to coder_dispatch for a real fix."""
    out: list[dict] = []
    try:
        import pipeline_freshness_monitor as pfm
        stale, missing, _ok = pfm.check()
        # A stale OUTPUT with a known data-REFRESH remediation (e.g. backtest aggregator / proposal
        # backtest engine) is auto-retryable — don't tag it kind='code' (which would route it to the AI
        # coder); the escalation handler runs the allowlisted refresh instead. Only feeders with NO
        # remediation stay kind='code' (genuinely stale-despite-cron → needs a real code fix).
        rmap = (_POLICY.get("remediation_map") or {})
        for s in stale:
            sev = "critical" if s["age_days"] > (s["threshold_days"] * 4) else "warning"
            ftype = f"stale_{s['name']}"
            extra = {} if ftype in rmap else {"kind": "code"}
            out.append(_f("pipeline_freshness", ftype, sev,
                          f"{s['name']} output {s['age_days']}d stale (>{s['threshold_days']}d) — shown on {s['surfaced']}",
                          age_days=s["age_days"], surfaced=s["surfaced"], **extra))
        for m in missing:
            out.append(_f("pipeline_freshness", f"missing_{m['name']}", "warning",
                          f"{m['name']} produces no output ({m['reason']}) — {m['surfaced']}",
                          kind="code", surfaced=m["surfaced"]))
    except Exception as e:
        out.append(_f("pipeline_freshness", "monitor_error", "info", f"freshness monitor failed: {str(e)[:80]}"))
    return out


def _assess_momentum_scalp_scan(log_age_min, last_status, failed_stages, log_exists, in_window) -> dict:
    """Pure: decide whether the momentum_scalp Finviz 5-min early lane is healthy. Schedule-aware —
    only judges DURING the 06:00-12:00 ET window (no off-hours/weekend false alarms). Returns a dict
    {finding: bool, type, severity, message} or {finding: False}."""
    if not in_window:
        return {"finding": False, "reason": "off_window"}
    # Cron is every 5 min; >12 min of no fresh log output ⇒ ≥2 missed runs (or the scan is hung).
    if not log_exists:
        return {"finding": True, "type": "momentum_scalp_finviz_scan_stale", "severity": "warning",
                "message": "momentum_scalp Finviz 5-min scan log missing during 06:00-12:00 ET window "
                           "(cron may not be firing) — re-running the early lane"}
    if log_age_min is not None and log_age_min > 12:
        sev = "critical" if log_age_min > 30 else "warning"
        return {"finding": True, "type": "momentum_scalp_finviz_scan_stale", "severity": sev,
                "message": f"momentum_scalp Finviz 5-min scan last ran {log_age_min:.0f} min ago "
                           f"(cron is */5) during the 06:00-12:00 ET window — re-running the early lane"}
    if last_status in ("PARTIAL", "FAIL") or failed_stages:
        return {"finding": True, "type": "momentum_scalp_early_lane_error", "severity": "warning",
                "message": f"momentum_scalp early lane last run status={last_status} "
                           f"failed_stages={failed_stages or []} — re-running to recover"}
    return {"finding": False, "reason": "fresh"}


def collect_momentum_scalp_source_health() -> list[dict]:
    """Schedule-aware health for the momentum_scalp Finviz every-5-min early lane (06:00-12:00 ET).
    A stale/failing scan during the window is auto-remediable (re-run the lane, source/sandbox only —
    no broker writes), so it is NOT tagged kind='code'. Outside the window this is silent."""
    out: list[dict] = []
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        import momentum_scalp_early_lane_runner as lane
        t = lane.now_et()
        in_window = lane.is_trading_day(t) and lane.in_window(t)
        log = PROJECT_ROOT / "logs" / "finviz_momentum_scalp_scan.log"
        log_exists = log.exists()
        age_min = (_file_age_h(log) or 0) * 60 if log_exists else None
        last_status, failed_stages = None, None
        if log_exists:
            try:
                tail = log.read_text(errors="replace").strip().splitlines()
                for ln in reversed(tail[-8:]):
                    ln = ln.strip()
                    if ln.startswith("{"):
                        j = json.loads(ln)
                        last_status = j.get("status")
                        failed_stages = j.get("failed_stages")
                        break
            except Exception:
                pass
        a = _assess_momentum_scalp_scan(age_min, last_status, failed_stages, log_exists, in_window)
        if a.get("finding"):
            out.append(_f("pipeline_freshness", a["type"], a["severity"], a["message"],
                          surfaced="Trading hub · momentum scalp early lane"))
    except Exception as e:
        out.append(_f("pipeline_freshness", "momentum_scalp_source_monitor_error", "info",
                      f"momentum scalp source monitor failed: {str(e)[:80]}"))
    return out


def _assess_source_stale(age_min, threshold_min, in_window, present=True) -> dict:
    """Pure, schedule-aware staleness: only judges inside the relevant window (no off-hours floods)."""
    if not in_window:
        return {"finding": False, "reason": "off_window"}
    if not present:
        return {"finding": True, "severity": "warning", "reason": "missing"}
    if age_min is None:
        return {"finding": False, "reason": "unknown_age"}
    if age_min > threshold_min:
        return {"finding": True, "severity": "critical" if age_min > threshold_min * 3 else "warning",
                "reason": f"stale {age_min:.0f}m (>{threshold_min}m)"}
    return {"finding": False, "reason": "fresh"}


def collect_momentum_scalp_multi_source_health() -> list[dict]:
    """Schedule-aware health for the remaining momentum_scalp sources beyond the Finviz lane: SEC/Form 4
    context, strategy signal sync, proposal generation, social scan. Silent outside each source's
    window (no off-hours floods). SEC context is auto-remediable (safe source-only wrapper); the rest
    surface for visibility. Never raises."""
    out: list[dict] = []
    try:
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        import momentum_scalp_early_lane_runner as lane
        t = lane.now_et()
        trading = lane.is_trading_day(t)
        hhmm = t.strftime("%H:%M")
        # Windows: SEC context after its 05:45 cron has had a chance to run (start 06:00). The
        # proposal/signal/social OUTPUT-staleness checks are scoped to the ACTIVE session (09:30+) —
        # pre-market 06:00-09:30 is legitimately quiet (weekend-stale quotes are correctly skipped, the
        # orchestrator runs at 09:00), so "no fresh output" there is EXPECTED, not a fault. This stops
        # the pre-market false floods seen 2026-06-29 (proposal_gen 3504m, social 750m at 07:46).
        in_sec = trading and ("06:00" <= hhmm <= "12:00")            # SEC context window (05:45 + 09:15)
        in_active = trading and ("09:30" <= hhmm <= "12:00")         # post-open signal/proposal flow
        in_active_social = trading and ("09:30" <= hhmm <= "16:00")  # post-open social scan

        def _age_min(sql):
            h = _db_age_h(sql)
            return h * 60 if h is not None else None

        # SEC/Form 4 context — log freshness. Auto-remediable (re-run the context wrapper).
        sec_log = PROJECT_ROOT / "logs" / "sec_form4_momentum_context.log"
        sec_age = (_file_age_h(sec_log) or 0) * 60 if sec_log.exists() else None
        a = _assess_source_stale(sec_age, 240, in_sec, present=sec_log.exists())
        if a["finding"]:
            out.append(_f("pipeline_freshness", "sec_form4_context_stale", a["severity"],
                          f"SEC/Form 4 momentum context {a['reason']} during its 05:45-09:15 ET window "
                          f"— re-running the context wrapper (source/read-only)",
                          surfaced="momentum scalp · SEC/Form 4 catalyst context"))

        # Signal sync — strategy_signals uses fired_at (NOT created_at, which does not exist). Active
        # session only.
        a = _assess_source_stale(_age_min("SELECT MAX(fired_at) FROM strategy_signals"), 120, in_active)
        if a["finding"]:
            out.append(_f("pipeline_freshness", "momentum_scalp_signal_sync_stale", "warning",
                          f"momentum scalp signal sync output {a['reason']} during the active session",
                          surfaced="momentum scalp · signal sync"))

        # Proposal generation — CONDITION-AWARE: only a real conversion gap counts. Fire only when a
        # FRESH GO strategy_signal exists (≤120m) but no proposal has been created since it fired. If
        # there are no fresh GO signals (or candidates are correctly stale-quote-skipped), an absence of
        # proposals is EXPECTED, not a fault — so it is not flagged.
        if in_active:
            go_sig_age = _age_min("SELECT MAX(fired_at) FROM strategy_signals WHERE signal_type='GO'")
            prop_age = _age_min("SELECT MAX(created_at) FROM paper_trade_proposals")
            if go_sig_age is not None and go_sig_age <= 120 and (prop_age is None or prop_age > go_sig_age + 90):
                out.append(_f("pipeline_freshness", "momentum_scalp_proposal_gen_stale", "warning",
                              f"fresh GO signal ({go_sig_age:.0f}m) not converting — proposal generation "
                              f"output stale ({'none' if prop_age is None else f'{prop_age:.0f}m'}) post-open",
                              surfaced="momentum scalp · proposal generation"))

        # Social scan — active-session output freshness (pre-market carryover excluded).
        a = _assess_source_stale(_age_min("SELECT MAX(scanned_at) FROM scalp_scan_results"), 180, in_active_social)
        if a["finding"]:
            out.append(_f("pipeline_freshness", "momentum_scalp_social_scan_stale", "warning",
                          f"momentum scalp social scan output {a['reason']} during the active session",
                          surfaced="momentum scalp · social scan"))
    except Exception as e:
        out.append(_f("pipeline_freshness", "momentum_scalp_multi_source_monitor_error", "info",
                      f"multi-source monitor failed: {str(e)[:80]}"))
    return out


def collect_scalp_catalyst_health() -> list[dict]:
    """URGENT: the real-time momentum-scalp GO/WAIT Telegram lane. Scalp GO tier depends on catalyst
    verification (news / RAG / Hermes); when that silently produces nothing, every setup is capped to
    WAIT and suppressed, so live scalp alerts go dark — exactly the 2026-07-01→07-08 outage (GO went
    1-6/day to 0 for a week, unnoticed). This collector catches that regression fast: the scanner is
    actively producing setups but ZERO reach GO across the window.

    Only assessed while the scanner is currently active (rows in the last 18h) → no weekend/holiday
    false-fires. Auto-remediable (re-run the scanner, source/advisory only — no broker writes), so it is
    NOT kind='code'; if the retry is futile (real code/data bug), the circuit breaker escalates to the
    operator after max_ineffective_attempts."""
    cfg = (_POLICY.get("scalp_catalyst_health") or {})
    if not cfg.get("enabled", True):
        return []
    out: list[dict] = []
    window_days = int(cfg.get("window_days", 3))
    min_rows = int(cfg.get("min_rows", 40))
    try:
        recent = _db("SELECT count(*) n FROM scalp_scan_results WHERE scanned_at > now() - interval '18 hours'",
                     fetch="one") or {}
        if int((recent or {}).get("n") or 0) == 0:
            return []  # scanner not currently active — the freshness collector owns 'not running'
        r = _db("""SELECT count(*) rows,
                          count(*) FILTER (WHERE catalyst_verified) verified,
                          count(*) FILTER (WHERE decision='GO') go,
                          count(*) FILTER (WHERE decision='WAIT') wait
                   FROM scalp_scan_results
                   WHERE scanned_at > now() - make_interval(days => %s)""", (window_days,), fetch="one") or {}
        rows = int((r or {}).get("rows") or 0)
        go = int((r or {}).get("go") or 0)
        verified = int((r or {}).get("verified") or 0)
        wait = int((r or {}).get("wait") or 0)
        if rows >= min_rows and go == 0:
            rc_note = ""
            sev = "critical"
            held = False
            try:
                from lib import health_root_cause_memory as _rcmem
                from datetime import datetime, timezone as _tz
                mem = _rcmem.summary_for("scalp_catalyst_verification_dead")
                if mem.get("last_root_cause"):
                    rc_note = (
                        f" [rc={mem.get('last_root_cause')}; "
                        f"fix={str(mem.get('last_how_to_fix') or '')[:120]}; "
                        f"strategy={mem.get('last_strategy_id')}]"
                    )
                # Product-regime hold: demote critical→warning so thrash stops and score recovers;
                # still visible until GO returns or hold expires.
                hu = mem.get("hold_until")
                rc = mem.get("last_root_cause") or ""
                fc = int(mem.get("fail_count") or 0)
                # Unconditional hold at fail_count≥4 for regime-gated findings — these can
                # NEVER self-resolve (max_score < GO_THRESHOLD is a market condition, not a
                # code/data bug).  Drop the hold_until expiry so the finding never re-enters
                # the enqueue→retry→exhaust→re-arm storm loop.
                if rc == "low_max_score_regime" and fc >= 4:
                    sev = "warning"
                    held = True
                    rc_note += " [hold — regime-gated, not thrashing scanner]"
                elif hu and rc == "low_max_score_regime":
                    try:
                        if datetime.now(_tz.utc) < datetime.fromisoformat(
                            str(hu).replace("Z", "+00:00")
                        ):
                            sev = "warning"
                            held = True
                            rc_note += " [hold — not thrashing scanner]"
                    except Exception:
                        pass
            except Exception:
                pass
            out.append(_f("intelligence_quality", "scalp_catalyst_verification_dead", sev,
                f"Momentum-scalp GO tier DARK: {rows} setups scored in {window_days}d ({wait} WAIT, "
                f"{verified} catalyst-verified) but ZERO reached GO — everything capped to WAIT and "
                f"suppressed, so real-time scalp GO/WAIT Telegram alerts are silently down (the 2026-07-01 "
                f"class). Check social_scalp_scanner catalyst enrichment / Hermes catalyst wiring / news feed."
                f"{rc_note}",
                surfaced="Trading hub · momentum scalp real-time alerts",
                held=held))
    except Exception as e:
        out.append(_f("intelligence_quality", "scalp_catalyst_monitor_error", "info",
                      f"scalp catalyst health monitor failed: {str(e)[:80]}"))
    return out


def collect_infra_optimization_health() -> list[dict]:
    """Health for the 2026-06-29 GPU/scheduling optimization work: zombie agent jobs (auto-remediable
    via the reaper), cloud-OAuth lane usage/health, and market-window LLM-contention regression. Never
    raises. Source/DB-state only — no broker writes."""
    out: list[dict] = []
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    # 1. Zombie 'processing' agent jobs — auto-remediable (reset → queued so the worker re-runs them).
    try:
        from db_adapter import get_connection
        from reset_stuck_agent_jobs import find_stuck
        stuck = find_stuck(get_connection())
        if stuck:
            sev = "warning" if len(stuck) < 10 else "critical"
            out.append(_f("execution_health", "agent_jobs_processing_stuck", sev,
                          f"{len(stuck)} agent jobs stuck in 'processing' >30m (worker died mid-job) — "
                          f"resetting to queued", count=len(stuck)))
    except Exception:
        pass
    # 1b. Zombie 'processing' synthesis rows (watchlist_analysis_maturity) — same failure mode, different
    # table: _check_synthesis_ready skips 'processing', so a stranded row silently excludes the symbol
    # from CIO-view refreshes (2026-07-01: 19 symbols, worst 34 days). Same reaper --apply remediates.
    try:
        from db_adapter import get_connection
        from reset_stuck_agent_jobs import find_stuck_synthesis
        stuck_syn = find_stuck_synthesis(get_connection())
        if stuck_syn:
            sev = "warning" if len(stuck_syn) < 10 else "critical"
            worst = max(float(s["age_min"]) for s in stuck_syn) / 60.0
            out.append(_f("execution_health", "synthesis_processing_stuck", sev,
                          f"{len(stuck_syn)} synthesis rows stuck in 'processing' >30m (worst {worst:.0f}h) — "
                          f"symbols silently excluded from CIO-view refresh; resetting to pending",
                          count=len(stuck_syn)))
    except Exception:
        pass
    # 2. Cloud-OAuth lanes — usage / reachability / paid-fallback.
    try:
        from cloud_oauth_usage_monitor import build as _oauth_build
        for f in _oauth_build().get("findings", []):
            out.append(_f("intelligence_quality", f["type"], f["severity"], f["message"]))
    except Exception:
        pass
    # 3. Market-window LLM contention regression — alert if an UNGUARDED T3 LLM job creeps back into the
    #    06:00-12:00 ET window (the guard should keep effective contention down).
    try:
        from job_schedule_audit import audit as _audit
        a = _audit()
        unguarded = [j["name"] for j in a["jobs"]
                     if j["tier"] == "T3" and j["resource_class"] == "llm" and not j.get("market_guarded")
                     and (set(j["hours"]) & set(range(6, 12))) and (set(j["hours"]) - set(range(6, 12)))]
        if len(unguarded) > 3:
            out.append(_f("execution_health", "llm_market_window_contention", "warning",
                          f"{len(unguarded)} unguarded T3 LLM jobs in the 06:00-12:00 ET window — "
                          f"re-run apply_llm_priority_guard_to_crontab.py --apply", count=len(unguarded)))
    except Exception:
        pass
    # 4. Disk-space monitoring — prevent the Aug 2026 backup-storm outage recurrence.
    #    Alerts at <20% (warning) and <10% (critical) so a filling disk is never invisible.
    try:
        import shutil
        for mp, warn_pct, crit_pct in [("/", 20, 10)]:
            usage = shutil.disk_usage(mp)
            pct_used = (usage.used / usage.total) * 100
            free_gb = usage.free / (1024 ** 3)
            if pct_used > (100 - crit_pct):
                out.append(_f("infra", "disk_critical", "critical",
                              f"Disk {mp}: {free_gb:.1f}GB free ({100-pct_used:.1f}%) — below {crit_pct}% threshold",
                              mountpoint=mp, free_gb=round(free_gb, 1), pct_free=round(100-pct_used, 1)))
            elif pct_used > (100 - warn_pct):
                out.append(_f("infra", "disk_low", "warning",
                              f"Disk {mp}: {free_gb:.1f}GB free ({100-pct_used:.1f}%) — below {warn_pct}% threshold",
                              mountpoint=mp, free_gb=round(free_gb, 1), pct_free=round(100-pct_used, 1)))
    except Exception:
        pass
    return out


def collect_pipeline_containment() -> list[dict]:
    """P0 pipeline-integrity checks — detects the failure mode that killed watchlist agent
    reviews for days (2026-08-03: containment flag cleared but crons left commented out).

    Checks:
      1. Agent jobs pipeline containment state (flag/env)
      2. Crontab integrity — are the 4 process_watchlist_agent_jobs lines commented?
      3. Discovery scorecard staleness (>7d no update)
      4. Catalyst quality ratio (other% > 80% → poor classification)

    Auto-fix: If containment is INACTIVE (no flag, no env) and governed PR is deployed
    (agent_flash_governance.py exists) BUT crons are still commented → auto-uncomment
    and report with retry_cmd so health-agent escalations can re-enable the pipeline.
    """
    out = []
    try:
        import subprocess
        # ── 1. Containment state ──
        from lib.agent_jobs_containment import evaluate_containment_state, STATUS_ACTIVE, STATUS_INACTIVE
        from pathlib import Path

        state = evaluate_containment_state()
        contained = state["status"] == STATUS_ACTIVE

        # ── 2. Crontab integrity — are critical watchlist agent lines commented? ──
        cron_proc = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, timeout=10
        )
        crontab_raw = cron_proc.stdout or ""
        if cron_proc.returncode != 0 and (
            "Permission denied" in (cron_proc.stderr or "") or "fopen" in (cron_proc.stderr or "")
        ):
            crontab_raw = ""
            out.append(_f(
                "intelligence_quality",
                "hermes_crontab_unreadable",
                "info",
                "Could not read crontab this cycle — skipping cron_missing checks (hardened systemd)",
            ))
        agent_cron_lines = [
            l for l in crontab_raw.split("\n")
            if "process_watchlist_agent_jobs.py" in l
        ]
        commented_lines = [l for l in agent_cron_lines if l.strip().startswith("#")]
        active_lines = [l for l in agent_cron_lines if not l.strip().startswith("#")]

        # ── 3. Governed PR deployed? ──
        gov_module = Path(__file__).resolve().parent / "lib" / "agent_flash_governance.py"
        governed_deployed = gov_module.exists()

        # ── 4. Discovery scorecard staleness ──
        scorecard_path = PROJECT_ROOT / "data" / "runtime" / "hermes_discovery_scorecard.json"
        scorecard_stale_days = None
        if scorecard_path.exists():
            try:
                age_s = __import__("time").time() - scorecard_path.stat().st_mtime
                scorecard_stale_days = age_s / 86400.0
                if scorecard_stale_days > 7:
                    out.append(_f("intelligence_quality", "discovery_scorecard_stale", "warning",
                                  f"Hermes discovery scorecard is {scorecard_stale_days:.0f}d stale "
                                  f"(last written {scorecard_stale_days:.0f} days ago). "
                                  f"Discovery intake continues but scorecard-based gating is blind. "
                                  f"Check hermes_discovery_scorecard.py cron.",
                                  age_days=round(scorecard_stale_days, 1)))
            except Exception:
                pass
        else:
            out.append(_f("intelligence_quality", "discovery_scorecard_missing", "warning",
                          "Hermes discovery scorecard file missing — scorecard cron may not be "
                          "running or writing to wrong path. Check hermes_discovery_scorecard.py."))

        # ── 5. Catalyst quality ratio ──
        try:
            cat_row = _db(
                """SELECT COUNT(*) FILTER (WHERE catalyst_type='other') AS other_n,
                          COUNT(*) AS total
                   FROM catalyst_events
                   WHERE created_at > now() - interval '7 days'""",
                fetch="one"
            )
            if cat_row and cat_row.get("total", 0) > 100:
                other_pct = (cat_row.get("other_n", 0) or 0) / max(cat_row["total"], 1) * 100
                if other_pct > 80:
                    out.append(_f("intelligence_quality", "catalyst_type_quality", "warning",
                                  f"Catalyst classification quality low: {other_pct:.0f}% 'other' "
                                  f"in last 7d ({cat_row['other_n']}/{cat_row['total']}). "
                                  f"catalyst_type_weights may need retuning or classifier retraining.",
                                  other_pct=round(other_pct, 1), total=cat_row["total"]))
        except Exception:
            pass

        # ── AUTO-FIX: stale containment — inactive but crons still commented ──
        if not contained and governed_deployed and commented_lines and not active_lines:
            # Uncomment the cron lines
            fixed_lines = []
            fixed_count = 0
            for line in crontab_raw.split("\n"):
                if "process_watchlist_agent_jobs.py" in line and line.strip().startswith("#"):
                    # Strip the leading '# CONTAINED ... : ' or '# ' prefix
                    uncommented = line.strip()
                    # Remove "# CONTAINED YYYY-MM-DD issue#NNN ... re-enable only after governed PR: "
                    import re
                    uncommented = re.sub(
                        r'^#\s*CONTAINED\s+\d{4}-\d{2}-\d{2}\s+issue#\d+\s+.*?re-enable only after governed PR:\s*',
                        '', uncommented
                    )
                    # Also handle plain "# " prefix if the above didn't match
                    if uncommented.startswith("# "):
                        uncommented = uncommented[2:]
                    elif uncommented.startswith("#"):
                        uncommented = uncommented[1:]
                    fixed_lines.append(uncommented)
                    fixed_count += 1
                else:
                    fixed_lines.append(line)

            if fixed_count > 0:
                new_crontab = "\n".join(fixed_lines) + "\n"
                try:
                    subprocess.run(
                        ["crontab", "-"],
                        input=new_crontab, text=True, timeout=10, capture_output=True
                    )
                    out.append(_f("execution_health", "agent_jobs_crons_auto_restored", "critical",
                                  f"AUTO-FIXED: {fixed_count} contained watchlist agent cron lines "
                                  f"uncommented. Containment is INACTIVE (flag absent, governed PR "
                                  f"deployed). Pipeline resuming next cron tick.",
                                  auto_fixed=True, fixed_count=fixed_count))
                except Exception as e:
                    out.append(_f("execution_health", "agent_jobs_crons_still_contained", "critical",
                                  f"{fixed_count} watchlist agent cron lines STILL COMMENTED despite "
                                  f"inactive containment. Auto-fix FAILED: {e}. "
                                  f"Manually run: crontab -l | sed 's/^# CONTAINED.*: //' | crontab -",
                                  auto_fix_failed=True, error=str(e)[:120]))
        elif not contained and governed_deployed and active_lines:
            # All good — pipeline is active
            pass
        elif contained:
            out.append(_f("execution_health", "agent_jobs_contained", "critical",
                          f"Watchlist agent jobs pipeline is CONTAINED "
                          f"(source={state.get('source','?')}, detail={state.get('detail','?')}). "
                          f"No LLM reviews firing. Clear flag and re-enable crons after governed PR deploy.",
                          contained=True, state=state))
        elif commented_lines and not governed_deployed:
            out.append(_f("execution_health", "agent_jobs_crons_contained_no_gov", "critical",
                          f"{len(commented_lines)} watchlist agent cron lines commented but "
                          f"governance module (agent_flash_governance.py) NOT deployed. "
                          f"Deploy PR #284 first, then uncomment crons."))

    except Exception as e:
        out.append(_f("execution_health", "pipeline_containment_check_failed", "warning",
                      f"Pipeline containment check failed: {type(e).__name__}: {str(e)[:120]}"))

    return out


def collect_proposal_integrity() -> list[dict]:
    """Per-proposal FINANCIAL correctness — the gap that let a stale favorable live R:R (WEN 13.48,
    computed when price was near the $7.37 stop) keep showing after the price blew past the $8.53
    target. The health agent previously watched only pipelines/freshness/scores, never the semantic
    correctness of individual proposal math, so a logically-inconsistent-but-fresh card passed every
    check. This recomputes thesis_validity from stored entry/stop/target + current_price (no broker API
    hit) and flags PENDING proposals whose LIVE thesis is invalid (price past target or at/below stop →
    no valid live R:R). A pile of these means expiry/recalibration is lagging and stale R:R may show."""
    out = []
    cfg = (_POLICY.get("proposal_integrity") or {})
    if not cfg.get("enabled", True):
        return out
    try:
        rows = _db("""SELECT id, symbol, proposed_entry, proposed_stop, proposed_target1, current_price,
                             updated_at
                      FROM paper_trade_proposals
                      WHERE status='PENDING' AND atm_expired_at IS NULL
                        AND proposed_entry > 0 AND proposed_stop > 0 AND proposed_target1 > 0
                        AND current_price IS NOT NULL""", fetch="all") or []
        if not rows:
            return out
        try:
            from broker_thesis_validity import compute_thesis_validity
        except Exception:
            return out
        broken = []
        for r in rows:
            try:
                entry = float(r["proposed_entry"]); stop = float(r["proposed_stop"])
                tgt = float(r["proposed_target1"]); px = float(r["current_price"])
            except (TypeError, ValueError):
                continue
            if px <= 0:
                continue
            tv = compute_thesis_validity(entry, stop, tgt, px, strategy_id="")
            # No valid live R:R at the current price = thesis broken (price past target or ≤ stop).
            if tv.get("ok") and tv.get("current_rr") is None:
                broken.append(f"{r['symbol']}@{px:.2f}")
        n = len(broken)
        if n > 0:
            warn_at = int(cfg.get("broken_warn", 3))
            out.append(_f("execution_health", "proposal_thesis_broken",
                          "warning" if n >= warn_at else "info",
                          f"{n} PENDING proposal(s) with an invalidated live thesis "
                          f"(price past target/stop) — verify not displaying a stale live R:R",
                          count=n, sample=broken[:6]))
    except Exception as e:
        out.append(_f("execution_health", "collector_error", "info", f"proposal_integrity check error: {e}"))
    return out


def collect_options_desk_health() -> list[dict]:
    """Enterprise options desk infra health — covers the layer the proposal-output checks
    (collect_proposal_maturity) don't: (1) vol-surface snapshot retention actually keeping
    options_chain_snapshots bounded, and (2) the operator approval queue not backing up or
    sitting on expired-but-unreviewed proposals. Both are cheap DB aggregates; advisory only."""
    out = []
    cfg = (_POLICY.get("options_desk") or {})
    if not cfg.get("enabled", True):
        return out
    try:
        import os as _os
        retention_days = int(_os.getenv("OPTIONS_SNAPSHOT_RETENTION_DAYS", "45"))
        grace_days = int(cfg.get("snapshot_grace_days", 7))
        row_warn = int(cfg.get("snapshot_row_warn", 50000))

        # (1) Retention: oldest snapshot should never exceed retention window + grace.
        snap = _db("""SELECT count(*) AS n,
                             EXTRACT(DAY FROM NOW() - MIN(captured_at))::int AS oldest_days
                      FROM options_chain_snapshots""", fetch="one")
        if snap:
            n = int(snap.get("n") or 0)
            oldest = snap.get("oldest_days")
            oldest = int(oldest) if oldest is not None else None
            if oldest is not None and oldest > retention_days + grace_days:
                out.append(_f("execution_health", "options_snapshot_retention_stale", "warning",
                              f"Oldest options_chain_snapshots row is {oldest}d old "
                              f"(> {retention_days}d retention + {grace_days}d grace) — prune not running",
                              oldest_days=oldest, retention_days=retention_days, rows=n))
            if n >= row_warn:
                out.append(_f("execution_health", "options_snapshot_table_bloat", "info",
                              f"options_chain_snapshots has {n:,} rows (>{row_warn:,}) — verify retention sweep",
                              rows=n))

        # (2) Approval queue. Backlog warning counts only PENDING (a genuine operator-review
        # lag); BLOCKED items are auto-gated (illiquid/earnings/etc.), not actionable by an
        # operator, so they get a separate softer info signal rather than tripping the warning.
        q = _db("""SELECT
                     count(*) FILTER (WHERE status='pending') AS pending,
                     count(*) FILTER (WHERE status='blocked') AS blocked,
                     count(*) FILTER (WHERE status='pending'
                                      AND expires_at IS NOT NULL AND expires_at < NOW()) AS expired_pending
                   FROM options_approval_queue""", fetch="one")
        if q:
            pending = int(q.get("pending") or 0)
            blocked = int(q.get("blocked") or 0)
            expired_pending = int(q.get("expired_pending") or 0)
            backlog_warn = int(cfg.get("approval_backlog_warn", 15))
            blocked_warn = int(cfg.get("blocked_pileup_warn", 30))
            if pending >= backlog_warn:
                out.append(_f("execution_health", "options_approval_backlog", "warning",
                              f"{pending} options proposals pending in desk approval queue "
                              f"(>{backlog_warn}) — operator review lagging",
                              count=pending, blocked=blocked))
            if blocked >= blocked_warn:
                out.append(_f("execution_health", "options_approval_blocked_pileup", "info",
                              f"{blocked} options proposals auto-blocked (illiquid/gated) in queue "
                              f"(>{blocked_warn}) — review desk universe or liquidity gates",
                              count=blocked))
            if expired_pending >= int(cfg.get("expired_pending_warn", 1)):
                out.append(_f("execution_health", "options_approval_expired_pending",
                              "warning" if expired_pending >= 5 else "info",
                              f"{expired_pending} pending options approval(s) past their 24h expiry — "
                              f"queue not being cleaned",
                              count=expired_pending))
    except Exception as e:
        out.append(_f("execution_health", "collector_error", "info",
                      f"options_desk health check error: {e}"))
    return out


def collect_trade_in_view_health() -> list[dict]:
    """TradeInView journal: Schwab ingest heartbeat, annotation coverage, MFE backfill."""
    out = []
    cfg = (_POLICY.get("trade_in_view") or {})
    if not cfg.get("enabled", True):
        return out
    try:
        # Schwab journal ingest — must tick every ~15m during market hours
        if _is_portfolio_market_hours():
            ingest_log = LOG_DIR / "schwab_ingest.log"
            if ingest_log.exists():
                age_h = round((datetime.now() - datetime.fromtimestamp(ingest_log.stat().st_mtime)).total_seconds() / 3600, 2)
                max_h = float(cfg.get("schwab_ingest_stale_hours", 0.5))
                if age_h > max_h:
                    out.append(_f("data_quality", "schwab_journal_ingest_stale", "warning",
                                  f"Schwab journal ingest log {age_h:.1f}h old (>{max_h:.1f}h) — "
                                  f"trade_closed may lag during market hours",
                                  age_hours=age_h, route="/v3/trade-in-view"))
            else:
                out.append(_f("data_quality", "schwab_journal_ingest_missing", "warning",
                              "schwab_ingest.log missing — journal ingest never ran",
                              route="/v3/trade-in-view"))

        # Annotation coverage (same join as Telegram reminder)
        cov = _db("""SELECT
                         (SELECT COUNT(*) FROM trade_closed t
                          WHERE t.buy_price > 0 OR t.pnl != 0) AS total,
                         (SELECT COUNT(*) FROM trade_closed t
                          JOIN journal_trade_reviews r
                            ON r.trade_key = (t.symbol || ':' || t.account || ':' || t.close_date::text)
                          WHERE t.buy_price > 0 OR t.pnl != 0) AS reviewed""",
                  fetch="one")
        total = int((cov or {}).get("total") or 0)
        reviewed = int((cov or {}).get("reviewed") or 0)
        if total > 0:
            pct = round(reviewed / total * 100, 1)
            warn_pct = float(cfg.get("annotation_warn_pct", 40))
            crit_pct = float(cfg.get("annotation_critical_pct", 20))
            if pct < crit_pct:
                sev = "critical"
            elif pct < warn_pct:
                sev = "warning"
            else:
                sev = None
            if sev:
                out.append(_f("data_quality", "journal_annotation_low", sev,
                              f"TradeInView annotation coverage {pct}% ({reviewed}/{total}) "
                              f"(target ≥{warn_pct:.0f}%)",
                              coverage_pct=pct, reviewed=reviewed, total=total,
                              route="/v3/trade-in-view"))

        # MFE / profit-capture backfill coverage
        mfe = _db("""SELECT
                         (SELECT COUNT(*) FROM trade_closed) AS trades,
                         (SELECT COUNT(*) FROM trade_profit_capture_analysis) AS mfe_rows""",
                  fetch="one")
        trades_n = int((mfe or {}).get("trades") or 0)
        mfe_n = int((mfe or {}).get("mfe_rows") or 0)
        if trades_n > 0:
            mfe_pct = round(mfe_n / trades_n * 100, 1)
            mfe_warn = float(cfg.get("mfe_coverage_warn_pct", 50))
            if mfe_pct < mfe_warn:
                out.append(_f("data_quality", "journal_mfe_coverage_low", "info",
                              f"TradeInView MFE backfill {mfe_pct}% ({mfe_n}/{trades_n}) "
                              f"(target ≥{mfe_warn:.0f}%) — Exit Intel may be thin",
                              mfe_pct=mfe_pct, mfe_rows=mfe_n, trades=trades_n,
                              route="/v3/trade-in-view"))

        # trade_closed output freshness (post-close on trading days). Rebased on the journal REBUILD
        # timestamp (created_at), NOT MAX(close_date): a quiet market with no recent closes is not a
        # broken ingest. schwab_journal_builder DELETE-then-INSERTs with created_at=NOW() each --apply.
        try:
            from zoneinfo import ZoneInfo
            now_et = datetime.now(ZoneInfo("America/New_York"))
            from market_session import is_trading_day
            trading = is_trading_day(now_et.date())
        except Exception:
            now_et = datetime.now()
            trading = now_et.weekday() < 5
        if trading and now_et.hour >= int(cfg.get("check_after_hour_et", 19)):
            age_d = _db_age_h("SELECT MAX(created_at)::timestamp FROM trade_closed WHERE account LIKE 'schwab%'")
            max_d = float(cfg.get("trade_closed_stale_days", 3))
            if age_d is not None and age_d > max_d * 24:
                out.append(_f("data_quality", "trade_closed_stale", "warning",
                              f"trade_closed journal rebuild {age_d:.0f}h old (>{max_d}d) — "
                              f"schwab_journal_builder may be broken",
                              age_hours=age_d, route="/v3/trade-in-view"))
    except Exception as e:
        out.append(_f("data_quality", "collector_error", "info",
                      f"trade_in_view check error: {e}"))
    return out


def collect_pullback_macd_screener() -> list[dict]:
    """Freshness of the S&P 500 pullback/MACD screener — did the daily scan run, and is the
    universe populated. Advisory; cheap DB reads."""
    out = []
    cfg = (_POLICY.get("pullback_macd_screener") or {})
    if not cfg.get("enabled", True):
        return out
    try:
        run = _db("SELECT scan_date, screened, trigger_count, watch_count, created_at "
                  "FROM pullback_macd_runs ORDER BY created_at DESC LIMIT 1", fetch="one")
        try:
            from market_session import is_trading_day
            trading = is_trading_day()
        except Exception:
            trading = datetime.now().weekday() < 5
        if run is None:
            if trading and datetime.now().hour >= int(cfg.get("check_after_hour", 18)):
                out.append(_f("execution_health", "pullback_macd_no_runs", "info",
                              "Pullback/MACD screener has no recorded runs yet", kind="code"))
        else:
            age_h = _db_age_h("SELECT created_at FROM pullback_macd_runs ORDER BY created_at DESC LIMIT 1")
            # slot-aware threshold: the screener runs weekdays 16:40, so judge age against the most
            # recent EXPECTED slot, not a flat 30h — Friday's run is legitimately ~65h old on Monday
            # morning and the flat threshold alarmed every weekend/Monday (2026-07-06 audit)
            _now = datetime.now()
            slot_age_h = None
            for _back in range(8):
                _slot = (_now - timedelta(days=_back)).replace(hour=16, minute=40, second=0, microsecond=0)
                if _slot.weekday() < 5 and _slot <= _now:
                    slot_age_h = (_now - _slot).total_seconds() / 3600
                    break
            allowed_h = (slot_age_h or 0) + float(cfg.get("scan_grace_hours", 3))
            if age_h is not None and age_h > allowed_h:
                out.append(_f("execution_health", "pullback_macd_scan_stale", "warning",
                              f"Pullback/MACD scan {age_h:.0f}h old (last expected slot {allowed_h:.0f}h ago) — daily cron may be down",
                              age_h=age_h, last_scan=str(run.get("scan_date"))))
        uni = _db("SELECT count(*) AS n FROM sp500_constituents WHERE active", fetch="one")
        if uni and int(uni.get("n") or 0) < int(cfg.get("min_universe", 400)):
            out.append(_f("execution_health", "pullback_macd_universe_thin", "warning",
                          f"S&P 500 universe table has {uni['n']} active names (<{cfg.get('min_universe',400)}) "
                          f"— constituent refresh may be failing", count=int(uni["n"])))
    except Exception as e:
        out.append(_f("execution_health", "collector_error", "info",
                      f"pullback_macd screener check error: {e}"))
    return out


def collect_execution_hardening_health() -> list[dict]:
    """Institutional hardening signals: readiness, kill switches, stale orders, audit ledger."""
    out = []
    cfg = (_POLICY.get("execution_hardening") or {})
    if cfg.get("enabled", True) is False:
        return out
    try:
        from brokers.kill_switches import list_active
        active = list_active()
        for row in active:
            if row.get("level") in ("global", "live_submit") or row.get("fail_closed"):
                out.append(_f("execution_health", "kill_switch_active", "critical",
                              f"Kill switch {row.get('level')}: {row.get('reason')}",
                              route="/v3/system?tab=Control+Plane",
                              recommended_action="Review kill switch status before any live submit"))
    except Exception as e:
        out.append(_f("execution_health", "readiness_resolver_error", "warning",
                      f"kill_switch inspect failed: {e}", route="/v3/system"))
    try:
        from brokers.reconcile_orders import find_stale_internal_orders
        stale = find_stale_internal_orders(max_age_minutes=int(cfg.get("stale_order_minutes", 30)))
        if stale:
            out.append(_f("execution_health", "broker_reconciliation_stale", "warning",
                          f"{len(stale)} stale SUBMIT_REQUESTED/OPERATOR_APPROVED orders",
                          count=len(stale), route="/v3/trading?tab=Broker+Orders",
                          recommended_action="Run reconcile_orders.py --dry-run"))
    except Exception as e:
        out.append(_f("execution_health", "reconcile_inspect_error", "info", str(e)[:120]))
    try:
        import execution_state as es
        state = es.build_state()
        if state.get("live_adjacent_dirty_count", 0) > 0:
            out.append(_f("execution_health", "live_adjacent_dirty", "warning",
                          f"{state['live_adjacent_dirty_count']} live-adjacent dirty files",
                          route="/v3/system"))
        for blocker in (state.get("current_blockers") or [])[:3]:
            if "kill_switch" in blocker or "cannot inspect" in blocker:
                out.append(_f("execution_health", "execution_state_conflict", "warning",
                              blocker, route="/v3/system"))
    except Exception as e:
        out.append(_f("execution_health", "execution_state_missing", "warning",
                      f"execution_state unavailable: {e}", route="/v3/system"))
    try:
        from audit_ledger import verify_chain
        chain = verify_chain(100)
        if not chain.get("ok"):
            out.append(_f("execution_health", "audit_ledger_chain_break", "critical",
                          f"audit ledger chain break: {chain.get('error')}",
                          recommended_action="Inspect data/runtime/audit_ledger/events.jsonl"))
    except Exception as e:
        out.append(_f("execution_health", "audit_ledger_inspect_error", "info", str(e)[:120]))
    try:
        exp = _db("""SELECT COUNT(*) AS c FROM options_approval_queue
                     WHERE status='pending' AND expires_at < NOW()""", fetch="one")
        if exp and int(exp.get("c") or 0) >= int(cfg.get("expired_pending_warn", 1)):
            out.append(_f("execution_health", "approval_queue_expired_pending", "warning",
                          f"{exp['c']} expired pending desk approvals", count=int(exp["c"]),
                          route="/v3/trading?tab=Options"))
    except Exception:
        pass

    # ── P1-6 monitoring extensions ──────────────────────────────────────────────────
    # 1. Release manifest WARN/FAIL (read the auto-generated manifest's status line).
    try:
        from pathlib import Path as _P
        man = _P(__file__).resolve().parent.parent / "docs" / "project" / "RELEASE_MANIFEST_LATEST.md"
        if man.exists():
            st = ""
            for line in man.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("Status:"):
                    st = line.split(":", 1)[1].strip()
                    break
            if st == "FAIL":
                out.append(_f("execution_health", "release_manifest_fail", "critical",
                              "Release manifest status FAIL — live-adjacent dirty or validator failed",
                              route="/v3/system",
                              recommended_action="Run scripts/validate_release_readiness.py --json --skip-build"))
            elif st == "WARN":
                out.append(_f("execution_health", "release_manifest_warn", "warning",
                              "Release manifest WARN (non-classified dirty files present)",
                              route="/v3/system",
                              recommended_action="Classify/clean dirty files; rerun release readiness"))
    except Exception:
        pass

    # 2. Audit-ledger coverage of live-adjacent event types (write/verify failure → blocker).
    try:
        from audit_ledger import coverage_report
        cov = coverage_report(release_mode=cfg.get("ledger_release_mode", "review"))
        if cov.get("status") == "FAIL":
            out.append(_f("execution_health", "audit_ledger_coverage_fail", "critical",
                          f"audit ledger coverage FAIL: missing {cov.get('missing_critical')}",
                          recommended_action="Investigate ledger write path before live-adjacent run",
                          route="/v3/system"))
        elif cov.get("status") == "WARN" and cov.get("any_live_activity"):
            out.append(_f("execution_health", "audit_ledger_coverage_warn", "warning",
                          f"audit ledger missing expected events: {cov.get('missing_expected')[:5]}",
                          route="/v3/system"))
    except Exception as e:
        out.append(_f("execution_health", "audit_ledger_coverage_error", "info", str(e)[:120]))

    # 3. Stale OPERATOR_APPROVED records specifically (separate from SUBMIT_REQUESTED).
    try:
        oa = _db("""SELECT COUNT(*) AS c FROM broker_order_intents
                    WHERE state='OPERATOR_APPROVED'
                      AND updated_at < NOW() - (%s || ' minutes')::interval""",
                 (int(cfg.get("stale_operator_approved_minutes", 60)),), fetch="one")
        if oa and int(oa.get("c") or 0) > 0:
            out.append(_f("execution_health", "stale_operator_approved", "warning",
                          f"{oa['c']} OPERATOR_APPROVED intents stale without submit",
                          count=int(oa["c"]), route="/v3/trading?tab=Broker+Orders",
                          recommended_action="Reconcile or expire stale approvals"))
    except Exception:
        pass

    # 4. Stale option chain snapshots (live options path depends on fresh broker chains).
    try:
        snap = _db("""SELECT EXTRACT(EPOCH FROM (NOW()-MAX(captured_at)))/60.0 AS age_min
                      FROM options_chain_snapshots""", fetch="one")
        if snap and snap.get("age_min") is not None:
            age = float(snap["age_min"])
            warn_min = float(cfg.get("chain_snapshot_warn_min", 1440))
            if age > warn_min:
                out.append(_f("execution_health", "option_chain_snapshot_stale", "warning",
                              f"newest option chain snapshot is {age/60.0:.1f}h old",
                              age_minutes=round(age, 1), route="/v3/trading?tab=Options",
                              recommended_action="Refresh option chain snapshots (vol-analytics cron)"))
    except Exception:
        pass

    # 5. AI critique stale rate + 6. replay-integrity (degraded) rate.
    try:
        crit = _db("""SELECT COUNT(*) AS total,
                             SUM(CASE WHEN stale THEN 1 ELSE 0 END) AS stale_n,
                             SUM(CASE WHEN status='degraded' THEN 1 ELSE 0 END) AS degraded_n
                      FROM journal_ai_critiques""", fetch="one")
        total = int((crit or {}).get("total") or 0)
        if total >= int(cfg.get("critique_min_sample", 20)):
            stale_rate = int((crit or {}).get("stale_n") or 0) / total * 100.0
            degraded_rate = int((crit or {}).get("degraded_n") or 0) / total * 100.0
            if stale_rate >= float(cfg.get("critique_stale_warn_pct", 25)):
                out.append(_f("intelligence_quality", "ai_critique_stale_rate", "warning",
                              f"{stale_rate:.0f}% of AI critiques are stale (tags changed)",
                              rate_pct=round(stale_rate, 1), route="/v3/trade-in-view",
                              recommended_action="Regenerate stale critiques"))
            if degraded_rate >= float(cfg.get("replay_degraded_warn_pct", 20)):
                out.append(_f("intelligence_quality", "replay_integrity_degraded_rate", "warning",
                              f"{degraded_rate:.0f}% of critiques degraded (replay integrity)",
                              rate_pct=round(degraded_rate, 1), route="/v3/trade-in-view",
                              recommended_action="Investigate replay markers / time integrity"))
    except Exception:
        pass
    return out


def collect_proposal_pipeline_health() -> list[dict]:
    """Dual-lane proposal pipeline: enrichment failures, stuck paper approvals, stale IN_PROGRESS."""
    import re as _re
    out = []
    cfg = (_POLICY.get("proposal_pipeline") or {})
    if cfg.get("enabled", True) is False:
        return out
    try:
        win_h = int(cfg.get("enrichment_failure_window_hours", 3))
        fail_warn = int(cfg.get("enrichment_failure_warn", 3))
        import_pat = _re.compile(r"cannot import|ModuleNotFoundError|ImportError", _re.I)

        elog = _db(
            f"""SELECT COUNT(*) AS c FROM enrichment_log
                WHERE success = false
                  AND completed_at > NOW() - INTERVAL '{win_h} hours'
                  AND (step = 'execution_readiness'
                       OR COALESCE(error_message, '') ~* 'cannot import|ModuleNotFoundError|ImportError')""",
            fetch="one",
        )
        elog_n = int((elog or {}).get("c") or 0)

        perror = _db(
            f"""SELECT COUNT(*) AS c FROM paper_trade_proposals
                WHERE status = 'PENDING'
                  AND enrichment_last_error IS NOT NULL
                  AND enrichment_last_error ~* 'cannot import|ModuleNotFoundError|ImportError'
                  AND enrichment_last_attempt_at > NOW() - INTERVAL '{win_h} hours'""",
            fetch="one",
        )
        perror_n = int((perror or {}).get("c") or 0)

        log_hits = 0
        log_file = LOG_DIR / "auto_enrichment.log"
        if log_file.exists():
            try:
                lines = log_file.read_text(errors="ignore").splitlines()[-400:]
                log_hits = sum(1 for ln in lines if import_pat.search(ln))
            except Exception:
                pass

        fail_total = max(elog_n, perror_n, log_hits)
        if fail_total >= fail_warn or (elog_n + perror_n) >= 1:
            sev = "critical" if fail_total >= fail_warn * 2 else "warning"
            out.append(_f(
                "execution_health", "enrichment_pipeline_failure", sev,
                f"Enrichment pipeline failing ({fail_total} signals in {win_h}h) — "
                f"readiness/import errors block ATM + broker lanes",
                enrichment_log_failures=elog_n, proposal_errors=perror_n,
                log_import_lines=log_hits, count=fail_total,
            ))

        pending_fail = _db(
            """SELECT COUNT(*) AS c FROM paper_trade_proposals
               WHERE status = 'PENDING'
                 AND COALESCE(enrichment_failures, 0) >= 2
                 AND COALESCE(enrichment_status, '') != 'COMPLETE'""",
            fetch="one",
        )
        pf = int((pending_fail or {}).get("c") or 0)
        if pf >= int(cfg.get("enrichment_pending_fail_warn", 5)):
            out.append(_f(
                "execution_health", "enrichment_failures_high", "warning",
                f"{pf} PENDING proposals with ≥2 enrichment failures — queue stalled",
                count=pf,
            ))

        stuck_h = int(cfg.get("approved_paper_stuck_hours", 2))
        stuck = _db(
            f"""SELECT COUNT(*) AS c FROM paper_trade_proposals
                WHERE status = 'APPROVED_FOR_PAPER_TEST'
                  AND (
                    updated_at < NOW() - INTERVAL '{stuck_h} hours'
                    OR paper_submit_state IN ('VALIDATING', 'NOT_SUBMITTED')
                    OR execution_eligibility_status = 'NEEDS_REVALIDATION'
                  )""",
            fetch="one",
        )
        stuck_n = int((stuck or {}).get("c") or 0)
        if stuck_n >= int(cfg.get("approved_paper_stuck_warn", 1)):
            sev = "critical" if stuck_n >= int(cfg.get("approved_paper_stuck_critical", 3)) else "warning"
            out.append(_f(
                "execution_health", "approved_paper_test_stuck", sev,
                f"{stuck_n} APPROVED_FOR_PAPER_TEST proposal(s) stuck in paper lane "
                f"(revalidation/submit drift)",
                count=stuck_n,
            ))

        stale_m = int(cfg.get("in_progress_stale_minutes", 30))
        inprog = _db(
            f"""SELECT
                  COUNT(*) FILTER (
                    WHERE status IN ('EXPIRED', 'REJECTED', 'APPROVED', 'RISK_BLOCKED')
                  ) AS terminal,
                  COUNT(*) FILTER (
                    WHERE status IN ('PENDING', 'APPROVED_FOR_PAPER_TEST', 'APPROVED')
                      AND COALESCE(enrichment_last_attempt_at, updated_at)
                          < NOW() - INTERVAL '{stale_m} minutes'
                  ) AS active
                FROM paper_trade_proposals
                WHERE enrichment_status = 'IN_PROGRESS'""",
            fetch="one",
        )
        terminal_n = int((inprog or {}).get("terminal") or 0)
        active_n = int((inprog or {}).get("active") or 0)
        total_ip = terminal_n + active_n
        ip_warn = int(cfg.get("in_progress_stale_warn", 3))
        if total_ip >= ip_warn:
            sev = "critical" if total_ip >= ip_warn * 3 else "warning"
            out.append(_f(
                "execution_health", "enrichment_status_in_progress_stale", sev,
                f"{total_ip} proposal(s) with stale enrichment_status=IN_PROGRESS "
                f"({terminal_n} terminal, {active_n} active >{stale_m}m)",
                count=total_ip, terminal=terminal_n, active_stuck=active_n,
            ))
    except Exception as e:
        out.append(_f("execution_health", "collector_error", "info",
                      f"proposal_pipeline check error: {e}"))
    return out


def collect_watchlist_news_guard_health() -> list[dict]:
    """Detect mis-tagged catalyst headlines on CIO-rated symbols (all verdict tiers)."""
    out = []
    cfg = (_POLICY.get("watchlist_news_guard") or {})
    if cfg.get("enabled", True) is False:
        return out
    try:
        from db_adapter import get_connection
        from news_symbol_guard import count_mismatched_watchlist
        conn = get_connection()
        try:
            audit = count_mismatched_watchlist(conn, limit=int(cfg.get("sample_limit", 120)))
        finally:
            conn.close()
        n = int(audit.get("mismatch_count") or 0)
        warn_n = int(cfg.get("mismatch_warn", 1))
        if n >= warn_n:
            samples = audit.get("mismatches") or []
            preview = ", ".join(
                f"{m.get('symbol')}" for m in samples[:5]
            ) or "see watchlist"
            sev = "critical" if n >= int(cfg.get("mismatch_critical", 5)) else "warning"
            out.append(_f(
                "data_quality", "news_symbol_mismatch", sev,
                f"{n} CIO-rated watchlist symbol(s) have mis-tagged catalyst headlines ({preview})",
                count=n, scanned=audit.get("scanned"), samples=samples[:8],
            ))
    except Exception as e:
        out.append(_f("data_quality", "collector_error", "info",
                      f"watchlist_news_guard check error: {e}"))
    return out


def collect_proposal_oversight_load() -> list[dict]:
    """Detect a BURST of newly-created PENDING proposals. Each PENDING broker-route proposal is
    picked up by broker_promote_oversight for per-proposal local + cloud LLM review; a bulk insert
    (e.g. a screener emitting 22 at once on 2026-06-26) spikes machine load and starves the
    single-threaded API server. This is the guardrail so that can't recur unnoticed."""
    out = []
    cfg = (_POLICY.get("proposal_oversight_load") or {})
    if not cfg.get("enabled", True):
        return out
    try:
        win = int(cfg.get("burst_window_min", 20))
        burst_warn = int(cfg.get("burst_warn", 15))
        burst_crit = int(cfg.get("burst_critical", 30))
        row = _db(f"""SELECT count(*) AS n, string_agg(DISTINCT COALESCE(discovery_source,'?'), ',') AS srcs
                      FROM paper_trade_proposals
                      WHERE status='PENDING' AND created_at > NOW() - INTERVAL '{win} minutes'""",
                  fetch="one")
        n = int((row or {}).get("n") or 0)
        if n >= burst_warn:
            sev = "critical" if n >= burst_crit else "warning"
            out.append(_f("execution_health", "proposal_creation_burst", sev,
                          f"{n} proposals created in {win}m (src: {(row or {}).get('srcs')}) — each triggers "
                          f"local+cloud LLM oversight; bulk creation can overload the single-threaded server",
                          count=n, window_min=win))
    except Exception as e:
        out.append(_f("execution_health", "collector_error", "info",
                      f"proposal_oversight_load check error: {e}"))
    return out


def collect_proposal_trade_plan_health() -> list[dict]:
    """Active broker-queue proposals blocked on gambling geometry / missing authoritative plan."""
    out = []
    cfg = (_POLICY.get("proposal_trade_plan") or {})
    if cfg.get("enabled") is False:
        return out
    try:
        from db_adapter import get_connection
        import remediate_proposal_trade_plans as rtpr
        audit = rtpr.audit_blocked_count(get_connection())
        n = int(audit.get("count") or 0)
        warn_n = int(cfg.get("blocked_warn", 1))
        crit_n = int(cfg.get("blocked_critical", 3))
        if n >= warn_n:
            syms = ", ".join(sorted((audit.get("by_symbol") or {}).keys())[:8])
            sev = "critical" if n >= crit_n else "warning"
            out.append(_f(
                "execution_health", "proposal_trade_plan_blocked", sev,
                f"{n} active proposal(s) lack authoritative trade plan (gambling-blocked) — {syms or 'see queue'}",
                count=n, symbols=audit.get("by_symbol"),
            ))
    except Exception as e:
        out.append(_f("execution_health", "collector_error", "info",
                      f"proposal_trade_plan check error: {e}"))
    return out


def collect_data_source_health() -> list[dict]:
    """Consume data_source_health (per-source ingestion liveness): stale sources + Finviz cookie.

    The table is written by ingestion lanes but previously had NO consumer — a dead source
    (e.g. the expired Finviz cookie, 2026-07-02) only surfaced as a suppressed Telegram digest
    line. When finviz is stale we live-validate the cookie (credential_monitor.check_finviz)
    to tell "cookie expired — needs operator" apart from a transient ingestion failure.
    """
    cfg = (_POLICY.get("data_sources") or {})
    if not cfg.get("enabled", True):
        return []
    out: list[dict] = []
    weekend_factor = float(cfg.get("weekend_stale_factor", 3.0))
    rows = _db("""SELECT source_key, status, last_success_at, max_stale_minutes, last_error
                  FROM data_source_health WHERE last_success_at IS NOT NULL""", fetch="all") or []
    for r in rows:
        try:
            last = r.get("last_success_at")
            max_stale_m = float(r.get("max_stale_minutes") or 1440)
            age_m = (datetime.now(timezone.utc) - last).total_seconds() / 60.0
        except Exception:
            continue
        allowed_m = max_stale_m * (weekend_factor if _IS_WEEKEND else 1.0)
        if age_m <= allowed_m:
            continue
        src = r.get("source_key")
        # Weekday-only ingestion lanes legitimately go stale over the weekend — house
        # convention (see collect_data_quality): visible as info + [weekend], escalates Monday.
        sev = "info" if _IS_WEEKEND else ("critical" if age_m > allowed_m * 3 else "warning")
        msg = (f"data source '{src}' stale: last success {age_m / 60:.1f}h ago "
               f"(max {max_stale_m / 60:.1f}h)" + (" [weekend]" if _IS_WEEKEND else ""))
        if src == "finviz" and cfg.get("finviz_cookie_check", True):
            # Distinguish cookie expiry (operator action) from transient failure.
            try:
                from credential_monitor import check_finviz
                ck = check_finviz()
                if str(ck.get("status")) != "ok":
                    out.append(_f("data_quality", "finviz_cookie_expired", "critical",
                                  f"Finviz cookie invalid ({ck.get('error') or ck.get('status')}) — "
                                  f"screener ingestion dead since {age_m / 60:.0f}h; operator must refresh "
                                  f"FINVIZ_COOKIE in .env", source=src))
                    continue
            except Exception:
                pass
        last_err = (r.get("last_error") or "")[:120]
        if "401" in last_err or "403" in last_err:
            # Auth failure = a rotated/expired API key, not a transient ingestion stall.
            # Auto-retrying the producer can never clear a 401, so surface it as a distinct
            # operator action (never auto) — mirrors finviz_cookie_expired.
            out.append(_f("data_quality", "data_source_auth_failed", "critical",
                          f"data source '{src}' auth failed ({last_err.strip()}) — key invalid/expired; "
                          f"operator must rotate {src.upper()}_API_KEY in Bitwarden",
                          source=src, last_error=last_err,
                          operator_action=True,
                          reauth_cmd=(f".venv/bin/python scripts/secrets/render_env.py --now && "
                                      f".venv/bin/python scripts/secret_validators.py {src.upper()}_API_KEY")))
            continue
        out.append(_f("data_quality", "data_source_stale", sev, msg,
                      source=src, last_error=last_err))
    return out


def collect_failed_systemd_units() -> list[dict]:
    """Failed trade-stack systemd units (e.g. tradeai-continuous boot-catch-up crash).

    Detection only — restarting system units needs privileges the agent doesn't have;
    the finding carries the operator command instead.
    """
    cfg = (_POLICY.get("systemd_units") or {})
    if not cfg.get("enabled", True):
        return []
    prefixes = tuple(cfg.get("unit_prefixes") or
                     ["tradeai-", "portfolio-", "grok-oauth", "chatgpt-oauth"])
    out: list[dict] = []
    try:
        # systemctl needs DBUS_SESSION_BUS_ADDRESS when running under cron (no login session).
        # Without it the subprocess fails and the bare `except` made this collector permanently
        # dead — failed units were never detected under cron.
        env = os.environ.copy()
        uid = os.getuid()
        env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
        env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
        proc = subprocess.run(["systemctl", "--failed", "--plain", "--no-legend", "--no-pager"],
                              capture_output=True, text=True, timeout=10, env=env)
        for line in (proc.stdout or "").splitlines():
            unit = (line.split() or [""])[0]
            if unit.startswith(prefixes):
                out.append(_f("execution_health", "systemd_unit_failed", "warning",
                              f"systemd unit {unit} is in failed state — scheduled runs may be "
                              f"missed; operator: sudo systemctl reset-failed {unit} "
                              f"(then check why it died: journalctl -u {unit})", unit=unit))
    except Exception as e:
        # Surface that we can't check — silence is worse than an info finding
        out.append(_f("execution_health", "systemd_check_unavailable", "info",
                      f"Cannot check systemd unit state: {e}. "
                      f"systemctl --failed may need DBUS_SESSION_BUS_ADDRESS or the "
                      f"collector may be running without a system bus.",
                      error=str(e)[:200]))
    return out


def collect_db_connection_health() -> list[dict]:
    """Postgres idle-in-transaction kills — a script holding a transaction through slow
    non-DB work (LLM call, big file parse) dies at the 120s session timeout with
    'SSL connection has been closed unexpectedly'. Catches the next scope-governor-style
    bug while it's one victim, not a fleet."""
    cfg = (_POLICY.get("db_connections") or {})
    if not cfg.get("enabled", True):
        return []
    import glob as _glob
    window_h = float(cfg.get("window_hours", 3))
    warn_at = int(cfg.get("idle_txn_kills_warn", 10))
    log_glob = cfg.get("pg_log_glob", "/var/log/postgresql/postgresql-*-main.log")
    tail_bytes = int(cfg.get("tail_bytes", 2_000_000))
    out: list[dict] = []
    try:
        paths = sorted(_glob.glob(log_glob))
        if not paths:
            return []
        cutoff = datetime.now() - timedelta(hours=window_h)
        n = 0
        with open(paths[-1], "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - tail_bytes))
            for raw in fh:
                if b"idle-in-transaction timeout" not in raw:
                    continue
                try:
                    ts = datetime.strptime(raw[:19].decode("ascii", "ignore"), "%Y-%m-%d %H:%M:%S")
                    if ts >= cutoff:
                        n += 1
                except Exception:
                    n += 1
        if n >= warn_at:
            out.append(_f("execution_health", "db_idle_txn_kills", "warning",
                          f"{n} Postgres idle-in-transaction kills in {window_h:.0f}h — some script "
                          f"holds a DB transaction through slow non-DB work (LLM call/file parse); "
                          f"check the killed PIDs in the PG log", count=n))
    except Exception:
        pass
    # Connection-slot saturation (2026-07-17): portfolio_server leaked idle conns until 97/100
    # slots were held, every new connection died FATAL, and warm_caches silently wrote an EMPTY
    # trade_ai cache. Direct psycopg2 connect (NOT db_adapter) so the FATAL itself is catchable
    # and attributable; per-app grouping via application_name names the offender.
    try:
        warn_per_app = int(cfg.get("slots_per_app_warn", 40))
        crit_total = int(cfg.get("slots_total_crit", 70))
        import psycopg2 as _pg
        try:
            _conn = _pg.connect(
                host=os.getenv("DB_HOST", "localhost"), port=int(os.getenv("DB_PORT", "5432")),
                dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                password=os.getenv("DB_PASSWORD", ""), connect_timeout=5,
                application_name="health_agent_slotcheck",
            )
        except Exception as e:
            if "connection slot" in str(e).lower():
                out.append(_f("execution_health", "db_slots_exhausted", "critical",
                              "Postgres connection slots EXHAUSTED — new connections are failing "
                              "FATAL; DB-fed writers (warm_caches etc.) silently degrade. Find the "
                              "holder: ss -tn 'dport = :5432' grouped by pid; restarting the "
                              "offending service frees its slots (2026-07-17 incident)."))
            return out
        try:
            with _conn.cursor() as c:
                c.execute("""SELECT COALESCE(application_name,'?'), count(*)
                             FROM pg_stat_activity WHERE usename = current_user
                             GROUP BY 1 ORDER BY 2 DESC""")
                rows = c.fetchall()
        finally:
            _conn.close()
        total = sum(r[1] for r in rows)
        top_app, top_n = (rows[0] if rows else ("?", 0))
        if total >= crit_total:
            out.append(_f("execution_health", "db_slots_near_exhaustion", "critical",
                          f"{total} Postgres connections held by trade_ai (cap ~100; top holder "
                          f"{top_app}={top_n}) — leak in progress, slots will exhaust and DB-fed "
                          f"writers will silently degrade; restart the top holder",
                          total=total, top_app=top_app, top_count=top_n))
        elif top_n >= warn_per_app:
            out.append(_f("execution_health", "db_slots_single_app_high", "warning",
                          f"{top_app} holds {top_n} Postgres connections (warn at {warn_per_app}) — "
                          f"idle-connection leak signature (2026-07-17 scanner incident); watch for "
                          f"growth and restart the service if it keeps climbing",
                          total=total, top_app=top_app, top_count=top_n))
    except Exception:
        pass
    return out


def collect_backup_health() -> list[dict]:
    """Backup cadence liveness (2026-07-17 scope audit): the 02:30 cadence owns ALL backups
    (pg dump, env/data/memory/ops/db-offsite/apps encrypted to Drive). Before this check a
    failed or silently-dead run alerted NOBODY. Critical when the last-run summary is stale
    (>26h) or any step failed; also checks the newest local pg dump is <26h old."""
    out: list[dict] = []
    cfg = (_POLICY.get("backup_health") or {})
    if not cfg.get("enabled", True):
        return out
    max_age_h = float(cfg.get("max_age_hours", 26))
    summary = PROJECT_ROOT / "data" / "runtime" / "portfolio_maintenance_backup_last_run.json"
    try:
        if not summary.exists():
            out.append(_f("pipeline_freshness", "backup_cadence_missing", "critical",
                          "backup cadence has never written its last-run summary — verify "
                          "tradeai-portfolio-backup-cadence.timer"))
            return out
        age_h = (datetime.now().timestamp() - summary.stat().st_mtime) / 3600
        if age_h > max_age_h:
            out.append(_f("pipeline_freshness", "backup_cadence_stale", "critical",
                          f"backup cadence last ran {age_h:.0f}h ago (>{max_age_h:.0f}h) — "
                          f"pg dump + offsite encrypted backups are NOT running",
                          age_hours=round(age_h, 1)))
        try:
            d = json.loads(summary.read_text())
            bad = [s for s in (d.get("steps") or [])
                   if str(s.get("status", "")).lower() not in
                   ("ok", "gated_skip_fresh", "excluded_not_run", "")]
            if bad:
                out.append(_f("pipeline_freshness", "backup_step_failed", "critical",
                              f"{len(bad)} backup step(s) failed in the last cadence run — "
                              f"check journalctl --user -u tradeai-portfolio-backup-cadence",
                              count=len(bad)))
        except Exception:
            pass
        import glob as _g
        min_bytes = int(cfg.get("min_dump_bytes", 500 * 1024 * 1024))  # ignore partial thrash dumps
        max_count = int(cfg.get("max_local_count", 1))  # 2026-08-11: single local dump only
        max_total = int(cfg.get("max_local_bytes", 5 * 1024 * 1024 * 1024))
        dumps = []
        total_bytes = 0
        for p in sorted(_g.glob(str(Path.home() / "db_backups" / "trade_ai_*.sql.gz"))):
            try:
                sz = Path(p).stat().st_size
                total_bytes += sz
                if sz >= min_bytes:
                    dumps.append(p)
            except OSError:
                continue
        if not dumps:
            out.append(_f("pipeline_freshness", "db_dump_missing", "critical",
                          "no local full pg dumps exist in ~/db_backups "
                          f"(min size {min_bytes // (1024*1024)}MB)"))
        else:
            dump_age_h = (datetime.now().timestamp() - Path(dumps[-1]).stat().st_mtime) / 3600
            if dump_age_h > max_age_h:
                # Notify only — NEVER auto-remediate (backup storm 2026-08). Operator runs
                # run_pg_backup.sh or waits for tradeai-portfolio-backup-cadence.timer.
                out.append(_f("pipeline_freshness", "db_dump_stale", "critical",
                              f"newest full pg dump is {dump_age_h:.0f}h old (>{max_age_h:.0f}h) — "
                              f"manual: bash linux_launchers/run_pg_backup.sh (auto-remediate disabled)",
                              age_hours=round(dump_age_h, 1)))
        # Cap enforcement (Aug 2026 storm left 38×2.3G dumps)
        if len(dumps) > max_count:
            out.append(_f("pipeline_freshness", "backup_local_count_exceeded", "critical",
                          f"{len(dumps)} full local pg dumps (max {max_count}) — "
                          f"run: .venv/bin/python scripts/backup_enforcer.py",
                          count=len(dumps), max_count=max_count))
        if total_bytes > max_total:
            out.append(_f("pipeline_freshness", "backup_local_bytes_exceeded", "critical",
                          f"~/db_backups total {total_bytes/1e9:.1f}GB exceeds "
                          f"{max_total/1e9:.1f}GB cap — run backup_enforcer.py",
                          total_bytes=total_bytes, max_bytes=max_total))
    except Exception as e:
        out.append(_f("pipeline_freshness", "backup_check_error", "info", str(e)[:120]))
    return out


def collect_broker_token_health() -> list[dict]:
    """Schwab OAuth token liveness — symmetric with the Finviz cookie check. The TTL-based
    `schwab_token_manager.health()` reports `refresh_valid=true` even after Schwab REVOKES the token
    (rotating-token reuse-detection race), so we detect the REAL signal: the `broker_oauth_tokens`
    degraded flag + last_error, plus an `invalid_grant` / no-login-token in the recent `schwab_ingest.log`.
    A revoked token has NO programmatic recovery (GATE A) — it needs a manual reauth — so this is a
    critical OPERATOR-ACTION finding, deliberately NOT in `remediation_map` (retrying the ingest is futile).
    Closes the gap where a revoked token silently stalled the trade journal for a full day (2026-07-07)."""
    out = []
    cfg = (_POLICY.get("broker_token_health") or {})
    if not cfg.get("enabled", True):
        return out
    reauth = ("Manual Schwab reauth required (token cannot be auto-renewed): run "
              "`.venv/bin/python scripts/schwab_token_manager.py reauth-url schwab_taxable`, open the URL, "
              "log in, then `exchange-code schwab_taxable \"<redirect URL>\"`; then re-run "
              "`scripts/schwab_transaction_ingest.py --apply`.")
    try:
        # AUTHORITATIVE, recency-correct signal: the `degraded` flag is SET when a refresh is rejected
        # (schwab_transport persists it on Schwab auth-rejection; token manager sets it on refresh failure)
        # and CLEARED on a successful reauth/refresh (`_clear_degraded`). We do NOT trigger on a raw
        # log-scan alone — the ingest log keeps stale invalid_grant lines after recovery, which would
        # false-positive. The log is used only to enrich the message once `degraded` confirms the failure.
        rows = _db("SELECT account_key, degraded, last_error FROM broker_oauth_tokens WHERE degraded IS TRUE",
                   fetch="all") or []
        if rows:
            acct = rows[0].get("account_key")
            err = str(rows[0].get("last_error") or "degraded flag set")
            log_sig = None
            try:
                p = LOG_DIR / "schwab_ingest.log"
                if p.exists():
                    tail = "\n".join(p.read_text(errors="ignore").splitlines()[-int(cfg.get("tail_lines", 200)):])
                    for sig in ("invalid_grant", "no Schwab login token", "Refresh token is invalid", "OAuthError"):
                        if sig in tail:
                            log_sig = sig
                            break
            except Exception:
                pass
            out.append(_f("execution_health", "schwab_token_revoked", "critical",
                          f"Schwab OAuth token DEGRADED/revoked ({acct}: {err[:80]}"
                          f"{'; log: ' + log_sig if log_sig else ''}). The TTL health may still read valid; "
                          f"ingest is silently failing → trade journal stalls. {reauth}",
                          operator_action=True, reauth_cmd=reauth))
    except Exception as e:
        out.append(_f("execution_health", "collector_error", "info", f"broker token health check error: {e}"))
    return out


def collect_trade_ai_session() -> list[dict]:
    """CC SETUPS session freshness (run_date), not cache mtime.

    Autonomously remediable via heal_trade_ai_session_cache.py — Health Agent /
    escalation run the producer; operators do not patch cache by hand.
    """
    out: list[dict] = []
    try:
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
        try:
            from zoneinfo import ZoneInfo
            today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        except Exception:
            pass
        cache_path = PROJECT_ROOT / "data" / "runtime" / "trade_ai_cache.json"
        # Also check DEV if live stamp is empty/stale relative to package pointer
        candidates = [cache_path]
        try:
            from lib.live_project_root import DEV_ROOT
            candidates.append(DEV_ROOT / "data" / "runtime" / "trade_ai_cache.json")
        except Exception:
            pass
        run_date = None
        used = None
        for p in candidates:
            if not p.exists():
                continue
            try:
                d = json.loads(p.read_text())
                rd = d.get("run_date")
                if rd:
                    run_date = str(rd)[:10]
                    used = str(p)
                    break
            except Exception:
                continue
        if not run_date:
            out.append(_f("pipeline_freshness", "trade_ai_session_missing", "critical",
                          "trade_ai_cache.json missing or has no run_date — SETUPS session unknown",
                          surfaced="CC SETUPS header"))
            return out
        if run_date < today:
            out.append(_f(
                "pipeline_freshness", "trade_ai_session_stale", "critical",
                f"SETUPS session stale: run_date={run_date} (today ET {today}) — "
                f"CC header will show STALE until cache is healed",
                run_date=run_date, today_et=today, cache=used,
                surfaced="CC SETUPS header",
            ))
    except Exception as e:
        out.append(_f("pipeline_freshness", "trade_ai_session_check_error", "info",
                      f"trade_ai session check failed: {str(e)[:100]}"))
    return out


# ── Phase 4 prevention collectors ────────────────────────────────────────────────────────────────────

def collect_cron_sanity() -> list[dict]:
    """Verify every scripts/*.py reference in the crontab exists (prevents C8 recurrence).

    Dead cron entries silently fail (exit 127 into cron mail) and are invisible to the
    log-scanner — the C8 bug class where watchlist_health_agent.py ran every 10-30 min
    for weeks without existing in prod."""
    try:
        from check_cron_sanity import check
        return check()
    except Exception as e:
        return [_f("execution_health", "cron_sanity_check_error", "info",
                   f"Cron sanity check failed: {str(e)[:100]}")]


def collect_queue_health() -> list[dict]:
    """Inspect the escalation queue for stuck, orphaned, or oversized items.

    Finds items that have been exhausted >24h (stuck), items from dead sources
    (orphaned), and reports total queue depth."""
    out: list[dict] = []
    try:
        from lib.queue_file import read_items
        items = read_items(QUEUE_FILE)
    except Exception:
        try:
            items = json.loads(QUEUE_FILE.read_text()) if QUEUE_FILE.exists() else []
        except Exception:
            return [_f("execution_health", "queue_health_read_error", "info",
                       "Could not read escalation queue for health check")]
    if not items:
        return []
    now_ts = __import__("time").time()
    stuck = 0
    orphaned_sources = set()
    for item in items:
        if item.get("_exhausted"):
            last_at = item.get("_last_attempt_ts", 0)
            if last_at and (now_ts - float(last_at)) > 86400:
                stuck += 1
        src = item.get("source", "")
        if src and src not in ("health_agent", "system_health_agent",
                                "hermes_health_inspector", "manual"):
            orphaned_sources.add(src)
    if stuck:
        out.append(_f("execution_health", "queue_stuck_items", "warning",
                      f"{stuck} escalation queue item(s) exhausted >24h — may need operator review"))
    if orphaned_sources:
        out.append(_f("execution_health", "queue_orphaned_sources", "info",
                      f"Escalation queue contains items from unknown sources: "
                      f"{', '.join(sorted(orphaned_sources)[:5])}"))
    if len(items) > 50:
        out.append(_f("execution_health", "queue_depth_high", "info",
                      f"Escalation queue has {len(items)} items (>50) — review may be needed"))
    return out


COLLECTORS = [
    collect_data_quality,
    collect_trade_ai_session,
    collect_broker_token_health,
    collect_trade_in_view_health,
    collect_pipeline_containment,
    collect_execution_health,
    collect_execution_hardening_health,
    collect_intelligence_quality,
    collect_hermes_scope_governor_health,
    collect_risk_protection,
    collect_retirement_planning,
    collect_strategy_output,
    collect_strategy_registry_integrity,
    collect_proposal_maturity,
    collect_proposal_trade_plan_health,
    collect_log_errors,
    collect_pipeline_freshness,
    collect_momentum_scalp_source_health,
    collect_momentum_scalp_multi_source_health,
    collect_scalp_catalyst_health,
    collect_infra_optimization_health,
    collect_proposal_integrity,
    collect_options_desk_health,
    collect_pullback_macd_screener,
    collect_proposal_pipeline_health,
    collect_watchlist_news_guard_health,
    collect_proposal_oversight_load,
    collect_data_source_health,
    collect_failed_systemd_units,
    collect_db_connection_health,
    collect_backup_health,
    # Phase 4 prevention collectors
    collect_cron_sanity,
    collect_queue_health,
]


# ── scoring ──────────────────────────────────────────────────────────────────────────────────────────

def score_category(findings: list[dict], penalties: dict) -> int:
    """Score a category 0-100.  The cumulative penalty is capped at the largest single
    severity penalty (default critical −40), so two concurrent criticals in the same
    category don't zero it — one critical already makes the point; redundant criticals
    don't add signal.  Info/warning findings still subtract below the cap."""
    score = 100
    max_penalty = max(penalties.values()) if penalties else 40  # critical
    total = 0
    for f in findings:
        total += penalties.get(f.get("severity"), 0)
    score -= min(total, max_penalty)
    # Info/warning penalties beyond the first critical still register (up to the cap)
    return max(0, min(100, score))


def compute(policy: dict):
    global _POLICY
    _POLICY = policy or {}

    # ── DB reachability probe (fail-closed: a dead DB must NOT score "healthy") ──
    # _db() swallows exceptions and returns None → collectors silently skip, which
    # historically scored 100/"healthy" during PostgreSQL outages.  This probe runs
    # BEFORE the collector loop and injects a critical finding if the DB is unreachable,
    # so the score correctly tanks even though file-based collectors still work.
    db_down = False
    try:
        from db_adapter import _execute, USE_DB
        if USE_DB:
            _execute("SELECT 1", fetch="one")  # raises on connectivity failure
    except Exception:
        db_down = True

    penalties = policy.get("penalties", {"critical": 40, "warning": 15, "info": 5})
    weights = policy.get("weights", {})
    all_findings = []

    if db_down:
        all_findings.append(_f("execution_health", "database_unreachable", "critical",
            "PostgreSQL is unreachable — DB-dependent collectors (data freshness, broker state, "
            "pipeline runs, options desk, etc.) cannot run. The score reflects ONLY file-based "
            "collectors and WILL be incomplete. Restore Postgres and re-run the health agent.",
            surfaced="All DB-dependent pages · health agent"))

    for fn in COLLECTORS:
        try:
            all_findings.extend(fn() or [])
        except Exception as e:
            all_findings.append(_f("execution_health", "collector_error", "info", f"{fn.__name__}: {e}"))
    # Annotate each finding with why-it-matters + recommended action (self-justifying + actionable).
    rmap = (policy.get("remediation_map") or {})
    for _f_ in all_findings:
        _annotate(_f_, rmap)
    # Group findings by their tagged category so multiple collectors can feed one category.
    cat_findings = {c: [f for f in all_findings if f.get("category") == c] for c in CATEGORIES}
    cat_scores = {c: score_category(cat_findings[c], penalties) for c in CATEGORIES}
    # weighted overall (fallback to equal weights)
    if weights:
        tot_w = sum(weights.get(c, 0) for c in cat_scores) or 1
        overall = round(sum(cat_scores[c] * weights.get(c, 0) for c in cat_scores) / tot_w)
    else:
        overall = round(sum(cat_scores.values()) / len(cat_scores))
    thr = policy.get("score_thresholds", {"healthy": 85, "degraded": 65})
    status = "healthy" if overall >= thr["healthy"] else ("degraded" if overall >= thr["degraded"] else "unhealthy")
    return overall, status, cat_scores, cat_findings


# ── trends ────────────────────────────────────────────────────────────────────────────────────────────

def ensure_snapshot_table():
    _db("""CREATE TABLE IF NOT EXISTS health_agent_snapshots (
             id SERIAL PRIMARY KEY,
             captured_at TIMESTAMPTZ DEFAULT now(),
             overall_score INT, status TEXT,
             category_scores JSONB, findings JSONB, mode TEXT)""", fetch=None)
    _db("""CREATE INDEX IF NOT EXISTS idx_health_agent_snapshots_captured_at
           ON health_agent_snapshots (captured_at DESC)""", fetch=None)


def detect_trends(policy: dict, overall: int, cat_scores: dict) -> list[dict]:
    look = policy.get("trend", {}).get("lookback_runs", 3)
    drop = policy.get("trend", {}).get("drop_alert_points", 10)
    rows = _db("SELECT overall_score, category_scores FROM health_agent_snapshots "
               "ORDER BY captured_at DESC LIMIT %s", (look,), fetch="all") or []
    trends = []
    if len(rows) >= 2:
        prev_overall = rows[0].get("overall_score")
        if prev_overall is not None and (prev_overall - overall) >= drop:
            trends.append({"scope": "overall", "from": prev_overall, "to": overall,
                           "message": f"overall health dropped {prev_overall}→{overall}"})
        # monotonic per-category decline across the window
        for cat in cat_scores:
            series = [overall if False else cat_scores[cat]] + [
                (r.get("category_scores") or {}).get(cat) for r in rows]
            series = [s for s in series if s is not None]
            if len(series) >= look and all(series[i] < series[i + 1] for i in range(len(series) - 1)):
                trends.append({"scope": cat, "from": series[-1], "to": series[0],
                               "message": f"{cat} declining {series[-1]}→{series[0]} over {len(series)} runs"})
    return trends


# ── escalation enqueue (feeds the existing handler + coder_dispatch) ─────────────────────────────────

def enqueue_escalations(policy: dict, findings_flat: list[dict]):
    """Append remediable findings to claude_escalation_queue.json (deduped by component:type).
    Data findings get an allowlisted retry_cmd (handler tier-1). Code-level findings get
    needs_code_fix + kind so coder_dispatch routes them to an AI coder."""
    enq = policy.get("enqueue", {})
    if not enq.get("escalations", True):
        return 0
    rmap = policy.get("remediation_map", {})
    never = set(policy.get("never_auto_remediate") or []) | set(_NEVER_AUTO_DEFAULT)

    # Pre-filter findings so we know the candidate set before the atomic update
    candidates = []
    for f in findings_flat:
        if f.get("severity") not in ("warning", "critical"):
            continue
        if f.get("type") == "execution_escalations":
            continue
        if f.get("held"):
            continue
        if f.get("type") in never or f.get("never_auto") or f.get("operator_action"):
            continue
        candidates.append(f)

    if not candidates:
        return 0

    count_box = [0]  # mutable container so the lambda can write to it

    def _update(existing):
        seen = {f"{i.get('component')}:{i.get('detail','')[:40]}" for i in existing}
        existing_components = {i.get("component") for i in existing
                              if (i.get("source") or "") in ("health_agent", "health_agent_meta")}
        existing_by_comp = {}
        for ei in existing:
            comp = ei.get("component")
            if comp:
                existing_by_comp[comp] = ei
        for f in candidates:
            comp = f"health:{f['category']}:{f['type']}"
            if comp in existing_components:
                continue
            key = f"{comp}:{f['message'][:40]}"
            if key in seen:
                continue
            item = {
                "component": comp,
                "detail": f["message"],
                "status": f["severity"],
                "critical": f["severity"] == "critical",
                "fixable": False,
                "source": "health_agent",
            }
            old_item = existing_by_comp.get(comp, {})
            for field in ("_attempts", "_last_attempt_ts", "_exhausted"):
                if field in old_item:
                    item[field] = old_item[field]
            retry = _data_source_retry_cmd(policy, f["type"], f)
            if isinstance(retry, str) and retry.strip():
                retry = _rewrite_remediation_cmd(retry)
                try:
                    from lib.agent_jobs_containment import guard_agent_jobs_execution
                    g = guard_agent_jobs_execution(retry, source="health_agent.enqueue_escalations")
                except Exception:
                    if "process_watchlist_agent_jobs" in str(retry).lower():
                        g = {"blocked": True, "remediation_status": "CONTAINMENT_CHECK_FAILED",
                             "message": "CONTAINMENT_CHECK_FAILED"}
                    else:
                        g = {"blocked": False}
                if g.get("blocked"):
                    item["fixable"] = False
                    item["retry_cmd"] = None
                    item["remediation_status"] = (
                        g.get("remediation_status") or g.get("status") or "CONTAINMENT_CHECK_FAILED"
                    )
                    item["detail"] = (
                        f"{f['message']} | {item['remediation_status']}: "
                        f"process_watchlist_agent_jobs will not be invoked"
                    )
                else:
                    item["fixable"] = True
                    item["retry_cmd"] = retry
            if f.get("kind") in ("code", "single_file", "multi_file", "schema") and enq.get("code_fixes", True):
                item["needs_code_fix"] = True
                item["kind"] = f.get("kind", "code")
            existing.append(item)
            seen.add(key)
            existing_components.add(comp)
            count_box[0] += 1
        return existing

    try:
        from lib.queue_file import atomic_update
        atomic_update(QUEUE_FILE, _update)
    except Exception:
        # Fallback: direct read/write if queue_file module is unavailable
        try:
            existing = json.loads(QUEUE_FILE.read_text()) if QUEUE_FILE.exists() else []
        except Exception:
            existing = []
        _update(existing)
        if count_box[0]:
            try:
                QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
                QUEUE_FILE.write_text(json.dumps(existing, indent=2))
            except Exception:
                pass
    return count_box[0]


# ── persistence + alerting ───────────────────────────────────────────────────────────────────────────

def prune_old_snapshots(policy: dict):
    """Drop snapshots older than retention_days (keeps DB/API history bounded)."""
    days = int((policy.get("history") or {}).get("retention_days", 90))
    if days <= 0:
        return
    try:
        _db("DELETE FROM health_agent_snapshots WHERE captured_at < now() - (%s * interval '1 day')",
            (days,), fetch=None)
    except Exception:
        pass


def persist(snapshot: dict, policy: dict | None = None):
    ensure_snapshot_table()
    _db("""INSERT INTO health_agent_snapshots (overall_score,status,category_scores,findings,mode)
           VALUES (%s,%s,%s,%s,%s)""",
        (snapshot["overall_score"], snapshot["status"],
         json.dumps(snapshot["category_scores"]), json.dumps(snapshot["findings"]),
         snapshot["mode"]), fetch=None)
    if policy:
        prune_old_snapshots(policy)
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(json.dumps(snapshot, indent=2, default=str))
    except Exception:
        pass
    try:
        AUDIT_JSONL.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_JSONL, "a") as fh:
            fh.write(json.dumps({"captured_at": snapshot["captured_at"],
                                 "overall": snapshot["overall_score"], "status": snapshot["status"],
                                 "category_scores": snapshot["category_scores"],
                                 "trends": snapshot["trends"], "enqueued": snapshot.get("enqueued", 0)},
                                default=str) + "\n")
    except Exception:
        pass


ALERT_STATE = STATE_DIR / "health_agent_alert_state.json"


def _parse_iso(ts) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def _alert_suppressed(policy: dict, snapshot: dict) -> bool:
    """Throttle repeat alerts: an unchanged DEGRADED re-alerted every 30-min run is noise
    (2026-07-04: 6 identical Telegrams in an hour, doubled by a duplicate systemd timer).
    Alert only on status change, a meaningful score drop, or a periodic heartbeat.

    Flap guard (2026-07-04 evening): a check oscillating each run (e.g. intelligence 100↔60)
    flips status DEGRADED↔UNHEALTHY every 30 min; each flip re-armed `changed`/`worsened`
    and paged 6 more times in 6 hours. We remember the last alert per status ("recent") —
    flipping back to a recently-alerted status at a similar score is suppressed; a genuinely
    new status or a real deterioration still alerts immediately."""
    acfg = policy.get("alert", {})
    realert_m = float(acfg.get("min_realert_minutes", 360))
    drop_pts = float(acfg.get("realert_on_score_drop", 5))
    flap_m = float(acfg.get("flap_suppress_minutes", 120))
    try:
        st = json.loads(ALERT_STATE.read_text()) if ALERT_STATE.exists() else {}
    except Exception:
        st = {}
    now = datetime.now(timezone.utc)
    last_at = _parse_iso(st.get("at", ""))
    status = snapshot["status"]
    score = snapshot["overall_score"]
    recent = st.get("recent") if isinstance(st.get("recent"), dict) else {}

    changed = st.get("status") != status
    if changed:
        prev = recent.get(status) or {}
        prev_at = _parse_iso(prev.get("at", ""))
        # Flapping back to a status we alerted on within flap_suppress_minutes, at a score
        # no worse than last time → not news. A real drop still passes via `worsened`.
        if prev_at and (now - prev_at).total_seconds() < flap_m * 60 \
                and score > float(prev.get("score", -1)) - drop_pts:
            changed = False
    # Worsening is judged against the last alerted score FOR THIS STATUS when we have one,
    # so an oscillation between two stable (status, score) pairs cannot re-arm it each flip.
    baseline = (recent.get(status) or {}).get("score", st.get("score", 100))
    worsened = score <= float(baseline) - drop_pts
    heartbeat_due = last_at is None or (now - last_at).total_seconds() >= realert_m * 60
    if not (changed or worsened or heartbeat_due):
        return True
    try:
        recent = dict(recent)
        recent[status] = {"at": now.isoformat(), "score": score}
        # prune per-status entries too old to matter for flap/worsening decisions
        horizon = max(realert_m, flap_m) * 60
        recent = {s: v for s, v in recent.items()
                  if (_parse_iso((v or {}).get("at", "")) or now) >= now - timedelta(seconds=horizon)}
        ALERT_STATE.parent.mkdir(parents=True, exist_ok=True)
        ALERT_STATE.write_text(json.dumps({"at": now.isoformat(), "status": status,
                                           "score": score, "recent": recent}))
    except Exception:
        pass
    return False


def alert(policy: dict, snapshot: dict):
    if snapshot["status"] not in policy.get("alert", {}).get("telegram_on_status", ["unhealthy", "degraded"]) \
            and not (snapshot["trends"] and policy.get("alert", {}).get("telegram_on_trend_drop", True)):
        return
    if _alert_suppressed(policy, snapshot):
        return
    icon = {"unhealthy": "🚨", "degraded": "⚠️", "healthy": "✅"}.get(snapshot["status"], "ℹ️")
    lines = [f"{icon} <b>Health Agent: {snapshot['status'].upper()} — {snapshot['overall_score']}/100</b>"]
    lines.append(" · ".join(f"{c.split('_')[0]}:{s}" for c, s in snapshot["category_scores"].items()))
    crit = [f for f in snapshot["findings"] if f["severity"] == "critical"]
    for f in crit[:6]:
        lines.append(f"• {f['message']}")
    for t in snapshot["trends"][:3]:
        lines.append(f"↘ {t['message']}")
    if snapshot.get("enqueued"):
        lines.append(f"→ {snapshot['enqueued']} finding(s) queued for auto-remediation")
    # "Auto-fixed" is claimed ONLY for a CLEARED verdict -- one where the
    # originating check was re-run and the finding no longer fires. It used to be
    # claimed on exit code 0, which is how a 24h stale repricer was reported fixed
    # every cycle.
    fixed = [r for r in (snapshot.get("remediated") or [])
             if r.get("outcome") == "CLEARED" or (r.get("ok") and "outcome" not in r)]
    if fixed:
        lines.append(f"✅ Auto-fixed (re-checked): {', '.join(r.get('type', '?') for r in fixed)}")
    worsened = [r for r in (snapshot.get("remediated") or []) if r.get("outcome") == "WORSENED"]
    for r in worsened:
        esc = r.get("escalate") or {}
        lines.append(
            f"🚨 WORSENED — {r.get('type', '?')}: {esc.get('metric_trend', 'condition regressed')}. "
            f"Stopped retrying. Cause: {r.get('root_cause') or 'UNDIAGNOSED'}. "
            f"Command that did not help: {esc.get('command_that_did_not_help') or r.get('cmd', '?')}")
    # An INEFFECTIVE attempt that has not yet tripped the breaker is reported
    # without paging. Staying silent until attempt 2 would leave the operator
    # seeing a critical finding with no indication that a fix had been tried and
    # had not worked -- which is the same information gap, one cycle narrower.
    trying = [r for r in (snapshot.get("remediated") or [])
              if r.get("outcome") == "INEFFECTIVE" and not r.get("ineffective")]
    for r in trying:
        lines.append(
            f"↻ Remediation ineffective (attempt recorded, not yet escalated) — "
            f"{r.get('type', '?')}: cause {r.get('root_cause') or 'UNDIAGNOSED'}. "
            f"Command that did not help: {r.get('cmd', '?')}")
    ineffective = [r for r in (snapshot.get("remediated") or [])
                   if r.get("ineffective") and r.get("outcome") != "WORSENED"]
    for r in ineffective:
        esc = r.get("escalate") or {}
        lines.append(
            f"🔁 Remediation ineffective (needs operator) — {r.get('type', '?')}: "
            f"cause {r.get('root_cause') or 'UNDIAGNOSED'}; {esc.get('metric_trend', '')}. "
            f"Command that did not help: {esc.get('command_that_did_not_help') or r.get('cmd', '?')}")
    unverified = [r for r in (snapshot.get("remediated") or []) if r.get("outcome") == "UNVERIFIED"]
    if unverified:
        lines.append(f"❓ Could not re-check (no success claimed): "
                     f"{', '.join(r.get('type', '?') for r in unverified)}")
    try:
        from telegram_alert import send_telegram
        send_telegram("\n".join(lines))
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description="Centralized proactive Health Agent")
    ap.add_argument("--no-enqueue", action="store_true", help="score only; do not touch escalation queue")
    ap.add_argument("--no-alert", action="store_true", help="do not send Telegram")
    ap.add_argument("--json", action="store_true", help="print snapshot json")
    args = ap.parse_args()

    # Register heartbeat
    hb = None
    try:
        from lib.agent_heartbeat import AgentHeartbeat
        from db_adapter import _get_conn
        hb_conn = _get_conn()
        if hb_conn:
            hb = AgentHeartbeat(hb_conn, 'health_agent', task='health_scoring')
            hb.register()
    except Exception:
        pass

    policy = load_policy()
    mode = (os.getenv("HEALTH_AGENT_MODE") or policy.get("mode") or "advisory").lower()
    ensure_snapshot_table()  # so the first-ever trend lookup has a table to read
    overall, status, cat_scores, cat_findings = compute(policy)
    findings_flat = [f for fs in cat_findings.values() for f in fs]
    trends = detect_trends(policy, overall, cat_scores)

    enqueued = 0
    if not args.no_enqueue:
        enqueued = enqueue_escalations(policy, findings_flat)

    remediated = []
    if not args.no_enqueue:
        remediated = run_auto_remediation(policy, findings_flat)

    # If auto-remediation actually fixed something, RE-SCORE so the snapshot/alert reflect the
    # post-fix state. Otherwise the alert pings DEGRADED for an issue resolved in the SAME cycle
    # (e.g. snaptrade_cash_stale → snaptrade_sync ran → data_quality already back to 100, yet the
    # pre-remediation score said data:70). The fix scripts (repricer/snaptrade_sync) mutate the
    # underlying data, so a fresh compute() reflects them honestly. Only re-score on a real success.
    rescored = False
    if remediated and any(r.get("ok") for r in remediated):
        try:
            overall, status, cat_scores, cat_findings = compute(policy)
            findings_flat = [f for fs in cat_findings.values() for f in fs]
            trends = detect_trends(policy, overall, cat_scores)
            rescored = True
        except Exception:
            pass

    scheduler = os.getenv("HEALTH_AGENT_SCHEDULER", "cron")
    hist_cfg = policy.get("history") or {}
    snapshot = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "overall_score": overall, "status": status, "mode": mode,
        "category_scores": cat_scores, "findings": findings_flat,
        "trends": trends, "enqueued": enqueued, "remediated": remediated,
        "rescored_after_remediation": rescored,
        "scheduler": scheduler,
        "history_retention_days": int(hist_cfg.get("retention_days", 90)),
        "summary": f"{status} {overall}/100 · {len([f for f in findings_flat if f['severity']=='critical'])} critical · "
                   f"{len([f for f in findings_flat if f['severity']=='warning'])} warnings",
    }
    persist(snapshot, policy)
    if not args.no_alert:
        alert(policy, snapshot)

    if args.json:
        print(json.dumps(snapshot, indent=2, default=str))
    else:
        print(f"Health: {status.upper()} {overall}/100  |  " +
              "  ".join(f"{c}={s}" for c, s in cat_scores.items()) +
              f"  |  {len(findings_flat)} findings, {enqueued} enqueued, "
              f"{len(remediated)} auto-remediated, {len(trends)} trends")

    # Mark heartbeat done
    if hb:
        try:
            hb.mark_done(success=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
