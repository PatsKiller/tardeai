#!/usr/bin/env python3
"""nightly_integrity_sweep.py — extends the journal integrity-warning pattern system-wide.

Detects the silent-corruption classes found in the 2026-06-11 reviews before they accumulate:
  scans:      forward rows missing sector / screener_label (post-fix writes must carry both)
  proposals:  stuck PENDING >72h; trades whose proposal shows a non-executed terminal status
  watchlist:  >1 visible row per symbol (the NVDA class)
  trades:     open paper rows with broker fill but stale 'pending' status (the ELVN class)
  hermes:     research_backlog rows above the daily cap; NULL-symbol research (non-backlog)
  backtest:   pit/replay rows lacking execution_assumptions provenance
Read-only checks + Telegram on findings. Cron: 02:45 daily.

  .venv/bin/python scripts/nightly_integrity_sweep.py [--telegram]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

CHECKS = [
    ("scans_missing_sector_fwd",
     "SELECT count(*) FROM trade_ai_scans WHERE scanned_at > NOW()-INTERVAL '24 hours' AND COALESCE(sector,'')='' AND source='screener'"),
    ("scans_missing_screener_label_fwd",
     "SELECT count(*) FROM trade_ai_scans WHERE scanned_at > NOW()-INTERVAL '24 hours' AND screener_label IS NULL AND source='screener' AND run_type='full'"),
    ("proposals_stuck_pending_72h",
     "SELECT count(*) FROM paper_trade_proposals WHERE status='PENDING' AND created_at < NOW()-INTERVAL '72 hours'"),
    ("trades_with_nonexec_proposal_status",
     """SELECT count(*) FROM paper_trades t JOIN paper_trade_proposals p ON p.id = COALESCE(t.proposal_id, t.source_proposal_id)
        WHERE t.created_at > NOW()-INTERVAL '7 days' AND p.status IN ('REJECTED','RISK_BLOCKED')"""),
    ("watchlist_visible_dupes",
     "SELECT count(*) FROM (SELECT symbol FROM watchlist_items WHERE status<>'removed' GROUP BY symbol HAVING count(*)>1) z"),
    ("paper_pending_but_filled",
     "SELECT count(*) FROM paper_trades WHERE status='pending' AND broker_status='filled' AND created_at < NOW()-INTERVAL '1 hour'"),
    ("hermes_backlog_over_cap_today",
     "SELECT GREATEST(count(*)-5,0) FROM hermes_research_intelligence WHERE research_type='research_backlog' AND created_at::date=CURRENT_DATE AND status<>'archived'"),
    ("hermes_null_symbol_research_fwd",
     "SELECT count(*) FROM hermes_research_intelligence WHERE created_at > NOW()-INTERVAL '24 hours' AND symbol IS NULL AND research_type NOT IN ('research_backlog','topic_research','source_discovery_followup')"),
    ("pit_rows_missing_provenance",
     "SELECT count(*) FROM strategy_backtest_trades t JOIN strategy_backtest_runs r ON r.run_id=t.run_id WHERE r.run_type='pit_simulated' AND t.execution_assumptions IS NULL"),
]


def run(telegram=False):
    from db_adapter import _get_conn
    cur = _get_conn().cursor()
    findings, report = [], []
    for name, q in CHECKS:
        try:
            cur.execute(q)
            n = cur.fetchone()[0] or 0
            report.append({"check": name, "count": n, "status": "ok" if n == 0 else "FLAG"})
            if n > 0:
                findings.append(f"🟠 {name}: {n}")
        except Exception as e:
            report.append({"check": name, "status": "check-error", "error": str(e)[:80]})
    out = {"status": "FLAGS" if findings else "ok", "findings": findings, "checks": report}
    print(json.dumps(out, indent=2))
    if findings and telegram:
        try:
            from telegram_alert import send_telegram
            send_telegram("🧹 NIGHTLY INTEGRITY SWEEP\n" + "\n".join(findings[:8]))
        except Exception:
            pass
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--telegram", action="store_true")
    run(ap.parse_args().telegram)
