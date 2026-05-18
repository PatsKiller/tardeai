#!/usr/bin/env python3
"""report_quote_freshness_provider_audit.py — Quote freshness and provider audit.

Read-only. No broker calls. No trade creation.

Usage:
    .venv/bin/python scripts/report_quote_freshness_provider_audit.py --verbose
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
    p = argparse.ArgumentParser(description="Quote freshness provider audit (read-only)")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.since_days)
    try:
        from proposal_quote_trust import classify_quote_trust
    except ImportError:
        classify_quote_trust = None

    proposals = _db_query("""
        SELECT ptp.id, ptp.symbol, ptp.strategy_id, ptp.status,
               per.quote_provider, per.quote_age_seconds, per.quote_is_delayed,
               per.quote_execution_eligible, per.bid, per.ask, per.spread_pct,
               per.readiness_state
        FROM paper_trade_proposals ptp
        LEFT JOIN LATERAL (
            SELECT * FROM proposal_execution_readiness
            WHERE proposal_id = ptp.id ORDER BY created_at DESC LIMIT 1
        ) per ON true
        WHERE ptp.created_at > %s
        ORDER BY ptp.created_at DESC
    """, [since]) or []

    results = []
    by_provider = {}
    display_only_count = 0
    stale_count = 0
    exec_eligible_count = 0
    no_check_count = 0

    for pr in proposals:
        er = {k: v for k, v in pr.items() if k.startswith("quote_") or k in ("bid", "ask", "spread_pct", "readiness_state")}
        qt = classify_quote_trust({"execution_readiness": er, "strategy_timeframe_class": "MEDIUM_SWING"}) if classify_quote_trust else {"quote_trust_status": "UNKNOWN", "quote_source": "unknown"}

        source = qt.get("quote_source", "unknown")
        by_provider[source] = by_provider.get(source, 0) + 1

        status = qt.get("quote_trust_status", "UNKNOWN")
        if status == "DISPLAY_ONLY": display_only_count += 1
        elif status == "STALE": stale_count += 1
        elif status == "EXECUTION_ELIGIBLE": exec_eligible_count += 1
        elif status == "NOT_CHECKED": no_check_count += 1

        results.append({
            "proposal_id": pr["id"], "symbol": pr["symbol"],
            "strategy_id": pr["strategy_id"], "quote_source": source,
            "quote_trust_status": status,
            "execution_eligible": qt.get("is_execution_eligible", False),
            "display_only_reason": qt.get("display_only_reason"),
        })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_proposals": len(proposals),
        "by_provider": by_provider,
        "execution_eligible": exec_eligible_count,
        "display_only": display_only_count,
        "stale": stale_count,
        "not_checked": no_check_count,
        "proposals": results[:50],
    }

    if args.verbose:
        print(f"Quote Freshness Audit — {len(proposals)} proposals")
        print(f"  Exec eligible: {exec_eligible_count}, Display-only: {display_only_count}, Stale: {stale_count}, Not checked: {no_check_count}")
        for src, cnt in sorted(by_provider.items(), key=lambda x: -x[1]):
            print(f"  {src}: {cnt}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Quote Freshness Provider Audit\n",
              f"Total: {len(proposals)} | Exec: {exec_eligible_count} | Display-only: {display_only_count} | Stale: {stale_count} | Not checked: {no_check_count}\n",
              "| Provider | Count |", "|----------|-------|"]
        for src, cnt in sorted(by_provider.items(), key=lambda x: -x[1]):
            md.append(f"| {src} | {cnt} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
