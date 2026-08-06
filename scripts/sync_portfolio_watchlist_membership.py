#!/usr/bin/env python3
"""sync_portfolio_watchlist_membership.py — keep source='portfolio' rows aligned with holdings.

ROOT CAUSE
----------
`watchlist_symbol_master` is a VIEW that defines:

    in_portfolio = bool_or(wi.source = 'portfolio')  WHERE status <> 'removed'

When a position is sold, holdings.json is updated but the `watchlist_items` row
with source='portfolio' is left as status='researched'. The master view still
reports in_portfolio=true, so the Watchlist HELD badge never clears.

This module is the single writer for portfolio-membership truth:
  • currently held symbols → ensure an active/researched source=portfolio row
  • no longer held         → status='removed' on source=portfolio rows only
                            (other sources on the same symbol are untouched)

Call after every holdings write (import, loader save, reprice). Pure relative to
broker APIs — only holdings.json + DB.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable, Optional, Set

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def held_symbols_from_holdings(holdings: dict | None = None,
                               holdings_path: Path | None = None) -> Set[str]:
    """Canonical currently-held set: shares>0 or market_value>0, non-cash.

    Filters CUSIP-style settlement IDs (9-char alphanumeric, no dots/dashes)
    that appear in broker holdings files. These are not tradeable tickers and
    pollute watchlist_items, watch_intelligence, and the reentry decision desk.
    """
    if holdings is None:
        path = holdings_path or (PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json")
        if not path.exists():
            return set()
        holdings = json.loads(path.read_text())
    out: Set[str] = set()
    for r in (holdings or {}).get("holdings") or []:
        if r.get("is_cash"):
            continue
        sym = str(r.get("symbol") or "").upper().strip()
        if not sym:
            continue
        # Skip CUSIP-style settlement IDs
        if len(sym) == 9 and sym.isalnum() and all(c not in sym for c in ('.', '-', '/', '^', ' ')):
            continue
        sh = float(r.get("quantity") or r.get("shares") or 0)
        mv = float(r.get("market_value") or 0)
        if sh > 0 or mv > 0:
            out.add(sym)
    return out


def sync_portfolio_watchlist_membership(
    holdings: dict | None = None,
    *,
    conn=None,
    dry_run: bool = False,
) -> dict:
    """Align watchlist_items source='portfolio' with live holdings.

    Returns counts: held, exited, ensured, skipped.
    """
    held = held_symbols_from_holdings(holdings)
    close = False
    if conn is None:
        from db_adapter import _get_conn
        conn = _get_conn()
        close = True
    cur = conn.cursor()

    # Portfolio-source rows still marking sold names as held
    cur.execute("""
        SELECT upper(symbol), status FROM watchlist_items
        WHERE source = 'portfolio' AND status <> 'removed'
    """)
    existing = {str(r[0]).upper(): r[1] for r in cur.fetchall()}

    to_exit = sorted(s for s in existing if s not in held)
    to_ensure = sorted(s for s in held if s not in existing)

    exited = 0
    if to_exit and not dry_run:
        cur.execute("""
            UPDATE watchlist_items
               SET status = 'removed', updated_at = now()
             WHERE source = 'portfolio'
               AND status <> 'removed'
               AND upper(symbol) = ANY(%s)
        """, (to_exit,))
        exited = cur.rowcount or 0
    elif to_exit:
        exited = len(to_exit)

    ensured = 0
    if to_ensure and not dry_run:
        for sym in to_ensure:
            cur.execute("""
                INSERT INTO watchlist_items (symbol, source, status, updated_at, first_seen_at, last_seen_at)
                VALUES (%s, 'portfolio', 'active', now(), now(), now())
                ON CONFLICT DO NOTHING
            """, (sym,))
            # Some schemas lack a unique on (symbol, source) — fall back to soft insert.
            if cur.rowcount == 0:
                cur.execute("""
                    SELECT 1 FROM watchlist_items
                     WHERE upper(symbol)=%s AND source='portfolio' AND status<>'removed'
                     LIMIT 1
                """, (sym,))
                if not cur.fetchone():
                    try:
                        cur.execute("""
                            INSERT INTO watchlist_items (symbol, source, status, updated_at)
                            VALUES (%s, 'portfolio', 'active', now())
                        """, (sym,))
                    except Exception:
                        conn.rollback()
                        # re-open transaction for remaining work
                        continue
            ensured += 1
    elif to_ensure:
        ensured = len(to_ensure)

    if not dry_run:
        try:
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    if close:
        try:
            from db_adapter import close_thread_conn
            close_thread_conn()
        except Exception:
            pass

    return {
        "held_count": len(held),
        "exited": exited,
        "exited_symbols": to_exit[:50],
        "ensured": ensured,
        "ensured_symbols": to_ensure[:50],
        "dry_run": dry_run,
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Sync portfolio watchlist membership to holdings.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)
    result = sync_portfolio_watchlist_membership(dry_run=args.dry_run)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"held={result['held_count']} exited={result['exited']} ensured={result['ensured']}")
        if result["exited_symbols"]:
            print("exited:", ", ".join(result["exited_symbols"][:30]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
