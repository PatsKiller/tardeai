#!/usr/bin/env python3
"""portfolio_lookthrough_themes.py — TRUE stock-level look-through, theme exposure + advisories.

Resolves every holding to its UNDERLYING STOCKS (funds via their proxy ETF's yfinance top-holdings),
aggregates portfolio-wide AND per-account, computes theme baskets (Mag 7, Nasdaq 100, S&P 500, semis,
AI, international, fixed income, defense, dividend), tracks SOURCE attribution (which funds hold each
stock — for tooltips), and emits rule-based concentration advisories. A separate grok_narrative() adds an
LLM read.

Honest approximation: yfinance gives each fund's TOP ~10 holdings, so mega-caps (Mag 7) are well-captured
but the long tail is understated — theme %s are lower bounds. Cached to fund_holdings_cache.json.

State resolves through scripts/lib/persistent_state_root (served copy first, §9.4), not the checkout.
--dry-run computes the deterministic report from the served holdings and prints it; it writes neither cache
nor lookthrough_themes.json, calls no LLM, and writes no receipt. A real run writes
<state_root>/data/runtime/portfolio-lookthrough-themes_last.json (ok_at only on success) and exits 1 when
holdings are missing/empty or the served report could not be written. A run without --grok keeps the previous
grok_narrative / agent_advisories (with their grok_generated_at) instead of blanking them, so the
deterministic report can run on its own schedule.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
LANE_ID = "portfolio-lookthrough-themes"
_STATE_REL = "data/portfolios/state"


def _state_dir() -> Path:
    """Served data/portfolios/state (persistent root when provisioned, else this checkout)."""
    try:
        from lib.persistent_state_root import resolve_durable_dir
    except ImportError:  # imported as scripts.portfolio_lookthrough_themes
        from scripts.lib.persistent_state_root import resolve_durable_dir
    return Path(resolve_durable_dir(_STATE_REL, ROOT))


def _state_write_targets() -> list[Path]:
    """Served copy first, then the checkout copy (dual-write, de-duplicated by realpath)."""
    try:
        from lib.persistent_state_root import portfolio_state_write_targets
    except ImportError:
        from scripts.lib.persistent_state_root import portfolio_state_write_targets
    return [Path(p) for p in portfolio_state_write_targets(ROOT)]


def _receipt_lib():
    try:
        from lib import lane_last_receipt as lr
    except ImportError:
        from scripts.lib import lane_last_receipt as lr
    return lr


def _dry_report(lane_id, summary, *, would_write, json_stdout=False):
    """lane_last_receipt.dry_run_report, sent to stderr when stdout carries the script's JSON report."""
    import contextlib
    with contextlib.redirect_stdout(sys.stderr) if json_stdout else contextlib.nullcontext():
        return _receipt_lib().dry_run_report(lane_id, summary, would_write=would_write)


STATE = _state_dir()
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


def _write_state_json(name: str, doc) -> list[str]:
    """Write ``name`` into every state write target (served first). Returns the paths written; raises when the
    served (first) target fails."""
    written = []
    for i, d in enumerate(_state_write_targets()):
        try:
            d.mkdir(parents=True, exist_ok=True)
            (d / name).write_text(json.dumps(doc, indent=2))
            written.append(str(d / name))
        except Exception:
            if i == 0:
                raise
    return written


def _resolve_underlying(holdings, *, persist: bool = True):
    """Return (underlying $ by stock, sources {stock:{holding_label:$}}, per-account underlying, total, covered).

    ``persist=False`` (dry run) leaves fund_holdings_cache.json untouched."""
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
    if persist:
        _write_state_json(HOLD_CACHE.name, cache)
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


