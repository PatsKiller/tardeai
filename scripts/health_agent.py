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
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
LOG_DIR = PROJECT_ROOT / "logs"
POLICY_FILE = PROJECT_ROOT / "config" / "health_agent_policy.json"
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
            ("cio_decisions", _db_age_h("SELECT MAX(created_at) FROM cio_decisions"), wk or 48, True),
            ("agent_jobs", _db_age_h("SELECT MAX(created_at) FROM watchlist_agent_jobs WHERE status='completed'"), wk or 4, False),
        ]
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
    except Exception as e:
        out.append(_f("data_quality", "collector_error", "info", f"data_quality check error: {e}"))
    return out


def collect_execution_health() -> list[dict]:
    out = []
    try:
        # recent pipeline failures
        pf = _db("SELECT COUNT(*) AS c FROM pipeline_runs WHERE status='failed' AND started_at > now() - interval '24 hours'", fetch="one")
        if pf and pf.get("c", 0) > 0:
            out.append(_f("execution_health", "pipeline_failures", "warning" if pf["c"] < 5 else "critical",
                          f"{pf['c']} pipeline run failures in 24h", count=pf["c"]))
        # stuck queued agent jobs
        q = _db("SELECT COUNT(*) AS c FROM watchlist_agent_jobs WHERE status='queued' AND created_at < now() - interval '2 hours'", fetch="one")
        if q and q.get("c", 0) > 0:
            out.append(_f("execution_health", "agent_jobs_stuck", "warning",
                          f"{q['c']} agent jobs queued >2h", count=q["c"]))
        # execution-integrity escalation queue depth (system_health_agent output)
        try:
            items = json.loads(QUEUE_FILE.read_text()) if QUEUE_FILE.exists() else []
        except Exception:
            items = []
        crit = [i for i in items if i.get("severity") in ("CRITICAL", "critical") or i.get("critical")]
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
        if pending >= 2000:
            out.append(_f("intelligence_quality", "hermes_embed_backlog", "critical",
                          f"{pending} Hermes embeddings pending in queue", count=pending))
        elif pending >= 200:
            out.append(_f("intelligence_quality", "hermes_embed_backlog", "warning",
                          f"{pending} Hermes embeddings pending in queue", count=pending))
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
        if age_min > 60:
            out.append(_f("intelligence_quality", "hermes_coordinator_stale", "critical",
                          f"Hermes coordinator last tick {int(age_min)}m ago", age_min=int(age_min)))
        elif age_min > 30:
            out.append(_f("intelligence_quality", "hermes_coordinator_stale", "warning",
                          f"Hermes coordinator last tick {int(age_min)}m ago", age_min=int(age_min)))
    except Exception as e:
        out.append(_f("intelligence_quality", "collector_error", "info", f"intelligence check error: {e}"))
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
        # stop lifecycle alerts
        al = _db("SELECT COUNT(*) AS c FROM stop_lifecycle WHERE health='alert'", fetch="one")
        if al and al.get("c", 0) > 0:
            out.append(_f("risk_protection", "stop_alerts", "warning",
                          f"{al['c']} stops in alert state", count=al["c"]))
        # recent P0/P1 protection SIEM events
        p = _db("""SELECT COUNT(*) AS c FROM alert_events
                   WHERE severity IN ('critical','urgent') AND created_at > now() - interval '24 hours'""", fetch="one")
        if p and p.get("c", 0) > 0:
            out.append(_f("risk_protection", "siem_p0p1", "warning" if p["c"] < 5 else "critical",
                          f"{p['c']} P0/P1 SIEM alerts in 24h", count=p["c"]))
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
    ]
    window_h = float(cfg.get("window_hours", 3))
    threshold = int(cfg.get("error_threshold", 5))
    tail = int(cfg.get("tail_lines", 400))
    # Case-SENSITIVE: match real log-level tokens / error markers, NOT domain words like the
    # severity label "high/critical" in a normal summary line (that caused false positives).
    pat = _re.compile(r"\bERROR\b|\bCRITICAL\b|\bFATAL\b|Traceback \(most recent call last\)"
                      r"|\bException\b|[A-Za-z]*error:|[A-Za-z]*exception:")
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
            errs = [ln for ln in lines if pat.search(ln)]
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
    "agent_jobs_stuck": "Agent jobs aren't draining — analysis is backing up and results are going stale.",
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
    "options_zero_proposals": "Options desk produced zero proposals — income/CC opportunities may be invisible in Command Center.",
    "options_proposals_stale": "Options proposal cache is stale — UI may show outdated or empty ideas.",
    "trade_proposals_backlog": "Many trade proposals are pending — approval queue may be clogged.",
    "watchlist_stale": "Watchlist items haven't been refreshed — rotation/options synergy may be weak.",
    "rotation_empty": "No rotation recommendations staged — capital redeployment signals may be missing.",
    "small_cap_signal_gap": "IWM/Russell 2000 is outperforming SPY in the market, but news curation, proposals, or watchlist lack small-cap coverage.",
    "golden_window_missing": "Retirement Golden Window drives Roth-conversion guidance; missing = a planning gap.",
    "dividend_income_zero": "Zero dividend income is almost certainly a data inconsistency, not reality.",
    "data_gaps_open": "Some symbols lack required enrichment until these gaps are resolved.",
}


