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
import subprocess
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


def run_auto_remediation(policy: dict, findings: list[dict]) -> list[dict]:
    """Execute allowlisted fix scripts immediately for portfolio-pricing findings (no escalation wait).
    Cooldown per finding-type prevents repricer storms."""
    cfg = policy.get("auto_remediate") or {}
    if not cfg.get("enabled", True):
        return []
    types = set(cfg.get("finding_types") or [
        "portfolio_totals_drift", "account_summary_drift", "snaptrade_cash_stale",
        "portfolio_repricer_stale", "finviz_quote_cache_stale", "market_quotes_stale",
    ])
    cooldown_m = float(cfg.get("cooldown_minutes", 10))
    # Circuit breaker: if a remediation keeps "succeeding" (exit 0) yet the SAME finding fires again
    # within ineffective_window_minutes, the fix isn't actually fixing it — stop the futile loop and
    # the false "✅ Auto-fixed" pings after max_ineffective_attempts; escalate for operator/code review.
    # (Caught snaptrade_cash_stale: 24 identical "fixes" of SPAXX $277,333, value never changed —
    # SnapTrade likely doesn't expose buying_power for that rollover IRA, or the cash is simply correct.)
    max_ineffective = int(cfg.get("max_ineffective_attempts", 3))
    ineff_window_m = float(cfg.get("ineffective_window_minutes", 60))
    rmap = policy.get("remediation_map") or {}
    actionable = [f for f in findings
                  if f.get("severity") in ("warning", "critical") and f.get("type") in types]
    if not actionable:
        return []
    try:
        state = json.loads(REMEDIATION_STATE.read_text()) if REMEDIATION_STATE.exists() else {}
    except Exception:
        state = {}
    now = datetime.now(timezone.utc)
    results = []
    ran_cmds: set[str] = set()

    def _st(ftype):  # normalize legacy str-timestamp state → dict
        s = state.get(ftype)
        if isinstance(s, str):
            return {"last_success": s, "ineffective_streak": 0}
        return s if isinstance(s, dict) else {"last_success": None, "ineffective_streak": 0}

    for f in actionable:
        ftype = f.get("type")
        cmd = rmap.get(ftype)
        if not cmd or cmd in ran_cmds:
            continue
        st = _st(ftype)
        last = st.get("last_success")
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
        if st.get("ineffective_streak", 0) >= max_ineffective:
            entry = {"at": now.isoformat(), "type": ftype, "cmd": cmd, "ok": False, "ineffective": True,
                     "streak": st["ineffective_streak"],
                     "note": f"remediation ineffective {st['ineffective_streak']}x within {int(ineff_window_m)}m "
                             f"— not re-running; needs operator/code review",
                     "trigger": f.get("message", "")[:200]}
            results.append(entry)
            with open(REMEDIATION_LOG, "a") as fh:
                fh.write(json.dumps(entry) + "\n")
            state[ftype] = st
            continue
        # Safe portfolio-pricing scripts only (no broker order submission).
        if "portfolio_repricer.py" not in cmd and "external_market_data_ingest.py" not in cmd \
                and "snaptrade_sync.py" not in cmd:
            continue
        try:
            proc = subprocess.run(cmd, shell=True, cwd=str(PROJECT_ROOT),
                                  capture_output=True, text=True, timeout=180)
            ok = proc.returncode == 0
            entry = {
                "at": now.isoformat(), "type": ftype, "cmd": cmd, "ok": ok,
                "exit_code": proc.returncode,
                "stdout_tail": (proc.stdout or "")[-400:],
                "stderr_tail": (proc.stderr or "")[-400:],
                "ineffective_streak": st.get("ineffective_streak", 0),
                "trigger": f.get("message", "")[:200],
            }
            results.append(entry)
            REMEDIATION_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(REMEDIATION_LOG, "a") as fh:
                fh.write(json.dumps(entry) + "\n")
            if ok:
                st["last_success"] = now.isoformat()
                state[ftype] = st
                ran_cmds.add(cmd)
        except Exception as ex:
            results.append({"at": now.isoformat(), "type": ftype, "cmd": cmd, "ok": False,
                            "error": str(ex)[:200], "trigger": f.get("message", "")[:200]})
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
            out.append(_f("execution_health", "pipeline_failures", "warning" if pf_count <= 5 else "critical",
                          f"{pf_count} pipeline run failures in 24h", count=pf_count))
        # stuck queued agent jobs — distinguish DECISION-FEEDING jobs (have an SLA) from the rolling
        # background research/discovery queue (no SLA; drained by priority, intentionally backloggy).
        # Penalizing execution_health for a research backlog was a false signal — only time-sensitive
        # jobs starved >2h are an execution defect; the rolling backlog is reported as info.
        _TIME_SENSITIVE = ("proposal_review", "full_analysis", "research_gap", "event")
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
    "agent_jobs_stuck": "Decision-feeding agent jobs (proposal/full-analysis/research-gap) aren't draining within SLA — proposals and reviews are going stale.",
    "research_backlog": "Background research/discovery queue is large but has no SLA — drained by priority; informational unless it never shrinks.",
    "proposal_thesis_broken": "A PENDING proposal's live price has passed its target or fallen to its stop — there is no valid live R:R; verify it's expiring/recalibrating and not displaying a stale favorable R:R.",
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
    "finviz_quote_cache_stale": "Finviz quote cache is the authoritative portfolio price layer — stale cache = wrong Command Center P/L.",
    "portfolio_repricer_stale": "portfolio_repricer.py has not run — holdings prices lag Finviz/broker reality.",
    "portfolio_totals_drift": "Header portfolio_value disagrees with sum of position market values — Command Center shows two different totals.",
    "account_summary_drift": "An account_summary total is stale vs its holdings rows (common after SnapTrade sync without repricer).",
    "snaptrade_cash_stale": "Fidelity SPAXX cash is stale (SnapTrade position units); should use balances.buying_power (~Fidelity core MM).",
    "market_quotes_stale": "Alpaca market_quotes backup feed is stale — Fidelity fallback prices may be wrong.",
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
        for s in stale:
            sev = "critical" if s["age_days"] > (s["threshold_days"] * 4) else "warning"
            out.append(_f("pipeline_freshness", f"stale_{s['name']}", sev,
                          f"{s['name']} output {s['age_days']}d stale (>{s['threshold_days']}d) — shown on {s['surfaced']}",
                          kind="code", age_days=s["age_days"], surfaced=s["surfaced"]))
        for m in missing:
            out.append(_f("pipeline_freshness", f"missing_{m['name']}", "warning",
                          f"{m['name']} produces no output ({m['reason']}) — {m['surfaced']}",
                          kind="code", surfaced=m["surfaced"]))
    except Exception as e:
        out.append(_f("pipeline_freshness", "monitor_error", "info", f"freshness monitor failed: {str(e)[:80]}"))
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


