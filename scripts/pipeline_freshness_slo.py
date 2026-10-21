#!/usr/bin/env python3
"""pipeline_freshness_slo.py — per-source freshness + row-count SLOs (silent-degradation killer).

Today's bug class: pipelines that keep "succeeding" while silently writing nothing useful (perf-context
zeroed nightly, scalp injection dead every cycle, stale-cache fallbacks, GO collapse during cookie/429
storms). This job compares each source's RECENT write volume against its OWN trailing baseline and alerts
on deviation — no hardcoded thresholds; the baseline IS the expectation.

Checks (source → table, recency window, baseline window):
  trade_ai_scans        — scans written in last 6h vs same-hours trailing-7d median
  GO production         — GOs last 24h vs trailing-14d daily median (collapse detector)
  hermes_research       — non-backlog rows last 24h vs trailing-7d
  news_articles         — rows last 12h vs trailing-7d
  paper proposals       — last 48h vs trailing-14d
  schwab_stream_book    — rows last 2h during market hours (expects >0 when open; PRODUCER_UNSCHEDULED when the
                          operator has the stream daemon's cron line commented out or its kill switch set)
  hermes_score_history  — snapshots last 2h (the 30-min scorer cron)

Alert policy: WARN at <40% of baseline, CRITICAL at 0 when baseline >0. Telegram + stdout. Read-only.
Cron: every 2h market days.

  .venv/bin/python scripts/pipeline_freshness_slo.py [--telegram]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

CHECKS = [
    ("trade_ai_scans_6h",
     "SELECT count(*) FROM trade_ai_scans WHERE scanned_at > NOW()-INTERVAL '6 hours'",
     "SELECT COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY c),0) FROM (SELECT count(*) c FROM trade_ai_scans WHERE scanned_at > NOW()-INTERVAL '7 days' GROUP BY date_trunc('day', scanned_at)) z",
     0.25/4),   # 6h ≈ quarter day vs daily median; factor applied to baseline
    ("go_decisions_24h",
     "SELECT count(*) FROM trade_ai_scans WHERE decision='GO' AND scanned_at > NOW()-INTERVAL '24 hours'",
     "SELECT COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY c),0) FROM (SELECT count(*) c FROM trade_ai_scans WHERE decision='GO' AND scanned_at > NOW()-INTERVAL '14 days' GROUP BY date_trunc('day', scanned_at)) z",
     1.0),
    ("hermes_research_24h",
     "SELECT count(*) FROM hermes_research_intelligence WHERE created_at > NOW()-INTERVAL '24 hours' AND research_type <> 'research_backlog'",
     "SELECT COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY c),0) FROM (SELECT count(*) c FROM hermes_research_intelligence WHERE created_at > NOW()-INTERVAL '7 days' AND research_type <> 'research_backlog' GROUP BY date_trunc('day', created_at)) z",
     1.0),
    ("news_articles_12h",
     "SELECT count(*) FROM news_articles WHERE created_at > NOW()-INTERVAL '12 hours'",
     "SELECT COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY c),0) FROM (SELECT count(*) c FROM news_articles WHERE created_at > NOW()-INTERVAL '7 days' GROUP BY date_trunc('day', created_at)) z",
     0.5),
    ("proposals_48h",
     "SELECT count(*) FROM paper_trade_proposals WHERE created_at > NOW()-INTERVAL '48 hours'",
     "SELECT COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY c),0)*2 FROM (SELECT count(*) c FROM paper_trade_proposals WHERE created_at > NOW()-INTERVAL '14 days' GROUP BY date_trunc('day', created_at)) z",
     1.0),
    # entry planner drain (weekday 17:35/17:45 crons). 72h window keeps the weekend green off the
    # Friday run; a crashed drain (2026-07-02 planned 2, 2026-07-03 planned 13 vs ~300 median)
    # trips this within a day instead of surfacing as a stale card 5 days later.
    ("entry_plans_72h",
     "SELECT count(*) FROM watchlist_entry_plans WHERE created_at > NOW()-INTERVAL '72 hours'",
     "SELECT COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY c),0) FROM (SELECT count(*) c FROM watchlist_entry_plans WHERE created_at > NOW()-INTERVAL '14 days' GROUP BY date_trunc('day', created_at)) z",
     0.25),
    # daily 15:45 IV snapshot — silently wrote 0 rows for a week before the 2026-07-05 fix; this
    # catches a recurrence (72h window spans weekends off the Friday capture)
    ("options_iv_history_72h",
     "SELECT count(*) FROM options_iv_history WHERE captured_at > NOW()-INTERVAL '72 hours'",
     "SELECT COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY c),0) FROM (SELECT count(*) c FROM options_iv_history WHERE captured_at > NOW()-INTERVAL '14 days' GROUP BY date_trunc('day', captured_at)) z",
     0.25),
    ("hermes_score_snapshots_2h",
     "SELECT count(*) FROM hermes_score_history WHERE scored_at > NOW()-INTERVAL '2 hours'",
     "SELECT COALESCE(percentile_cont(0.5) WITHIN GROUP (ORDER BY c),0)/12 FROM (SELECT count(*) c FROM hermes_score_history WHERE scored_at > NOW()-INTERVAL '7 days' GROUP BY date_trunc('day', scored_at)) z",
     1.0),
]

MARKET_HOURS_CHECKS = [
    ("schwab_stream_book_2h",
     "SELECT count(*) FROM schwab_stream_book WHERE captured_at > NOW()-INTERVAL '2 hours'",
     "SELECT 1", 1.0),   # baseline 1: any capture during market hours satisfies; 0 alerts
    # options desk monitor runs every 10 min 10:00-15:59 — any chain capture in the last 2h is
    # healthy; silence during market hours means the desk is down (2026-07-06 coverage audit:
    # the options pipeline had zero freshness monitoring)
    ("options_chain_snapshots_2h",
     "SELECT count(*) FROM options_chain_snapshots WHERE captured_at > NOW()-INTERVAL '2 hours'",
     "SELECT 1", 1.0),
]


MARKET_OPEN, MARKET_CLOSED, MARKET_UNKNOWN = "OPEN", "CLOSED", "UNKNOWN"
# Market-hours checks whose producer reads Schwab: while the operator has Schwab paused they are known-blind,
# reported as SCHWAB_PAUSED (the stop-health P1 already pages the pause) rather than a CRITICAL every tick.
SCHWAB_FED_CHECKS = {"schwab_stream_book_2h", "options_chain_snapshots_2h"}


# Market-hours checks whose producer is a cron-scheduled daemon. When the operator has taken that producer OFF
# the schedule (its crontab line commented out — e.g. "# PAUSED 2026-10-14 schwab-app-deactivated" for the
# stream daemon, still commented after Schwab reads were re-enabled 2026-10-16) or set its documented kill
# switch, zero rows is the EXPECTED result, not an outage: report PRODUCER_UNSCHEDULED / PRODUCER_KILL_SWITCH
# (visible in the JSON, no red page). Unreadable crontab → fall through to the normal count check (conservative).
SCHEDULED_PRODUCERS = {
    "schwab_stream_book_2h": {"match": "scripts/schwab_stream_daemon.py",
                              "kill_file": ROOT / "data" / "state" / "STREAM_DISABLED"},
}


def _active_cron_lines(text):
    return [ln for ln in (text or "").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]


def _producer_state(name, crontab_text=None):
    """None = producer scheduled (or unknown) → run the check; else (status, note) for an intentionally-off producer."""
    spec = SCHEDULED_PRODUCERS.get(name)
    if not spec:
        return None
    kill = spec.get("kill_file")
    if kill is not None and Path(kill).exists():
        return ("PRODUCER_KILL_SWITCH", f"kill switch present: {kill}")
    if crontab_text is None:
        return None
    if any(spec["match"] in ln for ln in _active_cron_lines(crontab_text)):
        return None
    return ("PRODUCER_UNSCHEDULED",
            f"no active crontab line runs {spec['match']} (commented/paused by operator) — silence expected; "
            "re-enabling the producer is an operator decision")


def _read_crontab_text():
    try:
        from lib.crontab_snapshot import read_crontab
        cr = read_crontab()
        return cr.text if cr.ok else None
    except Exception:  # noqa: BLE001
        return None


def _market_state():
    """OPEN / CLOSED from Schwab market hours; UNKNOWN when Schwab errors, answers without a flag, or is paused.

    Before (incident 2026-10-14): any Schwab error returned False = "closed", which silently suppressed every
    market-hours SLO exactly when a Schwab outage made them matter."""
    try:
        from lib import schwab_access_mode as _sam
        if not _sam.reads_allowed():
            _sam.log_skip("pipeline_freshness_slo", printer=lambda m: print(m, file=sys.stderr))
            return MARKET_UNKNOWN
    except Exception:  # noqa: BLE001
        pass
    try:
        import schwab_transport
        hours = schwab_transport.get_market_hours()
        eq = ((hours or {}).get("markets") or {}).get("equity") or {} if isinstance(hours, dict) else {}
        flag = eq.get("is_open", eq.get("isOpen"))
        if flag is None:
            return MARKET_UNKNOWN
        return MARKET_OPEN if flag else MARKET_CLOSED
    except Exception:
        return MARKET_UNKNOWN


def _clock_session_open(now=None):
    """The regular equity session by the ET clock (weekday 09:30-16:00) — the conservative UNKNOWN fallback."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = now or datetime.now(ZoneInfo("America/New_York"))
    mins = now.hour * 60 + now.minute
    return now.weekday() < 5 and 9 * 60 + 30 <= mins <= 16 * 60


