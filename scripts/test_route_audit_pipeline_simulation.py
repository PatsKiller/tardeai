#!/usr/bin/env python3
"""test_route_audit_pipeline_simulation.py — Simulate route audit for a representative candidate.

Default: dry-run. No real proposals created. No DB writes.

Usage:
    .venv/bin/python scripts/test_route_audit_pipeline_simulation.py --dry-run --verbose
"""
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ / "scripts"))


def main():
    p = argparse.ArgumentParser(description="Route audit pipeline simulation (dry-run)")
    p.add_argument("--symbol", type=str, default="TEST")
    p.add_argument("--strategy-id", type=str, default="recovery_watch")
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--output-json", type=str)
    p.add_argument("--output-md", type=str)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    from proposal_route_audit_integration import ensure_route_audit_for_proposal

    candidate = {
        "symbol": args.symbol,
        "price": 10.0,
        "rvol": 5.0,
        "float_m": 15.0,
        "gap_pct": -3.0,
        "score": 45,
        "decision": "GO",
        "catalyst": "Test catalyst",
        "catalyst_verified": True,
        "sector": "Technology",
        "industry": "Software",
    }

    result = ensure_route_audit_for_proposal(
        conn=None,
        proposal_id=0,
        symbol=args.symbol,
        original_strategy_id=args.strategy_id,
        candidate_payload=candidate,
        source="simulation",
        dry_run=True,
    )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "symbol": args.symbol,
        "strategy_id": args.strategy_id,
        "mode": "dry_run",
        "result": result,
    }

    if args.verbose:
        print(f"Route Audit Simulation — {args.symbol} ({args.strategy_id})")
        print(f"  Evaluated: {result['evaluated_strategy_count']}")
        print(f"  Passed: {result['passed_strategy_count']}")
        print(f"  Top match: {result['top_match_strategy_id']}")
        print(f"  Mismatch: {result['mismatch']}")
        print(f"  Invalid: {result['invalid_strategy_id']}")
        print(f"  Blockers: {result['blockers']}")
        print(f"  Warnings: {result['warnings']}")

    if args.output_json:
        Path(args.output_json).write_text(json.dumps(report, indent=2, default=str))
    if args.output_md:
        md = [f"# Route Audit Simulation — {args.symbol}",
              f"\nStrategy: {args.strategy_id} | Evaluated: {result['evaluated_strategy_count']} | Top: {result['top_match_strategy_id']} | Mismatch: {result['mismatch']}"]
        Path(args.output_md).write_text("\n".join(md))


if __name__ == "__main__":
    main()
