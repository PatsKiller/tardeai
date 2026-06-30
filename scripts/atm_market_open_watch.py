#!/usr/bin/env python3
"""ATM Market-Open Watch (Phase 189A) — READ-ONLY.

One-shot 09:30 ET audit. Does NOT submit orders, place/modify stops, mutate
trades, change strategy configs, or touch GO/WAIT logic. Paper account only.

Outputs a digest to docs/atm/PHASE189F_MARKET_OPEN_REVALIDATION_REPORT.md and
prints to stdout/log. Verifies broker stop coverage against the Alpaca *paper*
order book (read-only), revalidates ELMT freshness, and runs the STOP-V2.3
trailing engine in recommendation-only mode.
"""
import os, sys, json
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

# --- env ---
def load_env():
    env = {}
    p = os.path.join(ROOT, ".env")
    for line in open(p):
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k] = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, env[k])
    return env

ENV = load_env()

GUARD = {
    "paper_only": os.getenv("ALPACA_MODE") == "paper",
    "live_endpoint_blocked": True,
    "level7": "PROHIBITED",
    "mutations": "NONE",
}


def db():
    import psycopg2
    return psycopg2.connect(host=ENV["DB_HOST"], port=ENV["DB_PORT"],
                            dbname=ENV["DB_NAME"], user=ENV["DB_USER"],
                            password=ENV["DB_PASSWORD"])


def broker_open_orders():
    """READ-ONLY: paper order book. Returns {symbol: [stop orders]}."""
    import requests
    base = "https://paper-api.alpaca.markets"
    h = {"APCA-API-KEY-ID": os.getenv("ALPACA_API_KEY"),
         "APCA-API-SECRET-KEY": os.getenv("ALPACA_SECRET_KEY")}
    # nested=true so OCO/bracket child legs (the 'held' stop leg) are returned; descend into legs[] when
    # building the per-symbol order book, else an OCO-protected position looks NAKED (false alarm).
    r = requests.get(f"{base}/v2/orders", headers=h,
                     params={"status": "open", "limit": 200, "nested": "true"}, timeout=15)
    r.raise_for_status()
    out = {}
    for o in r.json():
        for c in [o] + (o.get("legs") or []):
            if c.get("symbol"):
                out.setdefault(c["symbol"], []).append(c)
    return out


def fresh_quote(sym):
    try:
        from market_quote_provider import get_best_quote
        q = get_best_quote(sym) or {}
    except Exception as e:
        return {"error": str(e)}
    now = datetime.now(timezone.utc)
    age = None
    qt = q.get("quote_timestamp")
    if qt:
        try:
            age = round((now - datetime.fromisoformat(qt)).total_seconds() / 60, 1)
        except Exception:
            pass
    q["age_min"] = age
    return q


def trailing_rec(strategy, entry, planned_stop, current_stop, price, mh):
    try:
        from strategy_trailing_policy import recommend_stop
        return recommend_stop(strategy, entry, planned_stop, current_stop, price, market_hours=mh)
    except Exception as e:
        return {"action": "error", "reason": str(e)}


