#!/usr/bin/env python3
"""sync_watchlist_items_to_db.py — Sync watchlist items from JSON sources into PostgreSQL.

Reads current JSON files as ingestion sources, upserts normalized records into watchlist_items.
DB is canonical. JSON is ingestion/cache only.

Sources:
- holdings.json → source='portfolio'
- discovery_candidates.json → source='ai_discovered'
- ai_watchlist.json → source='ai_watchlist'
- watchlist.json → source='personal_watchlist'
- classified_candidates.json → asset_type + bucket enrichment
- backtest_summary.json → backtest_score + backtest_data
- tos_trade_plans.json → trade_plan

Usage:
    python3 scripts/sync_watchlist_items_to_db.py [--json]
"""
import json, os, sys, uuid
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "data" / "portfolios" / "state"


def _load(filename, default=None):
    path = STATE_DIR / filename
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return default if default is not None else {}


def _get_conn():
    import psycopg2
    pw = os.environ.get("DB_PASSWORD", "")
    if not pw:
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("DB_PASSWORD="):
                    pw = line.split("=", 1)[1].strip()
    return psycopg2.connect(host="localhost", dbname="trade_ai", user="trade_ai", password=pw)


def sync():
    conn = _get_conn()
    cur = conn.cursor()
    now = datetime.now().isoformat()

    # Load all sources
    holdings_raw = _load("holdings.json", {})
    discovery_raw = _load("discovery_candidates.json", {})
    ai_watchlist_raw = _load("ai_watchlist.json", {})
    classified_raw = _load("classified_candidates.json", {})
    backtest_raw = _load("backtest_summary.json", {})
    trade_plans_raw = _load("tos_trade_plans.json", {})
    watchlist_raw = _load("watchlist.json", [])

    # Build classification lookup
    classifications = {}
    for c in classified_raw.get("classified_candidates", []):
        sym = c.get("symbol", "")
        if sym:
            classifications[sym] = {
                "asset_type": c.get("asset_type"),
                "buckets": c.get("buckets") or [],
            }

    # Build backtest lookup
    backtests = {}
    if isinstance(backtest_raw, dict):
        for sym, data in backtest_raw.items():
            if isinstance(data, dict):
                backtests[sym] = data

    # RETIRED 2026-07-20: watchlist_items.trade_plan.
    #
    # This never worked. tos_trade_plans.json is shaped
    # {"generated_at": ..., "trade_plans": [...]} but the dict branch below
    # iterated the TOP-LEVEL keys, so "generated_at" (a str) and "trade_plans"
    # (a list) both failed the isinstance(data, dict) test and nothing was ever
    # collected. Result: all 12,169 watchlist rows carry an empty {} — while
    # `trade_plan IS NOT NULL` still returns TRUE for an empty object, so
    # callers were told a plan existed when none did.
    #
    # It is also superseded: real entry plans live in watchlist_entry_plans
    # (5,230 rows, produced by watchlist_entry_planner at 17:35 weekdays). The
    # ToS export behind this path was last written 2026-04-28.
    #
    # The shape bug is deliberately NOT fixed — reviving a 3-month-stale source
    # to populate a superseded column would put a second, contradictory plan
    # store back in front of the operator.
    trade_plans: dict = {}

    # ── Source 1: Portfolio ──
    portfolio_items = []
    for h in holdings_raw.get("holdings", []):
        sym = h.get("symbol", "")
        mv = h.get("market_value", 0) or 0
        shares = h.get("shares", h.get("qty", h.get("quantity", 0))) or 0
        if sym and (mv > 100 or shares > 0) and sym not in ("CASH", "MMKT"):
            portfolio_items.append(sym)

    # ── Source 2: AI Discovered ──
    discovered_items = []
    for c in discovery_raw.get("candidates", []):
        sym = c.get("symbol", "")
        if sym:
            discovered_items.append({"symbol": sym, "score": c.get("score"), "bucket": c.get("bucket"),
                                     "asset_type": c.get("asset_type"), "payload": c})

    # ── Source 3: AI Watchlist ──
    ai_wl_items = []
    for w in ai_watchlist_raw.get("watchlist", []):
        sym = w.get("symbol", "")
        if sym:
            ai_wl_items.append({"symbol": sym, "score": w.get("score"), "bucket": w.get("bucket"),
                                "asset_type": w.get("asset_type"), "payload": w})

    # ── Source 4: Personal Watchlist ──
    personal_items = []
    if isinstance(watchlist_raw, list):
        for item in watchlist_raw:
            if isinstance(item, dict) and item.get("symbol"):
                personal_items.append(item["symbol"])
            elif isinstance(item, str):
                personal_items.append(item)
    elif isinstance(watchlist_raw, dict):
        personal_items = list(watchlist_raw.keys())

    # ── Upsert into DB ──
    upserted = 0

    def upsert(symbol, source, bucket=None, asset_type=None, score=None, payload=None):
        nonlocal upserted
        cls = classifications.get(symbol, {})
        at = asset_type or cls.get("asset_type")
        bk = bucket
        bt = backtests.get(symbol, {})
        tp = trade_plans.get(symbol, {})
        bt_score = bt.get("score") or bt.get("backtest_score")
        origin = {
            "ai_discovered": "discovery_candidates",
            "ai_watchlist": "ai_watchlist",
            "portfolio": "portfolio",
            "personal_watchlist": "personal_watchlist",
        }.get(source, source)

        cur.execute("""
            INSERT INTO watchlist_items (symbol, source, bucket, asset_type, status, score, backtest_score, backtest_data, trade_plan, source_payload, origin_system, last_seen_at, updated_at)
            VALUES (%s, %s, %s, %s, 'active', %s, %s, %s, %s, %s, %s, now(), now())
            ON CONFLICT (symbol, source, COALESCE(bucket, '__none__'))
            DO UPDATE SET
                asset_type = COALESCE(EXCLUDED.asset_type, watchlist_items.asset_type),
                score = COALESCE(EXCLUDED.score, watchlist_items.score),
                backtest_score = COALESCE(EXCLUDED.backtest_score, watchlist_items.backtest_score),
                backtest_data = CASE WHEN EXCLUDED.backtest_data != '{}' THEN EXCLUDED.backtest_data ELSE watchlist_items.backtest_data END,
                trade_plan = CASE WHEN EXCLUDED.trade_plan != '{}' THEN EXCLUDED.trade_plan ELSE watchlist_items.trade_plan END,
                source_payload = COALESCE(EXCLUDED.source_payload, watchlist_items.source_payload),
                last_seen_at = now(),
                updated_at = now(),
                status = CASE WHEN watchlist_items.status = 'removed' THEN 'active' ELSE watchlist_items.status END
        """, (symbol, source, bk, at, score, bt_score,
              json.dumps(bt) if bt else '{}', json.dumps(tp) if tp else '{}',
              json.dumps(payload) if payload else '{}', origin))
        upserted += 1

    # Portfolio
    for sym in set(portfolio_items):
        upsert(sym, 'portfolio')

    # AI Discovered
    for item in discovered_items:
        upsert(item["symbol"], 'ai_discovered', bucket=item.get("bucket"),
               asset_type=item.get("asset_type"), score=item.get("score"), payload=item.get("payload"))

    # AI Watchlist
    for item in ai_wl_items:
        upsert(item["symbol"], 'ai_watchlist', bucket=item.get("bucket"),
               asset_type=item.get("asset_type"), score=item.get("score"), payload=item.get("payload"))

    # Personal Watchlist
    for sym in set(personal_items):
        upsert(sym, 'personal_watchlist')

    # Log event
    cur.execute("""
        INSERT INTO watchlist_events (event_type, message, payload)
        VALUES ('sync_complete', %s, %s)
    """, (f"Synced {upserted} items at {now}",
          json.dumps({"portfolio": len(set(portfolio_items)), "ai_discovered": len(discovered_items),
                      "ai_watchlist": len(ai_wl_items), "personal": len(set(personal_items)),
                      "total_upserted": upserted})))

    conn.commit()
    cur.close()
    conn.close()

    return {
        "upserted": upserted,
        "portfolio": len(set(portfolio_items)),
        "ai_discovered": len(discovered_items),
        "ai_watchlist": len(ai_wl_items),
        "personal_watchlist": len(set(personal_items)),
    }


if __name__ == "__main__":
    result = sync()
    if "--json" in sys.argv:
        print(json.dumps(result, indent=2))
    else:
        print(f"[watchlist-sync] Upserted {result['upserted']} items")
        print(f"  Portfolio: {result['portfolio']}")
        print(f"  AI Discovered: {result['ai_discovered']}")
        print(f"  AI Watchlist: {result['ai_watchlist']}")
        print(f"  Personal: {result['personal_watchlist']}")
