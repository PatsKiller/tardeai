"""portfolio_dividend_calendar.py — Dividend Calendar & Income Optimization
Monthly income calendar, ex-div capture alerts, dividend safety scoring,
qualified vs ordinary classification, DRIP analysis.
"""
from __future__ import annotations
import json, os, requests, time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# Known dividend schedules for major holdings
# Updated via FMP/Finviz; fallback to these defaults
KNOWN_SCHEDULES = {
    "V":    {"frequency":"quarterly","yield_pct":0.83,"qualified":True,"safety":"strong"},
    "SCHD": {"frequency":"quarterly","yield_pct":3.58,"qualified":True,"safety":"strong"},
    "LMT":  {"frequency":"quarterly","yield_pct":2.68,"qualified":True,"safety":"strong"},
    "CSWC": {"frequency":"monthly","yield_pct":10.5,"qualified":False,"safety":"watch"},
    "PFLT": {"frequency":"monthly","yield_pct":11.2,"qualified":False,"safety":"watch"},
    "DIV":  {"frequency":"monthly","yield_pct":6.8,"qualified":False,"safety":"watch"},
    "BND":  {"frequency":"monthly","yield_pct":3.4,"qualified":False,"safety":"strong"},
    "SCHG": {"frequency":"quarterly","yield_pct":0.48,"qualified":True,"safety":"strong"},
    "NOC":  {"frequency":"quarterly","yield_pct":1.69,"qualified":True,"safety":"strong"},
    "RTX":  {"frequency":"quarterly","yield_pct":2.16,"qualified":True,"safety":"strong"},
    "NEE":  {"frequency":"quarterly","yield_pct":3.0,"qualified":True,"safety":"strong"},
    "SGOV": {"frequency":"monthly","yield_pct":5.1,"qualified":False,"safety":"strong"},
    "JEPI": {"frequency":"monthly","yield_pct":7.5,"qualified":False,"safety":"watch"},
    "JEPQ": {"frequency":"monthly","yield_pct":9.4,"qualified":False,"safety":"watch"},
    "PFF":  {"frequency":"monthly","yield_pct":6.2,"qualified":False,"safety":"watch"},
    "VCIT": {"frequency":"monthly","yield_pct":4.5,"qualified":False,"safety":"strong"},
    "AGG":  {"frequency":"monthly","yield_pct":3.8,"qualified":False,"safety":"strong"},
    "VXUS": {"frequency":"quarterly","yield_pct":3.2,"qualified":True,"safety":"strong"},
}

MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

def _env(k):
    return os.getenv(k,"").strip()

def _load_env(root: Path):
    ef = root/".env"
    if ef.exists():
        for line in ef.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k,v=line.split("=",1); os.environ.setdefault(k.strip(),v.strip().strip("\"'"))

def _fetch_fmp_dividends(symbols: List[str], root: Path) -> Dict[str,Dict]:
    """Fetch next ex-dividend date from FMP."""
    _load_env(root)
    key = _env("FMP_API_KEY")
    if not key: return {}
    result = {}
    for sym in symbols[:20]:  # Rate limit
        try:
            url = f"https://financialmodelingprep.com/api/v3/stock_dividend/{sym}"
            resp = requests.get(url, params={"apikey":key}, timeout=10)
            if not resp.ok: continue
            data = resp.json()
            if isinstance(data, list) and data:
                latest = data[0]
                result[sym] = {
                    "ex_date":     latest.get("date",""),
                    "pay_date":    latest.get("paymentDate",""),
                    "amount":      latest.get("dividend",0),
                    "adj_amount":  latest.get("adjDividend",0),
                }
            time.sleep(0.15)
        except Exception:
            pass
    return result

def _get_monthly_income_estimate(sym: str, shares: float, mv: float) -> float:
    """Estimate monthly dividend income."""
    sched = KNOWN_SCHEDULES.get(sym,{})
    if not sched: return 0.0
    annual = mv * sched.get("yield_pct",0) / 100
    freq = sched.get("frequency","quarterly")
    if freq == "monthly":    return round(annual/12, 2)
    if freq == "quarterly":  return round(annual/12, 2)  # amortize monthly
    if freq == "semi-annual":return round(annual/12, 2)
    if freq == "annual":     return round(annual/12, 2)
    return 0.0

