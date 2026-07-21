#!/usr/bin/env python3
"""paper_scale.py — mid-trade scale-IN / scale-OUT for an OPEN position, broker-routed (operator 2026-06-19).

Uniform interface scale_position(account, symbol, delta) routed by broker — same feature on every account:
  • alpaca_paper → LIVE paper: submits a market delta order, reconciles the protective stop, updates
    paper_trades (weighted-avg entry on scale-in, partial realized P&L on scale-out). Alpaca is truth.
  • schwab_*     → GATED 2FA: builds the scale as a Schwab order through the SAME fenced transport +
    per-order 2FA as the canary/protective path, but execution is DISABLED for now (returns 'gated',
    places NOTHING). Drop-in when the operator arms Schwab routing.
  • fidelity_*   → RECORD-ONLY: Fidelity has no trading API; records the scale as a manual trade
    (trade_transactions) + audit so it maps to the journal/holdings; operator executes at Fidelity.

delta_shares > 0 = scale IN (add); < 0 = scale OUT (trim). Scale-IN is capped at the remaining headroom
under the account's percent-of-equity position cap. BOTH directions require confirm=True (operator
decision). Every action is logged to queue_decision_audit. Fail-closed on any broker error.
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_adapter import _get_conn

ALPACA_KEYS = ("tradeai_automated", "ALPACA_PAPER", "alpaca")


def _broker_of(account: str) -> str:
    a = (account or "").lower()
    if a in [k.lower() for k in ALPACA_KEYS] or "alpaca" in a:
        return "alpaca"
    if a.startswith("schwab"):
        return "schwab"
    if a.startswith("fidelity"):
        return "fidelity"
    return "unknown"


def _audit(direction, **kw):
    try:
        import trade_modify as tm
        tm.audit_decision(direction, **kw)
    except Exception:
        pass


def _position_headroom(account: str, symbol: str, held: int, price: float) -> tuple[int, str | None]:
    """Max additional shares allowed under the account's percent-of-equity position cap."""
    import account_policy as ap
    policy = ap.load_policy(account)
    equity, _ = ap.equity_for_account(account)
    pos_pct = policy.get("max_position_allocation_pct")
    if pos_pct and equity > 0 and price > 0:
        max_pos = equity * (pos_pct / 100.0)
        headroom = max(0.0, max_pos - held * price)
        max_add = int(headroom / price)
        note = (f"position cap {pos_pct:g}% = ${max_pos:,.0f}; held ${held*price:,.0f}; headroom +{max_add} sh")
        return max_add, note
    return 10 ** 9, None  # no policy cap → unbounded (risk_gate/other caps still apply elsewhere)


def scale_position(account: str, symbol: str, delta_shares: int, *, actor: str = "operator",
                   channel: str = "web", confirm: bool = False) -> dict:
    symbol = (symbol or "").upper().strip()
    delta = int(delta_shares)
    if not symbol or delta == 0:
        return {"ok": False, "error": "symbol and non-zero delta_shares required"}
    broker = _broker_of(account)
    if broker == "alpaca":
        return _scale_alpaca(account, symbol, delta, actor=actor, channel=channel, confirm=confirm)
    if broker == "schwab":
        return _scale_schwab_gated(account, symbol, delta, actor=actor, channel=channel, confirm=confirm)
    if broker == "fidelity":
        return _scale_fidelity_record(account, symbol, delta, actor=actor, channel=channel, confirm=confirm)
    return {"ok": False, "error": f"unknown broker for account '{account}'"}


# ── ALPACA PAPER (live) ──────────────────────────────────────────────────────────────────────────
def _open_paper_trade(account: str, symbol: str) -> dict | None:
    cur = _get_conn().cursor()
    cur.execute("""SELECT id, symbol, account, status, shares, entry_price, stop_loss, current_stop,
                          stop_order_id FROM paper_trades
                    WHERE upper(symbol)=%s AND status='open'
                      AND account = ANY(%s) ORDER BY entry_time DESC NULLS LAST LIMIT 1""",
                (symbol, list(ALPACA_KEYS)))
    r = cur.fetchone()
    if not r:
        return None
    cols = ("id", "symbol", "account", "status", "shares", "entry_price", "stop_loss", "current_stop", "stop_order_id")
    return dict(zip(cols, r))


