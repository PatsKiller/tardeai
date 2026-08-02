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


_TICKER_RE = __import__("re").compile(r"^[A-Z][A-Z0-9.\-]{0,5}$")


def _is_tradeable_ticker(sym: str) -> bool:
    """Drop CUSIPs / junk ids that Yahoo cannot resolve (e.g. 12507E201)."""
    s = str(sym or "").upper().strip()
    if not s or not _TICKER_RE.match(s):
        return False
    if s[0].isdigit():
        return False
    return True


def _main_lane_symbols(cur) -> list[str]:
    try:
        from lib.watch_lane_admission import main_sql_source_clause, load_policy
        main_sql, main_params = main_sql_source_clause(load_policy())
        cur.execute(
            f"""
            SELECT DISTINCT upper(wi.symbol)
            FROM watchlist_items wi
            WHERE wi.status <> 'removed' AND {main_sql}
            ORDER BY 1
            """,
            main_params,
        )
        out = [r[0] for r in cur.fetchall() if r[0] and _is_tradeable_ticker(r[0])]
        return out
    except Exception as e:
        logger.warning("MAIN lane symbol load skipped: %s", e)
        return []


def _stale_or_missing(cur, symbols: list[str], *, max_age_h: int = 36) -> list[str]:
    if not symbols:
        return []
    cur.execute(
        """
        SELECT upper(m.symbol) AS symbol
        FROM unnest(%s::text[]) AS m(symbol)
        LEFT JOIN indicator_confluence_cache i
          ON upper(i.symbol) = upper(m.symbol) AND i.profile = 'swing'
        WHERE i.symbol IS NULL
           OR i.computed_at < NOW() - make_interval(hours => %s)
        ORDER BY 1
        """,
        (symbols, int(max_age_h)),
    )
    return [r[0] for r in cur.fetchall() if r[0] and _is_tradeable_ticker(r[0])]


def _exit_symbols(cur, *, exits_days: int) -> list[str]:
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
    return [r[0] for r in cur.fetchall() if r[0] and _is_tradeable_ticker(r[0])]


def _operator_desk_symbols(cur, *, exits_days: int, max_age_h: int = 36) -> list[str]:
    """Watch MAIN + Re-Entry exit gaps — one list for health agent / weekend desk ops."""
    main_syms = _main_lane_symbols(cur)
    exit_syms = _exit_symbols(cur, exits_days=exits_days)
    main_miss = _stale_or_missing(cur, main_syms, max_age_h=max_age_h)
    exit_miss = _stale_or_missing(cur, exit_syms, max_age_h=max_age_h)
    # MAIN first (operator setup desk), then Re-Entry exits not already covered
    main_set = set(main_miss)
    ordered = list(main_miss) + [s for s in exit_miss if s not in main_set]
    logger.info(
        "Operator desks missing/stale RSI: MAIN=%s/%s · Re-Entry exits=%s/%s → unique=%s",
        len(main_miss),
        len(main_syms),
        len(exit_miss),
        len(exit_syms),
        len(ordered),
    )
    return ordered


def _load_symbols(
    cur,
    *,
    exits_days: int,
    missing_exits_only: bool,
    main_missing_only: bool = False,
    operator_desks: bool = False,
    max_age_h: int = 36,
) -> list[str]:
    """Return symbols with MAIN desk gaps first (so --limit serves the operator desk)."""
    main_syms = _main_lane_symbols(cur)
    if operator_desks:
        return _operator_desk_symbols(cur, exits_days=exits_days, max_age_h=max_age_h)
    if main_missing_only:
        missing = _stale_or_missing(cur, main_syms, max_age_h=max_age_h)
        logger.info("MAIN missing/stale RSI: %s / %s", len(missing), len(main_syms))
        return missing

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
    exit_syms = _exit_symbols(cur, exits_days=exits_days)
    if missing_exits_only:
        symbols = _stale_or_missing(cur, exit_syms, max_age_h=max_age_h)
        logger.info(
            "Missing/stale exited symbols for refresh: %s (exits_days=%s)",
            len(symbols),
            exits_days,
        )
        return symbols

    before = len(set(symbols))
    symbols.extend(exit_syms)
    symbols.extend(main_syms)
    logger.info("Added MAIN lane symbols for refresh: %s", len(main_syms))
    logger.info(
        "Universe watchlist/screener=%s + exits=%s → unique=%s",
        before,
        len(exit_syms),
        len(set(symbols)),
    )

    # MAIN missing/stale first, then other MAIN, then the rest — never truncate MAIN off via --limit
    uniq = {str(s).upper() for s in symbols if s}
    main_set = {str(s).upper() for s in main_syms if s}
    main_missing = set(_stale_or_missing(cur, sorted(main_set)))
    main_fresh = sorted(main_set - main_missing)
    rest = sorted(uniq - main_set)
    ordered = sorted(main_missing) + main_fresh + rest
    logger.info(
        "Priority order: MAIN missing=%s, MAIN fresh=%s, rest=%s",
        len(main_missing),
        len(main_fresh),
        len(rest),
    )
    return ordered


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh indicator_confluence_cache")
    ap.add_argument("--exits-days", type=int, default=365, help="Include sells within N days")
    ap.add_argument(
        "--missing-exits-only",
        action="store_true",
        help="Only refresh exited symbols missing cache or older than 36h",
    )
    ap.add_argument(
        "--main-missing-only",
        action="store_true",
        help="Only refresh MAIN-lane symbols missing cache or older than max-age",
    )
    ap.add_argument(
        "--operator-desks",
        action="store_true",
        help="Watch MAIN + Re-Entry exit gaps (health agent / weekend operator path)",
    )
    ap.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbol list (overrides universe selection)",
    )
    ap.add_argument("--limit", type=int, default=0, help="Max symbols this run (0 = all)")
    ap.add_argument("--sleep-ms", type=int, default=350, help="Delay between symbols (Yahoo rate limit)")
    ap.add_argument("--max-age-hours", type=int, default=36, help="Stale threshold for missing-only modes")
    ap.add_argument("--profile", default="swing")
    args = ap.parse_args()

    from indicator_engine import analyze_confluence
    import time

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
        if str(args.symbols or "").strip():
            symbols = [
                s.strip().upper()
                for s in str(args.symbols).split(",")
                if s.strip() and _is_tradeable_ticker(s.strip())
            ]
            logger.info("Explicit symbol list: %s", len(symbols))
        else:
            symbols = _load_symbols(
                cur,
                exits_days=args.exits_days,
                missing_exits_only=args.missing_exits_only,
                main_missing_only=args.main_missing_only,
                operator_desks=args.operator_desks,
                max_age_h=int(args.max_age_hours),
            )
        if args.limit and args.limit > 0:
            symbols = symbols[: args.limit]
            logger.info("Limited to first %s symbols (MAIN-first order)", args.limit)

        logger.info("Refreshing %s symbols (profile=%s)...", len(symbols), args.profile)
        success = 0
        rate_hits = 0
        for idx, s in enumerate(symbols):
            try:
                if idx and args.sleep_ms > 0:
                    time.sleep(args.sleep_ms / 1000.0)
                r = analyze_confluence(s, args.profile)
                if not r.get("ok"):
                    logger.warning("  %s: analyze_confluence not ok (%s)", s, r.get("error") or "unknown")
                    # Consecutive OHLCV misses usually mean Yahoo rate limit
                    rate_hits += 1
                    time.sleep(min(45, 3 + rate_hits * 3))
                    if rate_hits >= 10:
                        logger.error("Yahoo rate limit persistent — stopping early (%s ok so far)", success)
                        break
                    continue
                rate_hits = 0
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
