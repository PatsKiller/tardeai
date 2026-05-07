#!/usr/bin/env python3
"""watchlist_price_levels.py — Populate entry/stop/target for watchlist symbols.

Runs nightly via overnight_batch. Non-destructive — only fills symbols that
have support/resistance or Finviz data but no price levels set yet.
"""
import sys, logging
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s [price_levels] %(message)s')
logger = logging.getLogger(__name__)


def populate_price_levels(conn):
    """
    For each watchlist symbol missing price levels:
    - ideal_entry = support level OR current_price * 0.98
    - stop_loss   = support - (2 * ATR) OR support * 0.94
    - target_price = resistance OR analyst_target OR entry * 1.15
    - risk_reward = (target - entry) / (entry - stop)
    """
    from psycopg2.extras import RealDictCursor
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT wsm.symbol, wsm.support, wsm.resistance, wsm.latest_price
        FROM watchlist_symbol_master wsm
        WHERE wsm.ideal_entry IS NULL
          AND (wsm.support IS NOT NULL OR wsm.latest_price IS NOT NULL)
    """)
    symbols = cur.fetchall()

    if not symbols:
        logger.info("No symbols need price level population")
        return 0

    # Get Finviz enrichment data from JSON cache
    import json
    enrichment_path = ROOT / "data" / "portfolios" / "state" / "ticker_enrichment_cache.json"
    finviz_map = {}
    try:
        ec = json.loads(enrichment_path.read_text()) if enrichment_path.exists() else {}
        for sym, data in ec.items():
            if isinstance(data, dict):
                finviz_map[sym] = {
                    'atr': data.get('atr'),
                    'analyst_target': data.get('target_price'),
                    'fe_price': data.get('price'),
                }
    except Exception:
        pass

    updated = 0
    for s in symbols:
        fe = finviz_map.get(s['symbol'], {})
        price = s['latest_price'] or fe.get('fe_price')
        if not price:
            continue

        price = float(price)
        entry = float(s['support']) if s['support'] else round(price * 0.98, 2)

        atr = fe.get('atr')
        if atr and float(atr) > 0:
            stop = round(entry - (2.0 * float(atr)), 2)
        else:
            stop = round(entry * 0.94, 2)

        if s['resistance']:
            target = float(s['resistance'])
        elif fe.get('analyst_target'):
            target = float(fe['analyst_target'])
        else:
            target = round(entry * 1.15, 2)
        target = round(target, 2)

        downside = entry - stop
        upside = target - entry
        rr = round(upside / downside, 1) if downside > 0 else None

        # Update watchlist_strategy_cards (feeds the symbol_master view)
        cur.execute("""
            UPDATE watchlist_strategy_cards
            SET ideal_entry  = %s,
                stop_loss    = %s,
                target_price = %s,
                risk_reward  = %s,
                updated_at   = NOW()
            WHERE symbol = %s
              AND ideal_entry IS NULL
        """, [entry, stop, target, rr, s['symbol']])
        if cur.rowcount == 0:
            # No strategy card exists — create a minimal one
            cur.execute("""
                INSERT INTO watchlist_strategy_cards (symbol, ideal_entry, stop_loss, target_price, risk_reward, latest_price, support, resistance, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (symbol) DO UPDATE
                SET ideal_entry = EXCLUDED.ideal_entry,
                    stop_loss = EXCLUDED.stop_loss,
                    target_price = EXCLUDED.target_price,
                    risk_reward = EXCLUDED.risk_reward,
                    updated_at = NOW()
                WHERE watchlist_strategy_cards.ideal_entry IS NULL
            """, [s['symbol'], entry, stop, target, rr, price, s.get('support'), s.get('resistance')])
        updated += 1

    conn.commit()
    logger.info(f"Populated price levels for {updated}/{len(symbols)} symbols")
    return updated


if __name__ == '__main__':
    import psycopg2
    pw = ""
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("DB_PASSWORD="): pw = line.split("=", 1)[1].strip()
    conn = psycopg2.connect(host='localhost', dbname='trade_ai', user='trade_ai', password=pw)
    count = populate_price_levels(conn)
    conn.close()
    print(f"Done: {count} symbols updated")