def _live_price(adapter, symbol: str, fallback: float) -> float:
    try:
        q = adapter._api_get(f"/v2/stocks/{symbol}/trades/latest")
        p = float(((q or {}).get("trade") or {}).get("p") or 0)
        return p if p > 0 else fallback
    except Exception:
        return fallback


def _scale_alpaca(account, symbol, delta, *, actor, channel, confirm):
    t = _open_paper_trade(account, symbol)
    if not t:
        return {"ok": False, "error": f"no open Alpaca paper position in {symbol}"}
    held = int(t.get("shares") or 0)
    entry = float(t.get("entry_price") or 0)

    from alpaca_paper_adapter import AlpacaPaperAdapter
    adapter = AlpacaPaperAdapter()
    if not adapter.enabled:
        return {"ok": False, "error": "Alpaca paper not enabled (ENABLE_ALPACA_PAPER)"}
    price = _live_price(adapter, symbol, entry)

    capped, cap_note = abs(delta), None
    if delta > 0:
        max_add, note = _position_headroom(account, symbol, held, price)
        if capped > max_add:
            capped, cap_note = max_add, f"capped to headroom (+{max_add} sh) — {note}"
        if capped < 1:
            return {"ok": False, "error": f"no headroom under position cap ({note})"}
    else:
        if capped > held:
            capped, cap_note = held, f"capped to held shares ({held})"

    new_shares = held + capped if delta > 0 else held - capped
    side = "buy" if delta > 0 else "sell"
    preview = {"ok": True, "preview": True, "broker": "alpaca", "symbol": symbol, "trade_id": t["id"],
               "direction": "scale_in" if delta > 0 else "scale_out", "side": side,
               "delta_applied": capped, "held_shares": held, "new_shares": new_shares,
               "price": round(price, 4), "delta_notional": round(capped * price, 2),
               "cap_note": cap_note, "needs_confirm": True}
    if not confirm:
        return preview

    try:
        order = adapter._api_post("/v2/orders", {"symbol": symbol, "qty": str(capped), "side": side,
                                                 "type": "market", "time_in_force": "day"})
    except Exception as e:
        return {"ok": False, "error": f"order submit failed: {str(e)[:140]}"}
    oid = order.get("id", "")
    fill_status, filled_qty, fill_price = order.get("status", "new"), 0, price
    for i in range(8):
        time.sleep(1 + i * 0.5)
        try:
            chk = adapter._api_get(f"/v2/orders/{oid}")
            fill_status = chk.get("status", "")
            filled_qty = int(float(chk.get("filled_qty", 0)))
            if fill_status == "filled":
                fill_price = float(chk.get("filled_avg_price", price) or price); break
            if fill_status in ("canceled", "cancelled", "rejected", "expired"):
                return {"ok": False, "error": f"scale order {fill_status}", "order_id": oid}
        except Exception:
            pass
    if filled_qty < 1:
        return {"ok": False, "error": f"scale order not filled (status={fill_status})", "order_id": oid}

    final_shares = held + filled_qty if delta > 0 else held - filled_qty
    conn = _get_conn(); cur = conn.cursor()
    before = {"shares": held, "entry_price": entry}
    realized = None
    if delta > 0:
        new_entry = round((held * entry + filled_qty * fill_price) / max(1, held + filled_qty), 4)
        cur.execute("UPDATE paper_trades SET shares=%s, entry_price=%s, dollar_size=%s, updated_at=now() WHERE id=%s",
                    (final_shares, new_entry, round(final_shares * new_entry, 2), t["id"]))
    else:
        realized = round((fill_price - entry) * filled_qty, 2)
        if final_shares <= 0:
            cur.execute("""UPDATE paper_trades SET shares=0, status='closed', exit_price=%s, exit_time=now(),
                              close_reason='scaled_out_full', updated_at=now() WHERE id=%s""", (fill_price, t["id"]))
        else:
            cur.execute("UPDATE paper_trades SET shares=%s, dollar_size=%s, updated_at=now() WHERE id=%s",
                        (final_shares, round(final_shares * entry, 2), t["id"]))
    conn.commit()
    stop_note = _reconcile_stop(adapter, conn, t, final_shares)
    _audit("scale_in" if delta > 0 else "scale_out", proposal_id=None, actor=actor, channel=channel,
           before=before, after={"shares": final_shares, "fill_price": fill_price, "applied": filled_qty,
                                  "realized": realized, "order_id": oid}, reason=f"alpaca scale {filled_qty}@{fill_price}")
    return {"ok": True, "broker": "alpaca", "symbol": symbol, "trade_id": t["id"],
            "direction": "scale_in" if delta > 0 else "scale_out", "applied": filled_qty,
            "fill_price": fill_price, "new_shares": final_shares, "realized_pnl": realized,
            "order_id": oid, "stop": stop_note, "cap_note": cap_note}