def run():
    ts = datetime.now(timezone.utc).astimezone()
    conn = db(); cur = conn.cursor()
    try:
        orders = broker_open_orders(); broker_err = None
    except Exception as e:
        orders = {}; broker_err = str(e)

    # --- open positions ---
    cur.execute("""select id,symbol,strategy_id,entry_price,current_price,unrealized_pnl,
                          shares,stop_loss,planned_stop,stop_order_id,take_profit_price,target_1
                   from paper_trades where status='open' order by id""")
    positions = []
    for (pid, sym, strat, entry, cp, upnl, sh, sl, pstop, soid, tp, t1) in cur.fetchall():
        bstops = [o for o in orders.get(sym, []) if o.get("type") == "stop"]
        broker_stop = bstops[0]["stop_price"] if bstops else None
        broker_stop_id = bstops[0]["id"] if bstops else None
        if broker_stop and soid:
            prot = "PROTECTED_TRACKED"
        elif broker_stop and not soid:
            prot = "PROTECTED_UNRECORDED"   # broker stop exists, DB blind to it
        elif not broker_stop:
            prot = "NAKED"                    # genuinely no broker stop
        rec = trailing_rec(strat, float(entry) if entry else None,
                           float(pstop) if pstop else None,
                           float(sl) if sl else None,
                           float(cp) if cp else None, mh=True)
        positions.append({
            "id": pid, "symbol": sym, "strategy": strat,
            "entry": float(entry) if entry else None,
            "current_price": float(cp) if cp else None,
            "unrealized_pnl": float(upnl) if upnl else None,
            "shares": sh, "db_stop_loss": float(sl) if sl else None,
            "db_stop_order_id": soid, "db_take_profit": float(tp) if tp else None,
            "broker_stop_price": broker_stop, "broker_stop_id": broker_stop_id,
            "protection": prot, "trailing_action": rec.get("action"),
            "trailing_reason": rec.get("reason"),
        })

    # --- ELMT proposal revalidation ---
    cur.execute("""select id,symbol,strategy_id,status,action_state,proposed_entry,
                          signal_grade,created_at,expires_at
                   from paper_trade_proposals where symbol='ELMT'
                   order by created_at desc limit 1""")
    row = cur.fetchone()
    elmt = None
    if row:
        q = fresh_quote("ELMT")
        spread = None
        if q.get("ask") and q.get("bid"):
            spread = round(q["ask"] - q["bid"], 4)
        elmt = {
            "proposal_id": row[0], "status": row[3], "action_state": row[4],
            "proposed_entry": float(row[5]) if row[5] else None, "grade": row[6],
            "created_at": str(row[7]),
            "quote_last": q.get("last_price"), "quote_age_min": q.get("age_min"),
            "bid": q.get("bid"), "ask": q.get("ask"), "spread": spread,
            "fresh": (q.get("age_min") is not None and q["age_min"] <= 30),
        }
    conn.close()

    counts = {
        "open": len(positions),
        "naked": sum(1 for p in positions if p["protection"] == "NAKED"),
        "protected_unrecorded": sum(1 for p in positions if p["protection"] == "PROTECTED_UNRECORDED"),
        "protected_tracked": sum(1 for p in positions if p["protection"] == "PROTECTED_TRACKED"),
        "db_stop_order_id_missing": sum(1 for p in positions if not p["db_stop_order_id"]),
        "take_profit_missing": sum(1 for p in positions if not p["db_take_profit"]),
    }
    report = {"run_at": ts.isoformat(), "guardrails": GUARD,
              "broker_query_error": broker_err, "counts": counts,
              "positions": positions, "elmt": elmt}
    write_digest(report)
    print(json.dumps(report, indent=2, default=str))
    return report


def write_digest(r):
    c = r["counts"]; e = r.get("elmt") or {}
    lines = [
        "# PHASE 189F — Market-Open Revalidation Report (auto-generated)",
        "",
        f"**Run:** {r['run_at']} · Alpaca **paper** only · Live endpoint blocked · "
        "READ-ONLY (no orders/stops/mutations)",
        "",
        f"Broker query: {'OK' if not r['broker_query_error'] else 'ERROR: ' + r['broker_query_error']}",
        "",
        "## ELMT",
    ]
    if e:
        lines += [
            f"- proposal #{e['proposal_id']} status={e['status']} action_state={e['action_state']}",
            f"- fresh quote: {'YES' if e.get('fresh') else 'NO'} (age {e.get('quote_age_min')} min, "
            f"last {e.get('quote_last')}, bid {e.get('bid')}/ask {e.get('ask')}, spread {e.get('spread')})",
            f"- result: {'AUTO_APPROVER_ELIGIBLE (pending its own gates)' if e.get('fresh') else 'HELD_STALE'}",
        ]
    else:
        lines.append("- no live ELMT proposal row")
    lines += [
        "",
        "## Open positions",
        "",
        "| id | sym | strat | uPnL | DB stop | broker stop | stop_order_id | protection | trailing |",
        "|----|-----|-------|------|---------|-------------|---------------|------------|----------|",
    ]
    for p in r["positions"]:
        lines.append(
            f"| {p['id']} | {p['symbol']} | {p['strategy']} | {p['unrealized_pnl']} | "
            f"{p['db_stop_loss']} | {p['broker_stop_price']} | "
            f"{'yes' if p['db_stop_order_id'] else 'NO'} | {p['protection']} | {p['trailing_action']} |")
    lines += [
        "",
        f"**Counts:** open={c['open']} · naked(no broker stop)={c['naked']} · "
        f"protected-but-unrecorded={c['protected_unrecorded']} · protected+tracked={c['protected_tracked']} · "
        f"stop_order_id missing in DB={c['db_stop_order_id_missing']} · take-profit missing={c['take_profit_missing']}",
        "",
        "_Guardrails: paper-only, live endpoint blocked, Level 7 prohibited, zero mutations._",
    ]
    out = os.path.join(ROOT, "docs/atm/PHASE189F_MARKET_OPEN_REVALIDATION_REPORT.md")
    with open(out, "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    run()