def _market_open():
    """Back-compat boolean: OPEN, or UNKNOWN inside the clock session (conservative — run the checks)."""
    state = _market_state()
    return state == MARKET_OPEN or (state == MARKET_UNKNOWN and _clock_session_open())


def run(telegram=False):
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    state = _market_state()
    include_market = state == MARKET_OPEN or (state == MARKET_UNKNOWN and _clock_session_open())
    checks = list(CHECKS) + (MARKET_HOURS_CHECKS if include_market else [])
    try:
        from lib import schwab_access_mode as _sam
        schwab_paused = _sam.is_paused()
    except Exception:  # noqa: BLE001
        schwab_paused = False
    crontab_text = _read_crontab_text() if include_market else None
    findings, report = [], []
    for name, recent_q, base_q, factor in checks:
        if schwab_paused and name in SCHWAB_FED_CHECKS:
            report.append({"check": name, "status": "SCHWAB_PAUSED",
                           "note": "producer reads Schwab; operator pause (config/schwab_access_mode.yaml)"})
            continue
        producer = _producer_state(name, crontab_text)
        if producer:
            report.append({"check": name, "status": producer[0], "note": producer[1]})
            continue
        try:
            cur.execute(recent_q); recent = cur.fetchone()[0] or 0
            cur.execute(base_q); base = float(cur.fetchone()[0] or 0) * factor
            if name in {"go_decisions_24h", "proposals_48h"}:
                # These are business outcomes, not producer heartbeats. Zero can
                # be the correct decision even when every scheduled run succeeds.
                status = "OUTCOME_OBSERVED; PRODUCER_LIVENESS_NOT_MEASURED"
            elif base <= 0:
                status = "no-baseline"
            elif recent == 0:
                status = "CRITICAL"
                findings.append(f"🔴 {name}: 0 recent rows (baseline ≈{base:.0f}) — inspect scheduled run receipts and source output")
            elif recent < 0.4 * base:
                status = "WARN"
                findings.append(f"🟠 {name}: {recent} rows vs baseline ≈{base:.0f} (<40%)")
            else:
                status = "ok"
            report.append({"check": name, "recent": recent, "baseline": round(base, 1), "status": status})
        except Exception as e:
            report.append({"check": name, "status": "check-error", "error": str(e)[:80]})
    out = {"status": "ALERT" if findings else "ok", "findings": findings, "checks": report,
           "market_state": state, "market_checks_included": include_market}
    print(json.dumps(out, indent=2))
    if findings and telegram:
        try:
            from telegram_alert import send_telegram
            send_telegram("⚠️ PIPELINE FRESHNESS SLO\n" + "\n".join(findings[:6]),
                          priority="P2", producer="pipeline_freshness_slo")
        except Exception:
            pass
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true")
    run(ap.parse_args().telegram)
