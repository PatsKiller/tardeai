#!/usr/bin/env python3
"""Phase 192I/J — Guarded paper protection adjustment (execution engine).

Applies a single approved adjustment on Alpaca **PAPER** only. Hard-guarded: paper endpoint,
fresh quote, live proposal, explicit confirm for broker writes.

Actions:
  MOVE_STOP_TO_PROFIT_LOCK / MOVE_STOP_TO_BREAKEVEN — PATCH stop (replace; stop never absent)
  ADD_FIXED_TAKE_PROFIT — POST sell limit at proposed_take_profit (keeps existing stop)
  CONVERT_TO_TRAILING_STOP — cancel fixed stop + POST native trailing_stop (trail % from env)

Audit: data/atm/protection_adjustment_audit/<date>_actions.jsonl
"""
import os, sys, json, argparse
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAPER_BASE = "https://paper-api.alpaca.markets"
QUOTE_FRESH_MIN = 30
TRAIL_PCT_MAX = 12.0
STOP_UP_ACTIONS = {"MOVE_STOP_TO_PROFIT_LOCK", "MOVE_STOP_TO_BREAKEVEN"}
ALLOWED_EXEC_ACTIONS = STOP_UP_ACTIONS | {"ADD_FIXED_TAKE_PROFIT", "CONVERT_TO_TRAILING_STOP"}
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


def _common_proposal_context(proposal_id, operator, reason, confirm, action_date):
    load_env()
    assert os.environ.get("ALPACA_MODE") == "paper", "GUARD: ALPACA_MODE must be paper"
    assert PAPER_BASE.startswith("https://paper-api."), "GUARD: paper endpoint only"
    import psycopg2.extras
    conn = db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("select * from paper_protection_adjustment_proposals where id=%s", (proposal_id,))
    p = cur.fetchone()
    result = {"date": action_date, "action_id": f"ppa-{proposal_id}-{action_date}",
              "timestamp": datetime.now(timezone.utc).isoformat(), "operator": operator,
              "proposal_id": proposal_id, "operator_reason": reason, "paper_only": True,
              "live_execution": False, "confirm_requested": confirm,
              "learning_outcome_tracking_required": True}

    def fail(reason_code, **extra):
        result.update({"status": "BLOCKED", "block_reason": reason_code, **extra})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result, None, None, None, None

    if not p:
        return fail("proposal_not_found")
    result.update({"trade_id": p["trade_id"], "symbol": p["symbol"], "action": p["action"],
                   "current_stop": p["current_stop"], "proposed_stop": p["proposed_stop"],
                   "proposed_take_profit": p.get("proposed_take_profit")})
    if p["status"] != "PROPOSED":
        return fail("proposal_not_live", proposal_status=p["status"])
    if p["action"] not in ALLOWED_EXEC_ACTIONS:
        return fail("action_not_executable_this_phase", action=p["action"])

    cur.execute("""select status, stop_order_id, take_profit_order_id, take_profit_price,
                          entry_price, shares, current_stop, strategy_id, planned_stop
                     from paper_trades where id=%s""", (p["trade_id"],))
    t = cur.fetchone()
    if not t or t["status"] != "open":
        return fail("trade_not_open")

    age, q = fresh_quote_age(p["symbol"])
    result["quote_age_min"] = age
    result["quote_price"] = q.get("last_price")
    if age is None or age > QUOTE_FRESH_MIN:
        return fail("quote_stale", quote_age_min=age)

    result.update({
        "profit_locked_before": p["profit_locked_before"],
        "profit_locked_after": p["profit_locked_after"],
        "giveback_before": p["giveback_before"],
        "giveback_after": p["giveback_after"],
        "tradeai_recommendation": p["tradeai_reason"],
        "hermes_recommendation": p["hermes_reason"],
        "advisory_refs": p["evidence_refs"],
    })
    return result, conn, p, t, q


