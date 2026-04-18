"""portfolio_correlation.py — Correlation & Factor Exposure Analysis
Correlation matrix, effective concentration, geographic exposure,
interest rate sensitivity, sector clustering.
"""
from __future__ import annotations
import json, math, time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import requests

# Sector/factor classifications
SECTOR_MAP = {
    "V":"Financials","SCHD":"Income","LMT":"Defense","NOC":"Defense",
    "RTX":"Defense","AVAV":"Defense","KTOS":"Defense","RKLB":"Growth/Space",
    "BAH":"Defense/IT","LDOS":"Defense/IT","CACI":"Defense/IT","LHX":"Defense",
    "SCHG":"US Growth","FCNTX":"US Growth","VTI":"Broad US","SCHB":"Broad US",
    "CSWC":"Income/BDC","PFLT":"Income/BDC","DIV":"Income","BND":"Bonds",
    "AGG":"Bonds","VCIT":"Bonds","SGOV":"T-Bills","SHV":"T-Bills",
    "VXUS":"International","NEE":"Utilities","ARKQ":"Growth/Tech",
    "JEPI":"Income/Options","JEPQ":"Income/Options","PFF":"Preferred",
    "IRDM":"Growth/Space","ARKG":"Growth/Biotech",
}
RATE_SENSITIVITY = {
    # -1=rate-sensitive (hurts when rates rise), 0=neutral, +1=benefits
    "BND":-2,"AGG":-2,"VCIT":-2,"PFF":-1,"CSWC":-1,"PFLT":-1,
    "DIV":-1,"NEE":-1,"JEPI":-1,"JEPQ":-1,"SGOV":+2,"SHV":+2,
    "V":0,"SCHG":-1,"FCNTX":-1,"SCHD":0,"LMT":0,"NOC":0,
}
GEO_MAP = {
    "V":"US","SCHD":"US","LMT":"US","NOC":"US","RTX":"US",
    "VXUS":"International","SCHG":"US","FCNTX":"US","BND":"US",
    "SCHB":"US","AGG":"US","SGOV":"US","CSWC":"US","PFLT":"US",
    "ARKQ":"US","NEE":"US","KTOS":"US","RKLB":"US","AVAV":"US",
}

def _yahoo_prices_short(sym: str, days: int=180) -> List[float]:
    try:
        end  = int(datetime.now().timestamp())
        start= int((datetime.now()-timedelta(days=days)).timestamp())
        url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
        resp = requests.get(url, headers={"User-Agent":"Mozilla/5.0"},
                            params={"interval":"1d","period1":start,"period2":end},
                            timeout=10)
        if not resp.ok: return []
        data = resp.json()
        r = data.get("chart",{}).get("result")
        if not r: return []
        closes = r[0].get("indicators",{}).get("quote",[{}])[0].get("close",[])
        return [c for c in closes if c is not None]
    except Exception:
        return []

def _returns(prices: List[float]) -> List[float]:
    if len(prices)<2: return []
    return [(prices[i]/prices[i-1])-1 for i in range(1,len(prices))]

def _pearson_corr(a: List[float], b: List[float]) -> Optional[float]:
    n = min(len(a),len(b))
    if n < 20: return None
    a,b = a[:n],b[:n]
    ma = sum(a)/n; mb = sum(b)/n
    num = sum((a[i]-ma)*(b[i]-mb) for i in range(n))
    da  = math.sqrt(sum((x-ma)**2 for x in a))
    db  = math.sqrt(sum((x-mb)**2 for x in b))
    if da==0 or db==0: return None
    return round(num/(da*db),3)