def _advisories(themes, top, total, ips_max=None):
    # Single-name guideline = the ratified IPS limit (operator 2026-10-09),
    # not a hardcoded 8%; lib.ips_policy falls back to 8% with a warning.
    if ips_max is None:
        from lib.ips_policy import ips_max_position_pct
        ips_max = ips_max_position_pct()
    adv = []
    for row in top:
        if row["pct"] >= ips_max:
            adv.append({"severity": "high", "title": f"{row['symbol']} concentration {row['pct']:.1f}%",
                        "detail": f"${row['value']:,.0f} look-through in {row['symbol']} — at/above the {ips_max:g}% IPS single-name limit. "
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


def run(account: str | None = None, *, persist: bool = True) -> dict:
    holdings = _load(STATE / "holdings.json", {}).get("holdings", [])
    if account:
        holdings = [h for h in holdings if (h.get("account") or "") == account]
    underlying, sources, by_account, total, covered = _resolve_underlying(holdings, persist=persist)
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
        lane = "grok" if llm_lane.available("grok") else "local"
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
        lane = "grok" if llm_lane.available("grok") else "local"
        out = llm_lane.generate(prompt, lane=lane, timeout=60)
        return out if out and not str(out).startswith("LLM error") else ""
    except Exception:
        return ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--account")
    ap.add_argument("--grok", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="deterministic report only; no cache/report write, no LLM, no receipt")
    a = ap.parse_args(argv)
    if a.dry_run:
        r = run(account=a.account, persist=False)
        summary = {"portfolio_total": r["portfolio_total"], "coverage_pct": r["coverage_pct"],
                   "accounts": len(r.get("accounts", [])), "advisories": len(r["advisories"]),
                   "theme_gaps": len(r["theme_gaps"]), "llm": "skipped (dry run)" if a.grok else "not requested"}
        would = [] if a.account else [str(t / "lookthrough_themes.json") for t in _state_write_targets()]
        would += [str(t / HOLD_CACHE.name) for t in _state_write_targets()]
        _dry_report(LANE_ID, summary, would_write=would,
            json_stdout=a.json)
        return 0
    from datetime import datetime, timezone
    started = datetime.now(timezone.utc).isoformat()
    summary: dict = {"account": a.account, "grok": bool(a.grok)}
    try:
        rc, r = _report(a, summary)
    except Exception as exc:
        if not a.account:
            _receipt_lib().write_lane_receipt(LANE_ID, ok=False, exit_code=1, started_at=started,
                                              script="portfolio_lookthrough_themes.py", summary=summary,
                                              error=f"{type(exc).__name__}: {exc}")
        raise
    if not a.account:  # the lane is the global run; a per-account manual run is not the lane
        _receipt_lib().write_lane_receipt(LANE_ID, ok=(rc == 0), exit_code=rc, started_at=started,
                                          script="portfolio_lookthrough_themes.py", summary=summary)
    if a.json:
        print(json.dumps(r, indent=2)); return rc
    print(f"Portfolio ${r['portfolio_total']:,.0f} · coverage {r['coverage_pct']}%"
          + (f" · {a.account}" if a.account else ""))
    for name, t in r["themes"].items():
        print(f"  {name:<22} ${t['value']:>11,.0f}  {t['pct']:>5.1f}%")
    print("Advisories:")
    for x in r["advisories"]:
        print(f"  [{x['severity']}] {x['title']} — {x['detail']}")
    if r.get("grok_narrative"):
        print("\nGrok:", r["grok_narrative"])
    return rc


def _report(a, summary: dict) -> tuple[int, dict]:
    """The real run. Returns (exit code, report)."""
    from datetime import datetime, timezone
    r = run(account=a.account)
    summary.update(portfolio_total=r["portfolio_total"], coverage_pct=r["coverage_pct"])
    if a.grok:
        r["grok_narrative"] = grok_narrative(r)
        r["agent_advisories"] = agent_advisories(r)
        r["grok_generated_at"] = datetime.now(timezone.utc).isoformat()
        # §9.2: a lane that could not run says so instead of rendering a silently empty section
        r["grok_status"] = "ok" if (r["grok_narrative"] or r["agent_advisories"]) else "unavailable"
        summary["grok_status"] = r["grok_status"]
    elif not a.account:
        prev = _load(STATE / "lookthrough_themes.json", {})
        for k in ("grok_narrative", "agent_advisories", "grok_generated_at", "grok_status"):
            if k in prev:
                r[k] = prev[k]
    # per-account detail (no LLM — themes/top/rule-advisories only; the fund-holdings cache makes this cheap)
    if not a.account:
        detail = {}
        for acct in r.get("accounts", []):
            ar = run(account=acct)
            detail[acct] = {k: ar[k] for k in ("portfolio_total", "coverage_pct", "themes",
                                               "top_underlying", "advisories")}
        r["accounts_detail"] = detail
    rc = 0
    if not r["portfolio_total"]:
        print("[lookthrough] no holdings / zero portfolio total -> exit 1", file=sys.stderr)
        rc = 1
    # write the cache the API serves (fast, no yfinance in the request path) — only for the global run
    if not a.account:
        try:
            summary["written"] = _write_state_json("lookthrough_themes.json", r)
        except Exception as exc:
            print(f"[lookthrough] report write failed: {type(exc).__name__} -> exit 1", file=sys.stderr)
            summary["write_error"] = type(exc).__name__
            rc = 1
    return rc, r


if __name__ == "__main__":
    sys.exit(main())
