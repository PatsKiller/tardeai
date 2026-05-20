#!/usr/bin/env python3
"""report_attr1_data_availability.py — Audit data availability for attribution computation.

Read-only. No trades. No orders.
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))
from dotenv import load_dotenv
load_dotenv(PROJ / ".env")

STATE_DIR = PROJ / "data" / "portfolios" / "state"
BENCHMARK_SYMS = ["SPY", "ITA", "AGG"]


def main():
    p = argparse.ArgumentParser(description="Attribution data availability audit (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor() if conn else None

    report = {"generated_at": datetime.now(timezone.utc).isoformat()}

    # 1. Attribution JSON file
    attr_path = STATE_DIR / "performance_attribution.json"
    report["attribution_file_exists"] = attr_path.exists()
    attr = {}
    if attr_path.exists():
        try:
            attr = json.loads(attr_path.read_text())
        except Exception:
            pass
    report["attribution_has_data"] = attr.get("has_data", False)
    report["alpha"] = attr.get("alpha_annualized")
    report["port_cagr"] = attr.get("port_cagr")
    report["bench_cagr"] = attr.get("bench_cagr")
    report["last_updated"] = attr.get("last_updated")

    # 2. Price cache benchmark presence
    cache_path = STATE_DIR / "price_cache.json"
    report["price_cache_exists"] = cache_path.exists()
    benchmark_status = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
            for sym in BENCHMARK_SYMS:
                prices = cache.get(sym, {})
                if prices:
                    dates = sorted(prices.keys())
                    benchmark_status[sym] = {"days": len(prices), "first": dates[0], "last": dates[-1]}
                else:
                    benchmark_status[sym] = None
        except Exception:
            pass
    report["benchmark_prices"] = benchmark_status

    # 3. Holdings history
    report["holdings_file_exists"] = (STATE_DIR / "holdings.json").exists()
    report["portfolio_snapshots_exist"] = (STATE_DIR / "portfolio_snapshots.json").exists()

    # 4. DB tables
    db_tables = {}
    if cur:
        for t in ["strategy_performance_snapshots", "performance_daily", "paper_trades",
                   "paper_performance_governance", "agent_performance_history"]:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                db_tables[t] = cur.fetchone()[0]
            except Exception:
                db_tables[t] = None
                conn.rollback()
        # Check for dedicated attribution tables
        cur.execute("""SELECT table_name FROM information_schema.tables
            WHERE table_schema='public' AND (table_name ILIKE '%attribution%' OR table_name ILIKE '%benchmark%')""")
        report["dedicated_attribution_tables"] = [r[0] for r in cur.fetchall()]
    report["db_tables"] = db_tables

    # 5. Closed paper trades
    closed_count = 0
    if cur:
        try:
            cur.execute("SELECT COUNT(*) FROM paper_trades WHERE status='closed'")
            closed_count = cur.fetchone()[0]
        except Exception:
            conn.rollback()
    report["closed_paper_trades"] = closed_count

    if conn:
        conn.close()

    # 6. N/A field analysis
    na_fields = []
    for field in ["alpha_annualized", "bench_cagr", "port_cagr", "port_sharpe",
                   "bench_sharpe", "port_sortino", "bench_sortino", "port_maxdd", "bench_maxdd"]:
        val = attr.get(field)
        if val is None:
            reason = "benchmark prices missing" if "bench" in field and not all(benchmark_status.get(s) for s in BENCHMARK_SYMS) else \
                     "insufficient portfolio history" if "port" in field else \
                     "requires both portfolio and benchmark data"
            na_fields.append({"field": field, "value": val, "reason": reason})
    report["na_fields"] = na_fields
    report["all_fields_populated"] = len(na_fields) == 0

    # Summary
    if report["all_fields_populated"]:
        report["status"] = "healthy"
        report["recommended_action"] = "none"
    elif not all(benchmark_status.get(s) for s in BENCHMARK_SYMS):
        report["status"] = "benchmark_missing"
        report["recommended_action"] = "run attribution pipeline to fetch benchmark prices"
    else:
        report["status"] = "partial"
        report["recommended_action"] = "investigate missing fields"

    if args.verbose:
        print(f"Attribution Data Availability: {report['status'].upper()}")
        print(f"  Attribution file: {'exists' if report['attribution_file_exists'] else 'MISSING'}")
        print(f"  Alpha: {report['alpha']}")
        print(f"  Port CAGR: {report['port_cagr']} | Bench CAGR: {report['bench_cagr']}")
        for sym in BENCHMARK_SYMS:
            s = benchmark_status.get(sym)
            print(f"  {sym}: {s['days']} days ({s['first']} → {s['last']})" if s else f"  {sym}: MISSING")
        print(f"  Closed paper trades: {closed_count}")
        print(f"  N/A fields: {len(na_fields)}")
        if na_fields:
            for f in na_fields:
                print(f"    {f['field']}: {f['reason']}")
        print(f"  Action: {report['recommended_action']}")

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        md = [f"# Attribution Data Availability: {report['status'].upper()}\n"]
        md.append("| Source | Status |")
        md.append("|--------|--------|")
        md.append(f"| attribution file | {'exists' if report['attribution_file_exists'] else 'MISSING'} |")
        md.append(f"| alpha | {report['alpha']} |")
        md.append(f"| port_cagr | {report['port_cagr']} |")
        md.append(f"| bench_cagr | {report['bench_cagr']} |")
        for sym in BENCHMARK_SYMS:
            s = benchmark_status.get(sym)
            md.append(f"| {sym} cache | {s['days']} days" if s else f"| {sym} cache | MISSING |")
        md.append(f"| closed trades | {closed_count} |")
        md.append(f"| N/A fields | {len(na_fields)} |")
        if na_fields:
            md.append("\n## N/A Fields")
            for f in na_fields:
                md.append(f"- `{f['field']}`: {f['reason']}")
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