def compute_correlation(portfolio: Dict, state_dir: Path) -> Dict:
    """Build correlation matrix and factor exposure analysis."""
    holdings = [h for h in portfolio.get("holdings",[])
                if h.get("market_value",0) >= 2000 and not h.get("is_loan")
                and not h.get("is_cash") and not (h.get("symbol","")).startswith("FID-")]

    total_mv = sum(h.get("market_value",0) for h in holdings)
    if not total_mv: return {"has_data":False}

    # Sector clustering
    sector_exposure: Dict[str,float] = {}
    for h in holdings:
        sym = h.get("symbol","").upper()
        sec = SECTOR_MAP.get(sym,"Other")
        mv  = h.get("market_value",0)
        sector_exposure[sec] = round(sector_exposure.get(sec,0)+mv, 2)
    sector_pct = {k:round(v/total_mv*100,1) for k,v in
                  sorted(sector_exposure.items(), key=lambda x:-x[1])}

    # Geographic exposure
    geo: Dict[str,float] = {}
    for h in holdings:
        sym = h.get("symbol","").upper()
        g   = GEO_MAP.get(sym,"US")
        mv  = h.get("market_value",0)
        geo[g] = geo.get(g,0) + mv
    geo_pct = {k:round(v/total_mv*100,1) for k,v in
               sorted(geo.items(),key=lambda x:-x[1])}

    # Interest rate sensitivity score (weighted)
    rate_score = 0.0
    for h in holdings:
        sym = h.get("symbol","").upper()
        wt  = h.get("market_value",0)/total_mv
        rate_score += wt * RATE_SENSITIVITY.get(sym,0)
    rate_score = round(rate_score, 2)

    # Defense cluster concentration
    defense_mv = sum(sector_exposure.get(s,0)
                     for s in ["Defense","Defense/IT"] if s in sector_exposure)
    defense_pct = round(defense_mv/total_mv*100,1)

    # Correlation matrix — top 20 by MV across all 4 accounts
    SKIP = {"CASH","--","SNSXX","SWVXX","SPRXX","VMFXX","FDRXX"}
    all_eligible = [h for h in holdings if h.get("symbol","").upper() not in SKIP]
    top20 = sorted(all_eligible, key=lambda x:-x.get("market_value",0))[:20]
    syms_for_corr = list(dict.fromkeys([h.get("symbol","").upper() for h in top20]))

    print(f"  [correlation] Fetching prices for {len(syms_for_corr)} symbols...")
    prices: Dict[str,List[float]] = {}
    for sym in syms_for_corr:
        prices[sym] = _yahoo_prices_short(sym, 180)
        time.sleep(0.15)

    rets: Dict[str,List[float]] = {s:_returns(p) for s,p in prices.items() if len(p)>=20}

    # Build matrix
    matrix = {}
    for s1 in rets:
        matrix[s1] = {}
        for s2 in rets:
            if s1==s2: matrix[s1][s2] = 1.0
            else: matrix[s1][s2] = _pearson_corr(rets[s1], rets[s2])

    # Find high correlations (risk clusters)
    clusters = []
    checked = set()
    for s1 in matrix:
        for s2 in matrix.get(s1,{}):
            if s1!=s2 and (s2,s1) not in checked:
                checked.add((s1,s2))
                c = matrix[s1].get(s2)
                if c and abs(c) >= 0.70:
                    clusters.append({"s1":s1,"s2":s2,"corr":c,
                                     "type":"High" if abs(c)>=0.85 else "Moderate"})
    clusters.sort(key=lambda x:-abs(x.get("corr",0)))

    # Effective concentration — "you think you're X% in V but effectively Y% in Financials"
    # V + FCNTX financial exposure
    v_mv = sum(h.get("market_value",0) for h in holdings if h.get("symbol","").upper()=="V")
    v_pct = round(v_mv/total_mv*100,1)
    fin_pct = sector_pct.get("Financials",0)

    result = {
        "has_data":          True,
        "sector_exposure":   sector_pct,
        "geographic":        geo_pct,
        "rate_sensitivity":  rate_score,
        "rate_interpretation":(
            "Rate-sensitive: rising rates would hurt portfolio"
            if rate_score < -0.3 else
            "Rate-neutral" if -0.3 <= rate_score <= 0.3 else
            "Rate-beneficiary: rising rates help this portfolio"
        ),
        "defense_cluster_pct": defense_pct,
        "v_concentration_pct": v_pct,
        "correlation_matrix":  matrix,
        "high_correlations":   clusters[:10],
        "symbols_analyzed":    list(rets.keys()),
        "total_value":         round(total_mv,0),
        "last_updated":        datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    (state_dir/"correlation.json").write_text(json.dumps(result,indent=2,default=str))
    return result
