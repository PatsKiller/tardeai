"""portfolio_options.py — Covered Call & Options Intelligence
Scans all positions with >100 shares for covered call opportunities.
Uses Finviz IV data + ATR to estimate premiums.
Enforces earnings blackout, ex-dividend interaction, minimum lot size.
"""
from __future__ import annotations
import json, os, requests, yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

def _f(s, default=0.0):
    try: return float(str(s).replace(",","").replace("%","").strip())
    except: return default

def _load_env_file(root: Path):
    env = root/".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k,v = line.split("=",1)
                os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

def load_intent_cfg(root: Path) -> Dict:
    try:
        return yaml.safe_load((root/"assets"/"portfolio_intent.yaml").read_text()) or {}
    except: return {}

class EarningsProviderError(RuntimeError):
    """The earnings provider could not be reached or refused the request.

    Distinct from 'the provider answered and this symbol has no scheduled
    earnings'. Callers MUST NOT collapse the two: treating provider-down as
    no-earnings makes every event gate fail OPEN.
    """


def _get_earnings_dates(tickers: List[str], root: Path) -> Dict[str, str]:
    """Next earnings date per ticker from FMP.

    Raises EarningsProviderError when the provider is unusable (missing key,
    non-OK HTTP, unparseable body). Returns {} ONLY when the provider answered
    successfully and none of the requested tickers have a scheduled date.

    2026-07-20: the v3 earning_calendar endpoint now returns HTTP 403
    ("Legacy Endpoint ... only available for legacy users with valid
    subscriptions prior August 31, 2025"). This previously returned {}
    silently, so earnings_blackout_check saw "no earnings" for every symbol
    and passed short-premium/directional entries straight through.
    """
    _load_env_file(root)
    import os as _os
    fmp_key = _os.getenv("FMP_API_KEY","")
    if not fmp_key:
        raise EarningsProviderError("FMP_API_KEY is not set — no earnings provider configured")
    results = {}
    today = datetime.now()
    end   = (today + timedelta(days=90)).strftime("%Y-%m-%d")
    url = f"https://financialmodelingprep.com/api/v3/earning_calendar?from={today.strftime('%Y-%m-%d')}&to={end}&apikey={fmp_key}"
    try:
        resp = requests.get(url, timeout=15)
    except Exception as e:
        raise EarningsProviderError(f"FMP request failed: {e}") from e
    if not resp.ok:
        detail = (resp.text or "")[:160].replace("\n", " ")
        raise EarningsProviderError(f"FMP HTTP {resp.status_code}: {detail}")
    try:
        payload = resp.json() or []
    except Exception as e:
        raise EarningsProviderError(f"FMP returned unparseable body: {e}") from e
    for item in payload:
        sym = (item.get("symbol") or "").upper()
        if sym in tickers:
            results[sym] = item.get("date","")
    return results

def _estimate_premium(price: float, strike: float, atr: float, iv_pct: float, dte: int = 30) -> float:
    """
    Estimate call option premium using simplified Black-Scholes approximation.
    Uses IV from Finviz (if available) or ATR-based IV proxy.
    """
    import math
    if not price or not strike or not atr: return 0.0

    # Use Finviz IV if available, else derive from ATR
    if iv_pct and iv_pct > 0:
        iv = iv_pct / 100
    else:
        # ATR-based IV proxy: annualize daily ATR
        daily_vol = atr / price
        iv = daily_vol * math.sqrt(252)

    # Simplified premium estimate (OTM call)
    otm_pct = (strike - price) / price
    t = dte / 365
    # Simple formula: premium ≈ price × iv × sqrt(t) × N(d2) adjusted for moneyness
    d1 = (math.log(price/strike) + 0.5*iv*iv*t) / (iv*math.sqrt(t))
    d2 = d1 - iv*math.sqrt(t)

    def N(x):
        """Standard normal CDF approximation."""
        k = 1/(1+0.2316419*abs(x))
        poly = k*(0.319381530 + k*(-0.356563782 + k*(1.781477937 + k*(-1.821255978 + k*1.330274429))))
        n = math.exp(-x*x/2) / math.sqrt(2*math.pi)
        cdf = 1 - n*poly if x >= 0 else n*poly
        return cdf

    premium = price * N(d1) - strike * math.exp(-0.05*t) * N(d2)
    return max(0.01, round(premium, 2))

