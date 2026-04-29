#!/usr/bin/env python3
"""Proactively find candidates for AI watchlists.

Inputs, in priority order:
- data/portfolios/state/asset_intelligence.json
- data/merged/latest_enriched.csv or latest_screeners.csv when present
- data/portfolios/state/manual_ideas.json for ideas from transcripts/YouTube/social notes

Outputs:
- discovery_candidates.json
- ai_watchlist.json (adds/keeps candidates with trade plans; no deletions)
- optional Postgres discovery_candidates_history rows
"""
from __future__ import annotations
import argparse, csv, json, os, re, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data/portfolios/state"
DATA = ROOT / "data"
CONFIG = ROOT / "config/agent_discovery_config.json"


def now_iso(): return datetime.now(timezone.utc).isoformat()
def read_json(p: Path, default: Any):
    try:
        return json.loads(p.read_text(errors="ignore")) if p.exists() else default
    except Exception: return default

def write_json(p: Path, data: Any):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(p)

def norm(s): return re.sub(r"[^A-Za-z0-9._-]", "", str(s or "").upper()).strip()

def load_csv_candidates() -> List[Dict[str, Any]]:
    paths = [DATA / "merged/latest_enriched.csv", DATA / "merged/latest_screeners.csv"]
    out = []
    for p in paths:
        if not p.exists():
            continue
        try:
            with p.open(newline="", errors="ignore") as f:
                for row in csv.DictReader(f):
                    sym = norm(row.get("symbol") or row.get("ticker") or row.get("Symbol"))
                    if sym:
                        out.append({"symbol": sym, "source": str(p), "raw": row})
        except Exception as e:
            print(f"[discovery] WARN: skipped {p}: {e}")
    return out

def make_trade_plan(item: Dict[str, Any]) -> Dict[str, Any]:
    bucket = item.get("bucket", "research_queue")
    symbol = item["symbol"]
    if bucket == "swing_trade":
        style = "swing_trade"
        entry = "Wait for confirmed breakout/retest or strong close above trigger level."
        exitp = "Use invalidation under recent support or ATR-based stop; review within 3-10 trading days."
    elif bucket in ("dividend_core", "defensive_income"):
        style = "dividend_or_income_candidate"
        entry = "Stage entry only after yield, expense, sector overlap, and account-placement review."
        exitp = "Remove if dividend thesis weakens, expense/overlap is inferior, or better replacement is found."
    elif bucket == "compounder":
        style = "compounder_candidate"
        entry = "Wait for valuation/technical setup and analyst/news confirmation."
        exitp = "Remove if thesis score decays, analyst skew turns negative, or relative strength breaks."
    else:
        style = "research_queue"
        entry = "Needs analyst/ETF/fund enrichment before actionable entry."
        exitp = "Remove if no thesis is formed before review deadline."
    return {"style": style, "entry_plan": entry, "exit_plan": exitp, "position_sizing": "No sizing until Steph/Risk review.", "symbol": symbol}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-score", type=float, default=8.0)
    args = ap.parse_args()

    cfg = read_json(CONFIG, {})
    asset_intel = read_json(STATE / "asset_intelligence.json", {"items": []}).get("items", [])
    manual = read_json(STATE / "manual_ideas.json", {"ideas": []}).get("ideas", [])
    csv_items = load_csv_candidates()

    by_symbol: Dict[str, Dict[str, Any]] = {}
    for r in asset_intel:
        sym = norm(r.get("symbol"))
        if sym:
            by_symbol[sym] = {**r, "source": "asset_intelligence"}
    for r in csv_items:
        sym = r["symbol"]
        by_symbol.setdefault(sym, {"symbol": sym, "score": 5, "bucket": "research_queue", "reasons": ["found in screener"], "source": r["source"]})
    for idea in manual:
        sym = norm(idea.get("symbol") or idea.get("ticker"))
        if sym:
            by_symbol.setdefault(sym, {"symbol": sym, "score": 6, "bucket": "research_queue", "reasons": ["manual/social/transcript idea"], "source": idea.get("source", "manual_ideas"), "idea": idea})

    candidates = []
    for sym, item in by_symbol.items():
        score = float(item.get("score") or 0)
        bucket = item.get("bucket") or "research_queue"
        if score >= args.min_score or bucket != "research_queue" or item.get("idea"):
            c = {
                "symbol": sym,
                "bucket": bucket,
                "score": score,
                "source": item.get("source", "unknown"),
                "generated_at": now_iso(),
                "reasons": item.get("reasons", []),
                "asset_type": item.get("asset_type", "unknown"),
                "trade_plan": make_trade_plan({"symbol": sym, "bucket": bucket}),
                "status": "candidate",
                "owner_agent": "maria" if bucket in ("research_queue", "dividend_core", "compounder") else "risk_agent"
            }
            candidates.append(c)
    candidates.sort(key=lambda x: (x.get("score", 0), x.get("symbol", "")), reverse=True)

    existing = read_json(STATE / "ai_watchlist.json", {"watchlist": []})
    watch = {norm(x.get("symbol")): x for x in existing.get("watchlist", []) if isinstance(x, dict) and norm(x.get("symbol"))}
    for c in candidates:
        sym = c["symbol"]
        old = watch.get(sym, {})
        watch[sym] = {**old, **c, "last_seen": now_iso(), "added_at": old.get("added_at") or now_iso(), "review_status": "active_ai_candidate"}

    out_candidates = {"generated_at": now_iso(), "candidates": candidates, "count": len(candidates)}
    out_watch = {"generated_at": now_iso(), "watchlist": sorted(watch.values(), key=lambda x: (x.get("bucket", ""), -float(x.get("score") or 0), x.get("symbol", "")))}
    write_json(STATE / "discovery_candidates.json", out_candidates)
    write_json(STATE / "ai_watchlist.json", out_watch)

    summary = {"ok": True, "candidates": len(candidates), "watchlist_size": len(out_watch["watchlist"]), "files_written": [str(STATE / "discovery_candidates.json"), str(STATE / "ai_watchlist.json")]}
    print(json.dumps(summary, indent=2) if args.json else f"[discovery] candidates={len(candidates)} watchlist={len(out_watch['watchlist'])}")
    return 0
if __name__ == "__main__": raise SystemExit(main())
