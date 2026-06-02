#!/usr/bin/env python3
"""Phase 192I/J — Guarded operator-approved paper protection adjustment (execution engine).

Applies a single approved adjustment to an Alpaca **PAPER** stop order. Hard-guarded:
PAPER ONLY, live endpoint refused, quote must be fresh, proposal must be live, broker
stop must match expected state, the move must NOT increase risk (stop up only), and an
explicit --confirm is required to touch the broker. Default is DRY-RUN (preview only).

Every call writes an audit record (before + after) to
  data/atm/protection_adjustment_audit/<date>_actions.jsonl

Allowed actions this phase: MOVE_STOP_TO_PROFIT_LOCK, MOVE_STOP_TO_BREAKEVEN (stop-up only,
via Alpaca order REPLACE so the stop is never absent). Others are preview/blocked.
"""
import os, sys, json, argparse
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAPER_BASE = "https://paper-api.alpaca.markets"
QUOTE_FRESH_MIN = 30
ALLOWED_EXEC_ACTIONS = {"MOVE_STOP_TO_PROFIT_LOCK", "MOVE_STOP_TO_BREAKEVEN"}
AUDIT_DIR = os.path.join(ROOT, "data/atm/protection_adjustment_audit")


def load_env():
    for line in open(os.path.join(ROOT, ".env")):
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def db():
    import psycopg2, psycopg2.extras
    return psycopg2.connect(host=os.environ["DB_HOST"], port=os.environ["DB_PORT"],
                            dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                            password=os.environ["DB_PASSWORD"])


def _headers():
    return {"APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
            "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"]}


def audit(rec):
    os.makedirs(AUDIT_DIR, exist_ok=True)
    f = os.path.join(AUDIT_DIR, f"{rec.get('date','latest')}_actions.jsonl")
    with open(f, "a") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")
    return f


def fresh_quote_age(sym):
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from market_quote_provider import get_best_quote
    q = get_best_quote(sym) or {}
    qt = q.get("quote_timestamp")
    if not qt:
        return None, q
    try:
        return round((datetime.now(timezone.utc) - datetime.fromisoformat(qt)).total_seconds() / 60, 1), q
    except Exception:
        return None, q


