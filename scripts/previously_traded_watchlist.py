#!/usr/bin/env python3
"""Previously Traded Watchlist — monitors former winning trades for re-entry signals."""
import os, sys, json, logging
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
ROOT = Path(__file__).resolve().parent.parent

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

# Load .env
for line in (ROOT / '.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip())

import psycopg2
from psycopg2.extras import RealDictCursor

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', '5432')),
    'dbname': os.getenv('DB_NAME', 'trade_ai'),
    'user': os.getenv('DB_USER', 'trade_ai'),
    'password': os.getenv('DB_PASSWORD', '')
}
HOLDINGS_PATH = ROOT / 'data' / 'portfolios' / 'state' / 'holdings.json'


def get_db():
    return psycopg2.connect(**DB_CONFIG)


def load_held_symbols():
    try:
        data = json.loads(HOLDINGS_PATH.read_text())
        return {h['symbol'].upper() for h in data.get('holdings', []) if h.get('symbol')}
    except Exception as e:
        log.error(f"Could not load holdings: {e}")
        return set()


def populate_from_journal():
    held = load_held_symbols()
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT symbol, SUM(pnl) as total_pnl, MAX(pnl) as best_pnl,
               MAX(pnl_pct) as best_pnl_pct, COUNT(*) as trade_count,
               AVG(hold_days) as avg_hold_days, MAX(buy_price) as last_entry_price,
               (ARRAY_AGG(sell_price ORDER BY close_date DESC))[1] as last_exit_price,
               MAX(close_date) as last_exit_date
        FROM trade_closed
        WHERE buy_price > 0
        GROUP BY symbol HAVING SUM(pnl) > 0
        ORDER BY SUM(pnl) DESC
    """)
    rows = cur.fetchall()
    inserted = 0

    for row in rows:
        sym = row['symbol'].upper()
        if sym in held:
            cur.execute("UPDATE previously_traded_watchlist SET is_currently_held=true, updated_at=NOW() WHERE symbol=%s", [sym])
            continue

        exit_px = float(row['last_exit_price'] or 0)
        if exit_px == 0:
            continue

        avg_days = float(row['avg_hold_days'] or 0)
        best_pct = float(row['best_pnl_pct'] or 0)

        if avg_days <= 5:
            zone_low, zone_high, category = exit_px * 0.85, exit_px * 1.05, 'day_swing'
        elif avg_days <= 90:
            zone_low, zone_high, category = exit_px * 0.80, exit_px * 0.95, 'position'
        elif best_pct > 50:
            zone_low, zone_high, category = exit_px * 0.70, exit_px * 0.90, 'long_term_compounder'
        else:
            zone_low, zone_high, category = exit_px * 0.80, exit_px * 1.00, 'position'

        cur.execute("""
            INSERT INTO previously_traded_watchlist
                (symbol, total_pnl, best_pnl, best_pnl_pct, trade_count, avg_hold_days,
                 last_entry_price, last_exit_price, last_exit_date,
                 reentry_zone_low, reentry_zone_high, category, is_currently_held, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,NOW())
            ON CONFLICT (symbol) DO UPDATE SET
                total_pnl=EXCLUDED.total_pnl, best_pnl=EXCLUDED.best_pnl,
                best_pnl_pct=EXCLUDED.best_pnl_pct, trade_count=EXCLUDED.trade_count,
                avg_hold_days=EXCLUDED.avg_hold_days, last_exit_price=EXCLUDED.last_exit_price,
                last_exit_date=EXCLUDED.last_exit_date, reentry_zone_low=EXCLUDED.reentry_zone_low,
                reentry_zone_high=EXCLUDED.reentry_zone_high, category=EXCLUDED.category,
                is_currently_held=false, updated_at=NOW()
        """, [sym, row['total_pnl'], row['best_pnl'], row['best_pnl_pct'],
              row['trade_count'], avg_days, row['last_entry_price'],
              exit_px, row['last_exit_date'], zone_low, zone_high, category])
        inserted += 1

    conn.commit()
    conn.close()
    log.info(f"populate_from_journal: {inserted} tracked")
    return inserted


def _conn_db_query(conn):
    """Adapt a DB-API connection to the broker projections' ``db_query(sql, params, fetch)``."""
    def _q(sql, params=None, fetch="all"):
        cur = conn.cursor()
        cur.execute(sql, params or ())
        cols = [d[0] for d in (cur.description or [])]
        if fetch == "one":
            row = cur.fetchone()
            return None if row is None else (dict(row) if hasattr(row, "keys") else dict(zip(cols, row)))
        rows = cur.fetchall() or []
        return [dict(r) if hasattr(r, "keys") else dict(zip(cols, r)) for r in rows]
    return _q


