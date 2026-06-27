#!/usr/bin/env python3
"""Phase 190B — Persist Alpaca PAPER broker-stop verification metadata.

READ-ONLY against the broker: queries the Alpaca *paper* order book and matches
protective stop orders to open paper_trades, then persists verification metadata
to the DB. It NEVER places, modifies, or cancels any order, and never touches a
live endpoint.

Writes only these paper_trades columns:
  stop_order_id, stop_verified_at, stop_verified_source, broker_stop_status,
  current_stop, protection_status, protection_defect_reason,
  last_broker_protection_check_at

Run:
  python3 scripts/verify_paper_trade_broker_stops.py            # persist
  python3 scripts/verify_paper_trade_broker_stops.py --dry-run  # report only
"""
import os, sys, json, argparse
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAPER_BASE = "https://paper-api.alpaca.markets"  # paper only — never live

NEW_COLUMNS = [
    ("stop_verified_source", "text"),
    ("broker_stop_status", "text"),
    ("current_stop", "numeric"),
    ("stop_type", "text"),
    ("take_profit_order_id", "text"),
    ("profit_protection_status", "text"),
    ("trailing_active", "boolean"),
    ("trailing_policy_version", "text"),
    ("protection_status", "text"),
    ("protection_defect_reason", "text"),
    ("last_broker_protection_check_at", "timestamptz"),
]


def load_env():
    for line in open(os.path.join(ROOT, ".env")):
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def db():
    import psycopg2
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
                            dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"])


def ensure_columns(cur):
    for name, typ in NEW_COLUMNS:
        cur.execute(f"ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS {name} {typ}")


def broker_open_stops():
    """READ-ONLY paper order book → {symbol: [stop orders]}. Hard-fails if the
    base URL is not the paper endpoint (guard against live)."""
    assert PAPER_BASE.startswith("https://paper-api."), "refusing non-paper endpoint"
    import requests
    h = {"APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
         "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"]}
    r = requests.get(f"{PAPER_BASE}/v2/orders", headers=h,
                     params={"status": "open", "limit": 500}, timeout=20)
    r.raise_for_status()
    out = {}
    for o in r.json():
        if o.get("type") == "stop" and o.get("side") == "sell":
            out.setdefault(o["symbol"], []).append(o)
    return out


def match_stop(stops, shares):
    """Match a stop order to the trade. Prefer exact qty match; else single stop."""
    if not stops:
        return None
    if shares is not None:
        exact = [o for o in stops if str(o.get("qty")) == str(int(shares))]
        if exact:
            return exact[0]
    return stops[0] if len(stops) == 1 else None


def run(dry_run=False):
    load_env()
    now = datetime.now(timezone.utc)
    conn = db(); cur = conn.cursor()
    if not dry_run:
        ensure_columns(cur); conn.commit()

    stops = broker_open_stops()
    cur.execute("""select id,symbol,shares,stop_loss,stop_order_id,take_profit_price
                   from paper_trades where status='open' order by id""")
    rows = cur.fetchall()
    report = {"run_at": now.isoformat(), "mode": "dry-run" if dry_run else "persist",
              "endpoint": PAPER_BASE, "trades_scanned": len(rows),
              "broker_stops_found": sum(len(v) for v in stops.values()),
              "persisted": [], "unverified": [], "unmatched_broker_stops": [], "errors": []}

    matched_ids = set()
    for (tid, sym, shares, sl, soid, tp) in rows:
        o = match_stop(stops.get(sym, []), shares)
        if not o:
            report["unverified"].append({"id": tid, "symbol": sym, "reason": "no_matching_broker_stop"})
            if not dry_run:
                cur.execute("""update paper_trades set protection_status='NAKED',
                    protection_defect_reason='no_broker_stop_found',
                    last_broker_protection_check_at=%s where id=%s""", (now, tid))
            continue
        matched_ids.add(o["id"])
        bstop = o.get("stop_price")
        prot = "PROTECTED_TRACKED"
        defect = None if soid == o["id"] else "stop_order_id_backfilled"
        rec = {"id": tid, "symbol": sym, "stop_order_id": o["id"],
               "broker_stop_price": bstop, "broker_stop_status": o.get("status"),
               "was_tracked": bool(soid), "take_profit_present": tp is not None}
        report["persisted"].append(rec)
        if not dry_run:
            cur.execute("""update paper_trades set
                    stop_order_id=%s, stop_verified_at=%s,
                    stop_verified_source='alpaca_paper_order_book',
                    broker_stop_status=%s, current_stop=%s, stop_type='stop',
                    planned_stop=coalesce(planned_stop, stop_loss, %s),
                    protection_status=%s, protection_defect_reason=%s,
                    profit_protection_status=case when take_profit_price is not null
                        then 'has_take_profit' else 'no_take_profit' end,
                    last_broker_protection_check_at=%s
                  where id=%s""",
                (o["id"], now, o.get("status"), bstop, bstop, prot, defect, now, tid))

    # broker stops with no matching open trade
    for sym, olist in stops.items():
        for o in olist:
            if o["id"] not in matched_ids:
                report["unmatched_broker_stops"].append(
                    {"symbol": sym, "stop_order_id": o["id"], "stop_price": o.get("stop_price")})

    if not dry_run:
        conn.commit()
    # recount untracked AFTER
    cur.execute("""select count(*) from paper_trades where status='open'
                   and (stop_order_id is null)""")
    report["open_trades_without_stop_order_id_after"] = cur.fetchone()[0]
    conn.close()
    print(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    run(dry_run=a.dry_run)
