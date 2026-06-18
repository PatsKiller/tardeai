#!/usr/bin/env python3
"""etf_analyst_enrich.py — give ETFs (and funds) an "analyst prediction".

ETFs/funds do NOT get traditional sell-side price targets (analysts cover companies, not baskets). So we
produce TWO honest signals and store them in symbol_profiles:
  1. direct: yfinance analyst fields if the provider has any (rare for ETFs);
  2. look_through_upside: the holdings-weighted average analyst upside of the ETF's top constituents — i.e.
     "what do analysts think of what this ETF actually holds." This is the defensible analyst view for a
     basket. For inverse ETFs the sign is flipped (short exposure).

Read-only re: trading. Bounded + polite (yfinance). Run after classify_instruments.py.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent
from db_adapter import _get_conn


def _holding_upsides(cur, symbols):
    """Latest analyst upside_pct per holding from yahoo_analyst_targets_history (target vs current)."""
    if not symbols:
        return {}
    cur.execute("""SELECT DISTINCT ON (symbol) symbol, target_mean_price, current_price
                   FROM yahoo_analyst_targets_history WHERE upper(symbol)=ANY(%s)
                   ORDER BY symbol, created_at DESC""", ([s.upper() for s in symbols],))
    out = {}
    for s, tm, cp in cur.fetchall():
        if tm and cp and float(cp) > 0:
            out[s.upper()] = round((float(tm) - float(cp)) / float(cp) * 100, 1)
    return out


def main():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("ALTER TABLE symbol_profiles ADD COLUMN IF NOT EXISTS analyst_look_through_pct numeric")
    cur.execute("ALTER TABLE symbol_profiles ADD COLUMN IF NOT EXISTS analyst_basis text")
    conn.commit()
    cur.execute("""SELECT upper(symbol), instrument_type, direction_hint FROM symbol_profiles
                   WHERE instrument_type IN ('etf','inverse_etf','fund')""")
    etfs = cur.fetchall()
    try:
        import yfinance as yf
        import time as _t
        from db_adapter import save_yahoo_analyst_targets_history
    except Exception as e:
        print("yfinance unavailable:", e)
        return 1

    # Pass 1: top holdings + weights per ETF (and direct provider target if any).
    etf_holdings, direct_up = {}, {}
    for sym, itype, direction in etfs[:45]:
        _t.sleep(0.8)
        try:
            tk = yf.Ticker(sym)
            info = tk.info
            tm, cp = info.get("targetMeanPrice"), info.get("currentPrice") or info.get("regularMarketPrice")
            if tm and cp and cp > 0:
                direct_up[sym] = round((tm - cp) / cp * 100, 1)
            fd = getattr(tk, "funds_data", None)
            top = fd.top_holdings if fd is not None else None
            if top is not None and len(top):
                etf_holdings[sym] = [(str(s).upper(), float(w)) for s, w in zip(top.index, top.iloc[:, -1])][:12]
        except Exception:
            continue

    # Pass 2: fetch analyst for constituents we don't already have (dedup, bounded), save to history.
    have = set()
    cur.execute("SELECT DISTINCT upper(symbol) FROM yahoo_analyst_targets_history")
    have = {r[0] for r in cur.fetchall()}
    need = sorted({h for hs in etf_holdings.values() for h, _ in hs} - have)
    import datetime
    ds = datetime.datetime.now().strftime("%Y-%m-%d")
    fetched = 0
    for s in need[:120]:
        _t.sleep(0.8)
        try:
            info = yf.Ticker(s).info
            tm, nop = info.get("targetMeanPrice"), info.get("numberOfAnalystOpinions")
            if tm is None and not nop:
                continue
            save_yahoo_analyst_targets_history([{"symbol": s, "current_price": info.get("currentPrice"),
                "target_mean_price": tm, "target_high_price": info.get("targetHighPrice"),
                "target_low_price": info.get("targetLowPrice"), "target_median_price": info.get("targetMedianPrice"),
                "recommendation_mean": info.get("recommendationMean"),
                "recommendation_key": info.get("recommendationKey"), "number_of_analyst_opinions": nop}], ds)
            fetched += 1
        except Exception:
            continue

    # Pass 3: compute holdings-weighted look-through from the now-populated analyst history.
    done = 0
    dirmap = {sym: direction for sym, _, direction in etfs}
    for sym, hs in etf_holdings.items():
        holds = [h for h, _ in hs]
        wts = {h: w for h, w in hs}
        ups = _holding_upsides(cur, holds)
        ncov = len([h for h in holds if h in ups])
        num = sum(wts[h] * ups[h] for h in holds if h in ups)
        den = sum(wts[h] for h in holds if h in ups)
        # require >=2 covered constituents — a 1-stock "look-through" isn't a basket view, just that stock.
        lt = round(num / den, 1) if (den > 0 and ncov >= 2) else None
        if lt is not None and dirmap.get(sym) == "short":
            lt = round(-lt, 1)
        final = direct_up.get(sym) if direct_up.get(sym) is not None else lt
        basis = ("direct analyst target" if sym in direct_up else
                 (f"holdings look-through ({len([h for h in holds if h in ups])} constituents)" if lt is not None else None))
        cur.execute("UPDATE symbol_profiles SET analyst_look_through_pct=%s, analyst_basis=%s WHERE upper(symbol)=%s",
                    (final, basis, sym))
        if final is not None:
            done += 1
    conn.commit()
    print(json.dumps({"ok": True, "etfs_funds": len(etfs), "etfs_with_holdings": len(etf_holdings),
                      "constituents_fetched": fetched, "with_analyst_view": done}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
