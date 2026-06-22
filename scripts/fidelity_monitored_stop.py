#!/usr/bin/env python3
"""Fidelity monitored stops — software-monitored STOP / STOP_LIMIT / TRAILING for SnapTrade-read holdings.

Fidelity has no trading API (SnapTrade connection is read-only). This module mirrors Schwab Stage 2c
discipline: per-order 2FA arms a monitored level in DB; unified_stop_supervisor checks price each cycle;
on breach requests 2FA for a manual Fidelity Active Trader ticket (never auto-submits to a broker API).

Trailing: ratchet-only — effective_stop = max(initial_stop, price * (1 - trail_pct/100)) as price rises.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

FIDELITY_TICKET_PLATFORM = "Fidelity Active Trader Pro"


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def ensure_table():
    conn = _conn(); cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS fidelity_monitored_stops (
        id              SERIAL PRIMARY KEY,
        symbol          TEXT NOT NULL,
        account         TEXT NOT NULL,
        order_type      TEXT NOT NULL DEFAULT 'STOP',
        stop_price      NUMERIC NOT NULL,
        trail_pct       NUMERIC,
        high_water      NUMERIC,
        qty             NUMERIC NOT NULL,
        limit_price     NUMERIC,
        status          TEXT NOT NULL DEFAULT 'armed',
        note            TEXT,
        armed_by        TEXT DEFAULT 'operator',
        armed_at        TIMESTAMPTZ DEFAULT NOW(),
        last_checked_at TIMESTAMPTZ,
        last_price      NUMERIC,
        effective_stop  NUMERIC,
        triggered_at    TIMESTAMPTZ,
        intent_id       TEXT,
        replace_of      INTEGER,
        updated_at      TIMESTAMPTZ DEFAULT NOW()
    )""")
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_fidelity_mon_stops_active
                   ON fidelity_monitored_stops (UPPER(symbol), account) WHERE status='armed'""")
    conn.commit()


def _effective_stop(row: dict, price: float | None) -> float:
    """Ratchet trailing: raise stop with price; never lower."""
    base = float(row["stop_price"])
    ot = (row.get("order_type") or "STOP").upper()
    trail = row.get("trail_pct")
    if ot != "TRAILING_STOP" or trail is None:
        return base
    hw = float(row.get("high_water") or price or base)
    if price is not None and price > hw:
        hw = price
    trail_stop = hw * (1.0 - float(trail) / 100.0)
    return max(base, trail_stop)


def ticket_line(symbol: str, qty, order_type: str, *, stop_price=None, limit_price=None, trail_pct=None) -> str:
    sym = (symbol or "").upper()
    ot = (order_type or "STOP").upper()
    if ot == "TRAILING_STOP":
        return f"SELL {qty} {sym} TRAILING STOP {trail_pct}% GTC — place in {FIDELITY_TICKET_PLATFORM}"
    if ot == "STOP_LIMIT":
        return (f"SELL {qty} {sym} STOP-LIMIT stop ${stop_price} / limit ${limit_price or stop_price} GTC "
                f"— place in {FIDELITY_TICKET_PLATFORM}")
    return f"SELL {qty} {sym} STOP ${stop_price} GTC — place in {FIDELITY_TICKET_PLATFORM}"


def arm(symbol, account, stop_price, qty, *, order_type="STOP", trail_pct=None, limit_price=None,
        note=None, armed_by="operator", replace_of=None):
    ensure_table()
    sym = (symbol or "").strip().upper()
    acct = (account or "").strip()
    ot = (order_type or "STOP").upper()
    try:
        sp = float(stop_price); q = float(qty)
    except Exception:
        return {"ok": False, "error": "stop_price and qty must be numeric"}
    if not (sym and acct) or sp <= 0 or q <= 0:
        return {"ok": False, "error": "symbol, account, positive stop_price and qty required"}
    if ot == "TRAILING_STOP" and trail_pct is None:
        return {"ok": False, "error": "TRAILING_STOP requires trail_pct"}
    conn = _conn(); cur = conn.cursor()
    cur.execute("UPDATE fidelity_monitored_stops SET status='canceled', updated_at=NOW() "
                "WHERE UPPER(symbol)=%s AND account=%s AND status='armed'", (sym, acct))
    cur.execute("""INSERT INTO fidelity_monitored_stops
                   (symbol, account, order_type, stop_price, trail_pct, high_water, qty, limit_price,
                    note, armed_by, replace_of, effective_stop)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (sym, acct, ot, sp, trail_pct, sp, q, limit_price, (note or "")[:300],
                 (armed_by or "operator")[:60], replace_of, sp))
    sid = cur.fetchone()[0]
    conn.commit()
    return {"ok": True, "id": sid, "symbol": sym, "account": acct, "order_type": ot,
            "stop_price": sp, "trail_pct": trail_pct, "qty": q,
            "ticket": ticket_line(sym, q, ot, stop_price=sp, limit_price=limit_price, trail_pct=trail_pct),
            "mode": "monitored",
            "note": "Monitored stop armed (no 2FA — monitor-only). On breach: alert + "
                    f"{FIDELITY_TICKET_PLATFORM} ticket; you place manually."}


