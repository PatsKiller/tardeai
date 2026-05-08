#!/usr/bin/env python3
"""proposal_enrichment_loop.py — Live price refresh for pending proposals.

Runs every 5 minutes during market hours (6 AM - 4 PM ET M-F via cron).
For each PENDING proposal, fetches a live quote and updates:
  - current_price, price_drift_pct
  - entry_zone_status (ENTRY_ZONE_VALID / ENTRY_ZONE_MARGINAL / ENTRY_MISSED)
  - lifecycle_status
  - last_price_checked_at, last_price_source

Usage:
    .venv/bin/python scripts/proposal_enrichment_loop.py           # single pass
    .venv/bin/python scripts/proposal_enrichment_loop.py --dry-run # print only
    .venv/bin/python scripts/proposal_enrichment_loop.py --force-all  # no batch limit
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from pipeline_registry import PipelineRun

log = logging.getLogger("proposal_enrichment")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

BATCH_SIZE = 20

# Entry zone thresholds by timeframe
ZONE_THRESHOLDS = {
    'tight': {'valid': 3.0, 'marginal': 7.0},      # intraday, short_swing
    'wide': {'valid': 5.0, 'marginal': 12.0},       # swing, event_window, position
}
WIDE_TIMEFRAMES = {'swing', 'event_window', 'position'}


def get_db():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def get_live_price(symbol: str):
    """Fetch live price using market_quote_provider. Returns (price, source)."""
    try:
        from market_quote_provider import get_best_quote
        q = get_best_quote(symbol)
        price = q.get("last_price")
        source = q.get("provider", "unknown")
        if price and price > 0:
            return float(price), source
    except Exception as e:
        log.debug(f"market_quote_provider failed for {symbol}: {e}")

    # Fallback: yfinance fast_info
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        price = t.fast_info.get("lastPrice") or t.fast_info.get("last_price")
        if price and price > 0:
            return float(price), "yfinance"
    except Exception as e:
        log.debug(f"yfinance failed for {symbol}: {e}")

    return None, "none"


def classify_entry_zone(drift_pct: float, timeframe_class: str) -> str:
    """Classify entry zone based on price drift and timeframe."""
    thresholds = ZONE_THRESHOLDS['wide'] if timeframe_class in WIDE_TIMEFRAMES else ZONE_THRESHOLDS['tight']
    abs_drift = abs(drift_pct)
    if abs_drift <= thresholds['valid']:
        return 'ENTRY_ZONE_VALID'
    elif abs_drift <= thresholds['marginal']:
        return 'ENTRY_ZONE_MARGINAL'
    else:
        return 'ENTRY_MISSED'


def fetch_pending_proposals(conn, limit=BATCH_SIZE):
    """Get pending proposals ordered by priority for price update."""
    import psycopg2.extras
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT id, symbol, strategy_id, proposed_entry, proposed_stop,
               proposal_timeframe_class, lifecycle_status, entry_zone_status,
               current_price, price_drift_pct, last_price_checked_at
        FROM paper_trade_proposals
        WHERE status = 'PENDING'
          AND proposed_entry IS NOT NULL
          AND proposed_entry > 0
        ORDER BY
            CASE lifecycle_status
                WHEN 'ENTRY_ZONE_VALID' THEN 1
                WHEN 'ACTIVE' THEN 2
                WHEN 'NEEDS_REVIEW' THEN 3
                WHEN 'ENTRY_MISSED' THEN 4
                ELSE 5
            END,
            last_price_checked_at ASC NULLS FIRST
        LIMIT %s
    """, [limit])
    return cur.fetchall()


def update_proposal_price(conn, proposal: dict, dry_run=False):
    """Fetch price, compute drift, update DB. Returns summary dict."""
    pid = proposal['id']
    symbol = proposal['symbol']
    entry = float(proposal['proposed_entry'])
    timeframe = proposal.get('proposal_timeframe_class') or 'short_swing'

    price, source = get_live_price(symbol)
    if price is None:
        return {"symbol": symbol, "id": pid, "status": "no_price", "source": source}

    drift_pct = round((price - entry) / entry * 100, 2)
    zone = classify_entry_zone(drift_pct, timeframe)

    # Map zone to lifecycle_status
    if zone == 'ENTRY_ZONE_VALID':
        new_lifecycle = 'ENTRY_ZONE_VALID'
    elif zone == 'ENTRY_ZONE_MARGINAL':
        new_lifecycle = 'ACTIVE'
    else:
        new_lifecycle = 'ENTRY_MISSED'

    # Auto-expire if drift > 15%
    expired = False
    if zone == 'ENTRY_MISSED' and abs(drift_pct) > 15:
        new_lifecycle = 'EXPIRED'
        expired = True

    result = {
        "symbol": symbol, "id": pid,
        "price": price, "drift_pct": drift_pct,
        "zone": zone, "lifecycle": new_lifecycle,
        "source": source, "expired": expired,
    }

    if dry_run:
        return result

    cur = conn.cursor()
    if expired:
        cur.execute("""
            UPDATE paper_trade_proposals
            SET current_price = %s,
                price_drift_pct = %s,
                entry_zone_status = %s,
                lifecycle_status = 'EXPIRED',
                lifecycle_message = 'Entry missed — price drifted beyond recovery (>15%%)',
                status = 'expired',
                last_price_checked_at = NOW(),
                last_price_source = %s,
                updated_at = NOW()
            WHERE id = %s
        """, [price, drift_pct, zone, source, pid])
    else:
        cur.execute("""
            UPDATE paper_trade_proposals
            SET current_price = %s,
                price_drift_pct = %s,
                entry_zone_status = %s,
                lifecycle_status = %s,
                last_price_checked_at = NOW(),
                last_price_source = %s,
                updated_at = NOW()
            WHERE id = %s
        """, [price, drift_pct, zone, new_lifecycle, source, pid])
    conn.commit()
    return result