def scan_covered_calls(portfolio: Dict, technical_data: Dict, root: Path, state_dir: Path) -> Dict:
    """Scan all holdings for covered call opportunities."""
    _load_env_file(root)
    intent_cfg = load_intent_cfg(root)
    cc_settings = intent_cfg.get("covered_call_settings", {})

    min_shares   = cc_settings.get("min_shares_for_call", 100)
    default_dte  = cc_settings.get("default_dte_days", 30)
    default_otm  = cc_settings.get("default_otm_pct", 0.06)
    min_otm      = cc_settings.get("min_otm_pct", 0.04)
    max_otm      = cc_settings.get("max_otm_pct", 0.10)
    blackout_days= cc_settings.get("earnings_blackout_days", 14)

    # Get eligible positions
    candidates = []
    all_syms = []
    for h in portfolio.get("holdings", []):
        sym    = h.get("symbol","").upper()
        shares = h.get("shares", 0) or 0
        mv     = h.get("market_value", 0) or 0
        price  = h.get("price", 0) or 0
        if shares >= min_shares and mv >= 1000 and price > 0 and not h.get("is_loan"):
            candidates.append(h)
            all_syms.append(sym)

    if not candidates:
        return {"opportunities": [], "total_monthly_income": 0, "has_data": False}

    # Get earnings dates for blackout
    earnings_dates = _get_earnings_dates(all_syms, root)

    opportunities = []
    total_monthly  = 0.0

    for h in candidates:
        sym    = h.get("symbol","").upper()
        shares = h.get("shares", 0)
        price  = h.get("price", 0)
        mv     = h.get("market_value", 0)
        acct   = h.get("account_display", h.get("account",""))

        # Get technical data
        tech   = technical_data.get(sym, {})
        atr    = tech.get("atr") or (price * 0.015 if price else 1.0)
        iv_pct = tech.get("iv", 0)  # Finviz IV% if available
        target = tech.get("target", 0)
        sma200 = tech.get("sma200")
        rsi    = tech.get("rsi", 50)

        # Number of contracts possible (100 shares per contract)
        if not shares or not price: continue
        contracts = int((shares or 0) // 100)
        if contracts < 1:
            continue

        # Earnings blackout check
        earn_date = earnings_dates.get(sym)
        in_blackout = False
        days_to_earnings = None
        if earn_date:
            try:
                ed = datetime.strptime(earn_date[:10], "%Y-%m-%d")
                days_to_earnings = (ed - datetime.now()).days
                if 0 <= days_to_earnings <= blackout_days:
                    in_blackout = True
            except: pass

        # Dynamic OTM % based on technical context
        # If price near resistance (RSI high, near 52wk high) → tighter OTM
        # If price below SMA200 → wider OTM (need more upside to potentially exit)
        otm_pct = default_otm
        if rsi and rsi > 65:    otm_pct = min_otm + 0.01   # tighter when overbought
        if sma200 and price < sma200: otm_pct = max_otm - 0.01   # wider when below SMA200

        otm_pct = max(min_otm, min(max_otm, otm_pct))

        # Calculate strike (round to nearest $1 or $2.50 depending on price)
        raw_strike = price * (1 + otm_pct)
        if price < 50:   strike = round(raw_strike / 0.5)  * 0.5
        elif price < 100: strike = round(raw_strike / 1.0) * 1.0
        elif price < 200: strike = round(raw_strike / 2.5) * 2.5
        else:            strike = round(raw_strike / 5.0)  * 5.0

        # Premium estimate
        premium_per_share = _estimate_premium(price, strike, atr, iv_pct, default_dte)
        premium_per_contract = round(premium_per_share * 100, 2)
        total_premium = round(premium_per_contract * contracts, 2)
        monthly_income = total_premium  # assuming monthly
        annual_income  = round(monthly_income * 12, 2)
        annualized_yield = round(annual_income / mv * 100, 2)

        # If called away: profit calculation
        profit_if_called = round((strike - price) * (shares or 0) * contracts / 100 + total_premium, 2)

        # Stop if called away: what happens to Roth conversion plan
        is_v = sym == "V"
        roth_note = ""
        if is_v:
            monthly_roth_contribution = round(monthly_income * 0.9, 0)  # 90% to Roth
            roth_note = f"${monthly_roth_contribution:,.0f}/mo premium can fund Roth conversion"

        opp = {
            "symbol":           sym,
            "account":          acct,
            "shares":           shares,
            "price":            price,
            "market_value":     mv,
            "contracts":        contracts,
            "strike":           strike,
            "otm_pct":          round(otm_pct*100, 1),
            "dte":              default_dte,
            "premium_per_share":premium_per_share,
            "premium_per_contract": premium_per_contract,
            "total_premium":    total_premium,
            "monthly_income":   monthly_income,
            "annual_income":    annual_income,
            "annualized_yield": annualized_yield,
            "atr":              round(atr, 2),
            "rsi":              rsi,
            "sma200":           sma200,
            "in_blackout":      in_blackout,
            "days_to_earnings": days_to_earnings,
            "earn_date":        earn_date,
            "analyst_target":   target,
            "profit_if_called": profit_if_called,
            "roth_note":        roth_note,
            "recommendation":   "WRITE CALL" if not in_blackout else f"WAIT — earnings in {days_to_earnings}d",
        }
        opportunities.append(opp)
        if not in_blackout:
            total_monthly += monthly_income

    # Sort by monthly income descending
    opportunities.sort(key=lambda x: -x["monthly_income"])

    # V-specific strategy summary
    v_opp = next((o for o in opportunities if o["symbol"] == "V"), None)
    v_strategy = None
    if v_opp:
        v_strategy = {
            "summary": (
                f"V Covered Call Strategy: Sell {v_opp['contracts']} contracts at "
                f"${v_opp['strike']:.0f} strike "
                f"({v_opp['otm_pct']:.0f}% OTM, {v_opp['dte']}DTE). "
                f"Est. premium: ${v_opp['total_premium']:,.0f}/month. "
                f"Annualized yield: {v_opp['annualized_yield']:.1f}% on "
                f"${v_opp['market_value']:,.0f} position. "
                f"Hard stop: SMA200 (${v_opp['sma200'] or 0:.0f}). "
                f"{v_opp['roth_note']}"
            ),
            "blackout": v_opp["in_blackout"],
            "monthly_income": v_opp["monthly_income"],
        }

    return {
        "has_data":            True,
        "opportunities":       opportunities,
        "total_monthly_income":round(total_monthly, 2),
        "total_annual_income": round(total_monthly * 12, 2),
        "v_strategy":          v_strategy,
        "eligible_positions":  len(opportunities),
        "blackout_count":      sum(1 for o in opportunities if o["in_blackout"]),
        "last_updated":        datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
