#!/usr/bin/env python3
"""report_no_leads_root_cause.py — Explain why no actionable leads exist.

Read-only. No trades. No orders. No alerts sent.

Usage:
    .venv/bin/python scripts/report_no_leads_root_cause.py --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def _db_query(sql, params=None, fetch="all"):
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        if not conn: return [] if fetch == "all" else None
        cur = conn.cursor()
        cur.execute(sql, params or [])
        if fetch == "one":
            row = cur.fetchone()
            return dict(zip([d[0] for d in cur.description], row)) if row else None
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return [] if fetch == "all" else None


def main():
    p = argparse.ArgumentParser(description="No-leads root cause (read-only)")
    p.add_argument("--since-hours", type=int, default=24)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    since = datetime.now(timezone.utc) - timedelta(hours=args.since_hours)

    # Latest run
    run = _db_query("SELECT run_label, status, symbols_scanned, go_count, created_at FROM screener_run_health ORDER BY created_at DESC LIMIT 1", fetch="one") or {}

    # Counts
    pending = _db_query("SELECT count(*) as c FROM paper_trade_proposals WHERE status='PENDING'", fetch="one") or {}
    incubator = _db_query("SELECT count(*) as c FROM incubator_universe WHERE status='ACTIVE' AND latest_score>=38 AND promoted_to_proposal_at IS NULL", fetch="one") or {}
    watchpool = _db_query("SELECT count(*) as c FROM strategy_watchpool WHERE current_status='ACTIVE'", fetch="one") or {}
    signals = _db_query("SELECT count(*) as c FROM strategy_signals WHERE created_at > %s", [since], fetch="one") or {}

    # Top no-go reasons from scans
    no_go = _db_query("""
        SELECT decision, count(*) as c FROM trade_ai_scans
        WHERE scanned_at > %s AND decision != 'GO'
        GROUP BY decision ORDER BY c DESC LIMIT 5
    """, [since]) or []

    pending_c = int(pending.get("c", 0))
    incubator_c = int(incubator.get("c", 0))
    watchpool_c = int(watchpool.get("c", 0))
    go_c = int(run.get("go_count", 0))
    signal_c = int(signals.get("c", 0))

    # Classification
    if go_c > 0 and pending_c > 0:
        conclusion = "system_producing"
    elif go_c == 0 and incubator_c > 0:
        conclusion = "system_quiet_but_explained"
    elif go_c == 0 and incubator_c == 0:
        conclusion = "screener_gap_detected"
    elif pending_c == 0 and incubator_c > 0 and watchpool_c > 0:
        conclusion = "promoter_gap_detected"
    else:
        conclusion = "data_gap_detected"

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "latest_run": {k: str(v) for k, v in run.items()} if run else None,
        "pending_proposals": pending_c,
        "incubator_ready": incubator_c,
        "watchpool_active": watchpool_c,
        "signals_today": signal_c,
        "go_count": go_c,
        "no_go_reasons": [{k: v for k, v in r.items()} for r in no_go],
        "conclusion": conclusion,
        "explanation": {
            "system_producing": "System is producing proposals normally.",
            "system_quiet_but_explained": f"Screener scanned {run.get('symbols_scanned', '?')} symbols but 0 met GO criteria. {incubator_c} incubator candidates exist but none promoted. Watchpool has {watchpool_c} active candidates maturing.",
            "screener_gap_detected": "No GO candidates and no incubator candidates ready. Review screener filters.",
            "promoter_gap_detected": f"{incubator_c} incubator ready + {watchpool_c} watchpool active but 0 promoted to proposal. Check promoter eligibility gates.",
            "data_gap_detected": "Insufficient data to classify. Check pipeline health.",
        }.get(conclusion, "Review pipeline."),
    }

    if args.verbose:
        print(f"No-Leads Root Cause — {conclusion}")
        print(f"  Run: {run.get('run_label','?')} {run.get('status','?')} scanned={run.get('symbols_scanned','?')} GO={go_c}")
        print(f"  Pending: {pending_c}, Incubator: {incubator_c}, Watchpool: {watchpool_c}, Signals: {signal_c}")
        print(f"  Explanation: {report['explanation']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# No-Leads Root Cause\n", f"Conclusion: **{conclusion}**\n", report["explanation"]]
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
