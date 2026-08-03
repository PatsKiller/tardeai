#!/usr/bin/env python3
"""portfolio_lookthrough_themes.py — TRUE stock-level look-through, theme exposure + advisories.

Resolves every holding to its UNDERLYING STOCKS (funds via their proxy ETF's yfinance top-holdings),
aggregates portfolio-wide AND per-account, computes theme baskets (Mag 7, Nasdaq 100, S&P 500, semis,
AI, international, fixed income, defense, dividend), tracks SOURCE attribution (which funds hold each
stock — for tooltips), and emits rule-based concentration advisories. A separate grok_narrative() adds an
LLM read.

Honest approximation: yfinance gives each fund's TOP ~10 holdings, so mega-caps (Mag 7) are well-captured
but the long tail is understated — theme %s are lower bounds. Cached to fund_holdings_cache.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STATE = ROOT / "data" / "portfolios" / "state"
HOLD_CACHE = STATE / "fund_holdings_cache.json"
CONSTITUENTS = STATE / "index_constituents.json"

# ETFs/funds we can pull holdings for directly (others map via proxy)
_KNOWN_ETFS = {"SPY", "QQQ", "SCHG", "SCHD", "DIV", "JEPI", "BND", "XLI", "XLB", "XLF", "XLK", "ARKG",
               "ARKQ", "VXUS", "IJH", "IWP", "IWN", "IWR", "IWM", "VTI", "VOO", "IVV"}

_STATIC_THEMES = {
    "Magnificent 7": {"AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA"},
    "Semiconductors": {"NVDA", "AVGO", "AMD", "QCOM", "TXN", "MU", "INTC", "ASML", "TSM", "LRCX",
                       "AMAT", "ADI", "KLAC", "MRVL", "NXPI", "MCHP", "ON", "SMCI", "ARM"},
    "AI mega-cap": {"NVDA", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "AVGO", "AMD", "PLTR", "TSM", "SMCI"},
    "Defense / Aerospace": {"LMT", "NOC", "RTX", "GD", "BA", "LHX", "TDG", "HII", "KTOS", "AVAV", "DRS",
                            "LDOS", "CACI", "BAH", "KBR", "AXON", "RKLB"},
    # current-event baskets — the AI build-out and its power/energy demand
    "AI datacenter & power": {"NVDA", "AVGO", "SMCI", "DELL", "ANET", "VRT", "ETN", "GEV", "PWR", "NVT",
                              "VST", "CEG", "TLN", "NRG", "NEE", "DLR", "EQIX", "AMD", "MU", "TSM"},
    "Nuclear / power gen": {"CEG", "VST", "TLN", "NRG", "GEV", "NEE", "OKLO", "SMR", "BWXT", "CCJ", "UEC"},
    "Energy": {"XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "VLO", "OXY", "WMB", "KMI", "LNG", "FANG",
               "DVN", "HES", "BKR", "HAL"},
    "Cybersecurity": {"PANW", "CRWD", "ZS", "FTNT", "NET", "S", "OKTA", "CYBR", "TENB", "QLYS"},
    "China / EM": {"BABA", "PDD", "JD", "BIDU", "NIO", "TCEHY", "MELI", "TSM"},
}


def _load(p, d):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return d


def _proxy_etf(sym: str):
    try:
        from holding_proxies import HOLDING_PROXY_MAP
    except Exception:
        HOLDING_PROXY_MAP = {}
    if sym in HOLDING_PROXY_MAP:
        return HOLDING_PROXY_MAP[sym][0]
    fmap = _load(ROOT / "config" / "snaptrade_401k_fund_map.json", {}).get("codes", {})
    if sym in fmap and fmap[sym].get("lookthrough_source") in HOLDING_PROXY_MAP:
        return HOLDING_PROXY_MAP[fmap[sym]["lookthrough_source"]][0]
    return None


def _fund_holdings(etf, cache):
    if etf in cache:
        return cache[etf]
    out = {}
    try:
        import yfinance as yf
        th = yf.Ticker(etf).funds_data.top_holdings
        for sym, row in th.iterrows():
            out[str(sym).upper()] = float(row["Holding Percent"])
    except Exception:
        out = {}
    cache[etf] = out
    return out


def _resolve_underlying(holdings):
    """Return (underlying $ by stock, sources {stock:{holding_label:$}}, per-account underlying, total, covered)."""
    import holding_family as hf
    cache = _load(HOLD_CACHE, {})
    underlying = defaultdict(float)
    sources = defaultdict(lambda: defaultdict(float))
    by_account = defaultdict(lambda: defaultdict(float))
    total = covered = 0.0
    for h in holdings:
        sym = (h.get("symbol") or "").upper()
        mv = float(h.get("market_value") or 0)
        acct = h.get("account") or "unknown"
        if not sym or h.get("is_cash") or mv <= 0:
            continue
        total += mv
        is_fund = hf.is_unstoppable_fund(sym) or sym in _KNOWN_ETFS or _proxy_etf(sym) is not None
        if not is_fund:                       # direct stock
            underlying[sym] += mv
            sources[sym][f"{sym} (direct · {acct})"] += mv
            by_account[acct][sym] += mv
            covered += mv
            continue
        etf = _proxy_etf(sym) or (sym if sym in _KNOWN_ETFS else None)
        if not etf:
            continue
        weights = _fund_holdings(etf, cache)
        if not weights:
            continue
        label = f"{sym} → {etf}" if etf != sym else sym
        for stock, w in weights.items():
            underlying[stock] += mv * w
            sources[stock][label] += mv * w
            by_account[acct][stock] += mv * w
        covered += mv * sum(weights.values())
    HOLD_CACHE.write_text(json.dumps(cache, indent=2))
    return underlying, sources, by_account, total, covered


def _themes(underlying, total):
    cons = _load(CONSTITUENTS, {})
    baskets = dict(_STATIC_THEMES)
    if cons.get("NASDAQ100"):
        baskets["Nasdaq 100"] = set(cons["NASDAQ100"])
    if cons.get("SP500"):
        baskets["S&P 500"] = set(cons["SP500"])
    out = {}
    for name, basket in baskets.items():
        val = sum(v for s, v in underlying.items() if s in basket)
        by_stock = [{"symbol": s, "value": round(underlying[s], 0)}
                    for s in sorted(basket, key=lambda x: -underlying.get(x, 0)) if underlying.get(s, 0) > 0][:12]
        out[name] = {"value": round(val, 0), "pct": round(val / total * 100, 2) if total else 0, "by_stock": by_stock}
    return out


def _advisories(themes, top, total):
    adv = []
    for row in top:
        if row["pct"] >= 8:
            adv.append({"severity": "high", "title": f"{row['symbol']} concentration {row['pct']:.1f}%",
                        "detail": f"${row['value']:,.0f} look-through in {row['symbol']} — above an 8% single-name guideline. "
                                  f"Consider trimming toward 5%."})
        elif row["pct"] >= 5:
            adv.append({"severity": "medium", "title": f"{row['symbol']} {row['pct']:.1f}%",
                        "detail": f"${row['value']:,.0f} in {row['symbol']} — watch; above a 5% comfort line."})
    m7 = themes.get("Magnificent 7", {})
    if m7.get("pct", 0) >= 25:
        adv.append({"severity": "medium", "title": f"Mag 7 {m7['pct']:.0f}%",
                    "detail": "Mega-cap tech is a large share of effective equity — diversified, but rate/AI-sensitive."})
    semi = themes.get("Semiconductors", {})
    if semi.get("pct", 0) >= 8:
        adv.append({"severity": "medium", "title": f"Semiconductors {semi['pct']:.1f}%",
                    "detail": "Cyclical, correlated cluster — sized like a sector bet via the growth funds."})
    if not adv:
        adv.append({"severity": "low", "title": "No concentration flags",
                    "detail": "No single name above 5% and themes within normal ranges."})
    return adv


def _theme_gaps(themes, total):
    """Underweight/0% DIVERSIFICATION sleeves that have a long ETF available — concrete fill candidates
    (operator 2026-06-18: "why is this not recommending tickers/ETFs for the 0% gaps"). A themed sleeve
    below its floor (config/etf_fund_universe.json sleeve_targets) becomes a gap with named ETF picks +
    a target-fill $ size. Overweight growth sleeves are trim-side (rotation engine), not here. Advisory."""
    uni = _load(ROOT / "config" / "etf_fund_universe.json", {})
    targets = uni.get("sleeve_targets", {})
    long_etfs = {}
    for it in uni.get("instruments", []):
        if it.get("direction") == "long":
            long_etfs.setdefault(it.get("sleeve"), []).append(
                {"symbol": it.get("symbol"), "name": it.get("name"), "type": it.get("type")})
    gaps = []
    for sleeve, target in targets.items():
        etfs = long_etfs.get(sleeve) or []
        if not etfs or sleeve not in themes:           # only sleeves we actually measure as a theme
            continue
        cur = float((themes.get(sleeve) or {}).get("pct") or 0)
        if cur < float(target):
            gap_pct = round(float(target) - cur, 2)
            gaps.append({
                "theme": sleeve, "current_pct": round(cur, 2), "target_pct": float(target),
                "gap_pct": gap_pct, "gap_dollars": round(gap_pct / 100 * total, 0),
                "suggested_etfs": etfs,
                "severity": "high" if cur == 0 else "medium" if cur < float(target) / 2 else "low",
            })
    gaps.sort(key=lambda g: -g["gap_pct"])
    return gaps


def run(account: str | None = None) -> dict:
    holdings = _load(STATE / "holdings.json", {}).get("holdings", [])
    if account:
        holdings = [h for h in holdings if (h.get("account") or "") == account]
    underlying, sources, by_account, total, covered = _resolve_underlying(holdings)
    themes = _themes(underlying, total)
    top = [{"symbol": s, "value": round(v, 0), "pct": round(v / total * 100, 2) if total else 0,
            "in": [{"src": k, "value": round(x, 0)} for k, x in sorted(sources[s].items(), key=lambda i: -i[1])[:6]]}
           for s, v in sorted(underlying.items(), key=lambda x: -x[1])[:20]]
    return {
        "portfolio_total": round(total, 0),
        "coverage_pct": round(covered / total * 100, 1) if total else 0,
        "account": account,
        "accounts": sorted(by_account.keys()),
        "themes": themes,
        "top_underlying": top,
        "advisories": _advisories(themes, top, total),
        "theme_gaps": _theme_gaps(themes, total),
    }


_AGENT_ROLES = [
    ("CIO", "You are the CIO. Give a 3-4 sentence verdict: does this effective allocation fit a balanced "
            "long-term portfolio, and what is the single highest-priority rebalancing action?"),
    ("Risk Agent", "You are the risk manager. In 3-4 sentences flag the top concentration and correlation "
                   "risks, name which position-size limits are breached (single-name >5-8%, theme clusters), "
                   "and state the de-risking priority order."),
    ("Steph · Allocation", "You are the allocation/income strategist. In 3-4 sentences assess sector/theme "
                           "balance and gaps, and suggest 2 specific adds/trims to improve diversification "
                           "without raising overall beta."),
]


def agent_advisories(data: dict) -> list:
    """Run the look-through through multiple agent lenses (CIO / Risk / Allocation) on the free Grok lane
    (local fallback). Returns [{agent, model, text}]. Each call is independent + resilient."""
    out = []
    try:
        import llm_lane
        lane = "deepseek-flash" if llm_lane.available("deepseek-flash") else ("grok" if llm_lane.available("grok") else "local")
        themes = " · ".join(f"{k} {v['pct']}%" for k, v in data.get("themes", {}).items())
        top = ", ".join(f"{t['symbol']} {t['pct']}%" for t in data.get("top_underlying", [])[:8])
        ctx = (f"Portfolio ${data.get('portfolio_total',0):,.0f}. LOOK-THROUGH exposure (funds resolved to "
               f"underlying stocks): themes [{themes}]; top names [{top}]. Be specific and brief.")
        for agent, role in _AGENT_ROLES:
            try:
                txt = llm_lane.generate(f"{role}\n\n{ctx}", lane=lane, timeout=60)
                if txt and not str(txt).startswith("LLM error"):
                    out.append({"agent": agent, "model": ("grok-3-mini" if lane == "grok" else "local"),
                                "text": str(txt).strip()})
            except Exception:
                continue
    except Exception:
        pass
    return out


def grok_narrative(data: dict) -> str:
    """LLM read of the look-through (free Grok lane, local fallback). Returns a short narrative."""
    try:
        import llm_lane
        themes = " · ".join(f"{k} {v['pct']}%" for k, v in data.get("themes", {}).items())
        top = ", ".join(f"{t['symbol']} {t['pct']}%" for t in data.get("top_underlying", [])[:8])
        prompt = (f"You are a portfolio risk analyst. A ${data['portfolio_total']:,.0f} portfolio has this "
                  f"LOOK-THROUGH exposure (funds resolved to underlying stocks): themes [{themes}]; top names "
                  f"[{top}]. In 4-5 sentences, give a concentration/diversification read and 2 concrete actions. "
                  f"Be specific and brief.")
        lane = "deepseek-flash" if llm_lane.available("deepseek-flash") else ("grok" if llm_lane.available("grok") else "local")
        out = llm_lane.generate(prompt, lane=lane, timeout=60)
        return out if out and not str(out).startswith("LLM error") else ""
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--account")
    ap.add_argument("--grok", action="store_true")
    a = ap.parse_args()
    r = run(account=a.account)
    if a.grok:
        r["grok_narrative"] = grok_narrative(r)
        r["agent_advisories"] = agent_advisories(r)
    # per-account detail (no LLM — themes/top/rule-advisories only; the fund-holdings cache makes this cheap)
    if not a.account:
        detail = {}
        for acct in r.get("accounts", []):
            ar = run(account=acct)
            detail[acct] = {k: ar[k] for k in ("portfolio_total", "coverage_pct", "themes",
                                               "top_underlying", "advisories")}
        r["accounts_detail"] = detail
    # write the cache the API serves (fast, no yfinance in the request path) — only for the global run
    if not a.account:
        try:
            (STATE / "lookthrough_themes.json").write_text(json.dumps(r, indent=2))
        except Exception:
            pass
    if a.json:
        print(json.dumps(r, indent=2)); return 0
    print(f"Portfolio ${r['portfolio_total']:,.0f} · coverage {r['coverage_pct']}%"
          + (f" · {a.account}" if a.account else ""))
    for name, t in r["themes"].items():
        print(f"  {name:<22} ${t['value']:>11,.0f}  {t['pct']:>5.1f}%")
    print("Advisories:")
    for x in r["advisories"]:
        print(f"  [{x['severity']}] {x['title']} — {x['detail']}")
    if r.get("grok_narrative"):
        print("\nGrok:", r["grok_narrative"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
