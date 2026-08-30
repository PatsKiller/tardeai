"""portfolio_rebalancer.py — Trade AI v12 Portfolio Intelligence
Fixed: double-count bug, specific ticker recommendations, net amount calculation.
"""
from __future__ import annotations
from collections import defaultdict
from typing import Any, Dict, List, Optional

# Canonical bucket name map — maps normalized keys (lowercase, spaces) → display name
BUCKET_CANONICAL = {
    "us large blend":          "US Large Blend",
    "us large growth":         "US Large Growth",
    "us large value":          "US Large Value",
    "us small":                "US Small",
    "international":           "International",
    "us equity":               "US Equity",
    "bonds":                   "Bonds",
    "income/dividend":         "Income ETF/Dividend",   # legacy alias
    "income dividend":         "Income ETF/Dividend",
    "dividend income":         "Income ETF/Dividend",   # YAML: dividend_income
    "income etf/dividend":     "Income ETF/Dividend",
    "income etf":              "Income ETF/Dividend",
    "income etf dividend":     "Income ETF/Dividend",
    "international equity":    "International Equity",
    "defense":                 "Defense",
    "bdc income":              "BDC Income",
    "growth etf":              "Growth ETF",
    "cash":                    "Cash",
}

def _normalize_bucket(key: str) -> str:
    """Normalize YAML key variants to canonical bucket display name."""
    return BUCKET_CANONICAL.get(key.lower().replace("_", " "), key)


DEFAULT_TARGETS = {
    "401k": {"US Large Blend":40,"US Large Growth":15,"US Large Value":15,"US Small":15,"International":15},
    "rollover_ira": {"US Equity":50,"Bonds":20,"Income ETF/Dividend":15,"International":10,"Cash":5},
    "roth_ira": {"US Large Growth":75,"US Large Blend":20,"Cash":5},
    "taxable": {"Defense":30,"Income ETF/Dividend":25,"BDC Income":20,"Growth ETF":15,"Cash":10},
}

SYMBOL_BUCKET = {
    "V":"US Equity","PFE":"US Equity","FCNTX":"US Equity",
    "SCHD":"Income ETF/Dividend",          # ← was "Income/Dividend" — now consistent with DIV
    "BND":"Bonds","XLI":"US Equity","XLB":"US Equity","ARKG":"US Equity",
    "AMANX":"US Equity","SRNE":"US Equity","SCHG":"US Large Growth",
    "AVAV":"Defense","BAH":"Defense","CACI":"Defense","DRS":"Defense",
    "IRDM":"Defense","KBR":"Defense","KTOS":"Defense","LDOS":"Defense",
    "LHX":"Defense","LMT":"Defense","NOC":"Defense","RKLB":"Defense",
    "RTX":"Defense","TDG":"Defense","NEE":"Defense",
    "CSWC":"BDC Income","PFLT":"BDC Income",
    "DIV":"Income ETF/Dividend",
    "ARKQ":"Growth ETF",
    "FID-CONTRA-F":"US Large Blend","SP500-D":"US Large Blend",
    "VANG-FTSE-SOC":"US Large Blend","TRP-LVAL":"US Large Value",
    "JPM-LGCG":"US Large Growth","SS-SMMD":"US Small",
    "WM-BLAIR":"US Small","AB-DISC-Z":"US Small",
    "FID-DIVINTL":"International","SS-GACEQ":"International",
}

BUCKET_SUGGESTIONS = {
    "US Large Blend":["VTI","SCHB","SPY"],"US Large Growth":["SCHG","VUG","QQQ"],
    "US Large Value":["VTV","SCHV","IVE"],"US Small":["VB","SCHA","IJR"],
    "International":["VXUS","SCHF","EFA"],"US Equity":["VTI","SCHB","SPY"],
    "Bonds":["BND","AGG","SCHZ"],"Income/Dividend":["SCHD","VIG","DVY"],
    "Income ETF/Dividend":["SCHD","DIV","VIG"],"BDC Income":["CSWC","PFLT","MAIN"],
    "Growth ETF":["ARKQ","SCHG","VGT"],"Defense":["LMT","NOC","RTX"],
    "Cash":["SGOV","SHV","T-bills"],
}