def fetch_current_prices():
    """Current price per tracked symbol through the shared Finviz-first batch — never yfinance.

    Operator price rule (2026-11-07, LQ-20261107-14): a live price comes from Finviz while its cache row is
    fresh (<= 30 min), else a fresh Schwab/Alpaca/moomoo quote; never yfinance, never a stored row older than
    that. ``get_price_batch`` is that ladder (Finviz overlay built in), so this lane calls it instead of its
    own yfinance loop. The batch's quote-only fallback is bounded per call, so the symbols go in chunks of that
    bound — otherwise everything past the first ten would keep yesterday's stored price all day. A symbol the
    batch cannot price inside the window is skipped and named in the log; its stored price is left alone
    rather than overwritten with a stale close or a zero.
    """
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT symbol FROM previously_traded_watchlist WHERE is_currently_held=false")
    symbols = [r['symbol'] for r in cur.fetchall()]
    conn.close()

    log.info(f"Fetching prices for {len(symbols)} symbols...")
    prices = {}
    batch = {}
    if symbols:
        conn = get_db()
        try:
            from lib.data_broker.market_quote import LIVE_FALLBACK_MAX_PER_BATCH, get_price_batch
            q = _conn_db_query(conn)
            step = max(1, int(LIVE_FALLBACK_MAX_PER_BATCH))
            for i in range(0, len(symbols), step):
                batch.update(get_price_batch(q, symbols[i:i + step], max_age_hours=0.5) or {})
        except Exception as e:  # noqa: BLE001 — a batch failure is named, never published as "no prices"
            log.error(f"price batch failed: {type(e).__name__}: {e}")
        finally:
            conn.close()
        for sym, quote in batch.items():
            try:
                px = float((quote or {}).get("price"))
            except (TypeError, ValueError):
                continue
            if "yfinance" in str((quote or {}).get("source") or "").lower():
                continue  # operator 2026-11-07: never yfinance — the stored price stays rather than a yfinance one
            if px > 0:
                prices[str(sym).upper()] = px
    unpriced = [s for s in symbols if s not in prices]
    for sym in unpriced[:20]:
        log.warning(f"  {sym}: no quote inside the 30-minute window — left at its stored price")
    if len(unpriced) > 20:
        log.warning(f"  ... and {len(unpriced) - 20} more without a fresh quote")

    if prices:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT symbol, last_exit_price FROM previously_traded_watchlist WHERE symbol = ANY(%s)", [list(prices.keys())])
        exits = {r['symbol']: float(r['last_exit_price'] or 0) for r in cur.fetchall()}
        for sym, price in prices.items():
            exit_px = exits.get(sym, 0)
            pct = ((price - exit_px) / exit_px * 100) if exit_px > 0 else None
            cur.execute("UPDATE previously_traded_watchlist SET current_price=%s, pct_above_exit=%s, updated_at=NOW() WHERE symbol=%s", [price, pct, sym])
        conn.commit()
        conn.close()

    log.info(f"Prices: {len(prices)} fresh inside 30 min, {len(unpriced)} without a fresh quote (stored prices kept)")
    return prices


def evaluate_reentry_signals():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT symbol, current_price, reentry_zone_low, reentry_zone_high FROM previously_traded_watchlist WHERE current_price IS NOT NULL AND is_currently_held=false")
    counts = {'IN_ZONE': 0, 'WATCH': 0, 'ABOVE_ZONE': 0, 'BELOW_ZONE': 0}
    for row in cur.fetchall():
        price, low, high = float(row['current_price']), float(row['reentry_zone_low'] or 0), float(row['reentry_zone_high'] or 0)
        if high == 0: continue
        if low <= price <= high: signal = 'IN_ZONE'
        elif price < low: signal = 'BELOW_ZONE'
        elif price <= high * 1.15: signal = 'WATCH'
        else: signal = 'ABOVE_ZONE'
        counts[signal] += 1
        cur.execute("UPDATE previously_traded_watchlist SET reentry_signal=%s WHERE symbol=%s", [signal, row['symbol']])
    conn.commit()
    conn.close()
    log.info(f"Signals: {counts}")
    return counts