def apply(proposal_id, operator, reason, confirm=False, action_date="latest"):
    load_env()
    assert os.environ.get("ALPACA_MODE") == "paper", "GUARD: ALPACA_MODE must be paper"
    assert PAPER_BASE.startswith("https://paper-api."), "GUARD: paper endpoint only"
    import requests
    import psycopg2.extras
    conn = db(); cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("select * from paper_protection_adjustment_proposals where id=%s", (proposal_id,))
    p = cur.fetchone()
    result = {"date": action_date, "action_id": f"ppa-{proposal_id}-{action_date}",
              "timestamp": datetime.now(timezone.utc).isoformat(), "operator": operator,
              "proposal_id": proposal_id, "operator_reason": reason, "paper_only": True,
              "live_execution": False, "confirm_requested": confirm,
              "learning_outcome_tracking_required": True}

    def fail(reason_code, **extra):
        result.update({"status": "BLOCKED", "block_reason": reason_code, **extra})
        audit(result); conn.close()
        print(json.dumps(result, indent=2, default=str)); return result

    if not p:
        return fail("proposal_not_found")
    result.update({"trade_id": p["trade_id"], "symbol": p["symbol"], "action": p["action"],
                   "current_stop": p["current_stop"], "proposed_stop": p["proposed_stop"]})
    if p["status"] != "PROPOSED":
        return fail("proposal_not_live", proposal_status=p["status"])
    if p["action"] not in ALLOWED_EXEC_ACTIONS:
        return fail("action_not_executable_this_phase", action=p["action"])

    # trade still open?
    cur.execute("select status, stop_order_id, entry_price, shares from paper_trades where id=%s", (p["trade_id"],))
    t = cur.fetchone()
    if not t or t["status"] != "open":
        return fail("trade_not_open")
    stop_oid = t["stop_order_id"]
    if not stop_oid:
        return fail("no_tracked_broker_stop")

    # quote fresh?
    age, q = fresh_quote_age(p["symbol"])
    result["quote_age_min"] = age; result["quote_price"] = q.get("last_price")
    if age is None or age > QUOTE_FRESH_MIN:
        return fail("quote_stale", quote_age_min=age)

    # broker stop matches expected state?
    r = requests.get(f"{PAPER_BASE}/v2/orders/{stop_oid}", headers=_headers(), timeout=15)
    if r.status_code != 200:
        return fail("broker_stop_fetch_failed", http=r.status_code)
    broker = r.json()
    result["broker_order_before"] = {"id": broker.get("id"), "stop_price": broker.get("stop_price"),
                                     "status": broker.get("status"), "qty": broker.get("qty")}
    if broker.get("status") not in ("new", "held", "accepted"):
        return fail("broker_stop_not_active", broker_status=broker.get("status"))
    try:
        broker_stop = float(broker.get("stop_price"))
    except Exception:
        return fail("broker_stop_price_unreadable")
    if abs(broker_stop - float(p["current_stop"])) > 0.01:
        return fail("broker_stop_state_mismatch", broker_stop=broker_stop, expected=float(p["current_stop"]))

    # risk guard: move stop UP only (never increase risk)
    new_stop = float(p["proposed_stop"]) if p["proposed_stop"] is not None else None
    if new_stop is None:
        return fail("no_proposed_stop")
    if new_stop <= broker_stop:
        return fail("would_not_raise_stop", new_stop=new_stop, broker_stop=broker_stop)
    if new_stop >= float(q.get("last_price", 1e18)):
        return fail("proposed_stop_above_price", new_stop=new_stop, price=q.get("last_price"))

    result.update({"proposed_stop_final": new_stop,
                   "profit_locked_before": p["profit_locked_before"],
                   "profit_locked_after": p["profit_locked_after"],
                   "giveback_before": p["giveback_before"], "giveback_after": p["giveback_after"],
                   "tradeai_recommendation": p["tradeai_reason"], "hermes_recommendation": p["hermes_reason"],
                   "advisory_refs": p["evidence_refs"]})

    if not confirm:
        result.update({"status": "DRY_RUN_PREVIEW",
                       "note": "All guards PASSED. Re-run with --confirm to modify the paper stop order."})
        audit(result); conn.close()
        print(json.dumps(result, indent=2, default=str)); return result

    # ---- CONFIRMED: replace the paper stop order (stop never absent) ----
    patch = requests.patch(f"{PAPER_BASE}/v2/orders/{stop_oid}",
                           headers=_headers(), json={"stop_price": str(round(new_stop, 2))}, timeout=20)
    if patch.status_code not in (200, 201):
        return fail("broker_replace_failed", http=patch.status_code, body=patch.text[:200])
    after = patch.json()
    new_oid = after.get("id", stop_oid)
    result["broker_order_after"] = {"id": new_oid, "stop_price": after.get("stop_price"),
                                    "status": after.get("status")}
    result["alpaca_response_id"] = new_oid
    # persist new stop metadata (paper_trades) + proposal status
    wc = conn.cursor()
    wc.execute("""update paper_trades set stop_order_id=%s, current_stop=%s, stop_loss=%s,
                  planned_stop=coalesce(planned_stop,%s), stop_verified_at=now(),
                  stop_verified_source='operator_approved_adjustment',
                  protection_status='PROTECTED_TRACKED' where id=%s""",
               (new_oid, round(new_stop, 2), round(new_stop, 2), round(new_stop, 2), p["trade_id"]))
    wc.execute("update paper_protection_adjustment_proposals set status='APPLIED' where id=%s", (proposal_id,))
    conn.commit()
    result.update({"status": "APPLIED", "new_stop": round(new_stop, 2)})
    audit(result); conn.close()
    print(json.dumps(result, indent=2, default=str)); return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposal-id", type=int, required=True)
    ap.add_argument("--operator", default="operator")
    ap.add_argument("--reason", default="")
    ap.add_argument("--confirm", action="store_true", help="actually modify the paper stop order")
    ap.add_argument("--date", default="latest")
    a = ap.parse_args()
    apply(a.proposal_id, a.operator, a.reason, confirm=a.confirm, action_date=a.date)
