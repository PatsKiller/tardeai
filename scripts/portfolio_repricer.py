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


def _utc_now_iso() -> str:
    from datetime import timezone
    return datetime.now(timezone.utc).isoformat()


def _preserve_broker_snapshot(h: Dict[str, Any], shares: float) -> None:
    """Capture broker facts once. Never overwrite them with a later mark."""
    if h.get("broker_shares") is None and shares:
        h["broker_shares"] = shares
    if h.get("broker_market_value") is None:
        # Only snapshot an existing MV if it is not already an analytical rewrite.
        if str(h.get("mv_basis") or "") != "shares_x_canonical_mark" and h.get("market_value") is not None:
            h["broker_market_value"] = h.get("market_value")
            h["broker_source"] = h.get("broker_source") or "broker_position_snapshot"
            h["broker_ingested_at"] = h.get("broker_ingested_at") or h.get("as_of") or _utc_now_iso()
    if h.get("broker_position_price") is None:
        implied = None
        try:
            if shares and h.get("broker_market_value") is not None:
                implied = float(h["broker_market_value"]) / float(shares)
        except (TypeError, ValueError, ZeroDivisionError):
            implied = None
        h["broker_position_price"] = implied
        h["broker_position_as_of"] = h.get("broker_position_as_of") or h.get("as_of")

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
            is_proxy = str(pub_sym).upper() != str(fid_sym).upper()
            sym_data = prices.get(pub_sym, {})
            for d in dates:
                val = sym_data.get(d)
                if val is not None:
                    px = float(val) if not isinstance(val, dict) else float(val.get("close", 0) or 0)
                    result[fid_sym] = {
                        "price": px,
                        "source": "proxy_public_ticker" if is_proxy else "price_cache_nav",
                        "source_as_of": d,
                        "proxy": is_proxy,
                        "not_for_valuation": is_proxy,
                        "mapped_symbol": pub_sym if is_proxy else fid_sym,
                    }
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
            meta = fidelity_prices.get(sym) if isinstance(fidelity_prices.get(sym), dict) else None
            raw_px = (meta or {}).get("price") if meta else fidelity_prices.get(sym)
            if raw_px and shares > 0:
                new_price = float(raw_px)
                if (meta or {}).get("proxy") or (meta or {}).get("not_for_valuation"):
                    h["proxy"] = True
                    h["not_for_valuation"] = True
                    h["canonical_mark_type"] = "proxy"
                    h["canonical_mark"] = round(new_price, 4)
                    h["canonical_mark_source"] = (meta or {}).get("source") or "proxy"
                    h["canonical_mark_as_of"] = (meta or {}).get("source_as_of")
                    # Never set market_value / UPL / weight from a proxy.
                    updated += 1
                    continue
                _preserve_broker_snapshot(h, shares)
                src = (meta or {}).get("source") or "nav"
                h["canonical_mark"] = round(new_price, 4)
                h["canonical_mark_source"] = src
                h["canonical_mark_as_of"] = (meta or {}).get("source_as_of")
                h["canonical_mark_ingested_at"] = _utc_now_iso()
                h["analytical_market_value"] = round(new_price * shares, 2)
                h["price_source"] = src
                updated += 1
        elif sym in live_prices and shares > 0:
            p          = live_prices[sym]
            new_price  = p["price"]
            prev_close = p.get("prev_close") or new_price
            chg_pct    = p.get("change_pct") or 0
            old_mark   = float(h.get("canonical_mark") or h.get("current_price") or new_price)
            if old_mark > 0 and abs(new_price - old_mark) / old_mark > 0.50:
                print(f"  [repricer] ⛔ REJECTED {sym}: price jump {old_mark:.2f} → {new_price:.2f} ({abs(new_price-old_mark)/old_mark*100:.0f}%) exceeds 50% guard")
                continue
            _preserve_broker_snapshot(h, shares)
            src = str(p.get("source") or "unknown")
            h["canonical_mark"] = round(new_price, 4)
            h["canonical_mark_source"] = src
            h["canonical_mark_type"] = p.get("mark_type") or "unknown"
            h["canonical_mark_as_of"] = p.get("source_as_of") or p.get("as_of")
            h["canonical_mark_ingested_at"] = _utc_now_iso()
            h["analytical_market_value"] = round(new_price * shares, 2)
            h["analytical_unrealized_pl_usd"] = None
            cost = h.get("cost_basis") or 0
            if cost:
                h["analytical_unrealized_pl_usd"] = round(h["analytical_market_value"] - float(cost), 2)
            # Day change is an analytical display field, not a broker fact.
            h["day_change"]     = round((new_price - prev_close) * shares, 2)
            h["day_change_pct"] = round(chg_pct, 4)
            h["price_source"]   = src
            updated += 1
    _annotate_canonical_quotes(holdings)
    return updated


