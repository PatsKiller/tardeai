#!/usr/bin/env python3
"""Synthetic stop monitor — protective stops for FRACTIONAL Schwab positions (operator 2026-06-21).

Schwab REJECTS a resting STOP order on a fractional share quantity (policy 2025-05-21: fractional orders
must use Market-Day / Limit-Day / Limit-GTC). So a fractional position (e.g. TDG 0.7169, NOC 1.2262) cannot
be protected by a broker-side stop. This module is the workaround:

  arm  → store a synthetic stop LEVEL for the full (fractional) position (advisory; no order placed)
  watch→ on each cycle (unified_stop_supervisor, every ~3 min RTH) compare the live price to the level
  fire → on breach, build a MARKET-DAY sell-all intent (Schwab-accepted for fractional) and REQUEST per-
         order 2FA (Telegram + email + web typed-ticker). It does NOT auto-submit — the operator approves
         through the existing protective-stop/confirm flow, exactly like every other live order. (A future
         auto-fire mode could submit without the per-order approval; intentionally NOT done here.)

Fail-closed + advisory: arming writes nothing to the broker; a breach only REQUESTS approval. Whole-share
positions should use a real broker STOP (open_trades card) — this is specifically the fractional path.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def ensure_table():
    conn = _conn(); cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS synthetic_stops (
        id            SERIAL PRIMARY KEY,
        symbol        TEXT NOT NULL,
        account       TEXT NOT NULL,
        stop_price    NUMERIC NOT NULL,
        qty           NUMERIC NOT NULL,
        status        TEXT NOT NULL DEFAULT 'armed',   -- armed | triggered | canceled
        note          TEXT,
        armed_by      TEXT DEFAULT 'operator',
        armed_at      TIMESTAMPTZ DEFAULT NOW(),
        last_checked_at TIMESTAMPTZ,
        last_price    NUMERIC,
        triggered_at  TIMESTAMPTZ,
        intent_id     TEXT,
        updated_at    TIMESTAMPTZ DEFAULT NOW()
    )""")
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_synthetic_stops_active
                   ON synthetic_stops (UPPER(symbol), account) WHERE status='armed'""")
    conn.commit()


def arm(symbol, account, stop_price, qty, note=None, armed_by="operator"):
    """Arm (or re-arm) a synthetic stop on a fractional position. One ACTIVE stop per (symbol, account):
    re-arming supersedes the prior armed row. Advisory — places NOTHING at the broker."""
    ensure_table()
    sym = (symbol or "").strip().upper()
    acct = (account or "").strip()
    try:
        sp = float(stop_price); q = float(qty)
    except Exception:
        return {"ok": False, "error": "stop_price and qty must be numeric"}
    if not (sym and acct) or sp <= 0 or q <= 0:
        return {"ok": False, "error": "symbol, account, positive stop_price and qty required"}
    conn = _conn(); cur = conn.cursor()
    cur.execute("UPDATE synthetic_stops SET status='canceled', updated_at=NOW() WHERE UPPER(symbol)=%s AND account=%s AND status='armed'",
                (sym, acct))
    cur.execute("""INSERT INTO synthetic_stops (symbol, account, stop_price, qty, note, armed_by)
                   VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                (sym, acct, sp, q, (note or "")[:300], (armed_by or "operator")[:60]))
    sid = cur.fetchone()[0]
    conn.commit()
    return {"ok": True, "id": sid, "symbol": sym, "account": acct, "stop_price": sp, "qty": q,
            "note": "Synthetic stop armed (advisory). On a price breach the monitor requests 2FA for a "
                    "Market-Day sell-all — nothing is placed at the broker until you approve."}


def cancel(symbol=None, account=None, stop_id=None):
    ensure_table()
    conn = _conn(); cur = conn.cursor()
    if stop_id is not None:
        cur.execute("UPDATE synthetic_stops SET status='canceled', updated_at=NOW() WHERE id=%s AND status='armed'", (int(stop_id),))
    else:
        cur.execute("UPDATE synthetic_stops SET status='canceled', updated_at=NOW() WHERE UPPER(symbol)=%s AND account=%s AND status='armed'",
                    ((symbol or "").strip().upper(), (account or "").strip()))
    n = cur.rowcount; conn.commit()
    return {"ok": True, "canceled": n}


