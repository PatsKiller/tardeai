"""Fidelity GTC stop sync — SnapTrade exposes positions/activities but NOT open stop orders.

Operator-placed sell stops at Fidelity Active Trader must be recorded in manual_broker_stops
(read by stop_lifecycle_monitor + Portfolio Stop Management). This module upserts those rows and
mirrors confirmed prices into stop_confirmations. Read-only on the broker — no order placement.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FIDELITY_STOPS_CONFIG = PROJECT_ROOT / "config" / "fidelity_rollover_stops.json"


_TERMINAL = frozenset({"cancelled", "canceled", "filled", "closed", "executed", "rejected", "expired"})


def ensure_manual_broker_stops_table(cur) -> None:
    cur.execute("""CREATE TABLE IF NOT EXISTS manual_broker_stops (
        id SERIAL PRIMARY KEY, account TEXT, symbol TEXT, broker TEXT,
        order_id TEXT, order_type TEXT DEFAULT 'STOP', stop_price NUMERIC,
        qty NUMERIC, status TEXT DEFAULT 'open', placed_date DATE, note TEXT,
        trail_pct NUMERIC, trail_link TEXT,
        active BOOLEAN DEFAULT TRUE, created_at TIMESTAMPTZ DEFAULT NOW(),
        updated_at TIMESTAMPTZ DEFAULT NOW())""")
    cur.execute("ALTER TABLE manual_broker_stops ADD COLUMN IF NOT EXISTS trail_pct NUMERIC")
    cur.execute("ALTER TABLE manual_broker_stops ADD COLUMN IF NOT EXISTS trail_link TEXT")
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS uq_manual_broker_stops_active
                   ON manual_broker_stops (UPPER(symbol), account) WHERE active = TRUE""")


def normalize_stop_row(row: dict[str, Any], *, default_account: str = "fidelity_rollover_ira") -> dict[str, Any]:
    sym = str(row.get("symbol") or "").strip().upper()
    acct = str(row.get("account") or default_account).strip()
    otype = str(row.get("order_type") or "STOP").upper().replace(" ", "_")
    trail_pct = row.get("trail_pct") or row.get("trail_offset") or row.get("trail_percent")
    try:
        trail_pct = float(trail_pct) if trail_pct not in (None, "") else None
    except (TypeError, ValueError):
        trail_pct = None
    is_trailing = "TRAIL" in otype or (trail_pct is not None and trail_pct > 0)
    if is_trailing and otype == "STOP":
        otype = "TRAILING_STOP"
    try:
        qty = float(row.get("qty") or row.get("shares") or row.get("quantity") or 0)
    except (TypeError, ValueError):
        qty = 0
    sp_raw = row.get("stop_price")
    try:
        sp = float(sp_raw) if sp_raw not in (None, "") else None
    except (TypeError, ValueError):
        sp = None
    if not sym or qty <= 0:
        raise ValueError(f"invalid stop row for {sym}: symbol and positive qty required")
    if not is_trailing and (sp is None or sp <= 0):
        raise ValueError(f"invalid stop row for {sym}: positive stop_price required for fixed stops")
    if is_trailing and trail_pct is None:
        raise ValueError(f"invalid stop row for {sym}: trail_pct required for trailing stops")
    trail_link = str(row.get("trail_link") or ("LAST" if is_trailing else "")).upper() or None
    oid_suffix = f"trail{trail_pct:.0f}pct" if is_trailing else f"{sp:.2f}"
    return {
        "symbol": sym,
        "account": acct,
        "broker": str(row.get("broker") or ("fidelity" if acct.startswith("fidelity") else "manual")),  # hardcode-ok: account-key prefix
        "order_id": str(row.get("order_id") or f"fidelity-gtc-{sym}-{oid_suffix}"),
        "order_type": otype,
        "stop_price": sp,
        "qty": qty,
        "trail_pct": trail_pct,
        "trail_link": trail_link,
        "status": str(row.get("status") or "open").lower(),
        "placed_date": row.get("placed_date") or date.today().isoformat(),
        "note": str(row.get("note") or ("Fidelity GTC trailing stop — operator recorded" if is_trailing
                                        else "Fidelity GTC stop — operator recorded"))[:300],
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
           (account, symbol, broker, order_id, order_type, stop_price, qty, status, placed_date, note,
            trail_pct, trail_link, active)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE) RETURNING id""",
        (norm["account"], norm["symbol"], norm["broker"], norm["order_id"], norm["order_type"],
         norm["stop_price"], norm["qty"], norm["status"], norm["placed_date"], norm["note"],
         norm.get("trail_pct"), norm.get("trail_link")),
    )
    sid = cur.fetchone()[0]
    return {"ok": True, "id": sid, **norm}


def mirror_stop_confirmation(cur, row: dict[str, Any]) -> None:
    """Keep stop_confirmations aligned so Portfolio heat + cards see broker_protected=true."""
    norm = normalize_stop_row(row)
    sym, acct = norm["symbol"], norm["account"]
    sp = norm["stop_price"]
    if sp is None and norm.get("trail_pct"):
        sp = row.get("trail_trigger")  # optional explicit trigger; UI may derive from price × (1 − trail%)
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


def _held_symbols_for_account(account: str) -> set[str]:
    """Symbols with positive shares in holdings — used to avoid retiring live manual stops on sync gaps."""
    try:
        import stop_lifecycle_monitor as slm
        hmap = slm._holdings_map() or {}
        out: set[str] = set()
        for (acct, sym), row in hmap.items():
            if acct != account:
                continue
            try:
                sh = float(row.get("shares") or row.get("quantity") or 0)
            except (TypeError, ValueError):
                sh = 0
            if sh > 0 and sym:
                out.add(str(sym).upper())
        return out
    except Exception:
        return set()


def deactivate_stale_stops(cur, account: str, active_symbols: set[str]) -> list[str]:
    """Mark manual stops inactive when absent from the sync batch AND no longer held."""
    ensure_manual_broker_stops_table(cur)
    held = _held_symbols_for_account(account)
    cur.execute(
        "SELECT UPPER(symbol) FROM manual_broker_stops WHERE account=%s AND active=TRUE",
        (account,),
    )
    retired = []
    for (sym,) in cur.fetchall():
        if sym in active_symbols:
            continue
        if sym in held:
            continue  # still held — keep manual stop even if omitted from this sync pass
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
            """SELECT account, symbol, broker, order_id, order_type, stop_price, qty, status,
                      trail_pct, trail_link
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
            trail = float(r[8]) if r[8] is not None else None
            otype = str(r[4] or "STOP").upper().replace(" ", "_")
            out[(acct, sym)] = {
                "order_id": str(r[3] or f"manual-{sym}"),
                "stop_price": sp,
                "trail_offset": trail,
                "trail_link": str(r[9] or ("PERCENT" if trail else "")).upper() or None,
                "order_type": otype,
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
        record_sync_run(report)
    return report


def load_fidelity_stops_config() -> list[dict[str, Any]]:
    """Read config/fidelity_rollover_stops.json when present (operator-editable registry)."""
    if not FIDELITY_STOPS_CONFIG.is_file():
        return []
    try:
        raw = json.loads(FIDELITY_STOPS_CONFIG.read_text())
        acct = str(raw.get("account") or "fidelity_rollover_ira")  # hardcode-ok: default account key in config JSON
        rows = raw.get("stops") or raw.get("rows") or []
        out: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append({**row, "account": row.get("account") or acct})
        return out
    except Exception:
        return []


def record_sync_run(report: dict[str, Any]) -> None:
    """Persist last successful fidelity stop sync for Command Center status."""
    try:
        from db_adapter import _get_conn
        payload = {
            "at": datetime.now(timezone.utc).isoformat(),
            "upserted": len(report.get("upserted") or []),
            "retired": len(report.get("retired") or []),
            "errors": len(report.get("errors") or []),
            "symbols": sorted({(u.get("symbol") or "") for u in (report.get("upserted") or []) if u.get("symbol")}),
        }
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO system_controls (key, value) VALUES ('fidelity_stops_last_sync', %s)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
            (json.dumps(payload),),
        )
        conn.commit()
    except Exception:
        pass


