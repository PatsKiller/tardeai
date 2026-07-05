#!/usr/bin/env python3
"""options_strategy_research.py — READ-ONLY options-chain strategy research CLI (spec Part D).

EDUCATIONAL_ONLY analysis over the options desk's existing Schwab chain read
path (schwab_transport.get_option_chain — the same call options_engine's
_schwab_chain makes). Output is JSON analysis ONLY: this tool has no order,
submit, cancel, or approval surface of any kind (test-enforced), writes
nothing to the DB, and degrades honestly to {"available": false, "reason"}
when chain data is unavailable (weekend / no linked account / transport
error) — numbers are never fabricated.

Usage:
  python3 scripts/options_strategy_research.py --symbol TEAM --strategy deep_itm_call --json
  python3 scripts/options_strategy_research.py --symbol AAPL --strategy chain_snapshot --json

Strategies:
  deep_itm_call    per-DTE-bucket deep ITM (0.80-0.95 delta) call candidates:
                   spread/OI/volume/earnings flags, extrinsic value, breakeven,
                   max loss, capital vs 100 shares
  chain_snapshot   normalized chain snapshot + liquidity + per-strategy
                   feasibility scores
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.strategy_research import options_chain  # noqa: E402

STRATEGIES = ("deep_itm_call", "chain_snapshot")


def _parse_buckets(raw: str) -> list[int]:
    return [int(x) for x in raw.split(",") if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", required=True, help="underlying symbol (e.g. TEAM)")
    ap.add_argument("--strategy", default="deep_itm_call", choices=STRATEGIES)
    ap.add_argument("--json", action="store_true",
                    help="accepted for consistency — output is ALWAYS json")
    ap.add_argument("--strike-count", type=int, default=40,
                    help="strikes around the money to request (default 40)")
    ap.add_argument("--delta-min", type=float, default=0.80)
    ap.add_argument("--delta-max", type=float, default=0.95)
    ap.add_argument("--dte-buckets", default="30,60,90,180,365",
                    help="comma-separated DTE buckets (default 30,60,90,180,365)")
    args = ap.parse_args()

    sym = args.symbol.strip().upper()
    if args.strategy == "chain_snapshot":
        result = options_chain.fetch_chain_snapshot(sym, strike_count=args.strike_count)
    else:
        result = options_chain.deep_itm_call_analysis(
            sym, delta_range=(args.delta_min, args.delta_max),
            dte_buckets=_parse_buckets(args.dte_buckets),
            strike_count=args.strike_count)

    # Analysis outputs JSON ONLY (spec hard rule); banner travels in-band.
    print(json.dumps(result, indent=2, default=str))
    return 0 if result.get("available") else 3  # 3 = honest-degrade exit


if __name__ == "__main__":
    raise SystemExit(main())
