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
    from db_adapter import _execute, _get_conn
    from finviz_enrichment import enrich_tickers

    rows = _execute(
        """SELECT id, symbol, catalyst, catalyst_verified FROM paper_trade_proposals
           WHERE status IN ('PENDING','APPROVED_FOR_PAPER_TEST','PROPOSED','MODIFIED','BROKER_SUBMITTED')
           ORDER BY updated_at DESC NULLS LAST
           LIMIT 40""",
        None, fetch="all") or []
    syms = sorted({(r["symbol"] or "").upper() for r in rows if r.get("symbol")})
    if not syms:
        print("[enrich_proposal_technicals] no active proposal symbols")
        return
    enrich_tickers(syms, project_root=str(ROOT), views=[141, 171], skip_fundamentals=True)
    print(f"[enrich_proposal_technicals] refreshed finviz technicals for {len(syms)} symbol(s)")

    conn = _get_conn()
    import proposal_enrichment_bridge as peb
    from proposal_technical_snapshot import generate_snapshot

    for row in rows:
        pid = int(row["id"])
        sym = str(row["symbol"] or "").upper()
        try:
            generate_snapshot(conn, proposal_id=pid, symbol=sym)
            ir = peb.compute_proposal_intel_readiness(
                sym, conn,
                catalyst=row.get("catalyst"),
                catalyst_verified=bool(row.get("catalyst_verified")),
                has_technical_snapshot=True,
            )
            conn.cursor().execute(
                "UPDATE paper_trade_proposals SET intel_readiness=%s, updated_at=NOW() WHERE id=%s",
                (ir, pid),
            )
            conn.commit()
            print(f"  {sym} #{pid}: snapshot + intel_readiness={ir}")
        except Exception as e:
            print(f"  {sym} #{pid}: snapshot failed — {e}")
            try:
                conn.rollback()
            except Exception:
                pass


if __name__ == "__main__":
    main()
