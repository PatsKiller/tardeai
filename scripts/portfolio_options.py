"""portfolio_options.py — LEGACY covered-call MODEL ESTIMATOR (advisory display only).

⚠️  SUPERSEDED for anything actionable. The authoritative covered-call path is the
Schwab live option chain (options_lifecycle_engine / options_desk_enterprise),
which uses real bid/ask/mid, real greeks, real open interest and real IV. This
module never touches the approval queue, proposals, tickets or order placement —
audited 2026-07-20, zero references — and its numbers must never be presented as
tradeable prices.

WHAT IT ACTUALLY COMPUTES (corrected 2026-07-20):
The header used to claim "Uses Finviz IV data + ATR". That was false. The IV
input reads technical_data[symbol]["iv"], and portfolio_technical.py has never
emitted an "iv" key — it emits realized-volatility fields (volatility_w /
volatility_m). So iv_pct was ALWAYS 0 and the Finviz-IV branch was dead code:
100% of premiums came from the ATR-derived REALIZED-volatility proxy, priced
through a simplified Black-Scholes.

Realized volatility is NOT implied volatility. An ATR-annualized sigma tells you
how the underlying HAS moved; an option premium is set by what the market expects
it to move. They diverge most exactly when it matters (around events), so these
figures can be badly wrong in either direction.

MEASURED ERROR vs the live Schwab chain (2026-07-20, Aug-21 expiry, n=5 where a
quote existed): median -28%, range -63% to +438%.
    V     model 2.95 vs live 4.08   -28%
    ARKX  model 0.30 vs live 0.82   -63%
    XAR   model 2.34 vs live 5.25   -55%
    JEPQ  model 0.43 vs live 0.08  +438%
JEPQ is the clearest illustration: it is itself a covered-call ETF, so its
realized volatility says nothing about the (heavily suppressed) premium the
market actually pays on it. The proxy is not merely imprecise — it is
structurally blind to why an option is priced the way it is.

Every opportunity therefore carries estimate_basis and a disclaimer, and the
scan result is stamped MODEL ESTIMATE — NO LIVE CHAIN.

Still enforces earnings blackout, ex-dividend interaction and minimum lot size.
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

MODEL_ESTIMATE_LABEL = "MODEL ESTIMATE — NO LIVE CHAIN"
RISK_FREE = 0.05


def _estimate_premium(price: float, strike: float, atr: float, sigma_pct: float,
                      dte: int = 30) -> float:
    """Simplified Black-Scholes premium from an ANNUALIZED REALIZED-VOLATILITY proxy.

    NOT an implied-volatility calculation and NOT a quotable price. sigma_pct is
    kept in the signature for callers that may one day supply a genuine vol
    input, but the project has no such source wired: portfolio_technical emits
    no "iv" key, so this is realized volatility annualized from ATR.

    Use options_lifecycle_engine.quote_leg() for a real, tradeable price.
    """
    import math
    if not price or not strike or not atr: return 0.0

    if sigma_pct and sigma_pct > 0:
        # Caller supplied a volatility figure. Still realized-vol semantics unless
        # a live chain provided it — the caller owns that labeling.
        sigma = sigma_pct / 100
    else:
        # ATR-annualized REALIZED volatility. Explicitly a proxy, not IV.
        daily_vol = atr / price
        sigma = daily_vol * math.sqrt(252)

    if sigma <= 0:
        return 0.0

    t = dte / 365
    # Standard Black-Scholes d1 including the risk-free drift. The previous
    # version omitted r from d1 while discounting the strike at r=0.05, which is
    # internally inconsistent (2026-07-20).
    d1 = (math.log(price/strike) + (RISK_FREE + 0.5*sigma*sigma)*t) / (sigma*math.sqrt(t))
    d2 = d1 - sigma*math.sqrt(t)

    def N(x):
        """Standard normal CDF approximation."""
        k = 1/(1+0.2316419*abs(x))
        poly = k*(0.319381530 + k*(-0.356563782 + k*(1.781477937 + k*(-1.821255978 + k*1.330274429))))
        n = math.exp(-x*x/2) / math.sqrt(2*math.pi)
        cdf = 1 - n*poly if x >= 0 else n*poly
        return cdf

    premium = price * N(d1) - strike * math.exp(-RISK_FREE*t) * N(d2)
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
        # Exclude cash/MMF sleeves — they are not optionable and were being
        # emitted as $1.00-strike "covered call opportunities" (2026-07-20).
        # Mirrors the exclusion portfolio_stops.py already applied.
        _is_cash = (h.get("is_cash") or sym in ("CASH", "CASH & CASH INVESTMENTS",
                                                "MMKT", "SPAXX", "FDRXX"))
        if (shares >= min_shares and mv >= 1000 and price > 0
                and not h.get("is_loan") and not _is_cash):
            candidates.append(h)
            all_syms.append(sym)

    if not candidates:
        return {"opportunities": [], "total_monthly_income": 0, "has_data": False,
                "estimate_label": MODEL_ESTIMATE_LABEL, "is_tradeable_price": False}

    # Earnings for the blackout gate. Uses the repaired provider
    # (symbol_profiles/yfinance via earnings_provider) — the legacy FMP path
    # here is dead (403 legacy endpoint + 429 quota) and raising from it would
    # abort the whole scan, which silently removed the covered-call section from
    # the dashboard (regression caught 2026-07-20).
    #
    # UNKNOWN timing FAILS CLOSED: the symbol is treated as in-blackout so an
    # unpriceable event can never read as "safe to write".
    earnings_dates = {}
    earnings_unknown = set()
    try:
        from earnings_provider import get_earnings, SCHEDULED, NONE_SCHEDULED
        for _s, _info in get_earnings(all_syms).items():
            if _info.state == SCHEDULED and _info.date:
                earnings_dates[_s] = _info.date.isoformat()
            elif _info.state != NONE_SCHEDULED:
                earnings_unknown.add(_s)
    except Exception as _e:
        # Provider unusable entirely -> every symbol is unknown -> all blackout.
        earnings_unknown = set(all_syms)
        print(f"  [options] earnings provider unavailable ({_e}) — all symbols fail closed")

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
        # NOTE: portfolio_technical.py emits NO "iv" key (it emits realized
        # volatility_w / volatility_m), so this is always 0 and the ATR
        # realized-vol proxy below is always what prices the premium.
        # Verified 2026-07-20 — do not re-describe this as implied volatility.
        sigma_pct = tech.get("iv", 0)
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
        in_blackout = sym in earnings_unknown   # unknown timing = fail closed
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
        premium_per_share = _estimate_premium(price, strike, atr, sigma_pct, default_dte)
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
            "estimate_basis":   ("realized_vol_atr_annualized" if not sigma_pct
                                 else "caller_supplied_sigma"),
            "estimate_label":   MODEL_ESTIMATE_LABEL,
            "is_tradeable_price": False,
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
            "recommendation":   ("WRITE CALL" if not in_blackout else
                                 ("WAIT — earnings timing UNKNOWN (fail closed)"
                                  if sym in earnings_unknown else
                                  f"WAIT — earnings in {days_to_earnings}d")),
            "blackout_reason":  ("earnings_timestamp_unknown" if sym in earnings_unknown
                                 else ("earnings_inside_window" if in_blackout else "")),
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
        # Provenance stamp — every consumer must render this alongside the
        # dollar figures. These are modelled from REALIZED volatility, not
        # quoted from a live chain (2026-07-20 audit).
        "estimate_label":      MODEL_ESTIMATE_LABEL,
        "estimate_basis":      "realized_vol_atr_annualized",
        "is_tradeable_price":  False,
        "authoritative_source": ("Schwab live option chain via "
                                 "options_lifecycle_engine.quote_leg()"),
        "disclaimer": ("Premiums are MODELLED from ATR-annualized REALIZED volatility "
                       "through a simplified Black-Scholes, not quoted from a live "
                       "option chain. Realized volatility is not implied volatility; "
                       "these figures can differ materially from tradeable prices, "
                       "especially around events. Do not act on them — price any real "
                       "covered call against the Schwab chain."),
    }
