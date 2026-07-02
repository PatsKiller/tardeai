#!/usr/bin/env python3
"""hermes_score_event_feeder.py — the event lane of Phase 1 (docs/design/HERMES_MATURITY_5_DESIGN.md §1.2).

Work happens when information changes, not when the clock ticks: fresh catalysts, news, Finviz
screener entries, directive hits, and new proposals enqueue an immediate rescore for that symbol
in hermes_score_event_queue — regardless of scope tier. An archived (S3) symbol with a fresh
event is reactivated to S1 (audited), which the old 4.1k clock sweep could never do despite
48 runs/day.

Cursorless: each run scans a window of 2x the cron cadence; the one-pending-event-per-symbol
unique index makes overlapping scans a no-op. Only symbols already in the watchlist universe
are enqueued (the scorer can't score anything else). Advisory-only; honors HERMES_DISABLED.

  python3 scripts/hermes_score_event_feeder.py            # dry-run
  python3 scripts/hermes_score_event_feeder.py --apply
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

KILL_SWITCH = PROJECT_ROOT / "data" / "runtime" / "HERMES_DISABLED"
CFG_FILE = PROJECT_ROOT / "config" / "hermes_scope_governor.yaml"

# source name -> (SQL yielding (symbol, ref) fresh within %s minutes)
SOURCE_SQL = {
    "catalyst": """SELECT DISTINCT UPPER(symbol), 'catalyst_events:' || MAX(id::text)
                   FROM catalyst_events WHERE created_at > NOW() - make_interval(mins => %s)
                   GROUP BY UPPER(symbol)""",
    "news": """SELECT DISTINCT UPPER(symbol), 'news_articles'
               FROM news_articles WHERE symbol IS NOT NULL
                 AND created_at > NOW() - make_interval(mins => %s)
               GROUP BY UPPER(symbol)""",
    "finviz": """SELECT DISTINCT UPPER(symbol), 'screener:' || MAX(screener_id::text)
                 FROM screener_symbol_membership
                 WHERE first_seen_in_screener_at > NOW() - make_interval(mins => %s)
                 GROUP BY UPPER(symbol)""",
    # first-EVER hit for the (directive, symbol) pair only — discovery restages existing hits
    # every 30 min (bumping surfaced_at), and treating restages as events reflooded the live
    # tiers with the exact inflation Phase 1 exists to stop (274 fake events per 20-min window).
    "directive_hit": """SELECT DISTINCT UPPER(h.symbol), 'directive:' || MAX(h.directive_id::text)
                        FROM watch_directive_hits h
                        WHERE h.surfaced_at > NOW() - make_interval(mins => %s)
                          AND NOT EXISTS (
                            SELECT 1 FROM watch_directive_hits h0
                            WHERE h0.directive_id = h.directive_id
                              AND UPPER(h0.symbol) = UPPER(h.symbol)
                              AND h0.surfaced_at <= NOW() - make_interval(mins => %s))
                        GROUP BY UPPER(h.symbol)""",
    "proposal": """SELECT DISTINCT UPPER(symbol), 'proposal:' || MAX(id::text)
                   FROM paper_trade_proposals
                   WHERE created_at > NOW() - make_interval(mins => %s)
                   GROUP BY UPPER(symbol)""",
}


def _cfg():
    import yaml
    return yaml.safe_load(CFG_FILE.read_text())


def run(apply: bool = False) -> dict:
    if KILL_SWITCH.exists():
        out = {"ok": False, "reason": "HERMES_DISABLED kill switch present — feeder idle"}
        print(json.dumps(out))
        return out
    from db_adapter import _get_conn
    cfg = _cfg()["event_feeder"]
    window = int(cfg["scan_minutes"])
    sources = list(cfg["sources"])
    conn = _get_conn()
    cur = conn.cursor()
    run_id = f"ev_{uuid.uuid4().hex[:10]}"

    cur.execute("""SELECT DISTINCT UPPER(symbol) FROM watchlist_items
                   WHERE status IN ('active','researched')""")
    universe = {r[0] for r in cur.fetchall()}

    found: dict[str, tuple[str, str]] = {}       # symbol -> (event_type, ref)
    for src in sources:
        sql = SOURCE_SQL.get(src)
        if not sql:
            continue
        cur.execute(sql, (window, window) if sql.count("%s") == 2 else (window,))
        for sym, ref in cur.fetchall():
            if sym in universe and sym not in found:
                found[sym] = (src, ref)

    enqueued = reactivated = 0
    if apply and found:
        for sym, (etype, ref) in found.items():
            cur.execute("""INSERT INTO hermes_score_event_queue (symbol, event_type, source_ref)
                           VALUES (%s,%s,%s)
                           ON CONFLICT (symbol) WHERE processed_at IS NULL DO NOTHING""",
                        (sym, etype, ref))
            enqueued += cur.rowcount
        # S3 -> S1 reactivation on any fresh event (audited; governor may re-tier later)
        cur.execute("""SELECT DISTINCT UPPER(symbol) FROM watchlist_items
                       WHERE scope_tier='S3' AND UPPER(symbol) = ANY(%s)
                         AND status IN ('active','researched')""", (list(found.keys()),))
        for (sym,) in cur.fetchall():
            etype, ref = found[sym]
            cur.execute("""UPDATE watchlist_items
                           SET scope_tier='S1', trigger_source=%s, last_trigger_at=NOW(), updated_at=NOW()
                           WHERE UPPER(symbol)=%s AND status IN ('active','researched')""",
                        (f"event:{etype}", sym))
            cur.execute("""INSERT INTO scope_governor_audit (run_id, symbol, action, from_tier, to_tier, reason)
                           VALUES (%s,%s,'reactivate','S3','S1',%s)""", (run_id, sym, f"event:{etype}:{ref}"))
            reactivated += 1
        conn.commit()

    by_type = {}
    for _s, (t, _r) in found.items():
        by_type[t] = by_type.get(t, 0) + 1
    out = {"ok": True, "apply": apply, "run_id": run_id, "window_minutes": window,
           "events_found": len(found), "by_type": by_type,
           "enqueued": enqueued, "reactivated_s3_to_s1": reactivated,
           "sample": [f"{s}<-{t}" for s, (t, _r) in list(found.items())[:10]],
           "ts": datetime.now(timezone.utc).isoformat()}
    print(json.dumps(out, indent=2))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    run(apply=args.apply)


if __name__ == "__main__":
    main()
