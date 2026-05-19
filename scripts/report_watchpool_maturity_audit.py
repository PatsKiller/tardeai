#!/usr/bin/env python3
"""report_watchpool_maturity_audit.py — Audit watchpool/incubator candidate maturity.

Read-only. No alerts sent. No trades. No orders.

Usage:
    .venv/bin/python scripts/report_watchpool_maturity_audit.py --verbose
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
    p = argparse.ArgumentParser(description="Watchpool maturity audit (read-only)")
    p.add_argument("--since-days", type=int, default=14)
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    from watchpool_maturity_policy import classify_watchpool_maturity, determine_watchpool_alert_type

    # Get watchpool + incubator candidates
    candidates = _db_query("""
        SELECT symbol, strategy_id, latest_score as score, status, days_active,
               catalyst, catalyst_verified, rvol_latest as rvol, source_first_seen
        FROM incubator_universe
        WHERE status = 'ACTIVE' AND latest_score >= 30
        ORDER BY latest_score DESC
        LIMIT %s
    """, [args.limit]) or []

    # Also get watchpool
    wp = _db_query("""
        SELECT symbol, strategy_id, current_status, evaluation_count,
               entered_at, expires_at, entry_snapshot
        FROM strategy_watchpool WHERE current_status = 'ACTIVE'
    """) or []

    wp_symbols = {r["symbol"] for r in wp}

    results = []
    by_state = {}
    alerts_required = 0

    for c in candidates:
        m = classify_watchpool_maturity(c)
        alert_type = determine_watchpool_alert_type(c)
        state = m["maturity_state"]
        by_state[state] = by_state.get(state, 0) + 1
        if alert_type != "NO_ACTION":
            alerts_required += 1

        results.append({
            "symbol": c["symbol"], "strategy_id": c.get("strategy_id"),
            "score": c.get("score"), "age_days": m["age_days"],
            "ttl_remaining": m["ttl_remaining"],
            "maturity_state": state, "alert_type": alert_type,
            "in_watchpool": c["symbol"] in wp_symbols,
            "has_catalyst": m["has_catalyst"], "has_quote": m["has_quote"],
            "has_technical": m["has_technical"],
            "human_review_only": True,
        })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidates_reviewed": len(results),
        "by_state": by_state,
        "alerts_required": alerts_required,
        "watchpool_count": len(wp),
        "results": results[:100],
    }

    if args.verbose:
        print(f"Watchpool Maturity Audit — {len(results)} candidates, {alerts_required} alerts required")
        for state, count in sorted(by_state.items()):
            print(f"  {state}: {count}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Watchpool Maturity Audit\n",
              f"Candidates: {len(results)} | Alerts required: {alerts_required}\n",
              "| State | Count |", "|-------|-------|"]
        for s, c in sorted(by_state.items()):
            md.append(f"| {s} | {c} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
