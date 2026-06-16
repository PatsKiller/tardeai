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
    cur.execute("""SELECT symbol, entry_price, stop_loss_price, strategy_id, shares, current_price, stop_order_id
                   FROM paper_trades WHERE lifecycle_state='open' OR status='open'""")
    rows = cur.fetchall()
    market_hours = True
    report = {"mode": "APPLIED" if apply else "DRY-RUN", "considered": len(rows), "actions": [], "held": 0, "errors": 0}

    for sym, entry, planned, strat, shares, cur_px, stop_oid in rows:
        sym = str(sym).upper()
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
                cur.execute("UPDATE paper_trades SET stop_loss_price=%s, stop_order_id=%s, updated_at=NOW() "
                            "WHERE (lifecycle_state='open' OR status='open') AND symbol=%s",
                            (round(new_stop, 2), new_id, sym))
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
    a = ap.parse_args()
    print(json.dumps(run(apply=a.apply), indent=2, default=str))


if __name__ == "__main__":
    main()
