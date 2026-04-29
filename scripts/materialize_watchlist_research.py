#!/usr/bin/env python3
import json, os, subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/"data/portfolios/state"
RESULTS=STATE/"watchlist_research_results.json"
OUT=STATE/"watchlist_research_cards.json"
ENV=ROOT/".env"

def load(p,d):
    return json.loads(p.read_text()) if p.exists() else d

def now():
    return datetime.now(timezone.utc).isoformat()

results=load(RESULTS,{"results":[]}).get("results",[])
cards={}
for r in results:
    sym=r.get("symbol")
    if not sym: continue
    route=r.get("route",{})
    cards[sym]={
        "symbol":sym,
        "last_researched_at":r.get("completed_at"),
        "research_status":r.get("status"),
        "research_agent":r.get("agent"),
        "request_type":r.get("request_type"),
        "summary":r.get("summary"),
        "recommended_next_action":r.get("recommended_next_action"),
        "route_to_agent":route.get("to_agent"),
        "confidence":route.get("confidence"),
        "freshness_ok":route.get("freshness_ok"),
        "reliability_mode":(route.get("reliability_controls") or {}).get("mode"),
        "blocked":(route.get("reliability_controls") or {}).get("blocked"),
        "reviewers":route.get("reviewers",[]),
        "needs_iteration": route.get("confidence",0) < 0.75 or bool((route.get("reliability_controls") or {}).get("blocked")),
        "updated_at":now()
    }

OUT.write_text(json.dumps({"generated_at":now(),"cards":cards},indent=2))
print(json.dumps({"ok":True,"cards":len(cards),"file":str(OUT)},indent=2))