def _bucket(sym, asset_type=""):
    if sym == "CASH": return "Cash"
    b = SYMBOL_BUCKET.get(sym.upper())
    if b: return b
    if "BOND" in asset_type.upper(): return "Bonds"
    return "US Equity"

def compute_drift(holdings, account_summaries, config):
    accounts_cfg = config.get("accounts", {})
    results = {}
    for acct_key, acct_cfg in accounts_cfg.items():
        acct_type = acct_cfg.get("type","unknown")
        target = acct_cfg.get("target_allocation") or DEFAULT_TARGETS.get(acct_type,{})
        # Normalize YAML keys to canonical bucket names
        target = {_normalize_bucket(k): v for k, v in target.items()}
        acct_total = account_summaries.get(acct_key,{}).get("total_value",0)
        if acct_total <= 0: continue
        acct_h = [h for h in holdings if h.get("account")==acct_key and not h.get("is_loan")]
        current = defaultdict(float)
        for h in acct_h:
            mv = h.get("market_value") or 0
            if mv > 0: current[_bucket(h.get("symbol",""), h.get("asset_type",""))] += mv
        drift_rows = []
        total_buys = total_sells = 0.0
        for bkt in sorted(set(list(target.keys())+list(current.keys()))):
            tgt_pct = target.get(bkt,0)
            cur_mv = current.get(bkt,0)
            cur_pct = cur_mv/acct_total*100 if acct_total else 0
            drift = cur_pct - tgt_pct
            tgt_mv = acct_total*tgt_pct/100
            reb_mv = tgt_mv - cur_mv
            action = "BUY" if reb_mv>100 else ("SELL" if reb_mv<-100 else "HOLD")
            if action=="BUY": total_buys += reb_mv
            if action=="SELL": total_sells += abs(reb_mv)
            holdings_in = [h.get("symbol") for h in acct_h
                           if _bucket(h.get("symbol",""),h.get("asset_type",""))==bkt
                           and (h.get("market_value") or 0)>0]
            drift_rows.append({
                "bucket":bkt,"target_pct":tgt_pct,"current_pct":round(cur_pct,1),
                "current_mv":round(cur_mv,2),"target_mv":round(tgt_mv,2),
                "drift_pct":round(drift,1),"rebalance_mv":round(reb_mv,2),
                "action":action,"needs_rebalance":abs(drift)>=5.0,
                "suggestions":BUCKET_SUGGESTIONS.get(bkt,[])[:3],
                "holdings_in_bucket":holdings_in,
            })
        is_tax_adv = acct_type in ("401k","rollover_ira","roth_ira","traditional_ira")
        net = min(total_buys,total_sells) if is_tax_adv else total_buys
        results[acct_key] = {
            "account_display":acct_cfg.get("display_name",acct_key),
            "account_type":acct_type,"total_value":acct_total,
            "drift_rows":drift_rows,"needs_rebalance":any(r["needs_rebalance"] for r in drift_rows),
            "max_drift":max((abs(r["drift_pct"]) for r in drift_rows),default=0),
            "net_to_move":round(net,2),"total_buys":round(total_buys,2),"total_sells":round(total_sells,2),
        }
    return results

def generate_rebalance_orders(drift_analysis):
    orders = []
    for acct_key, analysis in drift_analysis.items():
        if not analysis.get("needs_rebalance"): continue
        acct = analysis.get("account_display","")
        is_401k = analysis.get("account_type")=="401k"
        for row in analysis.get("drift_rows",[]):
            if not row.get("needs_rebalance"): continue
            action = row.get("action")
            mv = abs(row.get("rebalance_mv") or 0)
            if mv < 100 or action=="HOLD": continue
            suggestions = row.get("suggestions",[])
            current_tickers = row.get("holdings_in_bucket",[])
            if action=="BUY":
                ticker_note = f"Consider: {', '.join(suggestions[:2])}" if suggestions else "Add to existing"
            else:
                ticker_note = f"Trim: {', '.join(current_tickers[:3])}" if current_tickers else ("Exchange fund" if is_401k else "Reduce")
            orders.append({
                "account":acct,"account_type":analysis.get("account_type"),"bucket":row.get("bucket"),
                "action":action,"amount_usd":round(mv,2),"current_pct":row.get("current_pct"),
                "target_pct":row.get("target_pct"),"drift_pct":row.get("drift_pct"),
                "priority":"HIGH" if abs(row.get("drift_pct") or 0)>=10 else "MEDIUM",
                "ticker_suggestion":ticker_note,"current_tickers":current_tickers,
                "suggested_tickers":suggestions,
                "note":f"Drift {row.get('drift_pct'):+.1f}% vs {row.get('target_pct')}% target",
            })
    orders.sort(key=lambda x:(-abs(x.get("drift_pct") or 0),))
    return orders