def _apply_stop_up(result, conn, p, t, q, proposal_id, confirm):
    import requests
    stop_oid = t["stop_order_id"]
    if not stop_oid:
        result.update({"status": "BLOCKED", "block_reason": "no_tracked_broker_stop"})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result

    r = requests.get(f"{PAPER_BASE}/v2/orders/{stop_oid}", headers=_headers(), timeout=15)
    if r.status_code != 200:
        result.update({"status": "BLOCKED", "block_reason": "broker_stop_fetch_failed", "http": r.status_code})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result
    broker = r.json()
    result["broker_order_before"] = {"id": broker.get("id"), "stop_price": broker.get("stop_price"),
                                     "status": broker.get("status"), "qty": broker.get("qty")}
    if broker.get("status") not in ("new", "held", "accepted"):
        result.update({"status": "BLOCKED", "block_reason": "broker_stop_not_active",
                       "broker_status": broker.get("status")})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result
    try:
        broker_stop = float(broker.get("stop_price"))
    except Exception:
        result.update({"status": "BLOCKED", "block_reason": "broker_stop_price_unreadable"})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result
    if abs(broker_stop - float(p["current_stop"])) > 0.01:
        result.update({"status": "BLOCKED", "block_reason": "broker_stop_state_mismatch",
                       "broker_stop": broker_stop, "expected": float(p["current_stop"])})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result

    new_stop = float(p["proposed_stop"]) if p["proposed_stop"] is not None else None
    if new_stop is None:
        result.update({"status": "BLOCKED", "block_reason": "no_proposed_stop"})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result
    if new_stop <= broker_stop:
        result.update({"status": "BLOCKED", "block_reason": "would_not_raise_stop",
                       "new_stop": new_stop, "broker_stop": broker_stop})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result
    if new_stop >= float(q.get("last_price", 1e18)):
        result.update({"status": "BLOCKED", "block_reason": "proposed_stop_above_price",
                       "new_stop": new_stop, "price": q.get("last_price")})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result

    result["proposed_stop_final"] = new_stop
    if not confirm:
        result.update({"status": "DRY_RUN_PREVIEW",
                       "note": "All guards PASSED. Re-run with --confirm to modify the paper stop order."})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result

    patch = requests.patch(f"{PAPER_BASE}/v2/orders/{stop_oid}",
                           headers=_headers(), json={"stop_price": str(round(new_stop, 2))}, timeout=20)
    if patch.status_code not in (200, 201):
        result.update({"status": "BLOCKED", "block_reason": "broker_replace_failed",
                       "http": patch.status_code, "body": patch.text[:200]})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result
    after = patch.json()
    new_oid = after.get("id", stop_oid)
    result["broker_order_after"] = {"id": new_oid, "stop_price": after.get("stop_price"),
                                    "status": after.get("status")}
    result["alpaca_response_id"] = new_oid
    wc = conn.cursor()
    wc.execute("""update paper_trades set stop_order_id=%s, current_stop=%s, stop_loss=%s,
                  planned_stop=coalesce(planned_stop,%s), stop_verified_at=now(),
                  stop_verified_source='operator_approved_adjustment',
                  protection_status='PROTECTED_TRACKED' where id=%s""",
               (new_oid, round(new_stop, 2), round(new_stop, 2), round(new_stop, 2), p["trade_id"]))
    wc.execute("update paper_protection_adjustment_proposals set status='APPLIED' where id=%s", (proposal_id,))
    conn.commit()
    result.update({"status": "APPLIED", "new_stop": round(new_stop, 2)})
    audit(result)
    conn.close()
    print(json.dumps(result, indent=2, default=str))
    return result