COLLECTORS = [
    collect_data_quality,
    collect_execution_health,
    collect_intelligence_quality,
    collect_risk_protection,
    collect_retirement_planning,
    collect_strategy_output,
    collect_proposal_maturity,
    collect_log_errors,
    collect_pipeline_freshness,
    collect_proposal_integrity,
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
    # Dedup health findings by COMPONENT (category:type) alone. The message embeds a changing count
    # ("14 agent jobs queued >2h" → "132 ..."), so a message-based key never matched and the same
    # finding piled up — 14 agent_jobs_stuck items each carrying the --limit 15 retry_cmd, which the
    # handler then ran concurrently (the 2026-06-25 Ollama thundering-herd). One open escalation per
    # finding type is enough; the latest detail is what matters.
    existing_components = {i.get("component") for i in existing
                          if (i.get("source") or "") in ("health_agent", "health_agent_meta")}
    added = 0
    for f in findings_flat:
        if f.get("severity") not in ("warning", "critical"):
            continue
        # Never enqueue the meta execution_escalations finding — it only describes queue depth and
        # re-enqueueing it creates a critical-count feedback loop in Telegram alerts.
        if f.get("type") == "execution_escalations":
            continue
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
        retry = rmap.get(f["type"])
        if retry:
            item["fixable"] = True
            item["retry_cmd"] = retry
        if f.get("kind") in ("code", "single_file", "multi_file", "schema") and enq.get("code_fixes", True):
            item["needs_code_fix"] = True
            item["kind"] = f.get("kind", "code")
        existing.append(item)
        seen.add(key)
        existing_components.add(comp)
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
    fixed = [r for r in (snapshot.get("remediated") or []) if r.get("ok")]
    if fixed:
        suffix = " (score is post-fix)" if snapshot.get("rescored_after_remediation") else ""
        lines.append(f"✅ Auto-fixed: {', '.join(r.get('type', '?') for r in fixed)}{suffix}")
    ineffective = [r for r in (snapshot.get("remediated") or []) if r.get("ineffective")]
    if ineffective:
        lines.append(f"🔁 Remediation ineffective (needs operator): {', '.join(r.get('type', '?') for r in ineffective)}")
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


if __name__ == "__main__":
    main()