# ── Share-count enrichment ────────────────────────────────────────────────────

# Fallback yields (%) for suggested-buy tickers not in the portfolio.
# Held tickers are loaded from dividend_calendar.json at runtime.
_SUGGESTED_BUY_YIELDS: Dict[str, float] = {
    "AGG": 3.5, "JEPQ": 9.5, "O": 5.7, "PFE": 6.2,
    "PFF": 6.2, "VCIT": 4.8, "VXUS": 3.1,
}

_yield_cache: Optional[Dict[str, float]] = None


def _load_yields() -> Dict[str, float]:
    """Load live dividend yields from dividend_calendar.json, with static fallback for suggested buys."""
    global _yield_cache
    if _yield_cache is not None:
        return _yield_cache
    import json
    from pathlib import Path
    yields: Dict[str, float] = dict(_SUGGESTED_BUY_YIELDS)
    try:
        dc_path = Path(__file__).resolve().parent.parent / "data" / "portfolios" / "state" / "dividend_calendar.json"
        if dc_path.exists():
            dc = json.loads(dc_path.read_text())
            for p in dc.get("payers", []):
                sym = (p.get("symbol") or "").upper()
                yld = p.get("yield_pct")
                if sym and yld is not None:
                    yields[sym] = float(yld)
    except Exception:
        pass
    _yield_cache = yields
    return yields


def _div_income(ticker: str, market_value: float) -> float:
    """Annual dividend income from a position."""
    return market_value * _load_yields().get(ticker.upper(), 0) / 100


SUGGESTED_PRICES = {
    "VTI":26.5,"SCHB":25.8,"SPY":549.0,"SCHG":29.3,"VUG":285.0,"QQQ":468.0,
    "VTV":145.0,"SCHV":67.0,"IVE":85.0,"VB":195.0,"SCHA":48.0,"IJR":105.0,
    "VXUS":58.0,"SCHF":35.0,"EFA":75.0,"BND":73.5,"AGG":98.0,"SCHZ":47.0,
    "SCHD":30.5,"VIG":175.0,"DVY":120.0,"DIV":19.0,"CSWC":22.3,"PFLT":8.2,
    "MAIN":45.0,"ARKQ":114.0,"VGT":575.0,"LMT":622.0,"NOC":704.0,"RTX":195.0,
    "SGOV":100.1,"SHV":110.5,
    # Bond ETF recommendations
    "VCIT":85.0,"VCSH":78.0,"TLT":90.0,"VGIT":60.0,"BNDX":52.0,
}