def _apply_take_profit(result, conn, p, t, q, proposal_id, confirm):
    import requests
    if t.get("take_profit_order_id") or t.get("take_profit_price"):
        result.update({"status": "BLOCKED", "block_reason": "take_profit_already_present"})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result
    tp = p.get("proposed_take_profit")
    if tp is None:
        result.update({"status": "BLOCKED", "block_reason": "no_proposed_take_profit"})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result
    tp_px = round(float(tp), 2)
    last = float(q.get("last_price") or 0)
    if last <= 0 or tp_px <= last:
        result.update({"status": "BLOCKED", "block_reason": "take_profit_not_above_price",
                       "proposed_take_profit": tp_px, "price": last})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result
    shares = int(t.get("shares") or 0)
    if shares <= 0:
        result.update({"status": "BLOCKED", "block_reason": "invalid_share_qty"})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result

    # Pre-flight available-qty guard. A standalone take-profit sell can only use shares NOT already committed
    # to another exit order. When the existing protective stop holds all shares (qty_available == 0), Alpaca
    # rejects a separate TP limit with 403 "insufficient qty available" — and because the failure path leaves
    # the proposal status='PROPOSED', the ATM pass re-submitted it every run (the AGNC BLOCKED retry loop).
    # Placing a take-profit here would require an OCO conversion (cancel the standalone stop → replace with a
    # stop+limit OCO), which we do NOT do automatically: it would momentarily leave the position unprotected,
    # violating the engine's "stop never absent" invariant. So skip the doomed order and (when applying) mark
    # the proposal terminal (NOT_APPLICABLE) so it is not retried; surface it for operator OCO review.
    avail = shares
    try:
        posr = requests.get(f"{PAPER_BASE}/v2/positions/{p['symbol']}", headers=_headers(), timeout=20)
        if posr.status_code == 200:
            avail = int(float((posr.json() or {}).get("qty_available")))
    except Exception:
        avail = shares
    if avail < shares:
        result.update({"status": "NOT_APPLICABLE", "block_reason": "shares_held_by_existing_stop",
                       "qty_available": avail, "shares": shares,
                       "advisory": "All shares already held by the existing protective stop; a separate take-"
                                   "profit limit is not placeable (would require an OCO conversion — operator "
                                   "review). Auto-apply skipped; proposal marked terminal so it is not retried."})
        if confirm:
            wc = conn.cursor()
            wc.execute("update paper_protection_adjustment_proposals set status='NOT_APPLICABLE' where id=%s",
                       (proposal_id,))
            conn.commit()
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result

    result["proposed_take_profit_final"] = tp_px
    if not confirm:
        result.update({"status": "DRY_RUN_PREVIEW",
                       "note": "All guards PASSED. Re-run with --confirm to place take-profit limit."})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result

    post = requests.post(f"{PAPER_BASE}/v2/orders", headers=_headers(), timeout=20, json={
        "symbol": p["symbol"], "qty": str(shares), "side": "sell",
        "type": "limit", "limit_price": str(tp_px), "time_in_force": "gtc",
    })
    if post.status_code not in (200, 201):
        result.update({"status": "BLOCKED", "block_reason": "broker_take_profit_failed",
                       "http": post.status_code, "body": post.text[:200]})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result
    order = post.json()
    tp_oid = order.get("id")
    result["broker_order_after"] = {"id": tp_oid, "limit_price": order.get("limit_price"),
                                    "status": order.get("status"), "type": order.get("type")}
    wc = conn.cursor()
    wc.execute("""update paper_trades set take_profit_order_id=%s, take_profit_price=%s,
                  profit_protection_status='has_take_profit', protection_status='PROTECTED_TRACKED'
                  where id=%s""", (tp_oid, tp_px, p["trade_id"]))
    wc.execute("update paper_protection_adjustment_proposals set status='APPLIED' where id=%s", (proposal_id,))
    conn.commit()
    result.update({"status": "APPLIED", "take_profit_price": tp_px, "take_profit_order_id": tp_oid})
    audit(result)
    conn.close()
    print(json.dumps(result, indent=2, default=str))
    return result


