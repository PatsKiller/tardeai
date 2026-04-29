#!/usr/bin/env python3
import json, re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data/portfolios/state"
OUT = STATE / "watchlist_sources.json"
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,11}$")

def load(name, default):
    p = STATE / name
    if not p.exists():
        return default
    try:
        return json.loads(p.read_text())
    except Exception:
        return default

def norm(x):
    if not x:
        return ""
    s = str(x).strip().upper().replace("$", "")
    return s if TICKER_RE.match(s) else ""

def walk_symbols(obj):
    found = set()
    def walk(x):
        if isinstance(x, dict):
            s = norm(x.get("symbol") or x.get("ticker") or x.get("Symbol") or x.get("Ticker"))
            if s:
                found.add(s)
            for k, v in x.items():
                ks = norm(k)
                if ks and isinstance(v, dict) and len(ks) <= 6:
                    found.add(ks)
                walk(v)
        elif isinstance(x, list):
            for i in x:
                walk(i)
    walk(obj)
    return found

def holding_symbols(obj):
    found = set()
    def walk(x):
        if isinstance(x, dict):
            s = norm(x.get("symbol") or x.get("ticker") or x.get("Symbol") or x.get("Ticker"))
            keys = {str(k).lower() for k in x.keys()}
            holding_keys = {"shares","qty","quantity","market_value","cost_basis","account","account_name","current_value"}
            if s and keys.intersection(holding_keys):
                found.add(s)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for i in x:
                walk(i)
    walk(obj)
    return found

classified = load("classified_candidates.json", {}).get("classified_candidates", [])
symbols = {norm(c.get("symbol")) for c in classified if norm(c.get("symbol"))}

disc = walk_symbols(load("discovery_candidates.json", {}))
aiw = walk_symbols(load("ai_watchlist.json", {}))
hold = holding_symbols(load("holdings.json", {}))
research = set((load("watchlist_research_cards.json", {}).get("cards", {}) or {}).keys())

personal = set()
for f in ["personal_watchlist.json","manual_watchlist.json","watchlist.json","user_watchlist.json"]:
    personal |= walk_symbols(load(f, {}))

sources = {}
for s in sorted(symbols):
    sources[s] = {
        "symbol": s,
        "in_portfolio": s in hold,
        "ai_discovered": s in disc,
        "ai_watchlist": s in aiw,
        "personal_watchlist": s in personal,
        "researched": s in research,
        "source_files": []
    }
    if s in hold: sources[s]["source_files"].append("holdings.json")
    if s in disc: sources[s]["source_files"].append("discovery_candidates.json")
    if s in aiw: sources[s]["source_files"].append("ai_watchlist.json")
    if s in personal: sources[s]["source_files"].append("personal_watchlist/manual")
    if s in research: sources[s]["source_files"].append("watchlist_research_cards.json")

out = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "counts": {
        "total": len(sources),
        "portfolio": sum(1 for x in sources.values() if x["in_portfolio"]),
        "ai_discovered": sum(1 for x in sources.values() if x["ai_discovered"]),
        "ai_watchlist": sum(1 for x in sources.values() if x["ai_watchlist"]),
        "personal_watchlist": sum(1 for x in sources.values() if x["personal_watchlist"]),
        "researched": sum(1 for x in sources.values() if x["researched"])
    },
    "sources": sources
}
OUT.write_text(json.dumps(out, indent=2))
print(json.dumps(out["counts"], indent=2))
