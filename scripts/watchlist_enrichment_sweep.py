#!/usr/bin/env python3
"""watchlist_enrichment_sweep.py — E-1: standing enrichment sweep over the active watchlist.

The watchlist cards were data-starved because enrichment only ran on-demand at promotion. This sweep
fills rsi/trend/score/setup_advisory/price for ALL active watchlist_items, REUSING existing
computations (no new indicators):
  - rsi/float/rvol/sma  ← finviz_enrichment.get_enriched (cache; enrich_tickers refreshes it)
  - price/change%       ← market_quotes (Alpaca-primary, kept current by the repricer — not duplicated)
  - trend               ← open_trades_intelligence._trend_label(sma50, sma200)   (same as holdings cards)
  - setup_advisory band ← setup_quality_prior.rsi_band()                          (same band as the ⚠ badge)
  - watch score         ← directive_promotion.classify_tradeable (Bucket 2/3 ONLY; scalp/Bucket-1 excluded)

HARD: never reads/writes scalp screeners; never writes holdings.json; idempotent; fail-closed
(enrichment failure → leave prior values, mark nothing fake, log). Runs under the app role.

  python3 scripts/watchlist_enrichment_sweep.py --once [--limit N]
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))
from watchlist_priority import (
    WATCHLIST_TOP_N, daily_priority_sql_params, is_off_hours_et, off_hours_top_n,
    sql_daily_priority_exists,
)

BATCH = 15  # Finviz-Elite rate-limit aware


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _price(conn, symbol):
    try:
        cur = conn.cursor()
        cur.execute("""SELECT price, day_change_pct FROM market_quotes WHERE symbol=%s
                       AND fetched_at > NOW() - INTERVAL '12 hours'
                       ORDER BY fetched_at DESC LIMIT 1""", (symbol,))
        r = cur.fetchone()
        if r and r[0] is not None:
            return float(r[0]), (float(r[1]) if r[1] is not None else None)
    except Exception:
        pass
    # Fallback: no FRESH market_quotes row (e.g. a brand-new IPO the Alpaca/finviz repricer lags on) →
    # pull from yfinance and backfill market_quotes so downstream stays current.
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info or {}
        px, prev = info.get("regularMarketPrice"), info.get("regularMarketPreviousClose")
        if px:
            chg = round((px - prev) / prev * 100, 2) if prev else None
            try:
                cur = conn.cursor()
                cur.execute("INSERT INTO market_quotes (symbol, price, day_change_pct, source, fetched_at) "
                            "VALUES (%s,%s,%s,'yfinance',NOW())", (symbol, px, chg))
                conn.commit()
            except Exception:
                conn.rollback()
            return float(px), chg
    except Exception:
        pass
    return None, None


def _num(v):
    try:
        return float(str(v).replace("%", "").replace(",", "")) if v not in (None, "", "-") else None
    except Exception:
        return None


def enrich_symbols(symbols: list[str], *, dry: bool = False) -> dict:
    """Enrich explicit symbols (used by manual watchlist refresh in CC v3)."""
    from finviz_enrichment import enrich_tickers, get_enriched
    from open_trades_intelligence import _trend_label
    from setup_quality_prior import rsi_band
    import directive_promotion as dp

    syms = [str(s).upper().strip() for s in symbols if s and str(s).strip()]
    syms = list(dict.fromkeys(syms))
    if not syms:
        return {"total": 0, "enriched": 0, "symbols": []}

    conn = _conn()
    cur = conn.cursor()
    enriched = 0
    for i in range(0, len(syms), BATCH):
        batch = syms[i:i + BATCH]
        try:
            enrich_tickers(batch, project_root=str(PROJECT_ROOT))
        except Exception as e:
            print(f"  [sweep] enrich_tickers batch failed (non-fatal): {str(e)[:80]}")
        for sym in batch:
            try:
                tech = get_enriched(sym, project_root=str(PROJECT_ROOT)) or {}
                rsi = _num(tech.get("rsi"))
                sma50, sma200 = _num(tech.get("sma50_pct")), _num(tech.get("sma200_pct"))
                trend = _trend_label(sma50, sma200)
                floatm, rvol = _num(tech.get("float_m")), _num(tech.get("rvol"))
                price, chg = _price(conn, sym)
                if price is not None:
                    tech["price"] = price
                band = rsi_band(rsi) if rsi is not None else None
                advisory = (f"RSI {rsi:.0f} · band {band}" if rsi is not None else "awaiting enrichment")

                score, score_kind = None, None
                if price is not None:
                    try:
                        qual = dp.classify_tradeable(sym, tech)
                        if qual:
                            base = min(95, 55 + 8 * len(qual))
                            score, score_kind = base, "strategy_qualified"
                    except Exception:
                        pass
                if score is None and rsi is not None:
                    t = {"bullish": 18, "neutral": 8, "bearish": 0}.get(trend, 5)
                    score, score_kind = round(40 + t + (10 if 40 <= (rsi or 0) <= 60 else 0)), "technical"

                if dry:
                    print(f"  {sym}: rsi={rsi} trend={trend} price={price} score={score}({score_kind}) {advisory}")
                    continue
                cur.execute("""UPDATE watchlist_items SET
                                 rsi=%s, trend=%s, score=COALESCE(%s, score), setup_advisory=%s,
                                 price=%s, change_pct=%s, float_m=%s, rvol=%s,
                                 first_seen_price=COALESCE(first_seen_price, %s),
                                 watch_score_kind=%s, last_enriched_at=NOW(), updated_at=NOW()
                               WHERE symbol=%s AND status IN ('active','researched')""",
                            (rsi, trend, score, advisory, price, chg, floatm, rvol, price, score_kind, sym))
                if cur.rowcount:
                    enriched += 1
            except Exception as e:
                print(f"  [sweep] {sym} failed (non-fatal): {str(e)[:80]}")
        if not dry:
            conn.commit()
    # Persist intraday quotes into ticker_prices so strategy cards / agents see close history.
    if not dry and syms:
        try:
            from price_db_sync import sync_quotes_to_ticker_prices
            sync_quotes_to_ticker_prices(syms)
        except Exception as e:
            print(f"  [sweep] ticker_prices sync failed (non-fatal): {str(e)[:80]}")
    conn.close()
    return {"total": len(syms), "enriched": enriched, "symbols": syms}


def sweep(limit=None, dry=False):
    conn = _conn(); cur = conn.cursor()
    # Two-tier selection so the VISIBLE high-rank cards stay fresh (under the 1h stale flag) without
    # starving the long tail. The research pipeline moves items active→researched within hours; the
    # watchlist UI shows both, so enrich both.
    #  • PRIORITY pool = directive-linked OR active OR Hermes top-ranked (rank <= RANK_PRIORITY),
    #    rotated stalest-first — the cards the operator actually looks at (e.g. ELVN #3, SNOW #135).
    #  • TAIL = remainder of the cap, stalest-first over everyone else, so nothing is permanently
    #    starved. */30 intraday + post-close runs cycle the set; bounded cap keeps Finviz happy.
    off_hours = is_off_hours_et()
    cap = int(limit) if limit else 180
    if off_hours:
        cap = off_hours_top_n(limit) or WATCHLIST_TOP_N
    RANK_PRIORITY = WATCHLIST_TOP_N
    if off_hours:
        prio_limit = cap
    else:
        TAIL_MIN = max(30, cap // 4)
        prio_limit = max(cap - TAIL_MIN, 1)
    daily_sql = sql_daily_priority_exists("wi.symbol")
    dp = daily_priority_sql_params(project_root=PROJECT_ROOT)
    cur.execute(f"""SELECT wi.symbol FROM watchlist_items wi
                   WHERE wi.status IN ('active','researched') AND wi.symbol IS NOT NULL
                     AND ({daily_sql}
                          OR (wi.hermes_rank IS NOT NULL AND wi.hermes_rank <= %s))
                   ORDER BY (wi.directive_id IS NULL),
                            (NOT ({daily_sql})),
                            (wi.status <> 'active'),
                            wi.last_enriched_at ASC NULLS FIRST, wi.hermes_rank ASC NULLS LAST
                   LIMIT %s""", (*dp, RANK_PRIORITY, *dp, prio_limit))
    prio = [r[0] for r in cur.fetchall() if r[0]]
    tail = []
    if not off_hours:
        rem = cap - len(prio)
        if rem > 0:
            cur.execute("""SELECT symbol FROM watchlist_items
                           WHERE status IN ('active','researched') AND symbol IS NOT NULL
                             AND NOT (symbol = ANY(%s))
                           ORDER BY last_enriched_at ASC NULLS FIRST, updated_at DESC
                           LIMIT %s""", (prio or [''], rem))
            tail = [r[0] for r in cur.fetchall() if r[0]]
    symbols = list(dict.fromkeys(prio + tail))
    mode = "off-hours-top%d" % cap if off_hours else "intraday"
    print(f"[sweep] {mode}: selected {len(symbols)}: {len(prio)} priority (holdings/proposals/buy/start/rank<={RANK_PRIORITY})"
          + (f" + {len(tail)} tail rotation" if tail else ""))
    conn.close()
    if not symbols:
        print("[sweep] no active watchlist items"); return {"total": 0, "enriched": 0}

    result = enrich_symbols(symbols, dry=dry)
    enriched = result["enriched"]
    print(f"[sweep] enriched {enriched}/{len(symbols)} active watchlist items")
    return {"total": len(symbols), "enriched": enriched}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    sweep(limit=a.limit, dry=a.dry_run)


if __name__ == "__main__":
    main()
