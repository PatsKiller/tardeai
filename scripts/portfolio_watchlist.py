"""portfolio_watchlist.py — Watchlist Intelligence & Buy Pipeline
Buy candidate pipeline, position sizing opportunities, watchlist tracker.
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

# Curated watchlist aligned to John's thesis
DEFAULT_WATCHLIST = {
    # AI WWIII defense thesis
    "PLTR": {"thesis":"AI/defense data analytics — direct AI WWIII exposure","target_intent":"growth_speculative"},
    "HII":  {"thesis":"Huntington Ingalls — only US nuclear carrier/submarine builder","target_intent":"long_term_hold"},
    "GD":   {"thesis":"General Dynamics — Stryker, submarines, Gulfstream","target_intent":"long_term_hold"},
    "BWXT": {"thesis":"Nuclear propulsion systems — navy reactors","target_intent":"growth_speculative"},
    "AXON": {"thesis":"AI-enabled law enforcement tech — defense adjacent","target_intent":"growth_speculative"},
    # Income/BDC candidates
    "MAIN": {"thesis":"Main Street Capital — BDC with monthly dividend, internally managed","target_intent":"income"},
    "ARCC": {"thesis":"Ares Capital — largest BDC, well-diversified","target_intent":"income"},
    "HTGC": {"thesis":"Hercules Capital — tech-focused BDC","target_intent":"income"},
    # Roth growth candidates
    "MSFT": {"thesis":"Azure AI infrastructure — Copilot monetization","target_intent":"long_term_hold"},
    "NVDA": {"thesis":"GPU dominance for AI training","target_intent":"growth_speculative"},
    "VCIT": {"thesis":"Intermediate corporate bonds — reduce equity concentration","target_intent":"etf_broad"},
    "JEPI": {"thesis":"JPM equity premium income — covered call ETF, 7%+ yield","target_intent":"income"},
}

def load_watchlist(state_dir: Path) -> Dict:
    p = state_dir/"watchlist.json"
    if p.exists():
        try: return json.loads(p.read_text())
        except: pass
    # Initialize with defaults
    wl = {sym:{"thesis":d["thesis"],"target_intent":d["target_intent"],
               "added":datetime.now().strftime("%Y-%m-%d"),"notes":"","watching_since":""}
          for sym,d in DEFAULT_WATCHLIST.items()}
    (state_dir/"watchlist.json").write_text(json.dumps(wl,indent=2))
    return wl

def save_watchlist(state_dir: Path, wl: Dict) -> None:
    (state_dir/"watchlist.json").write_text(json.dumps(wl,indent=2))

def build_watchlist_intelligence(portfolio: Dict, technical_data: Dict,
                                  state_dir: Path) -> Dict:
    """Build watchlist with sizing opportunities and technical setup."""
    wl = load_watchlist(state_dir)

    # Identify sizing opportunities in current holdings
    holdings = {h.get("symbol","").upper(): h
                for h in portfolio.get("holdings",[])
                if h.get("market_value",0) > 500}
    total_mv = (portfolio.get("portfolio_totals",{}) or {}).get("total_value",1)

    # Underweight analysis vs intent targets
    from portfolio_technical import load_intent
    root = state_dir.parent.parent.parent  # Navigate to root
    intent_map = {}
    try:
        intent_map = load_intent(root)
    except Exception:
        pass

    # Target allocations by intent
    sizing_opps = []
    defense_syms = [sym for sym,intent in intent_map.items() if intent in ("long_term_hold","growth_speculative")]
    defense_mv   = sum(holdings.get(s,{}).get("market_value",0) for s in defense_syms)
    defense_pct  = round(defense_mv/total_mv*100,1) if total_mv else 0

    # Key underweight flags
    if defense_pct < 20:
        sizing_opps.append({
            "type":    "Underweight",
            "message": f"Defense sector at {defense_pct:.1f}% of portfolio vs 20-30% thesis target",
            "action":  "Consider adding LMT, NOC, or watchlist names on weakness",
        })

    # V overweight flag
    v_mv  = holdings.get("V",{}).get("market_value",0)
    v_pct = round(v_mv/total_mv*100,1) if total_mv else 0
    if v_pct > 20:
        sizing_opps.append({
            "type":    "Overweight — Action Required",
            "message": f"V is {v_pct:.1f}% of portfolio (target: ≤15% after rebalancing)",
            "action":  "Execute rebalancing sells in Rollover IRA (tax-free). Write covered calls on remainder.",
        })

    # International exposure gap
    int_syms = ["VXUS"]
    int_mv   = sum(holdings.get(s,{}).get("market_value",0) for s in int_syms)
    int_pct  = round(int_mv/total_mv*100,1) if total_mv else 0
    if int_pct < 5:
        sizing_opps.append({
            "type":    "Underweight",
            "message": f"International exposure at {int_pct:.1f}% (VXUS only). Target 10-15% for diversification.",
            "action":  "Add to VXUS position or consider VEA/VXUS in Roth IRA",
        })

    # Build watchlist entries with technical data
    enriched = []
    for sym, data in wl.items():
        tech = technical_data.get(sym,{}) if technical_data else {}
        curr_holding = holdings.get(sym)
        enriched.append({
            "symbol":       sym,
            "thesis":       data.get("thesis",""),
            "target_intent":data.get("target_intent",""),
            "notes":        data.get("notes",""),
            "added":        data.get("added",""),
            "currently_hold":curr_holding is not None,
            "current_shares":curr_holding.get("shares",0) if curr_holding else 0,
            "current_mv":   curr_holding.get("market_value",0) if curr_holding else 0,
            # Technical context
            "tech_score":   tech.get("tech_score"),
            "rsi":          tech.get("rsi"),
            "above_sma200": tech.get("above_sma200"),
            "pct_from_high":tech.get("pct_from_high"),
            "suggested_stop":tech.get("suggested_stop"),
        })

    enriched.sort(key=lambda x:(x["currently_hold"], -(x.get("tech_score") or 0)))

    result = {
        "has_data":          True,
        "watchlist":         enriched,
        "sizing_opportunities": sizing_opps,
        "v_concentration_pct": v_pct,
        "defense_pct":       defense_pct,
        "total_watchlist":   len(wl),
        "last_updated":      datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    (state_dir/"watchlist_intelligence.json").write_text(json.dumps(result,indent=2,default=str))
    return result