def fidelity_stops_sync_status() -> dict[str, Any]:
    """Last sync metadata + active manual stop count for UI."""
    out: dict[str, Any] = {
        "config_path": str(FIDELITY_STOPS_CONFIG),
        "config_present": FIDELITY_STOPS_CONFIG.is_file(),
        "configured_symbols": [r.get("symbol") for r in load_fidelity_stops_config()],
        "active_manual_stops": 0,
        "last_sync": None,
    }
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT value FROM system_controls WHERE key='fidelity_stops_last_sync'")
        row = cur.fetchone()
        if row and row[0]:
            out["last_sync"] = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        ensure_manual_broker_stops_table(cur)
        cur.execute(
            "SELECT COUNT(*) FROM manual_broker_stops WHERE active=TRUE AND account LIKE 'fidelity%'"
        )
        out["active_manual_stops"] = int(cur.fetchone()[0] or 0)
    except Exception as e:
        out["status_error"] = str(e)[:120]
    return out


def default_fidelity_rollover_stops() -> list[dict[str, Any]]:
    """Known GTC stops — prefers config/fidelity_rollover_stops.json, else baked-in fallback."""
    cfg = load_fidelity_stops_config()
    if cfg:
        return cfg
    acct = "fidelity_rollover_ira"  # hardcode-ok: fallback when config JSON missing
    return [
        {"symbol": "CSCO", "account": acct, "stop_price": 115.0, "qty": 100, "placed_date": "2026-07-10"},
        {
            "symbol": "ANET", "account": acct, "order_type": "TRAILING_STOP",
            "stop_price": 176.37, "trail_pct": 6, "trail_link": "LAST",
            "qty": 200, "placed_date": "2026-07-10",
        },
        {
            "symbol": "SCHG", "account": acct, "order_type": "TRAILING_STOP",
            "stop_price": 32.6, "trail_pct": 6, "trail_link": "LAST",
            "qty": 5000, "placed_date": "2026-07-09",
        },
        {
            "symbol": "DXCM", "account": acct, "order_type": "TRAILING_STOP",
            "stop_price": 71.04, "trail_pct": 6, "trail_link": "LAST",
            "qty": 225, "placed_date": "2026-07-08",
        },
        {"symbol": "ARKX", "account": acct, "stop_price": 31.06, "qty": 1000, "placed_date": "2026-07-07"},
        {"symbol": "XAR", "account": acct, "stop_price": 263.03, "qty": 100, "placed_date": "2026-07-07"},
        {"symbol": "DIVI", "account": acct, "stop_price": 40.58, "qty": 1000, "placed_date": "2026-07-02"},
    ]