"""Fidelity GTC stop sync — SnapTrade exposes positions/activities but NOT open stop orders.

Operator-placed sell stops at Fidelity Active Trader must be recorded in manual_broker_stops
(read by stop_lifecycle_monitor + Portfolio Stop Management). This module upserts those rows and
mirrors confirmed prices into stop_confirmations. Read-only on the broker — no order placement.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any


_TERMINAL = frozenset({"cancelled", "canceled", "filled", "closed", "executed", "rejected", "expired"})


def ensure_manual_broker_stops_table(cur) -> None:
    cur.execute("""CREATE TABLE IF NOT EXISTS manual_broker_stops (
        id SERIAL PRIMARY KEY, account TEXT, symbol TEXT, broker TEXT,
        order_id TEXT, order_type TEXT DEFAULT 'STOP', stop_price NUMERIC,
        qty NUMERIC, status TEXT DEFAULT 'open', placed_date DATE, note TEXT,
        active BOOLEAN DEFAULT TRUE, created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW())""")
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_manual_broker_stops_active
                   ON manual_broker_stops (UPPER(symbol), account) WHERE active = TRUE""")


def normalize_stop_row(row: dict[str, Any], *, default_account: str = "fidelity_rollover_ira") -> dict[str, Any]:
    sym = str(row.get("symbol") or "").strip().upper()
    acct = str(row.get("account") or default_account).strip()
    try:
        sp = float(row["stop_price"])
        qty = float(row.get("qty") or row.get("shares") or row.get("quantity") or 0)
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"invalid stop row for {sym}: need numeric stop_price and qty")
    if not sym or sp <= 0 or qty <= 0:
        raise ValueError(f"invalid stop row for {sym}: symbol, positive stop_price and qty required")
    return {
        "symbol": sym,
        "account": acct,
        "broker": str(row.get("broker") or ("fidelity" if acct.startswith("fidelity") else "manual")),  # hardcode-ok: account-key prefix
        "order_id": str(row.get("order_id") or f"fidelity-gtc-{sym}-{sp:.2f}"),
        "order_type": str(row.get("order_type") or "STOP").upper(),
        "stop_price": sp,
        "qty": qty,
        "status": str(row.get("status") or "open").lower(),
        "placed_date": row.get("placed_date") or date.today().isoformat(),
        "note": str(row.get("note") or "Fidelity GTC stop — operator recorded")[:300],
    }


def upsert_manual_stop(cur, row: dict[str, Any]) -> dict[str, Any]:
    """Insert or replace the active manual_broker_stops row for (symbol, account)."""
    ensure_manual_broker_stops_table(cur)
    norm = normalize_stop_row(row)
    sym, acct = norm["symbol"], norm["account"]
    cur.execute(
        "UPDATE manual_broker_stops SET active=FALSE, status='replaced', updated_at=NOW() "
        "WHERE UPPER(symbol)=%s AND account=%s AND active=TRUE",
        (sym, acct),
    )
    cur.execute(
        """INSERT INTO manual_broker_stops
           (account, symbol, broker, order_id, order_type, stop_price, qty, status, placed_date, note, active)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE) RETURNING id""",
        (norm["account"], norm["symbol"], norm["broker"], norm["order_id"], norm["order_type"],
         norm["stop_price"], norm["qty"], norm["status"], norm["placed_date"], norm["note"]),
    )
    sid = cur.fetchone()[0]
    return {"ok": True, "id": sid, **norm}


def mirror_stop_confirmation(cur, row: dict[str, Any]) -> None:
    """Keep stop_confirmations aligned so Portfolio heat + cards see broker_protected=true."""
    norm = normalize_stop_row(row)
    sym, acct, sp = norm["symbol"], norm["account"], norm["stop_price"]
    cur.execute(
        "SELECT id FROM stop_confirmations WHERE UPPER(symbol)=%s AND account=%s",
        (sym, acct),
    )
    existing = cur.fetchone()
    if existing:
        cur.execute(
            """UPDATE stop_confirmations SET
               stop_status='confirmed', stop_confirmed=TRUE, stop_confirmed_at=NOW(),
               stop_price_confirmed=%s, stop_confirmation_source='fidelity_manual_sync',
               updated_at=NOW()
               WHERE id=%s""",
            (sp, existing[0]),
        )
    else:
        cur.execute(
            """INSERT INTO stop_confirmations
               (symbol, account, stop_status, stop_confirmed, stop_confirmed_at,
                stop_price_confirmed, stop_confirmation_source)
               VALUES (%s,%s,'confirmed',TRUE,NOW(),%s,'fidelity_manual_sync')""",
            (sym, acct, sp),
        )


