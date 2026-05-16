"""strategy_watchpool.py — Watchpool reader + writer for Bucket 2/3 strategies (Phase B-1c).

Behavior gates (all must pass for watchpool to activate):
  1. cfg.freshness.watchpool == True
  2. cfg.freshness.get('rollback_to_legacy') != True
  3. cfg.freshness.bucket in ('MULTI_DAY', 'LONG_CYCLE')

If any gate fails, watchpool is bypassed and legacy path runs unchanged.
"""
import json
import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

log = logging.getLogger(__name__)


def _get_conn():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def is_watchpool_active(cfg: dict) -> bool:
    """Single source of truth for the gate decision."""
    fresh = cfg.get('freshness') or {}
    if not fresh.get('watchpool'):
        return False
    if fresh.get('rollback_to_legacy'):
        return False
    if fresh.get('bucket') not in ('MULTI_DAY', 'LONG_CYCLE'):
        return False
    return True


def maybe_write_watchpool(strategy_id: str, symbol: str, screener_id: str,
                          snapshot: dict, cfg: dict) -> bool:
    """Called from signal write path. No-op if strategy isn't watchpool-routed.
    Returns True if row was inserted, False otherwise."""
    if not is_watchpool_active(cfg):
        return False

    fresh = cfg['freshness']
    ttl_days = fresh.get('ttl_days', 10)
    bucket = fresh['bucket']

    conn = _get_conn()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO strategy_watchpool
                (strategy_id, symbol, screener_id, entry_snapshot, expires_at, bucket)
            SELECT %s, %s, %s, %s::jsonb,
                   NOW() + (%s || ' days')::interval, %s
            WHERE NOT EXISTS (
                SELECT 1 FROM strategy_watchpool
                WHERE strategy_id = %s AND symbol = %s AND current_status = 'ACTIVE'
            )
            RETURNING id;
        """, (strategy_id, symbol, screener_id, json.dumps(snapshot, default=str),
              str(ttl_days), bucket, strategy_id, symbol))
        row = cur.fetchone()
        conn.commit()
        if row:
            log.info(f"watchpool: +{strategy_id}/{symbol} ttl={ttl_days}d bucket={bucket}")
            return True
        return False
    except Exception as e:
        conn.rollback()
        log.warning(f"watchpool write failed (non-fatal): {strategy_id}/{symbol}: {e}")
        return False
    finally:
        conn.close()