def cancel(symbol=None, account=None, stop_id=None):
    ensure_table()
    conn = _conn(); cur = conn.cursor()
    if stop_id is not None:
        cur.execute("UPDATE fidelity_monitored_stops SET status='canceled', updated_at=NOW() "
                    "WHERE id=%s AND status='armed'", (int(stop_id),))
    else:
        cur.execute("UPDATE fidelity_monitored_stops SET status='canceled', updated_at=NOW() "
                    "WHERE UPPER(symbol)=%s AND account=%s AND status='armed'",
                    ((symbol or "").strip().upper(), (account or "").strip()))
    n = cur.rowcount; conn.commit()
    return {"ok": True, "canceled": n}


def list_stops(status="armed"):
    ensure_table()
    conn = _conn(); cur = conn.cursor()
    q = ("SELECT id, symbol, account, order_type, stop_price, trail_pct, high_water, qty, limit_price, "
         "status, effective_stop, last_price, last_checked_at, triggered_at, intent_id, armed_at "
         "FROM fidelity_monitored_stops ")
    if status == "all":
        cur.execute(q + "ORDER BY armed_at DESC LIMIT 200")
    else:
        cur.execute(q + "WHERE status=%s ORDER BY armed_at DESC LIMIT 200", (status,))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _live_price(symbol, account):
    sym = (symbol or "").upper()
    try:
        import json
        from pathlib import Path
        ec = json.loads((Path(HERE).parent / "data" / "state" / "ticker_enrichment_cache.json").read_text())
        rec = (ec.get("tickers") or ec or {}).get(sym) or {}
        if isinstance(rec, dict) and rec.get("price"):
            return float(rec["price"])
    except Exception:
        pass
    try:
        import json
        hj = Path(HERE).parent / "data" / "state" / "holdings.json"
        if hj.exists():
            data = json.loads(hj.read_text())
            for h in data.get("holdings") or data if isinstance(data, list) else []:
                if not isinstance(h, dict):
                    continue
                if (h.get("account") or h.get("account_id")) == account and (h.get("symbol") or "").upper() == sym:
                    for k in ("current_price", "price"):
                        if h.get(k):
                            return float(h[k])
    except Exception:
        pass
    return None


def check_and_trigger(dry_run=True):
    """Ratchet trailing stops; on breach alert + ticket (no execution, no 2FA)."""
    ensure_table()
    out = []
    try:
        stops = list_stops("armed")
    except Exception as e:
        return [{"error": str(e)[:120]}]
    conn = _conn(); cur = conn.cursor()
    for s in stops:
        sym, acct = s["symbol"], s["account"]
        px = _live_price(sym, acct)
        eff = _effective_stop(s, px)
        hw = float(s.get("high_water") or s["stop_price"])
        if px is not None and px > hw:
            hw = px
        try:
            cur.execute("""UPDATE fidelity_monitored_stops SET last_price=%s, effective_stop=%s,
                           high_water=%s, last_checked_at=NOW(), updated_at=NOW() WHERE id=%s""",
                        (px, eff, hw, s["id"]))
            conn.commit()
        except Exception:
            conn.rollback()
        if px is None:
            out.append({"symbol": sym, "account": acct, "status": "no_price", "effective_stop": eff})
            continue
        if px > eff:
            out.append({"symbol": sym, "account": acct, "status": "ok", "price": px, "effective_stop": eff})
            continue
        if dry_run:
            out.append({"symbol": sym, "account": acct, "status": "would_trigger", "price": px,
                        "effective_stop": eff, "ticket": ticket_line(sym, s["qty"], s["order_type"],
                        stop_price=eff, limit_price=s.get("limit_price"), trail_pct=s.get("trail_pct"))})
            continue
        try:
            tkt = ticket_line(sym, s["qty"], s["order_type"], stop_price=eff,
                              limit_price=s.get("limit_price"), trail_pct=s.get("trail_pct"))
            cur.execute("""UPDATE fidelity_monitored_stops SET status='triggered', triggered_at=NOW(),
                           updated_at=NOW() WHERE id=%s""", (s["id"],))
            conn.commit()
            try:
                from alert_event_writer import save_alert_event
                save_alert_event(alert_type="strategic_alert", severity="critical",
                                 source_script="fidelity_monitored_stop", symbol=sym,
                                 raw_text=f"[fidelity-monitored-stop:breach] {sym} {acct} px ${px:g} <= stop ${eff:g} → {tkt}",
                                 parsed_payload={"kind": "fidelity_monitored_stop", "symbol": sym,
                                                 "account": acct, "price": px, "effective_stop": eff,
                                                 "ticket": tkt, "qty": float(s["qty"])})
            except Exception:
                pass
            out.append({"symbol": sym, "account": acct, "status": "breach_alerted", "price": px,
                        "effective_stop": eff, "ticket": tkt,
                        "note": "Alert sent — place manually in Fidelity Active Trader; no auto-execution."})
        except Exception as e:
            out.append({"symbol": sym, "account": acct, "status": "trigger_error", "error": str(e)[:160]})
    return out