def deactivate_stale_stops(cur, account: str, active_symbols: set[str]) -> list[str]:
    """Mark manual stops inactive when the symbol is no longer in the active set (position closed)."""
    ensure_manual_broker_stops_table(cur)
    cur.execute(
        "SELECT UPPER(symbol) FROM manual_broker_stops WHERE account=%s AND active=TRUE",
        (account,),
    )
    retired = []
    for (sym,) in cur.fetchall():
        if sym not in active_symbols:
            cur.execute(
                "UPDATE manual_broker_stops SET active=FALSE, status='closed_position', updated_at=NOW() "
                "WHERE UPPER(symbol)=%s AND account=%s AND active=TRUE",
                (sym, account),
            )
            retired.append(sym)
    return retired


def load_manual_protective_stops() -> dict[tuple[str, str], dict[str, Any]]:
    """Read active manual_broker_stops keyed by (account, symbol) — same shape as Schwab broker stops."""
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        ensure_manual_broker_stops_table(cur)
        cur.execute(
            """SELECT account, symbol, broker, order_id, order_type, stop_price, qty, status
               FROM manual_broker_stops
               WHERE active=TRUE
                 AND lower(COALESCE(status,'open')) NOT IN ('cancelled','canceled','filled','closed')"""
        )
        out: dict[tuple[str, str], dict[str, Any]] = {}
        for r in cur.fetchall():
            acct = str(r[0] or "")
            sym = str(r[1] or "").upper()
            if not sym or not acct:
                continue
            sp = float(r[5]) if r[5] is not None else None
            out[(acct, sym)] = {
                "order_id": str(r[3] or f"manual-{sym}"),
                "stop_price": sp,
                "trail_offset": None,
                "trail_link": None,
                "order_type": str(r[4] or "STOP").upper().replace(" ", "_"),
                "status": str(r[7] or "open").lower(),
                "qty": float(r[6]) if r[6] is not None else None,
                "account": acct,
                "source": "fidelity_manual",
                "broker_verified": False,
            }
        return out
    except Exception:
        return {}


def sync_stops(rows: list[dict[str, Any]], *, retire_absent: bool = True, apply: bool = True) -> dict[str, Any]:
    from db_adapter import _get_conn
    report: dict[str, Any] = {"applied": apply, "upserted": [], "retired": [], "errors": []}
    if not rows:
        return {**report, "note": "no rows"}
    by_acct: dict[str, set[str]] = {}
    conn = _get_conn()
    cur = conn.cursor()
    for raw in rows:
        try:
            norm = normalize_stop_row(raw)
            if not apply:
                report["upserted"].append(norm)
                continue
            res = upsert_manual_stop(cur, norm)
            mirror_stop_confirmation(cur, norm)
            report["upserted"].append(res)
            by_acct.setdefault(norm["account"], set()).add(norm["symbol"])
        except Exception as e:
            report["errors"].append({"row": raw, "error": str(e)})
    if apply and retire_absent:
        for acct, syms in by_acct.items():
            report["retired"].extend(deactivate_stale_stops(cur, acct, syms))
    if apply:
        conn.commit()
    return report


def default_fidelity_rollover_stops() -> list[dict[str, Any]]:
    """Known GTC stops from Fidelity Rollover IRA #270135199 (operator-verified 2026-07-06)."""
    acct = "fidelity_rollover_ira"
    return [
        {"symbol": "ANET", "account": acct, "stop_price": 155.50, "qty": 200, "placed_date": "2026-07-02"},
        {"symbol": "DXCM", "account": acct, "stop_price": 67.23, "qty": 225, "placed_date": "2026-07-06"},
        {"symbol": "DIVI", "account": acct, "stop_price": 40.58, "qty": 1000, "placed_date": "2026-07-02"},
        {"symbol": "SMCI", "account": acct, "stop_price": 24.90, "qty": 500, "placed_date": "2026-07-02"},
    ]