#!/usr/bin/env python3
"""Alpaca Automatic Stop Manager (Stage 2c) — AUTOMATIC, R:R-maximizing stop movement for the PAPER account.

Operator: "for alpaca stop management is automatic … it should move stops / trailing stops based on stop
management to get most R:R possible" + "it's manual for all other accounts." So Schwab (taxable + the 2
IRAs) stays manual + per-order 2FA; ONLY the Alpaca paper account is auto-managed here.

For every open paper position it asks the strategy-aware trailing policy (strategy_trailing_policy.
recommend_stop — R-multiple tiers + optional structural overlay) for the R:R-optimal stop, then RATCHETS
the live Alpaca stop UP to that level (cancel + re-place). RATCHET-ONLY: a stop is never lowered, so locked
risk only improves. Automatic (no 2FA — paper), audited, and SIEM-logged. This is the paper analogue of the
Schwab Modify flow; it respects Hard Rule 7 (the paper pipeline owns paper execution — we use the Alpaca
paper API directly, never the Schwab guard).

  python3 scripts/alpaca_stop_manager.py            # DRY-RUN (prints the plan)
  python3 scripts/alpaca_stop_manager.py --apply     # execute the ratchets
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

_MIN_RAISE_PCT = 0.25   # ignore sub-0.25% nudges (avoid churn / fee-less but pointless order replacement)


def _f(v):
    try:
        return float(v)
    except Exception:
        return None


def _alpaca_req(env, path, method="GET", body=None):
    base = env.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{base}{path}", data=data, method=method,
                                 headers={"APCA-API-KEY-ID": env.get("ALPACA_API_KEY", ""),
                                          "APCA-API-SECRET-KEY": env.get("ALPACA_SECRET_KEY", ""),
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def _audit(symbol, action, detail):
    try:
        from alert_event_writer import save_alert_event
        save_alert_event(alert_type="strategic_alert", severity="info",
                         source_script="alpaca_stop_manager", symbol=symbol,
                         raw_text=f"[alpaca-stop-mgr] {action} · {symbol} · {detail}",
                         parsed_payload={"kind": "alpaca_stop_manager", "action": action, "symbol": symbol, "detail": detail})
    except Exception:
        pass


# ── P1: OCO brackets (stop + take-profit on the same shares) — Alpaca paper, auto ──────────────────────
# A standalone take-profit on a fully-stopped position 403s ("insufficient qty available" — all shares are
# held_for_orders by the stop). The only structure that holds a stop AND a take-profit on the same shares is
# a One-Cancels-Other (OCO) sell order. convert_to_oco replaces the standalone stop with an OCO; if the OCO
# POST fails it re-places the standalone stop (rollback) so the position is never left naked.
# Design: docs/design/OCO_ATM_UNIFICATION_DESIGN.md (P1).

def _ensure_oco_columns(conn):
    # ALTER needs an ACCESS EXCLUSIVE lock; with the dashboard server holding a long-lived connection on
    # paper_trades, an unbounded ALTER can block the whole run. Use a short lock_timeout and tolerate failure
    # (the convert UPDATE degrades gracefully if a column is briefly absent). ADD COLUMN IF NOT EXISTS with a
    # NULL default is metadata-only in PG11+ — once the columns exist this is a no-op.
    try:
        cur = conn.cursor()
        cur.execute("SET lock_timeout='4s'")
        cur.execute("ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS oco_group_id text")
        cur.execute("ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS bracket_state text")
        conn.commit()
    except Exception:
        conn.rollback()


def _place_simple_stop(env, symbol, qty, stop_price):
    return _alpaca_req(env, "/v2/orders", method="POST", body={
        "symbol": symbol, "qty": int(qty), "side": "sell", "type": "stop",
        "stop_price": str(round(float(stop_price), 2)), "time_in_force": "gtc"})


def convert_to_oco(env, symbol, qty, stop_price, take_profit_price, old_stop_id, conn=None):
    """Replace a standalone SELL stop with a SELL OCO (stop + take-profit) on the same shares.

    Stop-never-absent: cancel the old stop (frees the shares), place the OCO; if the OCO POST fails, re-place
    the standalone stop so the position is never naked. Returns a result dict (status: OCO_ACTIVE / ROLLED_BACK
    / BLOCKED / CRITICAL).
    """
    symbol = str(symbol).upper(); qty = int(qty)
    sp = round(float(stop_price), 2); tp = round(float(take_profit_price), 2)
    res = {"symbol": symbol, "qty": qty, "stop": sp, "take_profit": tp}
    if not (qty > 0 and tp > sp):
        res.update({"status": "BLOCKED", "reason": f"invalid OCO params (need qty>0 and tp>{sp}, got tp={tp})"})
        return res
    # 1. cancel the existing standalone stop (frees the shares). If cancel fails, leave the stop intact.
    if old_stop_id:
        try:
            _alpaca_req(env, f"/v2/orders/{old_stop_id}", method="DELETE")
        except Exception as e:
            res.update({"status": "BLOCKED", "reason": f"cancel_failed: {str(e)[:80]} — stop left intact, no change"})
            return res
    # 2. place the OCO (same proven shape as the bracket exit pair in alpaca_paper_adapter.submit_entry)
    try:
        oco = _alpaca_req(env, "/v2/orders", method="POST", body={
            "symbol": symbol, "qty": qty, "side": "sell", "type": "limit", "time_in_force": "gtc",
            "order_class": "oco",
            "take_profit": {"limit_price": str(tp)}, "stop_loss": {"stop_price": str(sp)}})
    except Exception as e:
        # 3. ROLLBACK — re-place the standalone stop so the position is never naked
        try:
            rb = _place_simple_stop(env, symbol, qty, sp)
        except Exception as e2:
            res.update({"status": "CRITICAL", "naked": True,
                        "reason": f"oco_failed AND stop_replace_failed: {str(e)[:60]} / {str(e2)[:60]}"})
            _audit(symbol, "OCO_ROLLBACK_FAILED", res["reason"])
            return res
        new_stop_id = str((rb or {}).get("id") or "")
        if conn is not None:
            try:
                cur = conn.cursor()
                cur.execute("UPDATE paper_trades SET stop_order_id=%s, updated_at=NOW() "
                            "WHERE (lifecycle_state='open' OR status='open') AND symbol=%s", (new_stop_id, symbol))
                conn.commit()
            except Exception:
                conn.rollback()
        res.update({"status": "ROLLED_BACK", "stop_order_id": new_stop_id,
                    "reason": f"oco_failed: {str(e)[:100]} — standalone stop re-placed (protected)"})
        _audit(symbol, "OCO_ROLLBACK", res["reason"])
        return res
    # 4. success — classify the two legs (parent + legs[]) into stop vs take-profit
    all_orders = [oco] + (oco.get("legs") or [])
    stop_leg = next((o for o in all_orders if "stop" in str(o.get("type", "")).lower()), None)
    tp_leg = next((o for o in all_orders if str(o.get("type", "")).lower() == "limit"), None)
    stop_id = str((stop_leg or {}).get("id") or "")
    tp_id = str((tp_leg or {}).get("id") or "")
    group_id = str(oco.get("id") or "")
    if conn is not None:
        try:
            cur = conn.cursor()
            cur.execute("""UPDATE paper_trades SET stop_order_id=%s, take_profit_order_id=%s, take_profit_price=%s,
                           oco_group_id=%s, bracket_state='OCO_ACTIVE',
                           profit_protection_status='has_take_profit', protection_status='PROTECTED_TRACKED',
                           updated_at=NOW()
                           WHERE (lifecycle_state='open' OR status='open') AND symbol=%s""",
                        (stop_id or old_stop_id, tp_id, tp, group_id, symbol))
            conn.commit()
        except Exception:
            conn.rollback()
    res.update({"status": "OCO_ACTIVE", "oco_group_id": group_id, "stop_order_id": stop_id, "take_profit_order_id": tp_id})
    _audit(symbol, "CONVERT_TO_OCO", f"stop ${sp} + take-profit ${tp} qty {qty} group {group_id}")
    return res


def run_oco_retrofit(apply: bool = False) -> dict:
    """Retrofit open paper positions that have a standalone stop but no take-profit into an OCO bracket.
    DRY-RUN by default; --apply executes. Take-profit source = take_profit_price else strategy target_1.
    Skips positions already on an OCO / with a take-profit, with no standalone stop, or whose take-profit
    would not sit above both the stop and the current price."""
    import alpaca_paper_reconciler as apr
    from db_adapter import _get_conn
    env = apr.get_env()
    orders = apr.get_alpaca_orders(env, status="open") or []
    live_stops, has_oco = {}, set()
    for o in orders:
        sym = str(o.get("symbol", "")).upper()
        oc = str(o.get("order_class", "") or "simple").lower()
        if oc == "oco":
            has_oco.add(sym)
        if (str(o.get("side", "")).lower() == "sell" and "stop" in str(o.get("type", "")).lower()
                and oc in ("simple", "")):
            live_stops[sym] = {"id": str(o.get("id")), "stop": _f(o.get("stop_price")), "qty": _f(o.get("qty"))}
    conn = _get_conn()
    if apply:
        _ensure_oco_columns(conn)   # DDL only on apply; dry-run stays read-only (never blocks behind the server)
    cur = conn.cursor()
    cur.execute("""SELECT symbol, shares, COALESCE(stop_loss_price, stop_loss) AS stop, current_price,
                          COALESCE(take_profit_price, target_1) AS tp, take_profit_order_id, strategy_id
                   FROM paper_trades WHERE lifecycle_state='open' OR status='open'""")
    report = {"mode": "APPLIED" if apply else "DRY-RUN", "considered": 0, "converted": 0, "errors": 0,
              "actions": [], "skipped": []}
    for sym, sh, stop, cur_px, tp, tp_oid, strat in cur.fetchall():
        sym = str(sym).upper(); report["considered"] += 1
        if sym in has_oco or tp_oid:
            report["skipped"].append({"symbol": sym, "reason": "already has take-profit / OCO"}); continue
        lv = live_stops.get(sym)
        if not lv:
            report["skipped"].append({"symbol": sym, "reason": "no standalone live stop to convert"}); continue
        stop_px = lv["stop"] if lv.get("stop") is not None else _f(stop)
        qty = int(lv["qty"]) if lv.get("qty") else int(sh or 0)
        tp_px, cur_pxf = _f(tp), _f(cur_px)
        if not (tp_px and stop_px and tp_px > stop_px):
            report["skipped"].append({"symbol": sym, "reason": f"no valid take-profit (tp={tp_px}, stop={stop_px})"}); continue
        if cur_pxf and tp_px <= cur_pxf:
            report["skipped"].append({"symbol": sym, "reason": f"take-profit {tp_px} <= current {cur_pxf} — would fill instantly"}); continue
        action = {"symbol": sym, "qty": qty, "keep_stop": round(stop_px, 2), "add_take_profit": round(tp_px, 2),
                  "strategy": strat, "old_stop_id": lv["id"]}
        if apply:
            r = convert_to_oco(env, sym, qty, stop_px, tp_px, lv["id"], conn=conn)
            action["result"] = r
            if r.get("status") == "OCO_ACTIVE":
                report["converted"] += 1
            else:
                report["errors"] += 1
        else:
            action["status"] = "would_convert_to_oco"
        report["actions"].append(action)
    return report


def run(apply: bool = False) -> dict:
    import alpaca_paper_reconciler as apr
    import strategy_trailing_policy as stp
    from db_adapter import _get_conn

    env = apr.get_env()
    # live Alpaca SELL stops (source of truth for the current stop price + order id)
    live = {}
    try:
        for o in (apr.get_alpaca_orders(env, status="open") or []):
            if str(o.get("side", "")).lower() == "sell" and "stop" in str(o.get("type", "")).lower():
                live[str(o.get("symbol", "")).upper()] = {"id": str(o.get("id")), "stop": _f(o.get("stop_price")),
                                                          "qty": _f(o.get("qty")), "type": o.get("type")}
    except Exception as e:
        return {"error": f"alpaca read failed: {str(e)[:100]}", "actions": []}

    conn = _get_conn(); cur = conn.cursor()
    # COALESCE so a position with only stop_loss set (older entries — the SNOW-era skip bug) is still
    # managed instead of silently held forever (fix 2026-06-19).
    # bracket_state may not exist on very old schemas — COALESCE via a LEFT-safe expression
    cur.execute("""SELECT symbol, entry_price, COALESCE(stop_loss_price, stop_loss) AS planned_stop,
                          strategy_id, shares, current_price, stop_order_id,
                          COALESCE(bracket_state, '') AS bracket_state
                   FROM paper_trades WHERE lifecycle_state='open' OR status='open'""")
    rows = cur.fetchall()
    market_hours = True
    report = {"mode": "APPLIED" if apply else "DRY-RUN", "considered": len(rows), "actions": [], "held": 0,
              "errors": 0, "oco_skipped": 0}

    for sym, entry, planned, strat, shares, cur_px, stop_oid, bracket_state in rows:
        sym = str(sym).upper()
        # OCO-managed positions: a standalone cancel+replace would cancel the OCO's stop leg and orphan the
        # take-profit. The OCO stop leg is 'held' (not in status=open) so it can't be ratcheted the simple
        # way. Skip here — in-place OCO leg-ratchet (PATCH the held stop leg) is the P1 follow-up increment.
        if str(bracket_state or "").upper() == "OCO_ACTIVE":
            report["oco_skipped"] += 1
            continue
        entry, planned, cur_px = _f(entry), _f(planned), _f(cur_px)
        lv = live.get(sym)
        current_stop = (lv["stop"] if lv and lv.get("stop") is not None else planned)
        if not (entry and planned and cur_px and current_stop):
            continue
        rec = stp.recommend_stop(strat or "unknown", entry, planned, current_stop, cur_px,
                                 market_hours=market_hours, symbol=sym)
        new_stop = _f(rec.get("recommended_stop"))
        # RATCHET-ONLY: act only when the policy raises the stop by a meaningful amount
        if rec.get("action") != "recommend_trail" or not new_stop or new_stop <= current_stop:
            report["held"] += 1
            continue
        if (new_stop - current_stop) / cur_px * 100 < _MIN_RAISE_PCT:
            report["held"] += 1
            continue
        # never place a stop at/above current price (would stop out immediately)
        if new_stop >= cur_px:
            report["held"] += 1
            continue
        plan = {"symbol": sym, "from_stop": round(current_stop, 2), "to_stop": round(new_stop, 2),
                "current_price": cur_px, "r_multiple": rec.get("r_multiple"), "family": rec.get("family"),
                "reason": rec.get("reason"), "old_order_id": (lv["id"] if lv else stop_oid)}
        if apply:
            try:
                old_id = lv["id"] if lv else stop_oid
                qty = int(lv["qty"]) if (lv and lv.get("qty")) else int(shares)
                if old_id:
                    try:
                        _alpaca_req(env, f"/v2/orders/{old_id}", method="DELETE")
                    except Exception:
                        pass   # already gone / filled — re-place anyway is unsafe, so guard below
                resp = _alpaca_req(env, "/v2/orders", method="POST", body={
                    "symbol": sym, "qty": qty, "side": "sell", "type": "stop",
                    "stop_price": str(round(new_stop, 2)), "time_in_force": "gtc"})
                new_id = str(resp.get("id") or "")
                # Keep EVERY stop column in sync (fix 2026-06-19): the ratchet previously updated only
                # stop_loss_price, so stop_loss / current_stop and the trailing flags went stale — readers
                # (journal, scale engine, card trailing-state) saw the OLD stop and trailing_active stayed
                # NULL (the SNOW symptom). Now stamp the trailing state on every ratchet.
                cur.execute("UPDATE paper_trades SET stop_loss_price=%s, stop_loss=%s, current_stop=%s, "
                            "stop_type='trailing', trailing_active=TRUE, stop_order_id=%s, "
                            "stop_updated_at=NOW(), updated_at=NOW() "
                            "WHERE (lifecycle_state='open' OR status='open') AND symbol=%s",
                            (round(new_stop, 2), round(new_stop, 2), round(new_stop, 2), new_id, sym))
                conn.commit()
                plan["new_order_id"] = new_id
                plan["status"] = "ratcheted"
                _audit(sym, "RATCHET", f"${plan['from_stop']}→${plan['to_stop']} (R={rec.get('r_multiple')}, {rec.get('family')}) #{new_id}")
            except Exception as e:
                conn.rollback()
                plan["status"] = f"error: {str(e)[:80]}"
                report["errors"] += 1
        else:
            plan["status"] = "would_ratchet"
        report["actions"].append(plan)
    return report


def main():
    from dotenv import load_dotenv
    load_dotenv(str(PROJECT_ROOT / ".env"))
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--retrofit-oco", action="store_true",
                    help="convert standalone stops on open paper positions into OCO brackets (stop + take-profit)")
    a = ap.parse_args()
    if a.retrofit_oco:
        print(json.dumps(run_oco_retrofit(apply=a.apply), indent=2, default=str))
    else:
        print(json.dumps(run(apply=a.apply), indent=2, default=str))


if __name__ == "__main__":
    main()
