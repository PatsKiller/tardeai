"""portfolio_stress.py — Portfolio Stress Testing & Scenario Analysis"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

# Scenario definitions with historical sector-level shocks
SCENARIOS = {
    "2022_rate_shock": {
        "name": "2022 Rate Shock",
        "description": "Fed raises 525bps in 12 months. Growth/tech crushed, bonds -13%, financials -20%.",
        "date": "2022",
        "shocks": {
            "Technology": -0.32, "Financials": -0.20, "Real Estate": -0.28,
            "Consumer Disc.": -0.37, "Communication": -0.40, "Healthcare": -0.05,
            "Energy": +0.59, "Industrials": -0.06, "Materials": -0.14,
            "Utilities": -0.01, "Consumer Stapl.": -0.03, "Bonds": -0.13,
            "Default": -0.18,
        },
    },
    "2020_covid": {
        "name": "2020 COVID Crash",
        "description": "33-day crash March 2020, S&P -34%. V-shaped recovery but initial shock severe.",
        "date": "Feb-Mar 2020",
        "shocks": {
            "Technology": -0.20, "Financials": -0.35, "Real Estate": -0.30,
            "Consumer Disc.": -0.35, "Communication": -0.22, "Healthcare": -0.12,
            "Energy": -0.55, "Industrials": -0.38, "Materials": -0.30,
            "Utilities": -0.14, "Consumer Stapl.": -0.10, "Bonds": +0.05,
            "Default": -0.34,
        },
    },
    "visa_doj": {
        "name": "Visa DOJ Adverse Ruling",
        "description": "DOJ prevails in debit routing antitrust case. V drops 25-35%, sector unaffected.",
        "date": "Hypothetical 2026",
        "shocks": {
            "V": -0.30,
            "Default": 0.0,
        },
    },
    "defense_reversal": {
        "name": "Defense Sector Reversal",
        "description": "AI WWIII thesis reverses — peace deal or budget cuts. Defense down 15%, broad market flat.",
        "date": "Hypothetical",
        "shocks": {
            "LMT": -0.15, "NOC": -0.15, "RTX": -0.15, "AVAV": -0.22,
            "KTOS": -0.25, "RKLB": -0.20, "BAH": -0.12, "LDOS": -0.12,
            "CACI": -0.12, "LHX": -0.15, "ARKQ": -0.20,
            "Default": 0.0,
        },
    },
}

# Sector mapping for positions
SECTOR_MAP = {
    "V": "Financials", "SCHD": "Default", "LMT": "Industrials",
    "NOC": "Industrials", "RTX": "Industrials", "AVAV": "Industrials",
    "KTOS": "Industrials", "RKLB": "Technology", "BAH": "Industrials",
    "LDOS": "Technology", "CACI": "Technology", "LHX": "Industrials",
    "SCHG": "Technology", "FCNTX": "Technology", "CSWC": "Financials",
    "PFLT": "Financials", "BND": "Bonds", "VXUS": "Default",
    "VTI": "Default", "SGOV": "Bonds", "JEPI": "Default",
    "JEPQ": "Technology", "DIV": "Default", "NEE": "Utilities",
    "IRDM": "Communication", "ARKQ": "Technology", "ARKG": "Healthcare",
    "PFF": "Financials", "AGG": "Bonds", "VCIT": "Bonds",
}

def run_stress_tests(portfolio: Dict, state_dir: Path) -> Dict:
    holdings = [h for h in portfolio.get("holdings",[])
                if h.get("market_value",0) >= 1000 and not h.get("is_loan")]
    total_value = sum(h.get("market_value",0) for h in holdings)
    if not total_value:
        return {"scenarios": {}, "has_data": False}

    # Load current stops
    stops_file = state_dir / "stops.json"
    stops = {}
    if stops_file.exists():
        try: stops = json.loads(stops_file.read_text())
        except: pass

    results = {}
    for scenario_id, scenario in SCENARIOS.items():
        shocks  = scenario["shocks"]
        pos_impacts = []
        total_loss  = 0.0
        stop_saves  = 0.0

        for h in holdings:
            sym    = h.get("symbol","").upper()
            mv     = h.get("market_value",0)
            price  = h.get("price",0) or 1
            shares = h.get("shares",0)

            # Determine shock for this position
            if sym in shocks:
                shock = shocks[sym]
            else:
                sector = SECTOR_MAP.get(sym, "Default")
                shock  = shocks.get(sector, shocks.get("Default", -0.15))

            loss      = mv * shock
            new_value = mv + loss
            new_price = price * (1 + shock)

            # Would stop have saved this loss?
            stop_data  = stops.get(sym, {})
            stop_price = stop_data.get("stop", 0)
            stop_saved = 0.0
            if stop_price and stop_price > 0 and shock < 0:
                stop_price_pct_loss = (stop_price - price) / price
                if stop_price_pct_loss > shock:  # stop triggers before full shock
                    stop_loss     = mv * stop_price_pct_loss
                    stop_saved    = abs(loss) - abs(stop_loss)
                    stop_saved    = max(0, stop_saved)
                    stop_saves   += stop_saved

            total_loss += loss
            pos_impacts.append({
                "symbol":    sym,
                "mv_before": round(mv, 0),
                "shock_pct": round(shock*100, 1),
                "loss":      round(loss, 0),
                "mv_after":  round(new_value, 0),
                "new_price": round(new_price, 2),
                "stop_price":stop_price,
                "stop_saved":round(stop_saved, 0),
            })

        pos_impacts.sort(key=lambda x: x["loss"])
        portfolio_after = total_value + total_loss

        results[scenario_id] = {
            "name":              scenario["name"],
            "description":       scenario["description"],
            "total_value_before":round(total_value, 0),
            "total_loss":        round(total_loss, 0),
            "total_value_after": round(portfolio_after, 0),
            "loss_pct":          round(total_loss/total_value*100, 1),
            "stops_would_save":  round(stop_saves, 0),
            "net_loss_with_stops":round(total_loss + stop_saves, 0),
            "positions":         pos_impacts,
            "worst_5":           pos_impacts[:5],
            "best_5":            sorted(pos_impacts, key=lambda x: x["loss"])[-5:],
        }

    # Summary: worst-case across all scenarios
    worst = min(results.values(), key=lambda x: x["total_loss"])

    output = {
        "has_data":           True,
        "portfolio_value":    round(total_value, 0),
        "scenarios":          results,
        "worst_case_scenario":worst["name"],
        "worst_case_loss":    worst["total_loss"],
        "worst_case_value":   worst["total_value_after"],
        "last_updated":       datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    (state_dir/"stress_test.json").write_text(json.dumps(output, indent=2, default=str))
    return output
