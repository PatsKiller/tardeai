#!/usr/bin/env python3
"""options_iv_snapshot.py — daily ATM-IV snapshot CLI (IV-rank history layer).

Captures one ATM-IV row per symbol per day into options_iv_history via
lib.strategy_research.iv_history.snapshot_iv (chain reads go through the
AST-proven READ-ONLY research adapter; upsert on (symbol, snapshot_date) —
re-running a day replaces, never duplicates). This history powers
iv_history.iv_rank(): honest {"available": false, reason: "insufficient
history"} below 20 stored days, then rank/percentile + cheap/rich verdicts.

Rewritten 2026-07-06: the previous version extracted IV via
options_engine._schwab_chain and captured 0 rows every run (see
logs/options_iv_snapshot.log); extraction now uses the research adapter's
parsed snapshot with the 30-60 DTE near-the-money average.

Usage:
    .venv/bin/python scripts/options_iv_snapshot.py --run --symbols-from-universe [--json]
    .venv/bin/python scripts/options_iv_snapshot.py --dry-run --symbols NVDA,MSFT
    .venv/bin/python scripts/options_iv_snapshot.py            # legacy-compat: --run
                                                               # with holdings+proposals universe
                                                               # (matches the installed cron)

--symbols-from-universe uses the SAME eligibility resolution as
options_strategy_scanner (current equity holdings + watchlist buy/strong_buy).

Suggested cron (NOT installed by this script — operator installs explicitly;
15:45 ET captures near the close while quotes are live):
    45 15 * * 1-5 cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && .venv/bin/python scripts/options_iv_snapshot.py --run --symbols-from-universe >> logs/options_iv_snapshot.log 2>&1

HARD SAFETY: no broker submit / order / 2FA imports (test-enforced by
tests/test_options_iv_rank.py). Advisory market-data capture only.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except Exception:
    pass

STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"
DEFAULT_LIMIT = 40
SUGGESTED_CRON = (
    "45 15 * * 1-5 cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild && "
    ".venv/bin/python scripts/options_iv_snapshot.py --run --symbols-from-universe "
    ">> logs/options_iv_snapshot.log 2>&1"
)


def _legacy_symbols() -> List[str]:
    """Holdings + queued option-proposal symbols (pre-2026-07-06 universe)."""
    syms = set()
    try:
        h = json.loads((STATE_DIR / "holdings.json").read_text(encoding="utf-8"))
        for row in h.get("holdings") or []:
            s = (row.get("symbol") or "").upper()
            if s and s.isalpha() and len(s) <= 6 and not row.get("is_cash"):
                syms.add(s)
    except Exception:
        pass
    try:
        p = json.loads((STATE_DIR / "options_proposals.json").read_text(encoding="utf-8"))
        for row in p.get("proposals") or []:
            s = (row.get("symbol") or "").upper()
            if s:
                syms.add(s)
    except Exception:
        pass
    return sorted(syms)


def _universe_symbols(limit: int) -> List[str]:
    """Scanner-parity universe: holdings equities + watchlist buy/strong_buy."""
    from options_strategy_scanner import resolve_eligible_underlyings
    return [u["symbol"] for u in resolve_eligible_underlyings(limit=limit)]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Daily ATM-IV snapshot into options_iv_history (IV-rank history)")
    ap.add_argument("--run", action="store_true", help="capture and upsert rows")
    ap.add_argument("--dry-run", action="store_true",
                    help="extract and print — write NOTHING")
    ap.add_argument("--json", action="store_true", help="emit full JSON result")
    ap.add_argument("--symbols-from-universe", action="store_true",
                    help="scanner-parity universe (holdings + buy/strong_buy watchlist)")
    ap.add_argument("--symbols", default=None,
                    help="explicit comma-separated symbol list")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                    help=f"max symbols (default {DEFAULT_LIMIT})")
    args = ap.parse_args(argv)

    if args.run and args.dry_run:
        print("ERROR: choose one of --run or --dry-run", file=sys.stderr)
        return 2
    # Legacy-compat default: the installed daily cron calls this with no args
    # and must keep capturing — no args behaves as --run (documented above).
    dry = bool(args.dry_run)

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        universe = "explicit"
    elif args.symbols_from_universe:
        symbols = _universe_symbols(args.limit)
        universe = "scanner_eligibility (holdings + buy/strong_buy watchlist)"
    else:
        symbols = _legacy_symbols()
        universe = "legacy (holdings + queued option proposals)"
    symbols = symbols[: max(1, int(args.limit))]

    from lib.strategy_research.iv_history import snapshot_iv
    result = snapshot_iv(symbols, dry_run=dry)
    result["universe"] = universe
    result["suggested_cron"] = SUGGESTED_CRON

    # Vol-surface snapshot retention sweep (kept from the legacy script — the
    # per-insert prune only touches active symbols; this catches quiet names).
    if not dry:
        try:
            import options_desk_enterprise as ent
            result["snapshot_prune"] = ent.prune_chain_snapshots()
        except Exception as e:
            result["snapshot_prune"] = {"ok": False, "error": str(e)[:160]}

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(json.dumps({
            "ok": result["ok"],
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "snapshot_date": result["snapshot_date"],
            "dry_run": dry,
            "universe": universe,
            "symbols_requested": result["symbols_requested"],
            "captured": len(result["captured"]),
            "rows_written": result["rows_written"],
            "skipped": len(result["skipped"]),
            "skip_reasons": sorted({s["reason"][:60] for s in result["skipped"]})[:5],
            "snapshot_prune": result.get("snapshot_prune"),
        }, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