def _apply_trailing(result, conn, p, t, q, proposal_id, confirm):
    import requests
    stop_oid = t["stop_order_id"]
    if not stop_oid:
        result.update({"status": "BLOCKED", "block_reason": "no_tracked_broker_stop"})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result
    from protection_trail_calculator import resolve_trail_percent_for_apply
    stored_trail = None
    refs = p.get("evidence_refs")
    if isinstance(refs, str):
        try:
            refs = json.loads(refs)
        except Exception:
            refs = None
    if isinstance(refs, dict):
        stored_trail = refs.get("trail")
    last_px = float(q.get("last_price") or q.get("last") or 0)
    trail_res = resolve_trail_percent_for_apply(
        stored_trail,
        t.get("strategy_id"),
        p["symbol"],
        float(t["entry_price"]) if t.get("entry_price") else None,
        float(t["planned_stop"]) if t.get("planned_stop") else None,
        last_px if last_px > 0 else None,
        float(t["current_stop"]) if t.get("current_stop") else None,
    )
    result["trail_resolution"] = {k: trail_res.get(k) for k in (
        "trail_method", "trail_family", "r_multiple", "r_threshold", "trail_source",
        "stored_drift_pct", "reason", "atr14", "atr_pct", "family_base_pct", "atr_component_pct",
    ) if k in trail_res}
    if not trail_res.get("eligible"):
        result.update({"status": "BLOCKED", "block_reason": "trail_not_eligible",
                       "detail": trail_res.get("reason")})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result
    try:
        trail_pct = float(trail_res["trail_percent"])
    except (KeyError, TypeError, ValueError):
        result.update({"status": "BLOCKED", "block_reason": "invalid_trail_percent"})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result
    if trail_pct <= 0 or trail_pct > TRAIL_PCT_MAX:
        result.update({"status": "BLOCKED", "block_reason": "invalid_trail_percent", "trail_percent": trail_pct})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result
    shares = int(t.get("shares") or 0)
    if shares <= 0:
        result.update({"status": "BLOCKED", "block_reason": "invalid_share_qty"})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result

    r = requests.get(f"{PAPER_BASE}/v2/orders/{stop_oid}", headers=_headers(), timeout=15)
    if r.status_code != 200:
        result.update({"status": "BLOCKED", "block_reason": "broker_stop_fetch_failed", "http": r.status_code})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result
    broker = r.json()
    result["broker_order_before"] = {"id": broker.get("id"), "stop_price": broker.get("stop_price"),
                                     "status": broker.get("status"), "type": broker.get("type")}
    if broker.get("status") not in ("new", "held", "accepted"):
        result.update({"status": "BLOCKED", "block_reason": "broker_stop_not_active",
                       "broker_status": broker.get("status")})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result
    if broker.get("type") == "trailing_stop":
        result.update({"status": "BLOCKED", "block_reason": "already_trailing_stop"})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result

    result["trail_percent"] = trail_pct
    if not confirm:
        result.update({"status": "DRY_RUN_PREVIEW",
                       "note": "All guards PASSED. Re-run with --confirm to convert to trailing stop."})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result

    cancel = requests.delete(f"{PAPER_BASE}/v2/orders/{stop_oid}", headers=_headers(), timeout=20)
    if cancel.status_code not in (200, 204):
        result.update({"status": "BLOCKED", "block_reason": "broker_stop_cancel_failed",
                       "http": cancel.status_code, "body": (cancel.text or "")[:200]})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result

    post = requests.post(f"{PAPER_BASE}/v2/orders", headers=_headers(), timeout=20, json={
        "symbol": p["symbol"], "qty": str(shares), "side": "sell",
        "type": "trailing_stop", "trail_percent": str(trail_pct), "time_in_force": "gtc",
    })
    if post.status_code not in (200, 201):
        result.update({"status": "BLOCKED", "block_reason": "broker_trailing_post_failed",
                       "http": post.status_code, "body": post.text[:200],
                       "critical": "fixed_stop_cancelled_trailing_failed"})
        audit(result)
        conn.close()
        print(json.dumps(result, indent=2, default=str))
        return result
    order = post.json()
    new_oid = order.get("id")
    result["broker_order_after"] = {"id": new_oid, "type": order.get("type"),
                                    "trail_percent": order.get("trail_percent"),
                                    "status": order.get("status")}
    wc = conn.cursor()
    wc.execute("""update paper_trades set stop_order_id=%s, decision_state='TRAILING_STOP_ACTIVE',
                  stop_verified_at=now(), stop_verified_source='operator_approved_adjustment',
                  protection_status='PROTECTED_TRACKED' where id=%s""",
               (new_oid, p["trade_id"]))
    wc.execute("update paper_protection_adjustment_proposals set status='APPLIED' where id=%s", (proposal_id,))
    conn.commit()
    result.update({"status": "APPLIED", "trailing_order_id": new_oid, "trail_percent": trail_pct})
    audit(result)
    conn.close()
    print(json.dumps(result, indent=2, default=str))
    return result


def apply(proposal_id, operator, reason, confirm=False, action_date="latest"):
    ctx = _common_proposal_context(proposal_id, operator, reason, confirm, action_date)
    if ctx[1] is None:
        return ctx[0]
    result, conn, p, t, q = ctx
    action = (p["action"] or "").upper()
    if action in STOP_UP_ACTIONS:
        return _apply_stop_up(result, conn, p, t, q, proposal_id, confirm)
    if action == "ADD_FIXED_TAKE_PROFIT":
        return _apply_take_profit(result, conn, p, t, q, proposal_id, confirm)
    if action == "CONVERT_TO_TRAILING_STOP":
        return _apply_trailing(result, conn, p, t, q, proposal_id, confirm)
    result.update({"status": "BLOCKED", "block_reason": "unknown_action", "action": action})
    audit(result)
    conn.close()
    print(json.dumps(result, indent=2, default=str))
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--proposal-id", type=int, required=True)
    ap.add_argument("--operator", default="operator")
    ap.add_argument("--reason", default="")
    ap.add_argument("--confirm", action="store_true", help="actually modify broker orders")
    ap.add_argument("--date", default="latest")
    a = ap.parse_args()
    apply(a.proposal_id, a.operator, a.reason, confirm=a.confirm, action_date=a.date)