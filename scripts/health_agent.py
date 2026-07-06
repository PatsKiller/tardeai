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
from datetime import datetime, timedelta, timezone
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
        # Safe scripts only (no broker order submission). run_finviz_momentum_scalp_scan and
        # run_sec_form4_momentum_context are source/sandbox-only (no live broker writes) — safe to
        # auto-run to unstick the lane / refresh supporting evidence.
        if "portfolio_repricer.py" not in cmd and "external_market_data_ingest.py" not in cmd \
                and "snaptrade_sync.py" not in cmd \
                and "run_finviz_momentum_scalp_scan.py" not in cmd \
                and "run_sec_form4_momentum_context.py" not in cmd \
                and "reset_stuck_agent_jobs.py" not in cmd \
                and "fix_strategy_registry_null_ids.py" not in cmd \
                and "remediate_proposal_trade_plans.py" not in cmd \
                and "hermes_scope_governor.py" not in cmd:
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

        # trade_closed output freshness (post-close on trading days)
        try:
            from zoneinfo import ZoneInfo
            now_et = datetime.now(ZoneInfo("America/New_York"))
            from market_session import is_trading_day
            trading = is_trading_day(now_et.date())
        except Exception:
            now_et = datetime.now()
            trading = now_et.weekday() < 5
        if trading and now_et.hour >= int(cfg.get("check_after_hour_et", 19)):
            age_d = _db_age_h("SELECT MAX(close_date)::timestamp FROM trade_closed")
            max_d = float(cfg.get("trade_closed_stale_days", 7))
            if age_d is not None and age_d > max_d * 24:
                out.append(_f("data_quality", "trade_closed_stale", "warning",
                              f"trade_closed newest close {age_d:.0f}h old (>{max_d}d) — "
                              f"journal ingest may be broken",
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
        out.append(_f("data_quality", "data_source_stale", sev, msg,
                      source=src, last_error=(r.get("last_error") or "")[:120]))
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
        proc = subprocess.run(["systemctl", "--failed", "--plain", "--no-legend", "--no-pager"],
                              capture_output=True, text=True, timeout=10)
        for line in (proc.stdout or "").splitlines():
            unit = (line.split() or [""])[0]
            if unit.startswith(prefixes):
                out.append(_f("execution_health", "systemd_unit_failed", "warning",
                              f"systemd unit {unit} is in failed state — scheduled runs may be "
                              f"missed; operator: sudo systemctl reset-failed {unit} "
                              f"(then check why it died: journalctl -u {unit})", unit=unit))
    except Exception:
        pass
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
    return out


COLLECTORS = [
    collect_data_quality,
    collect_trade_in_view_health,
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
    collect_infra_optimization_health,
    collect_proposal_integrity,
    collect_options_desk_health,
    collect_pullback_macd_screener,
    collect_proposal_oversight_load,
    collect_data_source_health,
    collect_failed_systemd_units,
    collect_db_connection_health,
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
