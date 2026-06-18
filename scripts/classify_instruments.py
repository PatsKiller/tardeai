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

    # AUTHORITATIVE pass: yfinance quoteType + expense ratio for every non-stock candidate (and confirm
    # heuristic stocks aren't actually ETFs/funds). quoteType (ETF/MUTUALFUND/EQUITY/INDEX) corrects the
    # heuristics so ANY ETF/fund flowing through the system is captured, not just the curated universe; and
    # ETFs/funds get their expense ratio. Bounded + polite; --no-fetch skips it.
    exp = {}  # symbol -> expense_ratio (fraction, e.g. 0.0009)
    qt = {}   # symbol -> quoteType
    if enrich:
        # fetch for everything not obviously a plain stock; cap to keep it bounded/polite
        fetch_syms = [s for s, i in cls.items() if i["type"] != "stock" or _FUND_CODE.match(s) or len(s) <= 4]
        try:
            import yfinance as yf, time as _t
            for s in fetch_syms[:120]:
                _t.sleep(0.9)
                try:
                    info = yf.Ticker(s).info
                    q = (info.get("quoteType") or "").upper()
                    if q:
                        qt[s] = q
                        mapped = {"ETF": "etf", "MUTUALFUND": "fund", "INDEX": "stock", "EQUITY": "stock"}.get(q)
                        # don't override a curated inverse_etf; otherwise trust quoteType
                        if mapped and cls[s].get("source") != "universe":
                            cls[s]["type"] = mapped
                        elif mapped == "etf" and cls[s]["type"] == "stock":
                            cls[s]["type"] = "etf"
                    er = info.get("netExpenseRatio")
                    if er is None:
                        er = info.get("annualReportExpenseRatio")
                    if isinstance(er, (int, float)) and er > 0:
                        # yfinance is inconsistent (fraction 0.0009 vs percent-number 0.09 vs 3.0). Normalize
                        # to a fraction: real ETF/fund expense ratios are < ~2%, so anything implying >2% is
                        # mis-scaled and gets divided down until sane.
                        v = float(er)
                        while v > 0.02:
                            v /= 100.0
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