def _reconcile_stop(adapter, conn, t: dict, new_shares: int) -> str:
    stop_px = t.get("current_stop") or t.get("stop_loss")
    old_stop_id = t.get("stop_order_id")
    try:
        if old_stop_id:
            try:
                adapter._api_delete(f"/v2/orders/{old_stop_id}")
            except Exception:
                pass
        if new_shares > 0 and stop_px:
            resp = adapter._api_post("/v2/orders", {"symbol": t["symbol"], "qty": str(int(new_shares)),
                                                    "side": "sell", "type": "stop",
                                                    "stop_price": str(round(float(stop_px), 2)), "time_in_force": "gtc"})
            cur = conn.cursor()
            cur.execute("UPDATE paper_trades SET stop_order_id=%s, stop_updated_at=now() WHERE id=%s",
                        (resp.get("id", ""), t["id"]))
            conn.commit()
            return f"stop re-placed for {new_shares} sh @ ${float(stop_px):.2f}"
        return "stop cleared (position closed)" if new_shares <= 0 else "no stop on record"
    except Exception as e:
        return f"stop reconcile best-effort failed: {str(e)[:80]}"


# ── SCHWAB (gated 2FA, prepared but disabled) ──────────────────────────────────────────────────────
def _scale_schwab_gated(account, symbol, delta, *, actor, channel, confirm):
    side = "buy" if delta > 0 else "sell"
    try:
        from queue_router import _schwab_gate_reason
        reason = _schwab_gate_reason(account)
    except Exception as e:
        reason = f"interlock unavailable ({str(e)[:60]})"
    res = {"ok": False, "gated": True, "broker": "schwab", "symbol": symbol, "account": account,
           "direction": "scale_in" if delta > 0 else "scale_out", "side": side, "delta": abs(delta),
           "needs_confirm": True,
           "detail": f"Schwab scale prepared but GATED ({reason}). Per-order 2FA would apply; no order placed."}
    if confirm:
        _audit("scale_in" if delta > 0 else "scale_out", proposal_id=None, actor=actor, channel=channel,
               after={"broker": "schwab", "delta": abs(delta), "gated": True}, reason="schwab scale gated")
    return res


# ── FIDELITY (record-only; no trading API) ─────────────────────────────────────────────────────────
def _scale_fidelity_record(account, symbol, delta, *, actor, channel, confirm):
    side = "Buy" if delta > 0 else "Sell"
    preview = {"ok": True, "preview": True, "broker": "fidelity", "symbol": symbol, "account": account,
               "direction": "scale_in" if delta > 0 else "scale_out", "side": side, "delta": abs(delta),
               "needs_confirm": True,
               "detail": "Fidelity has no trading API — this records the scale as a manual trade; execute it at Fidelity."}
    if not confirm:
        return preview
    try:
        conn = _get_conn(); cur = conn.cursor()
        cur.execute("""INSERT INTO trade_transactions (trade_date, action, symbol, quantity, account, import_source, description)
                       VALUES (CURRENT_DATE, %s, %s, %s, %s, 'manual_scale', %s)""",
                    (side, symbol, abs(delta), account, f"mid-trade {('scale-in' if delta>0 else 'scale-out')} (record-only)"))
        conn.commit()
    except Exception as e:
        try:
            _get_conn().rollback()
        except Exception:
            pass
        return {"ok": False, "error": f"record failed: {str(e)[:120]}"}
    _audit("scale_in" if delta > 0 else "scale_out", proposal_id=None, actor=actor, channel=channel,
           after={"broker": "fidelity", "delta": abs(delta), "record_only": True}, reason="fidelity scale recorded")
    return {"ok": True, "broker": "fidelity", "symbol": symbol, "account": account, "recorded": True,
            "direction": "scale_in" if delta > 0 else "scale_out", "delta": abs(delta),
            "detail": "Recorded as a manual trade; execute at Fidelity. Holdings reflect on next reconcile."}