def enrich_orders_with_shares(orders: List[Dict], holdings: List[Dict]) -> List[Dict]:
    """
    Add share-count details to each rebalancing order.
    For SELL: uses account-specific holdings (avoids cross-account symbol confusion).
    For BUY:  shows ONE primary trade + ONE alternative (not both as separate orders).
    """
    # Build account-specific price maps  {account_key: {symbol: {price, shares, mv}}}
    acct_price_map: Dict[str, Dict] = {}
    # Also a global fallback for prices only (no shares)
    global_price: Dict[str, float] = {}
    for h in holdings:
        sym   = h.get("symbol","").upper()
        acct  = h.get("account","")
        price = h.get("price") or 0
        shares= h.get("shares") or 0
        mv    = h.get("market_value") or 0
        if price > 0:
            acct_price_map.setdefault(acct, {})[sym] = {
                "price": price, "shares": shares, "mv": mv}
            global_price[sym] = price

    # Reverse-map display name → account key
    display_to_key: Dict[str, str] = {}
    for h in holdings:
        display_to_key[h.get("account_display","")] = h.get("account","")

    for order in orders:
        mv_needed = order.get("amount_usd", 0)
        action    = order.get("action")
        acct_disp = order.get("account","")
        acct_key  = display_to_key.get(acct_disp, "")
        acct_map  = acct_price_map.get(acct_key, {})
        current_tickers   = order.get("current_tickers", [])
        suggested_tickers = order.get("suggested_tickers", [])

        if action == "SELL" and current_tickers:
            sell_details = []
            # Use only THIS account's holdings for share counts
            total_mv_in_acct = sum(
                acct_map.get(t, {}).get("mv", 0) for t in current_tickers)
            remaining = mv_needed
            for ticker in current_tickers:
                info = acct_map.get(ticker, {})
                if not info or info.get("price", 0) <= 0:
                    continue
                ticker_mv = info.get("mv", 0)
                weight = ticker_mv / total_mv_in_acct if total_mv_in_acct > 0 \
                         else 1 / len(current_tickers)
                sell_mv     = min(remaining, mv_needed * weight)
                sell_shares = sell_mv / info["price"]
                max_shares  = info.get("shares", 0)
                sell_shares = min(sell_shares, max_shares)
                if sell_shares > 0.001:
                    sell_mv_actual = sell_shares * info["price"]
                    annual_div_lost = _div_income(ticker, sell_mv_actual)
                    sell_details.append({
                        "ticker":           ticker,
                        "shares_to_sell":   round(sell_shares, 2),
                        "price":            info["price"],
                        "proceeds":         round(sell_mv_actual, 2),
                        "annual_div_lost":  round(annual_div_lost, 2),
                        "monthly_div_lost": round(annual_div_lost / 12, 2),
                        "yield_pct":        _load_yields().get(ticker.upper(), 0),
                    })
                    remaining -= sell_mv_actual
            order["sell_details"] = sell_details

        elif action == "BUY" and suggested_tickers:
            # PRIMARY: first ticker at full amount
            # ALTERNATIVE: second ticker shown as "OR" option only
            buy_details = []
            for i, ticker in enumerate(suggested_tickers[:2]):
                price = acct_map.get(ticker, {}).get("price") \
                        or global_price.get(ticker) \
                        or SUGGESTED_PRICES.get(ticker)
                if not price or price <= 0:
                    continue
                shares_to_buy = mv_needed / price
                annual_div_gained = _div_income(ticker, mv_needed)
                buy_details.append({
                    "ticker":            ticker,
                    "shares_to_buy":     round(shares_to_buy, 2),
                    "price":             round(price, 2),
                    "cost":              round(mv_needed, 2),
                    "is_primary":        i == 0,
                    "is_alternative":    i > 0,
                    "annual_div_gained": round(annual_div_gained, 2),
                    "monthly_div_gained":round(annual_div_gained / 12, 2),
                    "yield_pct":         _load_yields().get(ticker.upper(), 0),
                })
            order["buy_details"] = buy_details

    return orders



# ── Bond recommendations ──────────────────────────────────────────────────────

BOND_RECOMMENDATIONS = [
    {
        "ticker": "BND",
        "name": "Vanguard Total Bond Market ETF",
        "yield_pct": 3.4,
        "duration_yrs": 6.2,
        "expense_ratio": 0.03,
        "price": 73.5,
        "credit_quality": "AAA/AA (74% govt/agency)",
        "best_for": "Core bond holding — diversified, very low cost",
        "risk": "LOW",
    },
    {
        "ticker": "AGG",
        "name": "iShares US Aggregate Bond ETF",
        "yield_pct": 3.5,
        "duration_yrs": 6.1,
        "expense_ratio": 0.03,
        "price": 98.0,
        "credit_quality": "AAA/AA (68% govt/agency)",
        "best_for": "BND alternative — similar composition",
        "risk": "LOW",
    },
    {
        "ticker": "VCIT",
        "name": "Vanguard Intermediate Corporate Bond",
        "yield_pct": 4.8,
        "duration_yrs": 6.4,
        "expense_ratio": 0.04,
        "price": 85.0,
        "credit_quality": "BBB/A (investment grade corporate)",
        "best_for": "Higher yield — good for IRA where tax drag isn't a concern",
        "risk": "LOW-MEDIUM",
    },
    {
        "ticker": "VGIT",
        "name": "Vanguard Intermediate-Term Treasury",
        "yield_pct": 4.1,
        "duration_yrs": 5.4,
        "expense_ratio": 0.04,
        "price": 60.0,
        "credit_quality": "AAA (US Government only)",
        "best_for": "Safest option — zero credit risk, good in volatile markets",
        "risk": "LOW",
    },
    {
        "ticker": "SGOV",
        "name": "iShares 0-3 Month Treasury Bill ETF",
        "yield_pct": 5.2,
        "duration_yrs": 0.1,
        "expense_ratio": 0.09,
        "price": 100.1,
        "credit_quality": "AAA (T-Bills)",
        "best_for": "Cash equivalent — highest yield, zero duration risk",
        "risk": "VERY LOW",
    },
]