def _annotate(f: dict, rmap: dict):
    """Attach why-it-matters + recommended action + actionability to a finding (write-time)."""
    t = f.get("type", "")
    f["why"] = WHY.get(t) or ("Stale data product — dependent pages/decisions use old numbers."
                              if t.endswith("_stale") else f"{f.get('category','')} signal needs review.")
    if t in rmap:
        f["action_type"] = "auto_retry"
        f["recommended_action"] = f"Auto-retry (allowlisted): {rmap[t]}"
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


CATEGORIES = ["data_quality", "execution_health", "intelligence_quality",
              "risk_protection", "retirement_planning"]

COLLECTORS = [
    collect_data_quality,
    collect_execution_health,
    collect_intelligence_quality,
    collect_risk_protection,
    collect_retirement_planning,
    collect_strategy_output,
    collect_proposal_maturity,
    collect_log_errors,
]


# ── scoring ──────────────────────────────────────────────────────────────────────────────────────────

def score_category(findings: list[dict], penalties: dict) -> int:
    score = 100
    for f in findings:
        score -= penalties.get(f.get("severity"), 0)
    return max(0, min(100, score))


def compute(policy: dict):
    global _POLICY
    _POLICY = policy or {}
    penalties = policy.get("penalties", {"critical": 40, "warning": 15, "info": 5})
    weights = policy.get("weights", {})
    all_findings = []
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
    try:
        existing = json.loads(QUEUE_FILE.read_text()) if QUEUE_FILE.exists() else []
    except Exception:
        existing = []
    seen = {f"{i.get('component')}:{i.get('detail','')[:40]}" for i in existing}
    added = 0
    for f in findings_flat:
        if f.get("severity") not in ("warning", "critical"):
            continue
        comp = f"health:{f['category']}:{f['type']}"
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
        retry = rmap.get(f["type"])
        if retry:
            item["fixable"] = True
            item["retry_cmd"] = retry
        if f.get("kind") in ("code", "single_file", "multi_file", "schema") and enq.get("code_fixes", True):
            item["needs_code_fix"] = True
            item["kind"] = f.get("kind", "code")
        existing.append(item)
        seen.add(key)
        added += 1
    if added:
        try:
            QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
            QUEUE_FILE.write_text(json.dumps(existing, indent=2))
        except Exception:
            pass
    return added


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


def alert(policy: dict, snapshot: dict):
    if snapshot["status"] not in policy.get("alert", {}).get("telegram_on_status", ["unhealthy", "degraded"]) \
            and not (snapshot["trends"] and policy.get("alert", {}).get("telegram_on_trend_drop", True)):
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

    policy = load_policy()
    mode = (os.getenv("HEALTH_AGENT_MODE") or policy.get("mode") or "advisory").lower()
    ensure_snapshot_table()  # so the first-ever trend lookup has a table to read
    overall, status, cat_scores, cat_findings = compute(policy)
    findings_flat = [f for fs in cat_findings.values() for f in fs]
    trends = detect_trends(policy, overall, cat_scores)

    enqueued = 0
    if not args.no_enqueue:
        enqueued = enqueue_escalations(policy, findings_flat)

    scheduler = os.getenv("HEALTH_AGENT_SCHEDULER", "cron")
    hist_cfg = policy.get("history") or {}
    snapshot = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "overall_score": overall, "status": status, "mode": mode,
        "category_scores": cat_scores, "findings": findings_flat,
        "trends": trends, "enqueued": enqueued,
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
              f"  |  {len(findings_flat)} findings, {enqueued} enqueued, {len(trends)} trends")


if __name__ == "__main__":
    main()
