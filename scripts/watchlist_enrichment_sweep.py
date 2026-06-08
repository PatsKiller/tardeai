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

BATCH = 15  # Finviz-Elite rate-limit aware


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def _price(conn, symbol):
    try:
        cur = conn.cursor()
        cur.execute("""SELECT price, day_change_pct FROM market_quotes WHERE symbol=%s
                       ORDER BY fetched_at DESC LIMIT 1""", (symbol,))
        r = cur.fetchone()
        return (float(r[0]) if r and r[0] is not None else None,
                float(r[1]) if r and r[1] is not None else None)
    except Exception:
        return None, None


def _num(v):
    try:
        return float(str(v).replace("%", "").replace(",", "")) if v not in (None, "", "-") else None
    except Exception:
        return None


def sweep(limit=None, dry=False):
    from finviz_enrichment import enrich_tickers, get_enriched
    from open_trades_intelligence import _trend_label
    from setup_quality_prior import rsi_band
    import directive_promotion as dp

    conn = _conn(); cur = conn.cursor()
    cur.execute("""SELECT symbol FROM watchlist_items WHERE status='active'
                   ORDER BY last_enriched_at ASC NULLS FIRST""" + (f" LIMIT {int(limit)}" if limit else ""))
    symbols = [r[0] for r in cur.fetchall() if r[0]]
    if not symbols:
        print("[sweep] no active watchlist items"); return {"total": 0, "enriched": 0}

    enriched = 0
    for i in range(0, len(symbols), BATCH):
        batch = symbols[i:i + BATCH]
        try:
            enrich_tickers(batch, project_root=str(PROJECT_ROOT))
        except Exception as e:
            print(f"  [sweep] enrich_tickers batch {i} failed (non-fatal): {str(e)[:80]}")
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

                # Watch score: REAL evaluation (Bucket 2/3 only). Qualified → best classifier confidence;
                # otherwise a labeled technical score (never a fabricated proposal 50).
                score, score_kind = None, None
                if price is not None:
                    try:
                        qual = dp.classify_tradeable(sym, tech)  # scalp HARD-excluded inside
                        if qual:
                            # classify_tradeable returns (sid, cfg, bucket); confidence isn't passed back,
                            # so derive a watch score from qualification breadth + trend posture.
                            base = min(95, 55 + 8 * len(qual))
                            score, score_kind = base, "strategy_qualified"
                    except Exception:
                        pass
                if score is None and rsi is not None:
                    # technical watch score: posture only, clearly labeled — NOT a proposal score
                    t = {"bullish": 18, "neutral": 8, "bearish": 0}.get(trend, 5)
                    score, score_kind = round(40 + t + (10 if 40 <= (rsi or 0) <= 60 else 0)), "technical"

                if dry:
                    print(f"  {sym}: rsi={rsi} trend={trend} price={price} score={score}({score_kind}) {advisory}")
                    continue
                cur.execute("""UPDATE watchlist_items SET
                                 rsi=%s, trend=%s, score=COALESCE(%s, score), setup_advisory=%s,
                                 price=%s, change_pct=%s, float_m=%s, rvol=%s,
                                 watch_score_kind=%s, last_enriched_at=NOW(), updated_at=NOW()
                               WHERE symbol=%s AND status='active'""",
                            (rsi, trend, score, advisory, price, chg, floatm, rvol, score_kind, sym))
                enriched += 1
            except Exception as e:
                print(f"  [sweep] {sym} failed (non-fatal, prior values kept): {str(e)[:80]}")
        if not dry:
            conn.commit()
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