BOND_RECOMMENDATION_NOTE = (
    "For Rollover IRA (tax-deferred): skip municipal bonds (tax-exempt feature wasted in IRA). "
    "Best core bond: BND or VCIT for higher yield. "
    "Suggested split: 60% VCIT ($68K) + 40% BND ($45K) = blended yield ~4.2%, "
    "generating ~$4,726/yr income inside tax-deferred account."
)


# ── V → SCHD Scenario Analysis ────────────────────────────────────────────────

def analyze_v_to_schd_scenario(holdings: List[Dict], scenario_sell_pct: float = 30.0) -> Dict:
    """
    Analyze the impact of selling X% of V position and reinvesting into SCHD.
    Shows dividend yield change, income change, and concentration reduction.

    Args:
        scenario_sell_pct: % of total V position to sell (default 30%)
    """
    # Current V data
    v_holdings = [h for h in holdings if h.get("symbol","").upper() == "V"]
    total_v_shares = sum(h.get("shares") or 0 for h in v_holdings)
    total_v_mv = sum(h.get("market_value") or 0 for h in v_holdings)
    v_price = v_holdings[0].get("price", 301.0) if v_holdings else 301.0
    v_yield = 0.83  # V forward dividend yield %

    # SCHD data
    schd_holdings = [h for h in holdings if h.get("symbol","").upper() == "SCHD"]
    schd_price = schd_holdings[0].get("price", 30.45) if schd_holdings else 30.45
    schd_yield = 3.58  # SCHD forward dividend yield %
    total_schd_mv = sum(h.get("market_value") or 0 for h in schd_holdings)

    # Total portfolio value
    total_portfolio = sum(h.get("market_value") or 0 for h in holdings
                         if not h.get("is_loan") and (h.get("market_value") or 0) > 0)

    results = []
    for pct in [10, 20, 30, 50]:
        sell_mv = total_v_mv * pct / 100
        sell_shares = sell_mv / v_price
        proceeds = sell_mv

        # New SCHD shares purchased
        new_schd_shares = proceeds / schd_price
        new_schd_mv = proceeds

        # Dividend impact
        lost_v_div = sell_mv * v_yield / 100
        gained_schd_div = new_schd_mv * schd_yield / 100
        net_div_change = gained_schd_div - lost_v_div

        # Concentration impact
        remaining_v_mv = total_v_mv - sell_mv
        new_v_pct = remaining_v_mv / total_portfolio * 100
        new_schd_total_mv = total_schd_mv + new_schd_mv
        new_schd_pct = new_schd_total_mv / total_portfolio * 100

        results.append({
            "scenario_pct": pct,
            "sell_v_shares": round(sell_shares, 1),
            "sell_v_mv": round(sell_mv, 0),
            "buy_schd_shares": round(new_schd_shares, 0),
            "lost_v_annual_div": round(lost_v_div, 0),
            "gained_schd_annual_div": round(gained_schd_div, 0),
            "net_div_change": round(net_div_change, 0),
            "net_div_change_monthly": round(net_div_change / 12, 0),
            "remaining_v_pct": round(new_v_pct, 1),
            "new_schd_pct": round(new_schd_pct, 1),
            "concentration_reduced_by": round((total_v_mv / total_portfolio * 100) - new_v_pct, 1),
        })

    current_v_pct = total_v_mv / total_portfolio * 100 if total_portfolio > 0 else 0
    current_v_annual_div = total_v_mv * v_yield / 100
    current_schd_annual_div = total_schd_mv * schd_yield / 100

    return {
        "current_v_shares": round(total_v_shares, 1),
        "current_v_mv": round(total_v_mv, 0),
        "current_v_pct_portfolio": round(current_v_pct, 1),
        "current_v_annual_div": round(current_v_annual_div, 0),
        "current_schd_annual_div": round(current_schd_annual_div, 0),
        "v_yield_pct": v_yield,
        "schd_yield_pct": schd_yield,
        "v_price": v_price,
        "schd_price": schd_price,
        "scenarios": results,
        "recommendation": _v_schd_recommendation(results, current_v_pct),
        "tax_note": "V is held in Rollover IRA (tax-deferred) and Roth IRA (tax-free). "
                    "Selling in IRA = NO capital gains tax. Ideal account for this rebalance.",
    }


