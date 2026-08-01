"""
indicator_cache_refresh.py
Refresh indicator_confluence_cache for watchlist + portfolio + screener + exited re-entry symbols.

Cadence (intended): 5:45 AM Mon–Fri via cron, plus health-agent auto-remediation when stale/missing.
Decision Desk READY gates require RSI from this cache — exited names must be included or they show MISSING MARKET.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

env_path = Path(".env")
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


def _load_symbols(cur, *, exits_days: int, missing_exits_only: bool) -> list[str]:
    symbols: list[str] = []
    if not missing_exits_only:
        cur.execute(
            "SELECT DISTINCT upper(symbol) FROM watchlist_symbol_master "
            "WHERE in_ai_watchlist=true OR in_personal_watchlist=true OR in_portfolio=true"
        )
        symbols.extend(r[0] for r in cur.fetchall() if r[0])

        cur.execute(
            """
            SELECT DISTINCT upper(symbol) FROM trade_ai_scans
            WHERE scanned_at > NOW() - INTERVAL '3 days'
              AND decision IN ('GO', 'WAIT')
            UNION
            SELECT DISTINCT upper(symbol) FROM incubator_universe
            WHERE status = 'ACTIVE'
            """
        )
        symbols.extend(r[0] for r in cur.fetchall() if r[0])

    # Re-Entry Decision Desk universe — price alone is not enough; RSI lives here.
    cur.execute(
        """
        SELECT DISTINCT upper(symbol) AS symbol
        FROM trade_transactions
        WHERE trade_date >= CURRENT_DATE - %s
          AND (lower(coalesce(action,'')) IN
                 ('sell','sold','assigned','assignment','expired','exercise','exercised','close','closed')
               OR lower(coalesce(action,'')) LIKE 'sell%%')
        """,
        (int(exits_days),),
    )
    exit_syms = [r[0] for r in cur.fetchall() if r[0]]
    if missing_exits_only:
        cur.execute(
            """
            SELECT DISTINCT upper(e.symbol)
            FROM (
              SELECT DISTINCT upper(symbol) AS symbol
              FROM trade_transactions
              WHERE trade_date >= CURRENT_DATE - %s
                AND (lower(coalesce(action,'')) IN
                       ('sell','sold','assigned','assignment','expired','exercise','exercised','close','closed')
                     OR lower(coalesce(action,'')) LIKE 'sell%%')
            ) e
            LEFT JOIN indicator_confluence_cache i
              ON upper(i.symbol) = e.symbol AND i.profile = 'swing'
            WHERE i.symbol IS NULL
               OR i.computed_at < NOW() - INTERVAL '36 hours'
            ORDER BY 1
            """,
            (int(exits_days),),
        )
        symbols = [r[0] for r in cur.fetchall() if r[0]]
        logger.info(
            "Missing/stale exited symbols for refresh: %s (exits_days=%s)",
            len(symbols),
            exits_days,
        )
    else:
        before = len(set(symbols))
        symbols.extend(exit_syms)
        logger.info(
            "Universe watchlist/screener=%s + exits=%s → unique=%s",
            before,
            len(exit_syms),
            len(set(symbols)),
        )

    # Stable unique order
    return sorted({str(s).upper() for s in symbols if s})


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh indicator_confluence_cache")
    ap.add_argument("--exits-days", type=int, default=365, help="Include sells within N days")
    ap.add_argument(
        "--missing-exits-only",
        action="store_true",
        help="Only refresh exited symbols missing cache or older than 36h",
    )
    ap.add_argument("--limit", type=int, default=0, help="Max symbols this run (0 = all)")
    ap.add_argument("--profile", default="swing")
    args = ap.parse_args()

    from indicator_engine import analyze_confluence

    try:
        import psycopg2
    except Exception as e:
        logger.error("psycopg2 required: %s", e)
        return 1

    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.getenv("DB_NAME", "trade_ai"),
            user=os.getenv("DB_USER", "trade_ai"),
            password=os.getenv("DB_PASSWORD", ""),
        )
        cur = conn.cursor()
        symbols = _load_symbols(
            cur,
            exits_days=args.exits_days,
            missing_exits_only=args.missing_exits_only,
        )
        if args.limit and args.limit > 0:
            symbols = symbols[: args.limit]
            logger.info("Limited to first %s symbols", args.limit)

        logger.info("Refreshing %s symbols (profile=%s)...", len(symbols), args.profile)
        success = 0
        for s in symbols:
            try:
                r = analyze_confluence(s, args.profile)
                if not r.get("ok"):
                    logger.warning("  %s: analyze_confluence not ok", s)
                    continue
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
                    (
                        s,
                        args.profile,
                        r.get("confluence_score", 0),
                        r.get("confluence_tier"),
                        r.get("signals_bullish", 0),
                        r.get("signals_bearish", 0),
                        r.get("signals_neutral", 0),
                        r.get("strategy_badges", []),
                        r.get("bearish_badges", []),
                        json.dumps(r.get("key_levels", {})),
                        r.get("stop_price"),
                        r.get("target_price"),
                        r.get("atr"),
                        r.get("adx_regime"),
                        r.get("entry_quality"),
                        json.dumps(r),
                    ),
                )
                conn.commit()
                success += 1
                logger.info("  %s: %s (%s bullish)", s, r.get("confluence_tier"), r.get("signals_bullish"))
                try:
                    from intelligence_entity_manager import upsert_entity as _iem_upsert

                    _iem_upsert(
                        conn,
                        s,
                        "market",
                        {
                            "confluence_tier": r.get("confluence_tier"),
                            "confluence_score": r.get("confluence_score"),
                            "confluence_badges": r.get("strategy_badges", []),
                            "confluence_profile": args.profile,
                            "confluence_updated": datetime.now(timezone.utc),
                            "atr_value": r.get("atr"),
                            "volatility_regime": r.get("adx_regime"),
                        },
                        source="indicator_engine",
                    )
                except Exception:
                    pass
            except Exception as e:
                logger.warning("  %s: FAILED %s", s, e)
                conn.rollback()

        conn.close()
        logger.info("Refresh complete: %s/%s symbols updated", success, len(symbols))
        return 0 if success or not symbols else 1
    except Exception as e:
        logger.error("Indicator cache refresh failed: %s", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
