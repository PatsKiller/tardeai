#!/usr/bin/env python3
"""report_finviz_screener_quality.py — Finviz screener quality audit.

Read-only. No mutations. No auto-optimization. No secrets printed.

Usage:
    .venv/bin/python scripts/report_finviz_screener_quality.py --verbose --since-days 30
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
        if not conn:
            return [] if fetch == "all" else None
        cur = conn.cursor()
        cur.execute(sql, params or [])
        if fetch == "one":
            row = cur.fetchone()
            if row:
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, row))
            return None
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return [] if fetch == "all" else None


def main():
    p = argparse.ArgumentParser(description="Finviz screener quality audit (read-only)")
    p.add_argument("--since-days", type=int, default=30)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.since_days)

    # Get screener configs
    configs = _db_query("""
        SELECT id, display_name, strategy_class, enabled, last_run_at, last_result_count
        FROM screener_config ORDER BY display_name
    """) or []

    # Get run health per screener
    run_health = _db_query("""
        SELECT source, count(*) as run_count,
               avg(symbols_scanned) as avg_symbols,
               sum(CASE WHEN symbols_scanned = 0 THEN 1 ELSE 0 END) as zero_runs,
               sum(CASE WHEN symbols_scanned < 5 THEN 1 ELSE 0 END) as underfilled_runs,
               max(created_at) as last_run
        FROM screener_run_health
        WHERE created_at > %s
        GROUP BY source
        ORDER BY source
    """, [since]) or []
    rh_map = {r["source"]: r for r in run_health}

    # Get proposal counts per source screener
    proposal_counts = _db_query("""
        SELECT screener_name, count(*) as proposal_count
        FROM paper_trade_proposals
        WHERE created_at > %s AND screener_name IS NOT NULL
        GROUP BY screener_name
    """, [since]) or []
    pc_map = {r["screener_name"]: r["proposal_count"] for r in proposal_counts}

    # Get trade counts per source
    trade_counts = _db_query("""
        SELECT pt.strategy_id, count(*) as trade_count,
               sum(CASE WHEN pt.pnl > 0 THEN 1 ELSE 0 END) as wins,
               sum(CASE WHEN pt.pnl <= 0 THEN 1 ELSE 0 END) as losses
        FROM paper_trades pt
        WHERE pt.created_at > %s AND pt.lifecycle_state = 'closed'
        GROUP BY pt.strategy_id
    """, [since]) or []
    tc_map = {r["strategy_id"]: r for r in trade_counts}

    # Incubator counts per screener source
    incubator_counts = _db_query("""
        SELECT source_first_seen, count(*) as candidate_count
        FROM incubator_universe
        WHERE first_seen_at > %s AND source_first_seen IS NOT NULL
        GROUP BY source_first_seen
    """, [since]) or []
    ic_map = {r["source_first_seen"]: r["candidate_count"] for r in incubator_counts}

    screeners = []
    for cfg in configs:
        name = cfg["display_name"]
        strategy = cfg.get("strategy_class") or ""
        rh = rh_map.get(name, {})
        run_count = int(rh.get("run_count", 0) or 0)
        avg_sym = float(rh.get("avg_symbols", 0) or 0)
        zero_runs = int(rh.get("zero_runs", 0) or 0)
        underfilled = int(rh.get("underfilled_runs", 0) or 0)
        candidates = ic_map.get(name, 0)
        proposals = pc_map.get(name, 0)
        tc = tc_map.get(strategy, {})
        trades = int(tc.get("trade_count", 0) or 0)
        wins = int(tc.get("wins", 0) or 0)

        # Quality classification
        if run_count == 0:
            quality = "insufficient_data"
        elif zero_runs > run_count * 0.5:
            quality = "broken"
        elif avg_sym < 3:
            quality = "too_narrow"
        elif avg_sym > 200:
            quality = "too_broad"
        elif underfilled > run_count * 0.3:
            quality = "underfilled"
        elif proposals > 0 and candidates > 0:
            quality = "healthy"
        else:
            quality = "insufficient_data"

        # Conversion rate
        conversion = round(proposals / candidates * 100, 1) if candidates > 0 else 0

        screeners.append({
            "screener_name": name,
            "strategy_class": strategy,
            "enabled": cfg.get("enabled", False),
            "run_count": run_count,
            "avg_symbols_per_run": round(avg_sym, 1),
            "zero_result_runs": zero_runs,
            "underfilled_runs": underfilled,
            "candidate_count": candidates,
            "proposal_count": proposals,
            "proposal_conversion_pct": conversion,
            "paper_trade_count": trades,
            "winning_trades": wins,
            "losing_trades": int(tc.get("losses", 0) or 0),
            "quality_status": quality,
            "recommended_action": {
                "healthy": None,
                "too_narrow": "Review filters — may be overly restrictive (human_review_only)",
                "too_broad": "Review filters — too many low-quality results (human_review_only)",
                "underfilled": "Check if Finviz URL is still valid (human_review_only)",
                "broken": "Screener returning zero results — check URL and filters (human_review_only)",
                "noisy": "Review quality gates — too many rejects (human_review_only)",
                "insufficient_data": "Needs more run history to evaluate",
            }.get(quality),
        })

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "since_days": args.since_days,
        "total_screeners": len(configs),
        "screeners": screeners,
    }

    if args.verbose:
        print(f"Finviz Screener Quality Audit — {len(configs)} screeners (last {args.since_days}d)")
        for s in screeners:
            print(f"\n  {s['screener_name']} [{s['strategy_class']}] — {s['quality_status']}")
            print(f"    Runs: {s['run_count']}, Avg symbols: {s['avg_symbols_per_run']}, Zero: {s['zero_result_runs']}")
            print(f"    Candidates: {s['candidate_count']}, Proposals: {s['proposal_count']}, Conversion: {s['proposal_conversion_pct']}%")
            print(f"    Trades: {s['paper_trade_count']} (W:{s['winning_trades']} L:{s['losing_trades']})")
            if s["recommended_action"]:
                print(f"    Action: {s['recommended_action']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = ["# Finviz Screener Quality Audit", f"\nPeriod: last {args.since_days} days\n"]
        md.append("| Screener | Strategy | Runs | Avg Sym | Candidates | Proposals | Conv% | Trades | Quality |")
        md.append("|----------|----------|------|---------|-----------|-----------|-------|--------|---------|")
        for s in screeners:
            md.append(f"| {s['screener_name']} | {s['strategy_class']} | {s['run_count']} | {s['avg_symbols_per_run']} | {s['candidate_count']} | {s['proposal_count']} | {s['proposal_conversion_pct']}% | {s['paper_trade_count']} | {s['quality_status']} |")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