def build_dividend_calendar(portfolio: Dict, root: Path, state_dir: Path) -> Dict:
    holdings = [h for h in portfolio.get("holdings",[])
                if (h.get("market_value") or 0) >= 500
                and (h.get("shares") or 0) > 0
                and not h.get("is_loan") and not h.get("is_cash")]

    # Identify dividend payers
    payers = []
    for h in holdings:
        sym    = h.get("symbol","").upper()
        shares = h.get("shares",0) or 0
        mv     = h.get("market_value",0) or 0
        price  = h.get("price",0) or 0
        sched  = KNOWN_SCHEDULES.get(sym,{})
        if not sched: continue

        annual_income = mv * sched.get("yield_pct",0) / 100
        monthly_amort = round(annual_income/12, 2)
        payers.append({
            "symbol":      sym,
            "shares":      shares,
            "price":       price,
            "market_value":mv,
            "yield_pct":   sched.get("yield_pct",0),
            "frequency":   sched.get("frequency","quarterly"),
            "annual_income":round(annual_income,2),
            "monthly_amort":monthly_amort,
            "qualified":   sched.get("qualified",True),
            "safety":      sched.get("safety","unknown"),
        })

    if not payers:
        return {"has_data":False,"note":"No dividend payers identified"}

    # Fetch live ex-div dates
    div_dates = _fetch_fmp_dividends([p["symbol"] for p in payers], root)

    # Build monthly income projection
    total_annual  = sum(p.get("annual_income",0) or 0 for p in payers)
    qualified_ann = sum(p["annual_income"] for p in payers if p["qualified"])
    ordinary_ann  = total_annual - qualified_ann
    monthly_total = round(total_annual/12, 2)

    # Monthly calendar — distribute quarterly payers across quarters
    monthly_calendar: Dict[int,List] = {m: [] for m in range(1,13)}
    today = datetime.now()
    for p in payers:
        sym  = p["symbol"]
        freq = p["frequency"]
        if freq == "monthly":
            # Hits every month
            for m in range(1,13):
                monthly_calendar[m].append({"symbol":sym,"income":round(p["annual_income"]/12,2)})
        elif freq == "quarterly":
            # Typical patterns: Mar/Jun/Sep/Dec or Jan/Apr/Jul/Oct or Feb/May/Aug/Nov
            q_month_map = {
                "V":["Jan","Apr","Jul","Oct"], "SCHD":["Mar","Jun","Sep","Dec"],
                "LMT":["Mar","Jun","Sep","Dec"],"NOC":["Mar","Jun","Sep","Dec"],
                "RTX":["Jan","Apr","Jul","Oct"],"NEE":["Mar","Jun","Sep","Dec"],
                "SCHG":["Mar","Jun","Sep","Dec"],"VXUS":["Mar","Jun","Sep","Dec"],
            }
            pay_months = q_month_map.get(sym,["Mar","Jun","Sep","Dec"])
            for m_name in pay_months:
                m_num = MONTHS.index(m_name[:3])+1
                monthly_calendar[m_num].append({"symbol":sym,"income":round(p["annual_income"]/4,2)})

    # Summarize each month
    monthly_summary = []
    for m in range(1,13):
        items = monthly_calendar[m]
        month_total = sum(i["income"] for i in items)
        syms = sorted(set(i["symbol"] for i in items))
        monthly_summary.append({
            "month":     m,
            "month_name":MONTHS[m-1],
            "total":     round(month_total,2),
            "symbols":   syms,
            "count":     len(syms),
        })

    # Ex-dividend alerts (within 14 days)
    ex_div_alerts = []
    for p in payers:
        dd = div_dates.get(p["symbol"],{})
        ex_date = dd.get("ex_date","")
        if ex_date:
            try:
                ex_dt = datetime.strptime(ex_date[:10],"%Y-%m-%d")
                days_until = (ex_dt - today).days
                if 0 <= days_until <= 21:
                    income = dd.get("amount",0) * p["shares"]
                    ex_div_alerts.append({
                        "symbol":     p["symbol"],
                        "ex_date":    ex_date[:10],
                        "days_until": days_until,
                        "amount":     dd.get("amount",0),
                        "total_income":round(income,2),
                        "pay_date":   dd.get("pay_date",""),
                        "urgent":     days_until <= 3,
                    })
            except Exception:
                pass
    ex_div_alerts.sort(key=lambda x: x["days_until"])

    # DRIP analysis for SCHD
    schd = next((p for p in payers if p["symbol"]=="SCHD"), None)
    drip_analysis = {}
    if schd:
        mv = schd["market_value"]
        yield_pct = schd["yield_pct"]/100
        growth_rate = 0.112  # SCHD 3-yr dividend growth ~11.2%
        current_annual = mv * yield_pct
        # Project 10 years with DRIP
        bal_drip = mv
        bal_cash = mv
        for yr in range(10):
            div_drip = bal_drip * yield_pct
            bal_drip = bal_drip * (1.07 + yield_pct)  # price appreciation + reinvested divs
            bal_cash = bal_cash * 1.07  # just price appreciation
        drip_analysis = {
            "symbol":        "SCHD",
            "current_income":round(current_annual,2),
            "10yr_drip_value":round(bal_drip,0),
            "10yr_cash_value":round(bal_cash,0),
            "drip_advantage":round(bal_drip-bal_cash,0),
            "recommendation":"DRIP if income not needed; take cash if funding Roth conversions",
        }

    # Dividend safety ratings
    safety_summary = {
        "strong":  [p["symbol"] for p in payers if p["safety"]=="strong"],
        "watch":   [p["symbol"] for p in payers if p["safety"]=="watch"],
        "at_risk": [p["symbol"] for p in payers if p["safety"]=="at_risk"],
    }

    result = {
        "has_data":          True,
        "payers":            sorted(payers, key=lambda x: -x["annual_income"]),
        "total_annual":      round(total_annual,2),
        "qualified_annual":  round(qualified_ann,2),
        "ordinary_annual":   round(ordinary_ann,2),
        "monthly_average":   monthly_total,
        "monthly_summary":   monthly_summary,
        "ex_div_alerts":     ex_div_alerts,
        "drip_analysis":     drip_analysis,
        "safety_summary":    safety_summary,
        "last_updated":      today.strftime("%Y-%m-%d %H:%M"),
    }

    (state_dir/"dividend_calendar.json").write_text(json.dumps(result,indent=2,default=str))
    return result
