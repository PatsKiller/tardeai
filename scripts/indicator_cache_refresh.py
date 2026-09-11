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
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
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
    # Portfolio + watchlist symbols
    cur.execute(
        "SELECT DISTINCT symbol FROM watchlist_symbol_master "
        "WHERE in_ai_watchlist=true OR in_personal_watchlist=true OR in_portfolio=true"
    )
    symbols = [r[0] for r in cur.fetchall()]

    # Also include recent screener GO/WAIT candidates and incubator ACTIVE symbols
    # so they have indicator data BEFORE strategy classification
    cur.execute("""
        SELECT DISTINCT symbol FROM trade_ai_scans
        WHERE scanned_at > NOW() - INTERVAL '3 days'
        AND decision IN ('GO', 'WAIT')
        UNION
        SELECT DISTINCT symbol FROM incubator_universe
        WHERE status = 'ACTIVE'
    """)
    screener_symbols = [r[0] for r in cur.fetchall()]
    existing = set(symbols)
    added = [s for s in screener_symbols if s not in existing]
    symbols.extend(added)
    logger.info(f"Refreshing {len(symbols)} symbols ({len(existing)} watchlist + {len(added)} screener/incubator)...")

    success = 0
    confluence_flips: list[dict] = []
    for s in symbols:
        try:
            r = analyze_confluence(s, 'swing')
            if r.get('ok'):
                # Confluence-flip detection: read the prior persisted state
                # before overwriting it, so a NEUTRAL->BULLISH_STRONG entry is
                # observable as a transition rather than silently overwritten.
                try:
                    cur.execute(
                        "SELECT full_result FROM indicator_confluence_cache "
                        "WHERE symbol=%s AND profile='swing'",
                        (s,),
                    )
                    prior_row = cur.fetchone()
                    prior_state = None
                    if prior_row and prior_row[0]:
                        prior = json.loads(prior_row[0]) if isinstance(prior_row[0], str) else prior_row[0]
                        prior_state = (prior.get("confluence_v2") or {}).get("state")
                except Exception:
                    prior_state = None
                new_state = (r.get("confluence_v2") or {}).get("state")
                aff = (r.get("confluence_v2") or {}).get("oscillator_affiliation")
                if prior_state is not None and new_state:
                    confluence_flips.append({
                        "symbol": s, "prior_state": prior_state,
                        "new_state": new_state, "affiliation": aff,
                    })

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

    # Confluence-flip alerting: bounded, deduped, DIGEST only. A failure here
    # must never fail the cache refresh, so it is fully best-effort.
    if confluence_flips:
        try:
            from oscillator_alerts import detect_confluence_flips, notify_confluence_flips
            from telegram_alert import send_telegram

            flips = detect_confluence_flips(confluence_flips)
            if flips:
                outcome = notify_confluence_flips(
                    flips, send_fn=send_telegram,
                    session=datetime.now(timezone.utc).date().isoformat(),
                )
                logger.info(
                    "confluence flips: %d sent, %d suppressed",
                    len(outcome.get("sent") or []),
                    len(outcome.get("suppressed") or []),
                )
        except Exception as e:
            # ALARM-DELIVERY-DECLARED: confluence-flip alerting is best-effort and
            # must never fail the pre-market cache refresh. notify_confluence_flips
            # already records each flip's dedupe state to alert_condition_state (a
            # durable store) before sending, so a failure here degrades alerting,
            # never the cache — the primary job still completes.
            logger.warning("confluence flip alerting skipped: %s", e)

    conn.close()
    logger.info(f"Refresh complete: {success}/{len(symbols)} symbols updated")

except Exception as e:
    logger.error(f"Indicator cache refresh failed: {e}")
    sys.exit(1)
