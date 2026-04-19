"""
portfolio_repricer.py — Live Portfolio Repricing Engine v2.0
Trade AI v12 / Portfolio Intelligence v1.2

Called by portfolio_live_monitor.py every 30-min cycle to:
  1. Fetch live prices from Finviz Elite (real-time, all day)
  2. Write full quote cache: data/portfolios/state/finviz_quote_cache.json
     - All 16 Finviz fields per symbol (price, change_pct, volume, analyst,
       target, perf_week/month/quarter/halfyr/ytd/year, volatility_w/m, rvol)
     - Delta-only writes: only changed fields are updated, timestamp per field
     - Covers portfolio tickers + watchlist tickers in one pass
  3. Recalculate day_change per holding from live price + derived prev_close
  4. Update account and portfolio totals in holdings.json
  5. Regenerate portfolio_live.html dashboard
  6. After 8 PM ET: reprice Fidelity 401k from Yahoo price cache (NAVs ~6 PM)

Architecture:
  prev_close  = price / (1 + change_pct/100)        [derived from Finviz]
  day_change$ = (price - prev_close) * shares
  Cache write: only overwrite fields that changed by >threshold (delta write)
  Fidelity funds: mapped via fidelity_ticker_map to public ETF/fund equivalents

Never re-reads Schwab CSVs. Positions/shares always from holdings.json.
Quote cache is the single source of truth for intraday prices system-wide.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import sys


# ── Change thresholds for delta writes ────────────────────────────────────────
PRICE_CHANGE_THRESHOLD  = 0.001   # $0.001 — update price if changed by this much
PCT_CHANGE_THRESHOLD    = 0.01    # 0.01% — update change_pct if changed this much
VOLUME_CHANGE_THRESHOLD = 0.05    # 5%    — update volume if changed this much


# ── ET time helpers ────────────────────────────────────────────────────────────
def _et_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
    except Exception:
        return datetime.utcnow() - timedelta(hours=4)


def _is_market_hours(now: Optional[datetime] = None) -> bool:
    now = now or _et_now()
    if now.weekday() >= 5:
        return False
    mins = now.hour * 60 + now.minute
    return 570 <= mins <= 960  # 9:30 AM - 4:00 PM


def _load_env(root: Path) -> None:
    """Load .env from project root — guaranteed before any API call."""
    try:
        from dotenv import load_dotenv
        load_dotenv(root / ".env", override=False)
    except Exception:
        pass


# ── Get all symbols to quote ───────────────────────────────────────────────────
def _get_all_symbols(portfolio: Dict, root: Path) -> Dict[str, List[str]]:
    """
    Returns dict of symbol lists by source:
      finviz: portfolio Schwab symbols + watchlist symbols
      yahoo:  Fidelity fund symbols (via fidelity_ticker_map)
    """
    holdings = portfolio.get("holdings", [])

    # Portfolio Schwab symbols (skip Fidelity proprietary, cash, loans)
    schwab_syms = list(set(
        h["symbol"] for h in holdings
        if not h.get("is_loan") and not h.get("is_cash")
        and h.get("broker") != "fidelity"
        and h.get("symbol") and len(h["symbol"]) <= 6
    ))

    # Fidelity proprietary symbols
    fidelity_syms = [
        h["symbol"] for h in holdings
        if h.get("broker") == "fidelity" and not h.get("is_loan")
    ]

    # Watchlist symbols from watchlist.json
    watchlist_syms = []
    wl_path = root / "data" / "portfolios" / "state" / "watchlist.json"
    if wl_path.exists():
        try:
            wl = json.loads(wl_path.read_text(encoding="utf-8"))
            if isinstance(wl, list):
                watchlist_syms = [x.get("symbol", x) if isinstance(x, dict) else str(x) for x in wl]
            elif isinstance(wl, dict):
                watchlist_syms = list(wl.keys())
        except Exception:
            pass

    # All Finviz symbols = Schwab portfolio + watchlist (deduplicated)
    finviz_syms = sorted(set(schwab_syms + watchlist_syms))

    return {
        "finviz": finviz_syms,
        "fidelity": fidelity_syms,
        "watchlist": watchlist_syms,
        "schwab": schwab_syms,
    }


# ── Finviz live price fetch ────────────────────────────────────────────────────
def _fetch_finviz(symbols: List[str], root: Path) -> Dict[str, Dict]:
    """
    Fetch all 16 Finviz fields for given symbols.
    Returns {symbol: {price, change_pct, prev_close, volume, analyst, target,
                       perf_week, perf_month, perf_quarter, perf_halfyr,
                       perf_ytd, perf_year, volatility_w, volatility_m, rvol}}
    """
    if not symbols:
        return {}
    _load_env(root)
    results = {}
    try:
        if str(root / "scripts") not in sys.path:
            sys.path.insert(0, str(root / "scripts"))
        from portfolio_technical import _finviz_api_batch
        raw = _finviz_api_batch(symbols, root)
        for sym, data in raw.items():
            price    = float(data.get("price") or 0)
            chg_pct  = float(data.get("change_pct") or 0)
            if price <= 0:
                continue
            prev_close = price / (1 + chg_pct / 100) if chg_pct != -100 else price
            results[sym] = {
                "price":       round(price, 4),
                "change_pct":  round(chg_pct, 4),
                "prev_close":  round(prev_close, 4),
                "volume":      int(data.get("volume") or 0),
                "analyst":     str(data.get("analyst") or ""),
                "target":      float(data.get("target") or 0),
                "perf_week":   float(data.get("perf_week") or 0),
                "perf_month":  float(data.get("perf_month") or 0),
                "perf_quarter":float(data.get("perf_quarter") or 0),
                "perf_halfyr": float(data.get("perf_halfyr") or 0),
                "perf_ytd":    float(data.get("perf_ytd") or 0),
                "perf_year":   float(data.get("perf_year") or 0),
                "volatility_w":float(data.get("volatility_w") or 0),
                "volatility_m":float(data.get("volatility_m") or 0),
                "rvol":        float(data.get("relative_volume") or 0),
                "source":      "finviz_elite",
            }
    except Exception as e:
        print(f"  [repricer] Finviz fetch error: {e}")
    return results


# ── Yahoo price cache fetch (Fidelity funds after 8 PM) ───────────────────────
def _fetch_fidelity_from_cache(fid_syms: List[str], root: Path) -> Dict[str, float]:
    """Pull latest NAV from price_cache.json for Fidelity proprietary symbols."""
    result = {}
    if not fid_syms:
        return result

    # Load fidelity_ticker_map from portfolio_accounts.yaml
    fid_map = {}
    try:
        import yaml
        yp = root / "assets" / "portfolio_accounts.yaml"
        if yp.exists():
            cfg = yaml.safe_load(yp.read_text(encoding="utf-8"))
            fid_map = cfg.get("fidelity_ticker_map", {})
    except Exception:
        pass

    # Fallback map
    if not fid_map:
        fid_map = {
            "JPM-LGCG":      "JLGMX", "FID-DIVINTL":   "FDIVX",
            "FID-CONTRA-F":  "FCNTX", "SP500-D":        "FXAIX",
            "SS-GACEQ":      "SSGAX", "SS-SMMD":        "SLYG",
            "WM-BLAIR":      "WBIGX", "AB-DISC-Z":      "ADVRX",
            "TRP-LVAL":      "TILCX", "VANG-FTSE-SOC":  "VFTNX",
        }

    cache_path = root / "data" / "portfolios" / "state" / "price_cache.json"
    if not cache_path.exists():
        return result

    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        prices = cache.get("prices", cache)
        now = _et_now()
        dates = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]

        for fid_sym in fid_syms:
            pub_sym = fid_map.get(fid_sym, fid_sym)
            sym_data = prices.get(pub_sym, {})
            for d in dates:
                val = sym_data.get(d)
                if val is not None:
                    result[fid_sym] = float(val) if not isinstance(val, dict) else float(val.get("close", 0))
                    break
    except Exception as e:
        print(f"  [repricer] Fidelity cache error: {e}")

    return result


# ── Quote cache: read, delta-update, write ────────────────────────────────────
def _update_quote_cache(
    live_prices: Dict[str, Dict],
    cache_path: Path,
    now_str: str,
) -> int:
    """
    Read existing cache, apply delta updates (only changed fields), write back.
    Returns number of symbols updated.
    """
    # Load existing cache
    existing: Dict[str, Any] = {}
    if cache_path.exists():
        try:
            existing = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    updated_count = 0

    for sym, new_data in live_prices.items():
        old = existing.get(sym, {})
        changed = {}

        # Price delta check
        old_price = float(old.get("price") or 0)
        new_price  = float(new_data.get("price") or 0)
        if abs(new_price - old_price) >= PRICE_CHANGE_THRESHOLD:
            changed["price"]      = new_data["price"]
            changed["prev_close"] = new_data.get("prev_close", 0)

        # Change pct delta
        old_chg = float(old.get("change_pct") or 0)
        new_chg  = float(new_data.get("change_pct") or 0)
        if abs(new_chg - old_chg) >= PCT_CHANGE_THRESHOLD:
            changed["change_pct"] = new_data["change_pct"]

        # Volume delta
        old_vol = float(old.get("volume") or 0)
        new_vol  = float(new_data.get("volume") or 0)
        if old_vol == 0 or (old_vol > 0 and abs(new_vol - old_vol) / old_vol >= VOLUME_CHANGE_THRESHOLD):
            changed["volume"] = new_data["volume"]

        # Performance / volatility fields — update if any change (daily values)
        for fld in ["analyst", "target", "perf_week", "perf_month", "perf_quarter",
                    "perf_halfyr", "perf_ytd", "perf_year", "volatility_w",
                    "volatility_m", "rvol"]:
            if new_data.get(fld) != old.get(fld):
                changed[fld] = new_data[fld]

        if changed or not old:
            # Merge: keep old fields, overlay changed fields
            merged = dict(old)
            merged.update(changed)
            merged["symbol"]       = sym
            merged["source"]       = new_data.get("source", "finviz_elite")
            merged["last_updated"] = now_str
            existing[sym] = merged
            updated_count += 1

    # Update meta
    existing["_meta"] = {
        "last_updated":   now_str,
        "symbols_cached": len([k for k in existing if k != "_meta"]),
        "source":         "finviz_elite_v152_v141",
        "fields":         ["price", "change_pct", "prev_close", "volume", "analyst",
                           "target", "perf_week", "perf_month", "perf_quarter",
                           "perf_halfyr", "perf_ytd", "perf_year",
                           "volatility_w", "volatility_m", "rvol"],
        "update_policy":  "delta — only changed fields overwritten",
    }

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(existing, indent=2, default=str), encoding="utf-8")
    return updated_count


# ── Apply prices to holdings ───────────────────────────────────────────────────
def _apply_to_holdings(
    holdings: List[Dict],
    live_prices: Dict[str, Dict],
    fidelity_prices: Dict[str, float],
) -> int:
    """Update price/market_value/day_change fields in holdings list. Returns update count."""
    updated = 0
    for h in holdings:
        if h.get("is_loan") or h.get("is_cash"):
            continue
        sym    = h.get("symbol", "")
        shares = float(h.get("shares") or 0)
        broker = h.get("broker", "")

        if broker == "fidelity":
            if sym in fidelity_prices and shares > 0:
                new_price = fidelity_prices[sym]
                old_price = float(h.get("price") or new_price)
                h["price"]          = round(new_price, 4)
                h["market_value"]   = round(new_price * shares, 2)
                h["day_change"]     = round((new_price - old_price) * shares, 2)
                h["day_change_pct"] = round(((new_price - old_price) / old_price * 100) if old_price else 0, 4)
                updated += 1
        else:
            if sym in live_prices and shares > 0:
                p          = live_prices[sym]
                new_price  = p["price"]
                prev_close = p["prev_close"]
                chg_pct    = p["change_pct"]
                h["price"]          = round(new_price, 4)
                h["market_value"]   = round(new_price * shares, 2)
                h["day_change"]     = round((new_price - prev_close) * shares, 2)
                h["day_change_pct"] = round(chg_pct, 4)
                cost = h.get("cost_basis") or 0
                if cost:
                    h["gain_loss"]     = round(h["market_value"] - cost, 2)
                    h["gain_loss_pct"] = round(h["gain_loss"] / cost * 100, 4)
                updated += 1
    return updated


# ── Recalculate totals ─────────────────────────────────────────────────────────
def _recalc_totals(portfolio: Dict) -> None:
    """Recalculate account summaries and portfolio totals from updated holdings."""
    holdings = portfolio.get("holdings", [])
    account_summaries = portfolio.get("account_summaries", {})

    def _choose_anchor(ah):
        candidates = [h for h in ah if not h.get("is_loan") and not h.get("is_cash")]
        if not candidates:
            return None
        proprietary = [h for h in candidates if "-" in str(h.get("symbol", ""))]
        if proprietary:
            contra = [h for h in proprietary if "CONTRA" in str(h.get("symbol", "")).upper() or "CONTRA" in str(h.get("name", "")).upper()]
            if contra:
                return max(contra, key=lambda x: x.get("market_value", 0) or 0)
            return max(proprietary, key=lambda x: x.get("market_value", 0) or 0)
        return max(candidates, key=lambda x: x.get("market_value", 0) or 0)

    for acct_key, acct in account_summaries.items():
        ah = [h for h in holdings if h.get("account") == acct_key and not h.get("is_loan")]
        derived_total = round(sum(h.get("market_value") or 0 for h in ah), 2)
        reported_total = float(acct.get("reported_total_value") or 0)
        source = str(acct.get("source", "")).lower()
        acct_total = derived_total

        if reported_total > 0 and (acct_key == "fidelity_401k" or "fidelity" in source):
            drift = round(reported_total - derived_total, 2)
            if abs(drift) >= 0.01:
                anchor = _choose_anchor(ah)
                if anchor:
                    before = round(anchor.get("market_value", 0) or 0, 2)
                    anchor["market_value"] = round(before + drift, 2)
                    shares = float(anchor.get("shares") or 0)
                    if shares > 0 and not anchor.get("is_cash"):
                        anchor["price"] = round(anchor["market_value"] / shares, 6)
                    acct_total = reported_total
                    print(f"  [repricer][guard] {acct_key}: derived ${derived_total:,.2f} vs reported ${reported_total:,.2f} → residual ${drift:+,.2f} applied to {anchor.get('symbol')}")
                else:
                    print(f"  [repricer][guard] WARNING {acct_key}: no anchor found for drift ${drift:+,.2f}")
            else:
                acct_total = reported_total

        acct["total_value"] = round(acct_total, 2)
        acct["day_change"]  = round(sum(h.get("day_change") or 0 for h in ah), 2)
        acct_prev = (acct["total_value"] - acct["day_change"])
        acct["day_change_pct"] = round((acct["day_change"] / acct_prev * 100) if acct_prev else 0, 4)
        cost = sum(h.get("cost_basis") or 0 for h in ah)
        gain = sum(h.get("gain_loss") or 0 for h in ah)
        acct["total_gain"]     = round(gain, 2)
        acct["total_gain_pct"] = round((gain / cost * 100) if cost else 0, 4)

    gt = round(sum((acct.get("total_value") or 0) for acct in account_summaries.values()), 2)
    valid = [h for h in holdings if not h.get("is_loan")]
    # Only include positions WITH cost basis in gain calculation
    # (positions without cost basis would inflate gain by treating them as $0 cost)
    valid_with_cost = [h for h in valid if h.get("cost_basis")]
    gc    = sum(h.get("cost_basis") or 0 for h in valid_with_cost)
    gv    = sum(h.get("market_value") or 0 for h in valid_with_cost)
    gg    = gv - gc
    # Track excluded positions for downstream labeling
    excluded_mv    = round(gt - gv, 2)
    excluded_count = len(valid) - len(valid_with_cost)
    gd    = sum((acct.get("day_change") or 0) for acct in account_summaries.values())

    portfolio["portfolio_totals"].update({
        "total_value":        round(gt, 2),
        "total_cost":         round(gc, 2),
        "total_gain":         round(gg, 2),
        "total_gain_pct":     round((gg / gc * 100) if gc else 0, 4),
        "total_mv_with_cost": round(gv, 2),
        "total_mv_excluded":  excluded_mv,
        "excluded_count":     excluded_count,
        "day_change":         round(gd, 2),
        "day_change_pct":     round((gd / (gt - gd) * 100) if (gt - gd) else 0, 4),
    })

    for h in holdings:
        mv = h.get("market_value") or 0
        h["portfolio_pct"] = round((mv / gt * 100) if gt > 0 else 0, 4)


# ── Main entry point ───────────────────────────────────────────────────────────
def reprice_portfolio(portfolio: Dict[str, Any], state_dir: Path) -> Dict[str, Any]:
    """
    Full reprice cycle:
      1. Fetch Finviz prices for all portfolio + watchlist symbols
      2. Delta-write to finviz_quote_cache.json
      3. Apply to holdings, recalc totals
      4. Optionally reprice Fidelity from Yahoo cache (after 8 PM)
    """
    root    = state_dir.parent.parent.parent  # data/portfolios/state -> project root
    _load_env(root)
    now     = _et_now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S ET")
    now_min = now.hour * 60 + now.minute

    print(f"  [repricer] {now_str} ({'market' if _is_market_hours(now) else 'after-hours'})")

    sym_groups = _get_all_symbols(portfolio, root)
    finviz_syms  = sym_groups["finviz"]    # Schwab portfolio + watchlist
    fidelity_syms = sym_groups["fidelity"] # Fidelity proprietary

    # Symbols known to be outside Finviz Elite coverage (mutual funds, OTC, delisted)
    # These fall back to Yahoo price cache for last available close
    YAHOO_FALLBACK_SYMS = {
        "AMANX",   # Amana Growth - mutual fund
        "FCNTX",   # Fidelity Contrafund - mutual fund
        "SRNE",    # Sorrento - delisted
        "LPIH",    # OTC / very illiquid
        "CDEX",    # OTC / very illiquid
    }

    # ── 1. Fetch Finviz live prices ────────────────────────────────────────────
    live_prices: Dict[str, Dict] = {}
    if finviz_syms:
        live_prices = _fetch_finviz(finviz_syms, root)
        priced = len([s for s in sym_groups["schwab"] if s in live_prices])
        print(f"  [repricer] Finviz: {len(live_prices)}/{len(finviz_syms)} symbols priced "
              f"({priced}/{len(sym_groups['schwab'])} portfolio, "
              f"{len([s for s in sym_groups['watchlist'] if s in live_prices])}/{len(sym_groups['watchlist'])} watchlist)")

    # ── 2. Delta-write to quote cache ──────────────────────────────────────────
    cache_path = state_dir / "finviz_quote_cache.json"
    if live_prices:
        n_updated = _update_quote_cache(live_prices, cache_path, now_str)
        print(f"  [repricer] Quote cache: {n_updated} symbols updated -> finviz_quote_cache.json")

    # ── 3. Apply to portfolio holdings ────────────────────────────────────────
    fidelity_prices: Dict[str, float] = {}
    if fidelity_syms and now_min >= 20 * 60:  # after 8 PM ET
        fidelity_prices = _fetch_fidelity_from_cache(fidelity_syms, root)
        print(f"  [repricer] Fidelity (8 PM cache): {len(fidelity_prices)}/{len(fidelity_syms)} funds")
    elif fidelity_syms:
        print(f"  [repricer] Fidelity: waiting for 8 PM NAV post (now {now.strftime('%H:%M')})")

    # ── 3b. Yahoo cache fallback for non-Finviz symbols ─────────────────────
    missing_schwab = [s for s in sym_groups["schwab"] if s not in live_prices]
    if missing_schwab:
        yahoo_prices = _fetch_fidelity_from_cache(missing_schwab, root)
        for sym, price in yahoo_prices.items():
            if price > 0:
                live_prices[sym] = {
                    "price":      round(price, 4),
                    "change_pct": 0.0,
                    "prev_close": round(price, 4),
                    "source":     "yahoo_cache_fallback",
                }
        if yahoo_prices:
            print(f"  [repricer] Yahoo fallback: {len(yahoo_prices)} symbols "
                  f"({', '.join(yahoo_prices.keys())})")

    n_holdings = _apply_to_holdings(portfolio.get("holdings", []), live_prices, fidelity_prices)
    print(f"  [repricer] Holdings updated: {n_holdings}")

    # ── 4. Recalculate totals ─────────────────────────────────────────────────
    _recalc_totals(portfolio)

    portfolio["last_repriced"]  = now_str
    portfolio["reprice_source"] = "finviz_live" if _is_market_hours(now) else "finviz_afterhours"

    total = portfolio["portfolio_totals"]["total_value"]
    day   = portfolio["portfolio_totals"]["day_change"]

    try:
        from ticker_snapshot_builder import build_ticker_snapshot
        out = build_ticker_snapshot(portfolio, root)
        print(f"  [repricer] Ticker snapshot → {out}")
    except Exception as e:
        print(f"  [repricer] WARNING: ticker snapshot build failed: {e}")

    print(f"  [repricer] Total: ${total:,.0f} | Day: ${day:+,.0f}")

    return portfolio


# ── Standalone ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root      = Path(__file__).parent.parent
    state_dir = root / "data" / "portfolios" / "state"
    hp        = state_dir / "holdings.json"

    if not hp.exists():
        print("holdings.json not found — run run_portfolio.bat first")
        raise SystemExit(1)

    portfolio = json.loads(hp.read_text(encoding="utf-8"))
    print(f"Loaded {len(portfolio.get('holdings', []))} holdings")
    print(f"Before: ${portfolio['portfolio_totals']['total_value']:,.0f} | "
          f"Day: ${portfolio['portfolio_totals']['day_change']:+,.0f}")

    portfolio = reprice_portfolio(portfolio, state_dir)

    hp.write_text(json.dumps(portfolio, indent=2, default=str), encoding="utf-8")
    print(f"After:  ${portfolio['portfolio_totals']['total_value']:,.0f} | "
          f"Day: ${portfolio['portfolio_totals']['day_change']:+,.0f}")
    print("holdings.json updated.")

    cache_path = state_dir / "finviz_quote_cache.json"
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        meta  = cache.get("_meta", {})
        print(f"Quote cache: {meta.get('symbols_cached',0)} symbols | updated {meta.get('last_updated','?')}")