def _annotate_canonical_quotes(holdings: List[Dict]) -> None:
    """Stamp named quote lineage onto holdings. Fail-soft — never breaks reprice."""
    try:
        try:
            from lib.cio_canonical_quote import (  # type: ignore
                CANONICAL_QUOTE_OUTPUT_FIELDS,
                apply_canonical_quote_fields,
            )
        except ImportError:
            from scripts.lib.cio_canonical_quote import (
                CANONICAL_QUOTE_OUTPUT_FIELDS,
                apply_canonical_quote_fields,
            )
    except Exception as e:
        print(f"  [repricer] canonical quote annotate unavailable: {e}")
        return
    n = 0
    for h in holdings:
        if not isinstance(h, dict):
            continue
        if h.get("is_loan") or h.get("is_cash"):
            continue
        try:
            named = apply_canonical_quote_fields(h)
            stamped = bool(h.get("canonical_mark_ingested_at"))
            for k in CANONICAL_QUOTE_OUTPUT_FIELDS:
                if k not in named:
                    continue
                if stamped and k.startswith("canonical_"):
                    continue
                h[k] = named[k]
            n += 1
        except Exception as e:
            print(f"  [repricer] canonical quote annotate skip {h.get('symbol')}: {e}")
    if n:
        print(f"  [repricer] canonical quote fields annotated on {n} holdings")


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
            acct["broker_reported_total_usd"] = reported_total
            acct["derived_broker_component_total_usd"] = derived_total
            if abs(drift) >= 0.01:
                # Residual is NON_SECURITY / NON_ACTIONABLE. Never inject into cash or a fund.
                acct["reconciliation_residual_usd"] = drift
                acct["residual_source"] = "broker_reported_vs_derived_holdings"
                acct["residual_as_of"] = now.isoformat() if hasattr(now, "isoformat") else str(now)
                acct["residual_quality"] = "UNEXPLAINED" if abs(drift) >= 1.0 else "IMMATERIAL"
                acct["residual_class"] = "NON_SECURITY"
                acct_total = derived_total
                if _reported_total_stale(acct, now) and not is_401k:
                    acct["reported_total_stale"] = True
                print(f"  [repricer][residual] {acct_key}: ACCOUNT_RECONCILIATION_RESIDUAL "
                      f"${drift:+,.2f} (reported ${reported_total:,.2f} vs derived ${derived_total:,.2f}) "
                      f"— not injected into cash or a fund")
            else:
                acct["reconciliation_residual_usd"] = 0.0
                acct_total = reported_total

        acct["total_value"] = round(acct_total, 2)
        acct["day_change"]  = round(sum(h.get("day_change") or 0 for h in ah), 2)
        acct_prev = (acct["total_value"] - acct["day_change"])
        acct["day_change_pct"] = round((acct["day_change"] / acct_prev * 100) if acct_prev else 0, 4)
        cost = sum(h.get("cost_basis") or 0 for h in ah)
        gain = sum(h.get("gain_loss") or 0 for h in ah)
        acct["total_gain"]     = round(gain, 2)
        acct["total_gain_pct"] = round((gain / cost * 100) if cost else 0, 4)

    if "portfolio_totals" not in portfolio or not isinstance(portfolio.get("portfolio_totals"), dict):
        portfolio["portfolio_totals"] = {}
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

    # total_cash is written here for the same reason as in portfolio_loader: it
    # was the one key in this dict that no writer refreshed, so every pass left
    # the previous value in place and it drifted ($478k vs $186k real by
    # 2026-07-21; $578,107.50 vs $630,784.82 by 2026-08-29).
    #
    # This is the writer that actually runs. The 16:10 Mon-Fri cron invokes
    # portfolio_repricer, not portfolio_loader.load_all_portfolios — the stored
    # document shows last_repriced on 08-28 while the loader's last_pipeline_run
    # was still 08-26. Patching the loader alone would not have fired.
    #
    # `total_mv_excluded` above is the tell: it sits in this update list and has
    # stayed correct to the cent, while total_cash — absent from it — rotted.
    _cash_rows = [h for h in holdings if h.get("is_cash")]
    _total_cash = round(sum(float(h.get("market_value") or 0) for h in _cash_rows), 2)

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
        "total_cash":            _total_cash,
        "total_cash_source":     "position_rows",
        "total_cash_written_at": _utc_now_iso(),
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
        for sym, rec in yahoo_prices.items():
            rec = rec if isinstance(rec, dict) else {"price": rec, "source": "yahoo_cache_fallback"}
            price = float(rec.get("price") or 0)
            if price > 0:
                live_prices[sym] = {
                    "price":      round(price, 4),
                    "change_pct": 0.0,
                    "prev_close": round(price, 4),
                    "source":     rec.get("source") or "yahoo_cache_fallback",
                    "source_as_of": rec.get("source_as_of"),
                    "mark_type": "unknown",
                }
        if yahoo_prices:
            print(f"  [repricer] Yahoo fallback: {len(yahoo_prices)} symbols "
                  f"({', '.join(yahoo_prices.keys())})")

    n_holdings = _apply_to_holdings(portfolio.get("holdings", []), live_prices, fidelity_prices)
    print(f"  [repricer] Holdings updated: {n_holdings}")

    # ── 4. Recalculate totals ─────────────────────────────────────────────────
    _recalc_totals(portfolio)
    # Residual 401k/cash guards may rewrite a fund `price`; re-stamp lineage.
    _annotate_canonical_quotes(portfolio.get("holdings") or [])

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
    root = Path(__file__).resolve().parents[1]
    # Make the repo ROOT importable so `from scripts.lib.X` resolves. Run as
    # `python scripts/portfolio_repricer.py` (how cron invokes it) sys.path[0] is
    # scripts/, not the repo root, so the scripts.-prefixed import raises
    # "No module named 'scripts'". Same bootstrap as portfolio_server.py.
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    # Resolve where the LIVE server reads from, not just this checkout. Every
    # deployed release symlinks data/portfolios/state at the persistent root,
    # so a checkout-relative write is invisible to the served surface.
    try:
        from scripts.lib.persistent_state_root import portfolio_state_write_targets
        state_dirs = portfolio_state_write_targets(root)
    except Exception as _e:  # helper genuinely unavailable
        print(f"  [repricer] WARN persistent-root helper unavailable ({_e}) — checkout only")
        state_dirs = [root / "data" / "portfolios" / "state"]

    # Ops/CI probe: print the resolved write targets and exit. No quotes fetched,
    # nothing written — safe to run against production at any time.
    if "--print-targets" in sys.argv:
        for _t in state_dirs:
            print(f"{_t}\t{'exists' if (_t / 'holdings.json').exists() else 'absent'}")
        raise SystemExit(0)

    state_dir = state_dirs[0]
    hp        = state_dir / "holdings.json"

    if not hp.exists():
        print("holdings.json not found — run run_portfolio.bat first")
        raise SystemExit(1)

    if len(state_dirs) > 1:
        print(f"  [repricer] state targets: {', '.join(str(d) for d in state_dirs)}")

    portfolio = json.loads(hp.read_text(encoding="utf-8"))
    print(f"Loaded {len(portfolio.get('holdings', []))} holdings")
    print(f"Before: ${portfolio['portfolio_totals']['total_value']:,.0f} | "
          f"Day: ${portfolio['portfolio_totals']['day_change']:+,.0f}")

    portfolio = reprice_portfolio(portfolio, state_dir)

    _payload = json.dumps(portfolio, indent=2, default=str)
    _written, _skipped = [], []
    for _d in state_dirs:
        _target = _d / "holdings.json"
        # Only refresh a copy that already exists: this writer reprices an
        # existing book, it does not create a new one somewhere unexpected.
        if not _target.exists():
            _skipped.append(f"{_target} (absent)")
            continue
        try:
            _target.write_text(_payload, encoding="utf-8")
            _written.append(str(_target))
        except OSError as _e:
            # Never let a secondary copy failure lose the primary reprice.
            _skipped.append(f"{_target} ({_e.__class__.__name__})")
    print(f"After:  ${portfolio['portfolio_totals']['total_value']:,.0f} | "
          f"Day: ${portfolio['portfolio_totals']['day_change']:+,.0f}")
    if not _written:
        print("ERROR: no holdings.json copy could be written")
        raise SystemExit(1)
    print(f"holdings.json updated ({len(_written)} copy/copies): {', '.join(_written)}")
    for _s in _skipped:
        print(f"  [repricer] WARN not updated: {_s}")
    try:
        from sync_portfolio_watchlist_membership import sync_portfolio_watchlist_membership
        _ms = sync_portfolio_watchlist_membership(portfolio)
        if _ms.get("exited"):
            print(f"portfolio watchlist membership: exited {_ms['exited']} sold symbols")
    except Exception as _e:
        print(f"portfolio watchlist membership sync failed: {_e}")

    cache_path = state_dir / "finviz_quote_cache.json"
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        meta  = cache.get("_meta", {})
        print(f"Quote cache: {meta.get('symbols_cached',0)} symbols | updated {meta.get('last_updated','?')}")
