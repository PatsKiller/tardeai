#!/usr/bin/env python3
"""classify_instruments.py — give every symbol a first-class instrument_type (stock | etf | fund |
inverse_etf) + a direction hint, so research, proposals, and rotations can treat ETFs/funds as their own
instruments (long OR short) instead of silently dropping them.

Sources, in priority order: the curated config/etf_fund_universe.json (explicit etf/inverse/fund) →
symbol_profiles sector/description heuristics (ETF/Fund/Index keywords) → mutual-fund code heuristic
(5 letters ending in X, e.g. FCNTX/AMANX) → holdings bucket → default stock. Persists to a new
symbol_profiles.instrument_type column + writes data/runtime/instrument_types_latest.json for the UI/rotation.
Read-only re: trading.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent
from db_adapter import _get_conn

UNIVERSE = ROOT / "config" / "etf_fund_universe.json"
OUT = ROOT / "data" / "runtime" / "instrument_types_latest.json"
_FUND_CODE = re.compile(r"^[A-Z]{4,5}X$")  # mutual-fund tickers usually end in X (FCNTX, AMANX, VFIAX)
_ETF_KW = ("etf", "ishares", "spdr", "invesco qqq", "vaneck", "select sector", "index fund")


def main():
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("ALTER TABLE symbol_profiles ADD COLUMN IF NOT EXISTS instrument_type text")
    cur.execute("ALTER TABLE symbol_profiles ADD COLUMN IF NOT EXISTS direction_hint text")
    cur.execute("ALTER TABLE symbol_profiles ADD COLUMN IF NOT EXISTS expense_ratio numeric")
    cur.execute("ALTER TABLE symbol_profiles ADD COLUMN IF NOT EXISTS quote_type text")
    conn.commit()
    enrich = "--no-fetch" not in sys.argv

    # 1) curated universe = ground truth
    uni = json.loads(UNIVERSE.read_text()).get("instruments", [])
    cls = {}  # symbol -> {type, direction, source}
    for it in uni:
        cls[it["symbol"].upper()] = {"type": it["type"], "direction": it.get("direction", "long"),
                                     "category": it.get("category"), "sleeve": it.get("sleeve"),
                                     "name": it.get("name"), "source": "universe"}

    # 2) classify the rest from symbol_profiles + holdings
    cur.execute("SELECT upper(symbol), sector, description_1s FROM symbol_profiles")
    for sym, sector, desc in cur.fetchall():
        if sym in cls:
            continue
        text = f"{sector or ''} {desc or ''}".lower()
        if _FUND_CODE.match(sym) or "fund" in (sector or "").lower():
            cls[sym] = {"type": "fund", "direction": "long", "source": "heuristic"}
        elif any(k in text for k in _ETF_KW) or (sector or "").lower().endswith("equity") and "schwab" in text:
            cls[sym] = {"type": "etf", "direction": "long", "source": "heuristic"}
        else:
            cls[sym] = {"type": "stock", "direction": "long", "source": "default"}

    # 3) holdings codes (401k fund proxies like 3905) -> fund
    try:
        hj = json.loads((ROOT / "data" / "portfolios" / "state" / "holdings.json").read_text())
        for h in hj.get("holdings", []):
            sym = (h.get("symbol") or "").upper()
            if not sym:
                continue
            buck = (h.get("bucket") or "").lower()
            if sym not in cls:
                if "fund" in buck or not re.match(r"^[A-Z]{1,5}$", sym):
                    cls[sym] = {"type": "fund", "direction": "long", "source": "holdings"}
    except Exception:
        pass

    # AUTHORITATIVE: yfinance quoteType (ETF/MUTUALFUND/INDEX/EQUITY) is the source of truth for instrument
    # type — it overrides the heuristics so ANY ETF/fund is caught, not just the curated set. We CACHE it in
    # symbol_profiles.quote_type so each run (a) applies every already-known type instantly with NO fetch,
    # and (b) only fetches symbols not yet typed. That's the fix for new tickers (e.g. DIVI/SCHY) silently
    # defaulting to 'stock' and never being re-checked: previously the fetch was capped and skipped them.
    _QMAP = {"ETF": "etf", "MUTUALFUND": "fund", "INDEX": "stock", "EQUITY": "stock"}
    exp, qt = {}, {}

    # 1) apply CACHED quote_type to every symbol (authoritative; instant; no network)
    cur.execute("SELECT upper(symbol), quote_type FROM symbol_profiles WHERE quote_type IS NOT NULL")
    for s, q in cur.fetchall():
        m = _QMAP.get((q or "").upper())
        if m and s in cls and cls[s].get("source") != "universe":
            cls[s]["type"] = m

    # 2) fetch quoteType for symbols NOT yet cached — prioritises new/unknown tickers, converges over runs
    if enrich:
        cur.execute("SELECT upper(symbol) FROM symbol_profiles WHERE quote_type IS NULL ORDER BY upper(symbol)")
        to_fetch = [r[0] for r in cur.fetchall() if r[0] in cls]
        # Release the read txn — the yfinance loop below runs for minutes and PG kills
        # idle-in-transaction at 120s, which also killed the batch UPDATE after it: the
        # whole weekly run's classifications were silently discarded (180 nulls piled up).
        conn.commit()
        try:
            import yfinance as yf, time as _t
            for s in to_fetch[:300]:                       # bounded per run; cached ones are skipped so this converges
                _t.sleep(0.8)
                try:
                    info = yf.Ticker(s).info
                    q = (info.get("quoteType") or "").upper()
                    if q:
                        qt[s] = q                          # cached for next run
                        m = _QMAP.get(q)
                        if m and cls[s].get("source") != "universe":
                            cls[s]["type"] = m              # quoteType wins over the heuristic
                    # DETERMINISTIC expense-ratio normalization (fix 2026-06-21, was a `while v>0.02` heuristic
                    # that let stale/mis-scaled values through — FCNTX read 1.47% vs true 0.74%). yfinance gives
                    # annualReportExpenseRatio as a FRACTION (0.0074) and netExpenseRatio as a PERCENT (0.74) —
                    # prefer the fraction, else percent/100. Reject >2.5% as mis-scaled. See validate_expense_ratios.py.
                    _ar = info.get("annualReportExpenseRatio")
                    _net = info.get("netExpenseRatio")
                    v = None
                    if isinstance(_ar, (int, float)) and _ar > 0:
                        v = float(_ar)
                    elif isinstance(_net, (int, float)) and _net > 0:
                        v = float(_net) / 100.0
                    if v is not None and 0 < v <= 0.025:
                        exp[s] = round(v, 6)
                except Exception:
                    continue
        except Exception as e:
            print("  yfinance enrichment skipped (non-fatal):", str(e)[:80])

    # persist instrument_type + expense ratio + quote_type back to symbol_profiles
    upd = 0
    for sym, info in cls.items():
        cur.execute("""UPDATE symbol_profiles SET instrument_type=%s, direction_hint=%s,
                         expense_ratio=COALESCE(%s, expense_ratio), quote_type=COALESCE(%s, quote_type)
                       WHERE upper(symbol)=%s""",
                    (info["type"], info["direction"], exp.get(sym), qt.get(sym), sym))
        upd += cur.rowcount
    conn.commit()

    counts = {}
    for info in cls.values():
        counts[info["type"]] = counts.get(info["type"], 0) + 1
    OUT.write_text(json.dumps({"types": {s: i["type"] for s, i in cls.items()},
                               "detail": cls, "counts": counts}, indent=2))
    print(json.dumps({"ok": True, "classified": len(cls), "profile_rows_updated": upd, "counts": counts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
