#!/usr/bin/env python3
"""report_attr1_benchmark_alpha.py — Report attribution/benchmark data health.

Read-only. No trades. No orders.

ATTR-1 correction: the original diagnosis said "no benchmark tables exist."
In fact, attribution uses a JSON file (performance_attribution.json), not DB tables.
The root cause was benchmark prices (SPY/ITA/AGG) missing from price_cache.json
due to a yfinance MultiIndex column change that silently failed the fetch.
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


def run_report(verbose=False):
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "attribution_file_exists": False,
        "has_data": False,
        "port_cagr": None,
        "bench_cagr": None,
        "alpha": None,
        "port_sharpe": None,
        "bench_sharpe": None,
        "benchmark_prices_cached": {},
        "price_cache_exists": False,
        "root_cause": None,
        "recommended_fix": None,
    }

    # Check attribution JSON
    attr_path = STATE_DIR / "performance_attribution.json"
    if attr_path.exists():
        report["attribution_file_exists"] = True
        try:
            data = json.loads(attr_path.read_text())
            report["has_data"] = data.get("has_data", False)
            report["port_cagr"] = data.get("port_cagr")
            report["bench_cagr"] = data.get("bench_cagr")
            report["alpha"] = data.get("alpha_annualized")
            report["port_sharpe"] = data.get("port_sharpe")
            report["bench_sharpe"] = data.get("bench_sharpe")
            report["last_updated"] = data.get("last_updated")
            report["snapshot_count"] = data.get("snapshot_count")
        except Exception:
            pass

    # Check price cache for benchmark symbols
    cache_path = STATE_DIR / "price_cache.json"
    report["price_cache_exists"] = cache_path.exists()
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
            for sym in BENCHMARK_SYMS:
                prices = cache.get(sym, {})
                if prices:
                    dates = sorted(prices.keys())
                    report["benchmark_prices_cached"][sym] = {
                        "days": len(prices),
                        "first": dates[0],
                        "last": dates[-1],
                    }
                else:
                    report["benchmark_prices_cached"][sym] = None
        except Exception:
            pass

    # Root cause
    if not report["attribution_file_exists"]:
        report["root_cause"] = "attribution file not generated"
        report["recommended_fix"] = "run portfolio_performance_attribution.py"
    elif report["bench_cagr"] is None:
        missing = [s for s in BENCHMARK_SYMS if not report["benchmark_prices_cached"].get(s)]
        if missing:
            report["root_cause"] = f"benchmark prices missing from cache: {missing}"
            report["recommended_fix"] = "run attribution pipeline to fetch benchmark prices"
        else:
            report["root_cause"] = "benchmark prices cached but CAGR computation failed"
            report["recommended_fix"] = "investigate attribution computation"
    elif report["alpha"] is None:
        report["root_cause"] = "alpha not computed (need both portfolio and benchmark CAGR)"
        report["recommended_fix"] = "ensure both CAGRs are available"
    else:
        report["root_cause"] = "none — attribution pipeline healthy"
        report["recommended_fix"] = "none"

    if verbose:
        print("=== Attribution Benchmark Report ===")
        print(f"  File exists: {report['attribution_file_exists']}")
        print(f"  Has data: {report['has_data']}")
        print(f"  Port CAGR: {report['port_cagr']}")
        print(f"  Bench CAGR: {report['bench_cagr']}")
        print(f"  Alpha: {report['alpha']}")
        print(f"  Port Sharpe: {report['port_sharpe']}")
        print(f"  Bench Sharpe: {report['bench_sharpe']}")
        for sym in BENCHMARK_SYMS:
            cached = report["benchmark_prices_cached"].get(sym)
            if cached:
                print(f"  {sym}: {cached['days']} days ({cached['first']} → {cached['last']})")
            else:
                print(f"  {sym}: MISSING from cache")
        print(f"  Root cause: {report['root_cause']}")
        print(f"  Fix: {report['recommended_fix']}")

    return report


def main():
    p = argparse.ArgumentParser(description="Attribution benchmark report (read-only)")
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    report = run_report(verbose=args.verbose)

    if args.output_json:
        Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        Path(args.output_md).parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Attribution Benchmark Report",
            f"Generated: {report['generated_at']}",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Port CAGR | {report['port_cagr']} |",
            f"| Bench CAGR | {report['bench_cagr']} |",
            f"| Alpha | {report['alpha']} |",
            f"| Port Sharpe | {report['port_sharpe']} |",
            f"| Bench Sharpe | {report['bench_sharpe']} |",
        ]
        for sym in BENCHMARK_SYMS:
            cached = report["benchmark_prices_cached"].get(sym)
            lines.append(f"| {sym} cache | {'yes' if cached else 'MISSING'} |")
        lines.append(f"\n## Root Cause\n{report['root_cause']}")
        lines.append(f"\n## Fix\n{report['recommended_fix']}")
        Path(args.output_md).write_text("\n".join(lines))


if __name__ == "__main__":
    main()