def send_telegram_msg(msg):
    """Send via telegram_alert.send_telegram chokepoint (no raw Bot API)."""
    try:
        from telegram_alert import send_telegram
        ok = bool(send_telegram(msg))
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="previously_traded_watchlist",
                subject_key="ops:prev_traded_watchlist",
                retention_class="operational", severity="info",
                sanitized_body=msg[:500], short_summary=msg[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
        return ok
    except Exception as e:
        log.error(f"Telegram send failed: {e}")
        return False


def send_weekly_telegram(dry_run=False):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT symbol, current_price, reentry_zone_low, reentry_zone_high, best_pnl_pct, pct_above_exit FROM previously_traded_watchlist WHERE reentry_signal='IN_ZONE' AND is_currently_held=false ORDER BY best_pnl_pct DESC LIMIT 5")
    in_zone = cur.fetchall()
    cur.execute("SELECT symbol, current_price, reentry_zone_high, best_pnl_pct FROM previously_traded_watchlist WHERE reentry_signal='WATCH' AND is_currently_held=false ORDER BY best_pnl_pct DESC LIMIT 3")
    watching = cur.fetchall()
    cur.execute("SELECT symbol, last_exit_price, current_price, pct_above_exit FROM previously_traded_watchlist WHERE pct_above_exit > 100 AND is_currently_held=false ORDER BY pct_above_exit DESC LIMIT 3")
    missed = cur.fetchall()
    conn.close()

    lines = ["*Weekly Re-entry Watchlist*\n"]
    if in_zone:
        lines.append("*IN ZONE:*")
        for r in in_zone:
            lines.append(f"  {r['symbol']} ${float(r['current_price']):.2f} (zone ${float(r['reentry_zone_low']):.2f}-${float(r['reentry_zone_high']):.2f}) best +{float(r['best_pnl_pct']):.0f}%")
    if watching:
        lines.append("\n*WATCH:*")
        for r in watching:
            lines.append(f"  {r['symbol']} ${float(r['current_price']):.2f} -> zone ${float(r['reentry_zone_high']):.2f}")
    if missed:
        lines.append("\n*MISSED:*")
        for r in missed:
            lines.append(f"  {r['symbol']} exited ${float(r['last_exit_price']):.2f}, now ${float(r['current_price']):.2f} (+{float(r['pct_above_exit']):.0f}%)")
    lines.append(f"\n_{date.today()}_")
    msg = "\n".join(lines)
    log.info(msg)
    if not dry_run:
        send_telegram_msg(msg)


def populate_prev_traded_to_watchlist():
    """Ensure all previously_traded_watchlist symbols are in watchlist_items with source='prev_traded'."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""
        SELECT p.symbol FROM previously_traded_watchlist p
        WHERE p.is_currently_held = false
        AND NOT EXISTS (SELECT 1 FROM watchlist_items w WHERE w.symbol = p.symbol)
    """)
    missing = [r['symbol'] for r in cur.fetchall()]
    for sym in missing:
        try:
            cur.execute("""
                INSERT INTO watchlist_items (symbol, source, status)
                VALUES (%s, 'prev_traded', 'active')
            """, [sym])
        except Exception as e:
            log.warning(f"Could not add {sym} to watchlist_items: {e}")
    conn.commit()
    conn.close()
    log.info(f"Added {len(missing)} previously traded symbols to watchlist_items")
    return len(missing)


def main():
    log.info("=== Previously Traded Watchlist ===")
    n = populate_from_journal()
    populate_prev_traded_to_watchlist()
    prices = fetch_current_prices()
    signals = evaluate_reentry_signals()

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("""SELECT symbol, reentry_signal, current_price, reentry_zone_low, reentry_zone_high, best_pnl_pct
        FROM previously_traded_watchlist WHERE is_currently_held=false
        ORDER BY CASE reentry_signal WHEN 'IN_ZONE' THEN 0 WHEN 'WATCH' THEN 1 WHEN 'BELOW_ZONE' THEN 2 ELSE 3 END, best_pnl_pct DESC""")
    rows = cur.fetchall()
    conn.close()

    print(f"\n{'SYMBOL':<8} {'SIGNAL':<12} {'PRICE':>8} {'ZONE LOW':>10} {'ZONE HIGH':>10} {'BEST %':>8}")
    print("-" * 60)
    for r in rows:
        print(f"{r['symbol']:<8} {r['reentry_signal'] or 'N/A':<12} ${float(r['current_price'] or 0):>7.2f} ${float(r['reentry_zone_low'] or 0):>9.2f} ${float(r['reentry_zone_high'] or 0):>9.2f} {float(r['best_pnl_pct'] or 0):>7.0f}%")

    if datetime.now().weekday() == 6:
        send_weekly_telegram()
    log.info("=== Done ===")


if __name__ == '__main__':
    main()
