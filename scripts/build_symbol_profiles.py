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


def _first_sentence(text, maxlen=180):
    if not text:
        return None
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    s = parts[0]
    if len(s) < 40 and len(parts) > 1:      # "Visa Inc." alone says nothing — take the next sentence too
        s = f"{s} {parts[1]}"
    return (s[: maxlen - 1] + "…") if len(s) > maxlen else s


def run(symbols=None, force=False):
    from db_adapter import _get_conn
    import watch_universe as wu
    from holding_proxies import HOLDING_PROXY_MAP
    conn = _get_conn(); cur = conn.cursor()
    uni = sorted(set(s.upper() for s in symbols) if symbols
                 else wu.symbols(cur) | set(HOLDING_PROXY_MAP))
    if not force:
        cur.execute("""SELECT symbol FROM symbol_profiles
                       WHERE updated_at > now() - interval '30 days' AND description_1s IS NOT NULL""")
        fresh = {r[0] for r in cur.fetchall()}
        uni = [s for s in uni if s not in fresh]
    if not uni:
        print(json.dumps({"status": "fresh", "updated": 0}))
        return
    import yfinance as yf
    updated = missed = 0
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
        desc = _first_sentence(info.get("longBusinessSummary"))
        sector = info.get("sector") or None
        industry = info.get("industry") or None
        if not (desc or sector):
            missed += 1
            continue
        cur.execute("""INSERT INTO symbol_profiles (symbol, description_1s, sector, industry, source, updated_at)
                       VALUES (%s,%s,%s,%s,'yfinance',now())
                       ON CONFLICT (symbol) DO UPDATE SET description_1s=EXCLUDED.description_1s,
                         sector=EXCLUDED.sector, industry=EXCLUDED.industry, source='yfinance', updated_at=now()""",
                    (sym, desc, sector, industry))
        updated += 1
    conn.commit()
    print(json.dumps({"checked": len(uni), "updated": updated, "no_profile": missed}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    run(symbols=a.symbols.split(",") if a.symbols else None, force=a.force)
