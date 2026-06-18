#!/usr/bin/env python3
"""build_symbol_profiles.py — one-sentence company profiles + sector for watch-grade symbols.

Feeds the unified card layer (operator 2026-06-12): every watchlist / open-trades / portfolio card
shows what the company DOES, its sector, and sector-relative performance. Source: yfinance
longBusinessSummary (first sentence, display-sized) + sector/industry. Proxy-mapped fund codes get
their asset-class label. Refresh: only missing or >30d-old rows (profiles barely change).

  python3 scripts/build_symbol_profiles.py [--symbols X,Y] [--force]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


# ETFs have no sector in yfinance .info — give the card a real sector so it shows sector + vs-sector.
# Mirrors open_trades_intelligence._ETF_SECTOR (reference data, kept in sync).
_ETF_SECTOR = {
    "XLK": "Technology", "XLF": "Financial", "XLV": "Healthcare", "XLE": "Energy",
    "XLI": "Industrials", "XLB": "Materials", "XLU": "Utilities", "XLP": "Consumer Defensive",
    "XLY": "Consumer Cyclical", "XLRE": "Real Estate", "XLC": "Communication Services",
    "BND": "Fixed Income", "AGG": "Fixed Income", "TLT": "Fixed Income", "BNDX": "Fixed Income", "LQD": "Fixed Income",
    "JEPI": "Income / Covered Call", "JEPQ": "Income / Covered Call",
    "SCHD": "Dividend Equity", "DGRO": "Dividend Equity", "VYM": "Dividend Equity", "DIV": "Dividend Equity", "SCHG": "Growth Equity",
    "SPY": "Broad Equity", "VOO": "Broad Equity", "VTI": "Broad Equity", "QQQ": "Broad Equity", "IWM": "Broad Equity",
    "ARKG": "Healthcare", "ARKK": "Innovation", "ARKQ": "Innovation", "ARKW": "Innovation", "ARKF": "Innovation",
}

# Open-end mutual funds have no single GICS sector in yfinance either — give them an asset-class label
# so the card's sector slot isn't blank (Morningstar-style category, not a GICS sector → no vs-sector).
_FUND_SECTOR = {
    "FCNTX": "Large-Cap Growth Fund", "TILCX": "Large-Cap Growth Fund",
    "AMANX": "Equity Income Fund", "VFTNX": "Large-Cap Equity Fund (ESG)",
    "ABSZX": "Small/Mid-Cap Equity Fund",
}


def _two_line_summary(text, maxlen=300):
    """First TWO sentences of the business summary — a ~two-line 'what the company does' blurb."""
    if not text:
        return None
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    s = " ".join(parts[:2]).strip() if parts else ""
    if not s:
        return None
    return (s[: maxlen - 1] + "…") if len(s) > maxlen else s


def _finviz_map(symbols, root="."):
    """Batch Finviz sector/industry/company for plain tickers — the fallback when yfinance is
    rate-limited (it provides no business summary, so we synthesize a one-liner from company+industry)."""
    plain = [s for s in symbols if re.fullmatch(r"[A-Z]{1,5}", s)]
    if not plain:
        return {}
    try:
        import finviz_enrichment as fe
        return fe.enrich_tickers(plain, project_root=root) or {}
    except Exception as e:
        print(f"  [finviz fallback] error: {str(e)[:80]}")
        return {}


def run(symbols=None, force=False, watchlist_top=0):
    from db_adapter import _get_conn
    import watch_universe as wu
    from holding_proxies import HOLDING_PROXY_MAP
    conn = _get_conn(); cur = conn.cursor()
    uni = set(s.upper() for s in symbols) if symbols else (wu.symbols(cur) | set(HOLDING_PROXY_MAP))
    # operator 2026-06-18: also cover the top watchlist names so their cards get sector/description
    # (the unified card layer was blank for AI-discovered names — only watch_universe was profiled).
    if watchlist_top and not symbols:
        cur.execute("""SELECT symbol FROM watchlist_items WHERE status<>'removed' AND symbol ~ '^[A-Z]{1,5}$'
                       ORDER BY hermes_rank ASC NULLS LAST LIMIT %s""", (watchlist_top,))
        uni |= {r[0].upper() for r in cur.fetchall()}
    uni = sorted(uni)
    if not force:
        cur.execute("""SELECT symbol FROM symbol_profiles
                       WHERE updated_at > now() - interval '30 days' AND description_1s IS NOT NULL""")
        fresh = {r[0] for r in cur.fetchall()}
        uni = [s for s in uni if s not in fresh]
    if not uni:
        print(json.dumps({"status": "fresh", "updated": 0}))
        return
    import yfinance as yf
    fvz = _finviz_map(uni)                      # batch Finviz once (sector/industry/company)
    updated = missed = fvz_used = 0
    for sym in uni:
        if sym in HOLDING_PROXY_MAP and not re.fullmatch(r"[A-Z]{1,5}", sym):
            etf, label = HOLDING_PROXY_MAP[sym]
            cur.execute("""INSERT INTO symbol_profiles (symbol, description_1s, sector, industry, source, updated_at)
                           VALUES (%s,%s,%s,%s,'proxy_label',now())
                           ON CONFLICT (symbol) DO UPDATE SET description_1s=EXCLUDED.description_1s,
                             sector=EXCLUDED.sector, source='proxy_label', updated_at=now()""",
                        (sym, f"Retirement-plan fund — {label} (tracked via {etf} proxy).", label, None))
            updated += 1
            continue
        try:
            info = yf.Ticker(sym).info or {}
        except Exception:
            info = {}
        desc = _two_line_summary(info.get("longBusinessSummary"))
        sector = info.get("sector") or _ETF_SECTOR.get(sym) or _FUND_SECTOR.get(sym) or None
        industry = info.get("industry") or ("Exchange Traded Fund" if sym in _ETF_SECTOR
                                            else "Mutual Fund" if sym in _FUND_SECTOR else None)
        source = "yfinance"
        # ── Finviz fallback (yfinance rate-limited / empty): sector + industry + a synthesized one-liner ──
        if not (desc or sector):
            fd = fvz.get(sym) or {}
            f_sector, f_industry, f_company = fd.get("sector"), fd.get("industry"), fd.get("company")
            if f_sector or f_industry:
                sector = sector or f_sector
                industry = industry or f_industry
                if not desc:
                    bits = [b for b in (f_company, f_industry) if b]
                    desc = " — ".join(bits) + "." if bits else None
                source = "finviz"
                fvz_used += 1
        if not (desc or sector):
            missed += 1
            continue
        cur.execute("""INSERT INTO symbol_profiles (symbol, description_1s, sector, industry, source, updated_at)
                       VALUES (%s,%s,%s,%s,%s,now())
                       ON CONFLICT (symbol) DO UPDATE SET description_1s=EXCLUDED.description_1s,
                         sector=EXCLUDED.sector, industry=EXCLUDED.industry, source=EXCLUDED.source, updated_at=now()""",
                    (sym, desc, sector, industry, source))
        updated += 1
    conn.commit()
    print(json.dumps({"checked": len(uni), "updated": updated, "finviz_fallback": fvz_used, "no_profile": missed}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--watchlist-top", type=int, default=0,
                    help="also profile the top-N watchlist names by hermes_rank")
    a = ap.parse_args()
    run(symbols=a.symbols.split(",") if a.symbols else None, force=a.force, watchlist_top=a.watchlist_top)
