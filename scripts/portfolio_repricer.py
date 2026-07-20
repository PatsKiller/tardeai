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

# ── Cash / money-market symbols — never reprice these as stocks ───────────────
_CASH_SYMBOLS = frozenset({
    "SNAXX", "SWVXX", "VMFXX", "SPRXX", "FDRXX",
    "CASH & CASH INVESTMENTS", "CASH", "MMKT",
})

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
def _tradeable_equity_symbol(h: dict) -> Optional[str]:
    """Standard US exchange ticker (Schwab + Fidelity IRA stocks/ETFs). Skips cash, loans, plan codes."""
    sym = (h.get("symbol") or "").upper().strip()
    if not sym or sym in _CASH_SYMBOLS or h.get("is_loan") or h.get("is_cash"):
        return None
    core = sym.split(".")[0]
    if not (core.isalpha() and 1 <= len(core) <= 5):
        return None   # 401k/plan codes (OG51, SP500-D) — no Finviz series
    return sym


# Intraday Finviz refresh cadence (portfolio_live_monitor + cron share this target).
FINVIZ_REFRESH_INTERVAL_MIN = 15


def _get_all_symbols(portfolio: Dict, root: Path) -> Dict[str, List[str]]:
    """
    Returns dict of symbol lists by source:
      finviz: ALL tradeable portfolio equities (Schwab + fidelity_rollover_ira + watchlist)
      fidelity: proprietary mutual-fund / plan codes (Yahoo NAV after 8 PM)
    """
    holdings = portfolio.get("holdings", [])

    portfolio_syms = sorted({s for h in holdings if (s := _tradeable_equity_symbol(h))})
    schwab_syms = sorted({s for h in holdings if (s := _tradeable_equity_symbol(h))
                          and str(h.get("account") or "").startswith("schwab")})
    fidelity_ira_syms = sorted({s for h in holdings if (s := _tradeable_equity_symbol(h))
                                and str(h.get("account") or "").startswith("fidelity")
                                and str(h.get("account") or "") != "fidelity_401k"})

    # Fidelity proprietary / plan symbols (not on Finviz)
    fidelity_syms = sorted({
        (h.get("symbol") or "").upper() for h in holdings
        if (h.get("broker") == "fidelity" or str(h.get("account") or "").startswith("fidelity"))
        and not h.get("is_loan") and not _tradeable_equity_symbol(h)
        and (h.get("symbol") or "")
    })

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

    # All Finviz symbols = full portfolio tradeables + watchlist (deduplicated)
    finviz_syms = sorted(set(portfolio_syms + watchlist_syms))

    return {
        "finviz": finviz_syms,
        "fidelity": fidelity_syms,
        "watchlist": watchlist_syms,
        "schwab": schwab_syms,
        "fidelity_ira": fidelity_ira_syms,
        "portfolio": portfolio_syms,
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
            merged = dict(old)
            merged.update(changed)
            merged["symbol"]       = sym
            merged["source"]       = new_data.get("source", "finviz_elite")
            merged["last_updated"] = now_str
            merged["last_fetched"] = now_str
            existing[sym] = merged
            updated_count += 1
        else:
            # Price within delta — still stamp fetch time so staleness checks stay honest
            merged = dict(old)
            merged["last_fetched"] = now_str
            existing[sym] = merged
            updated_count += 1

    # Update meta
    existing["_meta"] = {
        "last_updated":   now_str,
        "last_fetched":   now_str,
        "symbols_cached": len([k for k in existing if k != "_meta"]),
        "source":         "finviz_elite_v152_v141",
        "refresh_interval_minutes": FINVIZ_REFRESH_INTERVAL_MIN,
        "fields":         ["price", "change_pct", "prev_close", "volume", "analyst",
                           "target", "perf_week", "perf_month", "perf_quarter",
                           "perf_halfyr", "perf_ytd", "perf_year",
                           "volatility_w", "volatility_m", "rvol"],
        "update_policy":  "delta fields + always refresh last_fetched timestamp",
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
        if sym in _CASH_SYMBOLS:
            continue
        shares = float(h.get("shares") or 0)
        broker = h.get("broker", "")
        acct = str(h.get("account") or "")

        if broker == "fidelity" and sym not in live_prices:
            if sym in fidelity_prices and shares > 0:
                new_price = fidelity_prices[sym]
                old_price = float(h.get("price") or new_price)
                # Sanity: reject price jumps > 50% in a single reprice
                if old_price > 0 and abs(new_price - old_price) / old_price > 0.50:
                    print(f"  [repricer] ⛔ REJECTED {sym}: price jump {old_price:.2f} → {new_price:.2f} ({abs(new_price-old_price)/old_price*100:.0f}%) exceeds 50% guard")
                    continue
                h["price"]          = round(new_price, 4)
                h["market_value"]   = round(new_price * shares, 2)
                h["day_change"]     = round((new_price - old_price) * shares, 2)
                h["day_change_pct"] = round(((new_price - old_price) / old_price * 100) if old_price else 0, 4)
                updated += 1
        elif sym in live_prices and shares > 0:
            p          = live_prices[sym]
            new_price  = p["price"]
            prev_close = p["prev_close"]
            chg_pct    = p["change_pct"]
            old_price  = float(h.get("price") or h.get("current_price") or new_price)
            if old_price > 0 and abs(new_price - old_price) / old_price > 0.50:
                print(f"  [repricer] ⛔ REJECTED {sym}: price jump {old_price:.2f} → {new_price:.2f} ({abs(new_price-old_price)/old_price*100:.0f}%) exceeds 50% guard")
                continue
            h["price"]          = round(new_price, 4)
            h["current_price"]  = round(new_price, 4)  # always keep in sync — guard must not split these
            h["market_value"]   = round(new_price * shares, 2)
            h["day_change"]     = round((new_price - prev_close) * shares, 2)
            h["day_change_pct"] = round(chg_pct, 4)
            h["price_source"]   = "finviz"
            cost = h.get("cost_basis") or 0
            if not cost and h.get("avg_cost"):
                cost = float(h["avg_cost"]) * shares
                h["cost_basis"] = round(cost, 2)
            if cost:
                h["gain_loss"]     = round(h["market_value"] - float(cost), 2)
                h["gain_loss_pct"] = round(h["gain_loss"] / float(cost) * 100, 4) if float(cost) else None
            updated += 1
    return updated


# ── Recalculate totals ─────────────────────────────────────────────────────────
def _recalc_totals(portfolio: Dict) -> None:
    """Recalculate account summaries and portfolio totals from updated holdings."""
    holdings = portfolio.get("holdings", [])
    account_summaries = portfolio.get("account_summaries", {})

    def _choose_fund_anchor(ah):
        """401k proprietary fund codes — residual lands on largest plan holding."""
        candidates = [h for h in ah if not h.get("is_loan") and not h.get("is_cash") and h.get("symbol") not in _CASH_SYMBOLS]
        if not candidates:
            return None
        proprietary = [h for h in candidates if "-" in str(h.get("symbol", ""))]
        if proprietary:
            contra = [h for h in proprietary if "CONTRA" in str(h.get("symbol", "")).upper() or "CONTRA" in str(h.get("name", "")).upper()]
            if contra:
                return max(contra, key=lambda x: x.get("market_value", 0) or 0)
            return max(proprietary, key=lambda x: x.get("market_value", 0) or 0)
        return max(candidates, key=lambda x: x.get("market_value", 0) or 0)

    def _choose_cash_anchor(ah):
        """Cash / money-market — safe sink for brokerage total drift (never corrupts live quotes)."""
        cash = [h for h in ah if h.get("is_cash") or str(h.get("symbol") or "").upper() in _CASH_SYMBOLS]
        return max(cash, key=lambda x: x.get("market_value", 0) or 0) if cash else None

    def _reported_total_stale(acct: dict, now: datetime) -> bool:
        as_of = str(acct.get("reported_total_as_of") or acct.get("as_of") or "")
        if not as_of:
            return False
        try:
            ref = datetime.strptime(as_of[:10], "%Y-%m-%d")
            return (now.date() - ref.date()).days > 2
        except ValueError:
            return False

    now = _et_now()

    for acct_key, acct in account_summaries.items():
        ah = [h for h in holdings if h.get("account") == acct_key and not h.get("is_loan")]
        derived_total = round(sum(h.get("market_value") or 0 for h in ah), 2)
        reported_total = float(acct.get("reported_total_value") or 0)
        source = str(acct.get("source", "")).lower()
        acct_total = derived_total
        is_fidelity = str(acct_key).startswith("fidelity") or "fidelity" in source
        is_401k = str(acct_key) == "fidelity_401k"

        if reported_total > 0 and is_fidelity:
            drift = round(reported_total - derived_total, 2)
            if abs(drift) >= 0.01:
                if _reported_total_stale(acct, now) and not is_401k:
                    acct_total = derived_total
                    acct["reported_total_stale"] = True
                    print(f"  [repricer][guard] {acct_key}: reported ${reported_total:,.2f} stale "
                          f"(as_of {acct.get('reported_total_as_of') or acct.get('as_of')}) — using derived ${derived_total:,.2f}")
                else:
                    anchor = _choose_cash_anchor(ah) if not is_401k else _choose_fund_anchor(ah)
                    if anchor and (anchor.get("is_cash") or str(anchor.get("symbol") or "").upper() in _CASH_SYMBOLS):
                        before = round(anchor.get("market_value", 0) or 0, 2)
                        after = round(before + drift, 2)
                        if after >= 0:
                            anchor["market_value"] = after
                            anchor["shares"] = after
                            anchor["price"] = 1.0
                            anchor["current_price"] = 1.0
                            acct_total = reported_total
                            print(f"  [repricer][guard] {acct_key}: derived ${derived_total:,.2f} vs reported "
                                  f"${reported_total:,.2f} → residual ${drift:+,.2f} applied to cash {anchor.get('symbol')}")
                        else:
                            acct_total = derived_total
                            print(f"  [repricer][guard] {acct_key}: cash residual ${drift:+,.2f} would go negative — "
                                  f"using derived ${derived_total:,.2f}")
                    elif anchor and is_401k:
                        before = round(anchor.get("market_value", 0) or 0, 2)
                        anchor["market_value"] = round(before + drift, 2)
                        shares = float(anchor.get("shares") or 0)
                        if shares > 0:
                            anchor["price"] = round(anchor["market_value"] / shares, 6)
                        acct_total = reported_total
                        print(f"  [repricer][guard] {acct_key}: residual ${drift:+,.2f} applied to fund {anchor.get('symbol')}")
                    else:
                        acct_total = derived_total
                        print(f"  [repricer][guard] {acct_key}: no cash anchor for drift ${drift:+,.2f} — "
                              f"using derived ${derived_total:,.2f}")
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

    # Sanity: reject if total changed > 25% from previous (likely data corruption)
    prev_total = portfolio.get("portfolio_totals", {}).get("total_value", 0) or 0
    if prev_total > 0 and gt > 0:
        drift_pct = abs(gt - prev_total) / prev_total * 100
        if drift_pct > 25:
            print(f"  [repricer] ⛔ TOTAL SANITY FAIL: ${prev_total:,.0f} → ${gt:,.0f} ({drift_pct:.1f}% drift)")
            print(f"  [repricer]   Likely data corruption. Keeping previous total.")
            return  # abort total update, keep previous values

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
        priced_schwab = len([s for s in sym_groups["schwab"] if s in live_prices])
        priced_fid = len([s for s in sym_groups.get("fidelity_ira", []) if s in live_prices])
        print(f"  [repricer] Finviz: {len(live_prices)}/{len(finviz_syms)} symbols priced "
              f"(schwab {priced_schwab}/{len(sym_groups['schwab'])}, "
              f"fidelity_ira {priced_fid}/{len(sym_groups.get('fidelity_ira', []))}, "
              f"watchlist {len([s for s in sym_groups['watchlist'] if s in live_prices])}/{len(sym_groups['watchlist'])})")

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
    # generated_at used to hold the date the POSITION LIST was built and was never
    # touched by repricing, so a file repriced seconds ago still advertised
    # generated_at from days earlier (observed 2026-07-20: generated_at
    # 2026-07-17 alongside last_repriced 10:05 the same morning). Anything using
    # the obvious freshness field would call live data three days stale.
    # generated_at now means "these contents are current as of"; the original
    # build time is preserved once under positions_built_at.
    if portfolio.get("generated_at") and not portfolio.get("positions_built_at"):
        portfolio["positions_built_at"] = portfolio["generated_at"]
    portfolio["generated_at"] = now_str
    portfolio["_freshness_note"] = (
        "generated_at = contents current as of (refreshed every reprice). "
        "positions_built_at = when the position list was constructed. "
        "last_repriced = price refresh time.")

    total = portfolio["portfolio_totals"]["total_value"]
    day   = portfolio["portfolio_totals"]["day_change"]

    try:
        from ticker_snapshot_builder import build_ticker_snapshot
        out = build_ticker_snapshot(portfolio, root)
        print(f"  [repricer] Ticker snapshot → {out}")
    except Exception as e:
        print(f"  [repricer] WARNING: ticker snapshot build failed: {e}")

    print(f"  [repricer] Total: ${total:,.0f} | Day: ${day:+,.0f}")

    # ── Follow-up B: unify ticker_prices for held symbols so ALL surfaces agree with the portfolio view ──
    try:
        _sync_ticker_prices(portfolio, root)
    except Exception as e:
        print(f"  [repricer] WARNING: ticker_prices sync failed: {e}")

    return portfolio


def _sync_ticker_prices(portfolio, root):
    """Write each held symbol's repriced close into ticker_prices for today (update today's row, else insert)
    so surfaces reading ticker_prices match holdings.json. Best-effort; never breaks repricing."""
    import psycopg2
    _load_env(root)
    seen, n = set(), 0
    c = psycopg2.connect(host=os.getenv("DB_HOST", "localhost"), port=os.getenv("DB_PORT", "5432"),
                         dbname=os.getenv("DB_NAME", "trade_ai"), user=os.getenv("DB_USER", "trade_ai"),
                         password=os.getenv("DB_PASSWORD"))
    cur = c.cursor()
    for h in portfolio.get("holdings", []):
        sym, px = h.get("symbol"), h.get("price")
        if not sym or sym in seen or h.get("is_cash") or not px or px <= 0:
            continue
        seen.add(sym)
        cur.execute("UPDATE ticker_prices SET close_price=%s, source='portfolio_repricer' WHERE symbol=%s AND price_date=CURRENT_DATE", (px, sym))
        if cur.rowcount == 0:
            cur.execute("INSERT INTO ticker_prices (symbol, price_date, close_price, source, created_at) VALUES (%s, CURRENT_DATE, %s, 'portfolio_repricer', now())", (sym, px))
        n += 1
    c.commit(); c.close()
    print(f"  [repricer] ticker_prices synced for {n} held symbols (unified with portfolio view)")


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