def _v_schd_recommendation(scenarios: List[Dict], current_v_pct: float) -> str:
    if current_v_pct > 25:
        s30 = next(s for s in scenarios if s["scenario_pct"] == 30)
        return (f"RECOMMENDED: Sell 30% of V ({s30['sell_v_shares']:.0f} shares, "
                f"${s30['sell_v_mv']:,.0f}) inside Rollover IRA. "
                f"Buy {s30['buy_schd_shares']:.0f} shares of SCHD. "
                f"Result: +${s30['net_div_change']:,.0f}/yr more dividends "
                f"(${s30['net_div_change_monthly']:,.0f}/mo), "
                f"V concentration drops from {current_v_pct:.1f}% → {s30['remaining_v_pct']:.1f}%. "
                f"Zero tax consequence (IRA).")
    return "V concentration is within acceptable range."


def compute_rebalancing(portfolio):
    holdings = portfolio.get("holdings",[])
    account_summaries = portfolio.get("account_summaries",{})
    config = portfolio.get("config",{})
    print("  [rebalancer] Computing drift analysis...")
    drift = compute_drift(holdings, account_summaries, config)
    print("  [rebalancer] Generating rebalance orders...")
    orders = generate_rebalance_orders(drift)
    try:
        try:
            from scripts.lib.cio_rebalancer_readonly import (
                append_avoid_refusal_receipt,
                drop_orders_against_avoid,
                load_cio_product_readonly,
            )
        except ImportError:
            from lib.cio_rebalancer_readonly import (  # type: ignore
                append_avoid_refusal_receipt,
                drop_orders_against_avoid,
                load_cio_product_readonly,
            )
        cio = load_cio_product_readonly()
        # G-AUTH-01: drop AVOID contradictions from actionable list by default.
        # READ_ONLY_ADVISORY / MBI=0 / no broker write / no notify-on.
        orders, dropped = drop_orders_against_avoid(orders, cio, drop_contradictions=True)
        n_kept, n_dropped = len(orders), len(dropped)
        print(
            f"  [rebalancer] CIO AVOID: kept={n_kept} dropped={n_dropped} "
            "(read-only, job continues for remaining; never broker-write)"
        )
        if dropped:
            receipt_path = append_avoid_refusal_receipt(dropped)
            if receipt_path is not None:
                print(f"  [rebalancer] CIO AVOID refusal receipt: {receipt_path}")
    except Exception as exc:
        print(f"  [rebalancer] CIO product read failed ({type(exc).__name__}); continuing")
    print("  [rebalancer] Computing share counts...")
    orders = enrich_orders_with_shares(orders, holdings)
    print("  [rebalancer] V→SCHD scenario analysis...")
    v_scenario = analyze_v_to_schd_scenario(holdings)
    needs = any(a.get("needs_rebalance") for a in drift.values())
    total_net = sum(a.get("net_to_move",0) for a in drift.values())
    return {
        "drift_analysis": drift,
        "rebalance_orders": orders,
        "needs_rebalance": needs,
        "total_to_rebalance": round(total_net,2),
        "order_count": len(orders),
        "bond_recommendations": BOND_RECOMMENDATIONS,
        "bond_note": BOND_RECOMMENDATION_NOTE,
        "v_to_schd_scenario": v_scenario,
    }

