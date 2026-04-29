#!/usr/bin/env python3
"""Review AI watchlist and justify keep/remove/research status.

This script does not delete. It writes review recommendations and marks stale items.
"""
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data/portfolios/state"
CONFIG = ROOT / "config/agent_discovery_config.json"

def now(): return datetime.now(timezone.utc)
def now_iso(): return now().isoformat()
def read_json(p: Path, d: Any):
    try: return json.loads(p.read_text(errors="ignore")) if p.exists() else d
    except Exception: return d
def write_json(p: Path, data: Any):
    p.parent.mkdir(parents=True, exist_ok=True); tmp=p.with_suffix(p.suffix+'.tmp'); tmp.write_text(json.dumps(data, indent=2, sort_keys=True)); tmp.replace(p)
def parse_dt(s: str):
    try: return datetime.fromisoformat(str(s).replace('Z','+00:00'))
    except Exception: return None

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--json', action='store_true'); args=ap.parse_args()
    cfg=read_json(CONFIG,{})
    stale_after=int(((cfg.get('watchlist_review') or {}).get('stale_after_days') or 14))
    remove_after=int(((cfg.get('watchlist_review') or {}).get('remove_after_days_without_thesis') or 30))
    wl=read_json(STATE/'ai_watchlist.json', {'watchlist':[]}).get('watchlist',[])
    reviews=[]
    for item in wl:
        sym=item.get('symbol')
        last=parse_dt(item.get('last_seen') or item.get('added_at') or '')
        age=(now()-last).days if last else 999
        plan=item.get('trade_plan') or {}
        thesis='; '.join(item.get('reasons') or [])
        action='keep'
        status='active'
        if not plan or not plan.get('entry_plan') or not plan.get('exit_plan'):
            action='needs_trade_plan'; status='incomplete'
        if age >= stale_after:
            action='review'; status='stale_review_needed'
        if age >= remove_after and (not thesis or thesis == 'needs more data'):
            action='remove_candidate'; status='no_thesis_expired'
        reviews.append({**item, 'reviewed_at':now_iso(), 'age_days':age, 'recommended_action':action, 'review_status':status, 'justification': thesis or 'No clear thesis recorded.'})
    out={'generated_at':now_iso(),'reviews':reviews,'counts':{}}
    for r in reviews: out['counts'][r['recommended_action']]=out['counts'].get(r['recommended_action'],0)+1
    write_json(STATE/'ai_watchlist_review.json', out)
    print(json.dumps({'ok':True,'reviewed':len(reviews),'counts':out['counts'],'file':str(STATE/'ai_watchlist_review.json')}, indent=2) if args.json else f"[watchlist-review] reviewed {len(reviews)}")
    return 0
if __name__=='__main__': raise SystemExit(main())