def run_once(dry_run=False, force_all=False):
    """Single enrichment pass."""
    conn = get_db()
    try:
        limit = 999 if force_all else BATCH_SIZE
        proposals = fetch_pending_proposals(conn, limit=limit)
        log.info(f"Processing {len(proposals)} pending proposals")

        results = []
        seen_symbols = set()

        for p in proposals:
            symbol = p['symbol']
            # Deduplicate: only fetch price once per symbol
            if symbol in seen_symbols:
                # Reuse the last fetched price for this symbol
                prev = next((r for r in reversed(results) if r['symbol'] == symbol and r.get('price')), None)
                if prev:
                    # Apply same price to this proposal
                    entry = float(p['proposed_entry'])
                    drift_pct = round((prev['price'] - entry) / entry * 100, 2)
                    timeframe = p.get('proposal_timeframe_class') or 'short_swing'
                    zone = classify_entry_zone(drift_pct, timeframe)
                    new_lifecycle = 'ENTRY_ZONE_VALID' if zone == 'ENTRY_ZONE_VALID' else ('ACTIVE' if zone == 'ENTRY_ZONE_MARGINAL' else 'ENTRY_MISSED')
                    expired = zone == 'ENTRY_MISSED' and abs(drift_pct) > 15
                    if expired:
                        new_lifecycle = 'EXPIRED'

                    result = {
                        "symbol": symbol, "id": p['id'],
                        "price": prev['price'], "drift_pct": drift_pct,
                        "zone": zone, "lifecycle": new_lifecycle,
                        "source": prev['source'], "expired": expired,
                    }
                    if not dry_run:
                        cur = conn.cursor()
                        if expired:
                            cur.execute("""
                                UPDATE paper_trade_proposals
                                SET current_price=%s, price_drift_pct=%s, entry_zone_status=%s,
                                    lifecycle_status='EXPIRED', lifecycle_message='Entry missed — price drifted beyond recovery (>15%%)',
                                    status='expired', last_price_checked_at=NOW(), last_price_source=%s, updated_at=NOW()
                                WHERE id=%s
                            """, [prev['price'], drift_pct, zone, prev['source'], p['id']])
                        else:
                            cur.execute("""
                                UPDATE paper_trade_proposals
                                SET current_price=%s, price_drift_pct=%s, entry_zone_status=%s,
                                    lifecycle_status=%s, last_price_checked_at=NOW(), last_price_source=%s, updated_at=NOW()
                                WHERE id=%s
                            """, [prev['price'], drift_pct, zone, new_lifecycle, prev['source'], p['id']])
                        conn.commit()
                    results.append(result)
                    continue

            seen_symbols.add(symbol)
            result = update_proposal_price(conn, p, dry_run=dry_run)
            results.append(result)

            if result.get('price'):
                tag = "EXPIRED (>15%)" if result.get('expired') else result['zone']
                log.info(f"[enrichment] {symbol}: price={result['price']:.2f} drift={result['drift_pct']:+.1f}% zone={tag} source={result['source']}")
            else:
                log.warning(f"[enrichment] {symbol}: no price available")

            # Rate limit between unique symbols
            time.sleep(0.5)

        return results
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Proposal price enrichment loop")
    parser.add_argument("--dry-run", action="store_true", help="Print only, no DB writes")
    parser.add_argument("--force-all", action="store_true", help="Process all pending, ignore batch limit")
    args = parser.parse_args()

    with PipelineRun('proposal_enrichment_loop', triggered_by='cli') as pipe:
        results = run_once(dry_run=args.dry_run, force_all=args.force_all)
        updated = sum(1 for r in results if r.get('price'))
        pipe.rows(updated)

    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"\n{prefix}Proposal Enrichment Loop")
    print(f"{prefix}{'=' * 40}")

    valid = sum(1 for r in results if r.get('zone') == 'ENTRY_ZONE_VALID')
    marginal = sum(1 for r in results if r.get('zone') == 'ENTRY_ZONE_MARGINAL')
    missed = sum(1 for r in results if r.get('zone') == 'ENTRY_MISSED')
    expired = sum(1 for r in results if r.get('expired'))
    no_price = sum(1 for r in results if not r.get('price'))

    print(f"  Processed: {len(results)}")
    print(f"  ENTRY_ZONE_VALID: {valid}")
    print(f"  ENTRY_ZONE_MARGINAL: {marginal}")
    print(f"  ENTRY_MISSED: {missed}")
    print(f"  Auto-expired (>15%): {expired}")
    print(f"  No price: {no_price}")


if __name__ == "__main__":
    main()
