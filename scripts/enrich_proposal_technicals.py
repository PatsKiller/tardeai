#!/usr/bin/env python3
"""enrich_proposal_technicals.py — keep the moving-average / entry-helper technicals fresh for every
ACTIVE (and recently-expired) broker proposal symbol.

The card's "Entry helper" strip (SMA20/50/200 vs live price, RSI, RVOL, ATR%) reads the Finviz
technical enrichment cache (data/state/ticker_enrichment_cache.json). Watchlist/income proposals are
never momentum-scanned, so without this refresh their technicals stay blank. This pulls Finviz views
141 (RVOL/volatility) + 171 (RSI/SMA20-50-200/ATR — no cookie needed) for those symbols.

Cron (every 2h, flock-guarded single-flight):
    /usr/bin/flock -n /tmp/enrich_proposal_tech.lock .venv/bin/python scripts/enrich_proposal_technicals.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def main():
    from db_adapter import _execute
    from finviz_enrichment import enrich_tickers

    rows = _execute(
        """SELECT DISTINCT symbol FROM paper_trade_proposals
           WHERE status IN ('PENDING','APPROVED_FOR_PAPER_TEST')
              OR (status='EXPIRED' AND created_at > now() - interval '3 days')""",
        None, fetch="all") or []
    syms = sorted({(r["symbol"] or "").upper() for r in rows if r.get("symbol")})
    if not syms:
        print("[enrich_proposal_technicals] no active proposal symbols")
        return
    # Technical views only (fast, no cookie). enrich_tickers is cache-aware (6h TTL) so this only
    # hits Finviz for stale/missing symbols.
    enrich_tickers(syms, project_root=str(ROOT), views=[141, 171], skip_fundamentals=True)
    print(f"[enrich_proposal_technicals] refreshed technicals for {len(syms)} proposal symbol(s)")


if __name__ == "__main__":
    main()
