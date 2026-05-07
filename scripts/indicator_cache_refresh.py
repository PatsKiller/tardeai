"""
indicator_cache_refresh.py
Pre-market refresh of indicator confluence cache for all watchlist + portfolio symbols.
Run via cron at 5:45 AM Mon-Fri.
"""
import sys
import os
import json
import logging
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.join(os.path.dirname(__file__), '..'))

# Load .env
from pathlib import Path
env_path = Path('.env')
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

from indicator_engine import analyze_confluence

try:
    import psycopg2
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        port=int(os.getenv('DB_PORT', '5432')),
        dbname=os.getenv('DB_NAME', 'trade_ai'),
        user=os.getenv('DB_USER', 'trade_ai'),
        password=os.getenv('DB_PASSWORD', ''),
    )
    cur = conn.cursor()
    cur.execute(
        "SELECT DISTINCT symbol FROM watchlist_symbol_master "
        "WHERE in_ai_watchlist=true OR in_personal_watchlist=true OR in_portfolio=true"
    )
    symbols = [r[0] for r in cur.fetchall()]
    logger.info(f"Refreshing {len(symbols)} symbols...")

    success = 0
    for s in symbols:
        try:
            r = analyze_confluence(s, 'swing')
            if r.get('ok'):
                cur.execute(
                    """INSERT INTO indicator_confluence_cache
                       (symbol, profile, confluence_score, confluence_tier,
                        signals_bullish, signals_bearish, signals_neutral,
                        strategy_badges, bearish_badges, key_levels,
                        stop_price, target_price, atr, adx_regime, entry_quality,
                        full_result, computed_at, expires_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW()+INTERVAL '1 hour')
                       ON CONFLICT (symbol,profile) DO UPDATE SET
                         confluence_score=EXCLUDED.confluence_score,
                         confluence_tier=EXCLUDED.confluence_tier,
                         signals_bullish=EXCLUDED.signals_bullish,
                         signals_bearish=EXCLUDED.signals_bearish,
                         signals_neutral=EXCLUDED.signals_neutral,
                         strategy_badges=EXCLUDED.strategy_badges,
                         bearish_badges=EXCLUDED.bearish_badges,
                         key_levels=EXCLUDED.key_levels,
                         stop_price=EXCLUDED.stop_price,
                         target_price=EXCLUDED.target_price,
                         atr=EXCLUDED.atr,
                         adx_regime=EXCLUDED.adx_regime,
                         entry_quality=EXCLUDED.entry_quality,
                         full_result=EXCLUDED.full_result,
                         computed_at=NOW(),
                         expires_at=NOW()+INTERVAL '1 hour'""",
                    (s, 'swing', r.get('confluence_score', 0), r.get('confluence_tier'),
                     r.get('signals_bullish', 0), r.get('signals_bearish', 0),
                     r.get('signals_neutral', 0),
                     r.get('strategy_badges', []), r.get('bearish_badges', []),
                     json.dumps(r.get('key_levels', {})),
                     r.get('stop_price'), r.get('target_price'),
                     r.get('atr'), r.get('adx_regime'), r.get('entry_quality'),
                     json.dumps(r))
                )
                conn.commit()
                success += 1
                logger.info(f"  {s}: {r.get('confluence_tier')} ({r.get('signals_bullish')} bullish)")
                # === IER WRITE-BACK (non-fatal) ===
                try:
                    from intelligence_entity_manager import upsert_entity as _iem_upsert
                    from datetime import datetime, timezone as _tz
                    _iem_upsert(conn, s, 'market', {
                        'confluence_tier': r.get('confluence_tier'),
                        'confluence_score': r.get('confluence_score'),
                        'confluence_badges': r.get('strategy_badges', []),
                        'confluence_profile': 'swing',
                        'confluence_updated': datetime.now(_tz.utc),
                        'atr_value': r.get('atr'),
                        'volatility_regime': r.get('adx_regime'),
                    }, source='indicator_engine')
                except Exception:
                    pass
                # === END WRITE-BACK ===
        except Exception as e:
            logger.warning(f"  {s}: FAILED {e}")
            conn.rollback()

    conn.close()
    logger.info(f"Refresh complete: {success}/{len(symbols)} symbols updated")

except Exception as e:
    logger.error(f"Indicator cache refresh failed: {e}")
    sys.exit(1)
