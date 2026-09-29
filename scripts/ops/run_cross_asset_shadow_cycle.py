#!/usr/bin/env python3
"""run_cross_asset_shadow_cycle.py — evaluate expressions; never trade.

Usage:
  .venv/bin/python scripts/ops/run_cross_asset_shadow_cycle.py --symbols NFLX,AAPL --dry-run
  CROSS_ASSET_SHADOW=1 .venv/bin/python scripts/ops/run_cross_asset_shadow_cycle.py --symbols NFLX --apply-ledger
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cross_asset.assemble import assemble_symbol_decision  # noqa: E402
from scripts.lib.cross_asset.persistence import append_symbol_decision  # noqa: E402
from scripts.lib.cross_asset.symbol_decision_object import validate_symbol_decision  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Cross-asset shadow cycle (advisory only)")
    ap.add_argument("--symbols", required=True, help="Comma-separated tickers")
    ap.add_argument("--signal", default="buy", choices=["buy", "hold", "sell", "reentry"])
    ap.add_argument("--dry-run", action="store_true", help="Print only; no ledger write")
    ap.add_argument("--apply-ledger", action="store_true", help="Append to symbol_decisions.jsonl")
    ap.add_argument("--ledger", default="", help="Optional ledger path override")
    args = ap.parse_args(argv)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        print(json.dumps({"ok": False, "error": "no_symbols"}))
        return 2

    out_rows = []
    for sym in symbols:
        obj = assemble_symbol_decision(sym, signal={"kind": args.signal, "lane": "shadow_cycle"}, route=True)
        check = validate_symbol_decision(obj)
        row = {
            "symbol": sym,
            "ok": check["ok"],
            "errors": check.get("errors"),
            "top_family": (obj.get("expression_comparison") or {}).get("top_family"),
            "ranked": [
                {"family": c.get("family"), "status": c.get("status"), "blocks": c.get("blocks")}
                for c in ((obj.get("expression_comparison") or {}).get("ranked") or [])
            ],
        }
        if args.apply_ledger and not args.dry_run:
            path = Path(args.ledger) if args.ledger else None
            wr = append_symbol_decision(obj, path=path, root=ROOT)
            row["write"] = wr
        out_rows.append(row)

    print(json.dumps({"ok": True, "authority": "READ_ONLY_ADVISORY", "shadow": True, "results": out_rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