def list_stops(status="armed"):
    ensure_table()
    conn = _conn(); cur = conn.cursor()
    if status == "all":
        cur.execute("SELECT id, symbol, account, stop_price, qty, status, note, last_price, last_checked_at, triggered_at, intent_id, armed_at FROM synthetic_stops ORDER BY armed_at DESC LIMIT 200")
    else:
        cur.execute("SELECT id, symbol, account, stop_price, qty, status, note, last_price, last_checked_at, triggered_at, intent_id, armed_at FROM synthetic_stops WHERE status=%s ORDER BY armed_at DESC LIMIT 200", (status,))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _live_price(symbol, account):
    """Best-effort live price: Schwab quote (last/mark) first, then the holdings/enrichment cache. None if
    unknown (fail-closed — a missing price NEVER triggers a stop)."""
    sym = (symbol or "").upper()
    try:
        import schwab_transport as st
        q = st.get_quotes([sym], account_key=account)
        if isinstance(q, dict) and q.get("status") == "ok":
            d = (q.get("quotes") or {}).get(sym) or {}
            for k in ("last", "mark", "lastPrice", "regularMarketLastPrice", "bid"):
                v = d.get(k)
                if v:
                    return float(v)
    except Exception:
        pass
    try:
        import json
        from pathlib import Path
        root = Path(HERE).parent
        holdings_path = root / "data" / "portfolios" / "state" / "holdings.json"
        if holdings_path.exists():
            h = json.loads(holdings_path.read_text()) or {}
            acct = (account or "").strip()
            for row in (h.get("holdings") or []):
                if str(row.get("symbol", "")).upper() == sym and str(row.get("account", "")) == acct:
                    for k in ("current_price", "price"):
                        v = row.get(k)
                        if v is not None:
                            return float(v)
    except Exception:
        pass
    try:
        import json
        from pathlib import Path
        ec = json.loads((Path(HERE).parent / "data" / "state" / "ticker_enrichment_cache.json").read_text())
        rec = (ec.get("tickers") or ec or {}).get(sym) or {}
        if isinstance(rec, dict) and rec.get("price"):
            return float(rec["price"])
    except Exception:
        pass
    return None


def check_and_trigger(dry_run=True, verbose=False):
    """Compare each armed synthetic stop to the live price. On breach (price <= stop), in apply mode build a
    Market-Day sell-all intent and REQUEST 2FA (no auto-submit). Returns the per-stop outcomes. Never raises."""
    ensure_table()
    out = []
    try:
        stops = list_stops("armed")
    except Exception as e:
        return [{"error": f"could not load synthetic stops: {str(e)[:120]}"}]
    conn = _conn(); cur = conn.cursor()
    for s in stops:
        sym, acct = s["symbol"], s["account"]
        sp = float(s["stop_price"])
        px = _live_price(sym, acct)
        try:
            cur.execute("UPDATE synthetic_stops SET last_price=%s, last_checked_at=NOW(), updated_at=NOW() WHERE id=%s",
                        (px, s["id"])); conn.commit()
        except Exception:
            conn.rollback()
        if px is None:
            out.append({"symbol": sym, "account": acct, "status": "no_price", "stop": sp}); continue
        if px > sp:
            out.append({"symbol": sym, "account": acct, "status": "ok", "price": px, "stop": sp}); continue
        # ── BREACH ──
        if dry_run:
            out.append({"symbol": sym, "account": acct, "status": "would_trigger", "price": px, "stop": sp,
                        "action": "Market-Day sell-all 2FA request"})
            continue
        try:
            from brokers import protective_stop_pilot as psp
            intent = psp.build_intent(acct, sym, float(s["qty"]), "MARKET",
                                      advised_stop=sp, current_price=px, held_qty=float(s["qty"]))
            req = psp.request_2fa(intent)
            if req.get("ok"):
                cur.execute("UPDATE synthetic_stops SET status='triggered', triggered_at=NOW(), intent_id=%s, updated_at=NOW() WHERE id=%s",
                            (intent.intent_id, s["id"])); conn.commit()
                try:
                    from alert_event_writer import save_alert_event
                    save_alert_event(alert_type="strategic_alert", severity="critical",
                                     source_script="synthetic_stop", symbol=sym,
                                     raw_text=f"[synthetic-stop:breach] {sym} {acct} px ${px} <= stop ${sp} → Market-Day sell-all 2FA requested (intent {intent.intent_id[:8]})",
                                     parsed_payload={"kind": "synthetic_stop", "symbol": sym, "account": acct,
                                                     "price": px, "stop": sp, "qty": float(s["qty"]), "intent_id": intent.intent_id})
                except Exception:
                    pass
                out.append({"symbol": sym, "account": acct, "status": "triggered", "price": px, "stop": sp,
                            "intent_id": intent.intent_id, "note": "2FA requested — approve to sell-all at market"})
            else:
                out.append({"symbol": sym, "account": acct, "status": "trigger_blocked", "price": px, "stop": sp,
                            "error": req.get("reason") or "could not request approval"})
        except Exception as e:
            out.append({"symbol": sym, "account": acct, "status": "trigger_error", "error": str(e)[:160]})
    return out


def main():
    import json, argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "list", "arm", "cancel"])
    ap.add_argument("--apply", action="store_true", help="check: actually request 2FA on breach (else dry-run)")
    ap.add_argument("--symbol"); ap.add_argument("--account")
    ap.add_argument("--stop", type=float); ap.add_argument("--qty", type=float); ap.add_argument("--note")
    a = ap.parse_args()
    if a.cmd == "check":
        print(json.dumps(check_and_trigger(dry_run=not a.apply, verbose=True), indent=2, default=str))
    elif a.cmd == "list":
        print(json.dumps(list_stops("all"), indent=2, default=str))
    elif a.cmd == "arm":
        print(json.dumps(arm(a.symbol, a.account, a.stop, a.qty, a.note), indent=2, default=str))
    elif a.cmd == "cancel":
        print(json.dumps(cancel(a.symbol, a.account), indent=2, default=str))


if __name__ == "__main__":
    main()
