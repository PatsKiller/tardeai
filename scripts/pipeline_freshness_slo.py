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
  schwab_stream_book    — rows last 2h during market hours (expects >0 when open)
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


def _market_open():
    try:
        import schwab_transport
        eq = (schwab_transport.get_market_hours().get("markets") or {}).get("equity") or {}
        return bool(eq.get("is_open"))
    except Exception:
        return False


def run(telegram=False):
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    checks = list(CHECKS) + (MARKET_HOURS_CHECKS if _market_open() else [])
    findings, report = [], []
    for name, recent_q, base_q, factor in checks:
        try:
            cur.execute(recent_q); recent = cur.fetchone()[0] or 0
            cur.execute(base_q); base = float(cur.fetchone()[0] or 0) * factor
            if base <= 0:
                status = "no-baseline"
            elif recent == 0:
                status = "CRITICAL"
                findings.append(f"🔴 {name}: 0 rows (baseline ≈{base:.0f}) — pipeline silently dead?")
            elif recent < 0.4 * base:
                status = "WARN"
                findings.append(f"🟠 {name}: {recent} rows vs baseline ≈{base:.0f} (<40%)")
            else:
                status = "ok"
            report.append({"check": name, "recent": recent, "baseline": round(base, 1), "status": status})
        except Exception as e:
            report.append({"check": name, "status": "check-error", "error": str(e)[:80]})
    out = {"status": "ALERT" if findings else "ok", "findings": findings, "checks": report}
    print(json.dumps(out, indent=2))
    if findings and telegram:
        try:
            from telegram_alert import send_telegram
            send_telegram("⚠️ PIPELINE FRESHNESS SLO\n" + "\n".join(findings[:6]))
        except Exception:
            pass
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true")
    run(ap.parse_args().telegram)
