#!/usr/bin/env python3
"""share_reconciliation.py — dividend / share-count drift detection + operator-approved reconcile.

Problem: DRIP and small corporate actions change broker share counts while Trade AI calculations
still use holdings[].shares (system SSOT). This module:

  1. Stamps broker_actual_shares on every broker sync row
  2. Detects drift vs prior system shares and classifies likely source
  3. For small positive DRIP-like drift: keeps system shares sticky + opens an approval task
  4. On operator approval: updates holdings.json shares via protected_holdings_write + audit log

Does NOT place/cancel/replace broker stops. Does NOT auto-reconcile without approval.

Usage:
  python3 scripts/share_reconciliation.py --detect          # scan holdings.json, open tasks
  python3 scripts/share_reconciliation.py --list
  python3 scripts/share_reconciliation.py --apply-id N
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
PROJECT_ROOT = Path(os.environ.get("TRADE_AI_ROOT") or Path(__file__).resolve().parents[1])
HOLDINGS_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"

log = logging.getLogger("share_reconciliation")

# Configurable thresholds (env overrides)
SHARE_DRIFT_TOL = float(os.environ.get("SHARE_DRIFT_TOL", "0.01"))
# Deltas larger than this fraction of prior shares are treated as trades (auto-apply broker qty)
TRADE_LIKE_PCT = float(os.environ.get("SHARE_DRIFT_TRADE_PCT", "0.05"))
# Absolute cap for "small" drip-like increases even on large positions
DRIP_ABS_CAP = float(os.environ.get("SHARE_DRIFT_DRIP_CAP", "200"))

SOURCES = (
    "dividend_reinvestment",
    "corporate_action",
    "manual_deposit",
    "missed_trade",
    "api_sync",
    "manual",
    "unknown",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def ensure_tables(cur=None) -> None:
    """Idempotent DDL (also in migrations/2026_07_15_share_reconciliation.sql)."""
    own = cur is None
    if own:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS position_share_drift (
            id SERIAL PRIMARY KEY,
            account_key TEXT NOT NULL,
            symbol TEXT NOT NULL,
            system_shares NUMERIC NOT NULL,
            broker_shares NUMERIC NOT NULL,
            drift_amount NUMERIC NOT NULL,
            source TEXT NOT NULL DEFAULT 'unknown',
            status TEXT NOT NULL DEFAULT 'open',
            snooze_until TIMESTAMPTZ,
            notes TEXT,
            detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_position_share_drift_open_lot
            ON position_share_drift (account_key, symbol)
            WHERE status IN ('open', 'snoozed')""")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS position_reconciliation_log (
            id SERIAL PRIMARY KEY,
            account_key TEXT NOT NULL,
            symbol TEXT NOT NULL,
            previous_system_shares NUMERIC NOT NULL,
            new_system_shares NUMERIC NOT NULL,
            broker_shares_at_time NUMERIC,
            drift_amount NUMERIC NOT NULL,
            source TEXT NOT NULL,
            reconciled_by TEXT NOT NULL DEFAULT 'operator',
            reconciled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            notes TEXT,
            impact_json JSONB,
            drift_task_id INTEGER
        )""")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS ix_position_recon_log_lot
            ON position_reconciliation_log (account_key, symbol, reconciled_at DESC)""")
    if own:
        conn.commit()


def classify_drift(prior: float, broker: float, *, is_etf_or_div: bool = False) -> str:
    """Heuristic classification of share drift source."""
    delta = broker - prior
    if abs(delta) <= SHARE_DRIFT_TOL:
        return "api_sync"
    if prior <= 0:
        return "api_sync"
    pct = abs(delta) / prior
    # Small positive increase → classic DRIP
    if delta > SHARE_DRIFT_TOL and pct <= TRADE_LIKE_PCT and delta <= DRIP_ABS_CAP:
        return "dividend_reinvestment"
    if delta > SHARE_DRIFT_TOL and is_etf_or_div and pct <= 0.10 and delta <= DRIP_ABS_CAP * 2:
        return "dividend_reinvestment"
    if abs(delta) > 0 and pct > TRADE_LIKE_PCT:
        return "missed_trade"
    if delta < -SHARE_DRIFT_TOL and pct <= TRADE_LIKE_PCT:
        return "corporate_action"
    return "unknown"


def is_drip_like(prior: float, broker: float) -> bool:
    """True when we should keep system shares sticky and open an approval task."""
    if prior is None or prior <= 0:
        return False
    delta = broker - prior
    if delta <= SHARE_DRIFT_TOL:
        return False
    if abs(delta) <= SHARE_DRIFT_TOL:
        return False
    pct = abs(delta) / prior
    return pct <= TRADE_LIKE_PCT and delta <= DRIP_ABS_CAP


def stamp_broker_qty(
    prior_row: dict | None,
    broker_qty: float,
    *,
    account_key: str,
    symbol: str,
    name: str | None = None,
) -> tuple[dict, dict | None]:
    """Apply broker qty to a holdings row with optional sticky system shares on DRIP-like drift.

    Returns (updated_row_fields, drift_event|None).
    drift_event is a dict suitable for upsert_open_drift when sticky.
    """
    prior = None
    if prior_row:
        prior = _f(prior_row.get("system_shares") if prior_row.get("system_shares") is not None
                   else prior_row.get("shares"), None)
        if prior is None:
            try:
                prior = float(prior_row.get("shares"))
            except (TypeError, ValueError):
                prior = None

    fields: dict[str, Any] = {
        "broker_actual_shares": round(broker_qty, 6),
        "shares_synced_at": _now(),
    }

    # New position or no prior → trust broker immediately
    if prior is None or prior <= 0:
        fields["shares"] = broker_qty
        fields["system_shares"] = broker_qty
        fields.pop("share_drift", None)
        fields["share_drift_status"] = "aligned"
        return fields, None

    delta = broker_qty - prior
    if abs(delta) <= SHARE_DRIFT_TOL:
        fields["shares"] = broker_qty
        fields["system_shares"] = broker_qty
        fields["share_drift"] = 0
        fields["share_drift_status"] = "aligned"
        return fields, None

    # Trade-like change (buy/sell size) → auto-apply broker
    if not is_drip_like(prior, broker_qty):
        fields["shares"] = broker_qty
        fields["system_shares"] = broker_qty
        fields["share_drift"] = round(delta, 6)
        fields["share_drift_status"] = "auto_applied"
        fields["last_reconciliation_source"] = "api_sync"
        fields["last_reconciled_at"] = _now()
        return fields, None

    # DRIP-like: sticky system shares + pending task
    is_etf = bool(name and ("ETF" in name.upper() or "FUND" in name.upper()))
    source = classify_drift(prior, broker_qty, is_etf_or_div=is_etf)
    fields["shares"] = prior
    fields["system_shares"] = prior
    fields["share_drift"] = round(delta, 6)
    fields["share_drift_status"] = "pending"
    fields["share_drift_source"] = source
    event = {
        "account_key": account_key,
        "symbol": symbol.upper(),
        "system_shares": prior,
        "broker_shares": broker_qty,
        "drift_amount": round(delta, 6),
        "source": source,
        "notes": f"Detected on broker sync; system shares held sticky pending operator approval",
    }
    return fields, event


def upsert_open_drift(event: dict) -> int | None:
    """Insert or refresh open/snoozed drift task. Returns task id."""
    ensure_tables()
    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    acct = str(event["account_key"])
    sym = str(event["symbol"]).upper()
    # clear expired snooze → reopen
    cur.execute("""
        UPDATE position_share_drift SET status='open', snooze_until=NULL, updated_at=NOW()
        WHERE account_key=%s AND symbol=%s AND status='snoozed'
          AND (snooze_until IS NULL OR snooze_until < NOW())
    """, (acct, sym))
    cur.execute("""
        SELECT id, status FROM position_share_drift
        WHERE account_key=%s AND symbol=%s AND status IN ('open','snoozed')
        ORDER BY id DESC LIMIT 1
    """, (acct, sym))
    row = cur.fetchone()
    if row:
        tid, st = row[0], row[1]
        if st == "snoozed":
            conn.commit()
            return int(tid)  # still snoozed — don't nag
        cur.execute("""
            UPDATE position_share_drift SET
                system_shares=%s, broker_shares=%s, drift_amount=%s, source=%s,
                notes=%s, updated_at=NOW()
            WHERE id=%s
        """, (event["system_shares"], event["broker_shares"], event["drift_amount"],
              event.get("source") or "unknown", event.get("notes"), tid))
        conn.commit()
        return int(tid)
    cur.execute("""
        INSERT INTO position_share_drift
            (account_key, symbol, system_shares, broker_shares, drift_amount, source, status, notes)
        VALUES (%s,%s,%s,%s,%s,%s,'open',%s)
        RETURNING id
    """, (acct, sym, event["system_shares"], event["broker_shares"], event["drift_amount"],
          event.get("source") or "unknown", event.get("notes")))
    tid = cur.fetchone()[0]
    conn.commit()
    log.info("Position %s/%s drift task #%s opened (+%s shares, source=%s)",
             acct, sym, tid, event["drift_amount"], event.get("source"))
    try:
        from alert_event_writer import save_alert_event
        save_alert_event(
            alert_type="strategic_alert", severity="warning",
            source_script="share_reconciliation", symbol=sym,
            raw_text=(f"[share-drift] {sym} · {acct}: system {event['system_shares']} → "
                      f"broker {event['broker_shares']} ({event['drift_amount']:+} sh, "
                      f"{event.get('source')})"),
            parsed_payload={"kind": "share_drift", **event, "task_id": tid},
        )
    except Exception:
        pass
    return int(tid)


def process_sync_events(events: list[dict]) -> int:
    """Upsert a batch of drift events from Schwab/SnapTrade sync. Returns count opened/updated."""
    n = 0
    for ev in events or []:
        if not ev:
            continue
        try:
            if upsert_open_drift(ev):
                n += 1
        except Exception as e:
            log.warning("upsert drift failed %s: %s", ev.get("symbol"), e)
    return n


def list_open_drifts(*, include_snoozed: bool = True) -> list[dict]:
    ensure_tables()
    from db_adapter import _get_conn
    cur = _get_conn().cursor()
    statuses = ("open", "snoozed") if include_snoozed else ("open",)
    cur.execute("""
        SELECT id, account_key, symbol, system_shares, broker_shares, drift_amount,
               source, status, snooze_until, notes, detected_at, updated_at
        FROM position_share_drift
        WHERE status = ANY(%s)
          AND (status <> 'snoozed' OR snooze_until IS NULL OR snooze_until < NOW() + INTERVAL '1 second')
        ORDER BY abs(drift_amount) DESC, detected_at DESC
    """, (list(statuses),))
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall() or []:
        d = dict(zip(cols, r))
        # re-open expired snooze in response
        if d.get("status") == "snoozed" and d.get("snooze_until"):
            su = d["snooze_until"]
            if hasattr(su, "tzinfo") and su < datetime.now(timezone.utc):
                d["status"] = "open"
        for k in ("system_shares", "broker_shares", "drift_amount"):
            if d.get(k) is not None:
                d[k] = float(d[k])
        for k in ("detected_at", "updated_at", "snooze_until"):
            if d.get(k) is not None:
                d[k] = d[k].isoformat() if hasattr(d[k], "isoformat") else str(d[k])
        d["message"] = format_user_message(d)
        out.append(d)
    return out


def format_user_message(d: dict) -> str:
    sym = d.get("symbol") or "?"
    sys_s = float(d.get("system_shares") or 0)
    brk = float(d.get("broker_shares") or 0)
    drift = float(d.get("drift_amount") or (brk - sys_s))
    src = str(d.get("source") or "unknown").replace("_", " ")
    sign = f"+{drift:g}" if drift >= 0 else f"{drift:g}"
    if d.get("source") == "dividend_reinvestment":
        lead = f"{sym} received dividend reinvestment"
    else:
        lead = f"{sym} share count drift ({src})"
    return (
        f"{lead}. System shows {sys_s:g} shares. Broker shows {brk:g} shares "
        f"({sign} shares). Update system position to match actual ownership?"
    )


def impact_preview(account: str, symbol: str, new_shares: float | None = None) -> dict:
    """Compute stop/risk impact of updating system shares to broker (or new_shares)."""
    port = json.loads(HOLDINGS_PATH.read_text()) if HOLDINGS_PATH.exists() else {}
    holdings = port.get("holdings") or []
    sym = symbol.upper()
    h = next((x for x in holdings
              if str(x.get("symbol") or "").upper() == sym
              and str(x.get("account") or "") == account), None)
    if not h:
        return {"ok": False, "error": "holding not found"}
    old_sh = _f(h.get("system_shares") if h.get("system_shares") is not None else h.get("shares"))
    broker = _f(h.get("broker_actual_shares") if h.get("broker_actual_shares") is not None else h.get("shares"))
    new_sh = _f(new_shares if new_shares is not None else broker)
    px = _f(h.get("current_price") or h.get("price"))
    total = sum(_f(x.get("market_value")) for x in holdings) or 1.0
    old_mv = old_sh * px
    new_mv = new_sh * px
    # live stop qty if any
    live_stop = None
    try:
        from open_trades_intelligence import load_broker_stops  # may not exist
    except Exception:
        load_broker_stops = None
    stop_qty = None
    stop_price = None
    try:
        # lightweight: read stop_lifecycle snapshot
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute("""
            SELECT qty, stop_price, order_type, status FROM stop_lifecycle
            WHERE upper(symbol)=%s AND account_key=%s
            ORDER BY updated_at DESC NULLS LAST LIMIT 1
        """, (sym, account))
        r = cur.fetchone()
        if r:
            stop_qty, stop_price = _f(r[0], None), _f(r[1], None)
            live_stop = {"qty": stop_qty, "stop_price": stop_price,
                         "order_type": r[2], "status": r[3]}
    except Exception:
        pass
    # coverage
    coverage = None
    if stop_qty is not None and new_sh > 0:
        if abs(stop_qty - new_sh) <= 0.01:
            coverage = "full"
        elif stop_qty > new_sh + 0.01:
            coverage = "oversized"
        else:
            coverage = "partial"
    risk_old = (old_mv / total * 100) if total else None
    risk_new = (new_mv / total * 100) if total else None
    stop_dist_old = ((px - stop_price) / px * 100) if (px and stop_price) else None
    warn_live_stop = bool(live_stop and stop_qty is not None and abs((stop_qty or 0) - new_sh) > 0.01)
    return {
        "ok": True,
        "symbol": sym,
        "account": account,
        "old_shares": old_sh,
        "new_shares": new_sh,
        "broker_shares": broker,
        "drift": round(new_sh - old_sh, 6),
        "price": px,
        "old_market_value": round(old_mv, 2),
        "new_market_value": round(new_mv, 2),
        "old_portfolio_pct": round(risk_old, 4) if risk_old is not None else None,
        "new_portfolio_pct": round(risk_new, 4) if risk_new is not None else None,
        "live_stop": live_stop,
        "stop_coverage_after": coverage,
        "stop_distance_pct": round(stop_dist_old, 3) if stop_dist_old is not None else None,
        "warn_live_stop": warn_live_stop,
        "warn_message": (
            "A live broker stop exists with a different share quantity. After updating system shares, "
            "review/replace the Schwab stop so qty matches held shares. Trade AI will not auto-cancel "
            "or replace the broker order."
            if warn_live_stop else None
        ),
        "whole_share_note": (
            "Schwab protective stops require whole shares; residual fractionals stay monitored only."
            if (new_sh % 1) > 1e-9 and str(account).startswith("schwab") else None
        ),
    }


def apply_reconciliation(
    *,
    account: str,
    symbol: str,
    source: str = "manual",
    notes: str | None = None,
    reconciled_by: str = "operator",
    task_id: int | None = None,
    new_shares: float | None = None,
) -> dict:
    """Set system shares = broker (or new_shares), log audit, close open task."""
    ensure_tables()
    if not HOLDINGS_PATH.exists():
        return {"ok": False, "error": "holdings.json missing"}
    port = json.loads(HOLDINGS_PATH.read_text())
    holdings = port.get("holdings") or []
    sym = symbol.upper()
    idx = next((i for i, x in enumerate(holdings)
                if str(x.get("symbol") or "").upper() == sym
                and str(x.get("account") or "") == account), None)
    if idx is None:
        return {"ok": False, "error": f"holding {sym}/{account} not found"}
    h = holdings[idx]
    if h.get("is_cash") or sym == "CASH":
        return {"ok": False, "error": "cash rows are not share-reconciled"}
    old_sh = _f(h.get("system_shares") if h.get("system_shares") is not None else h.get("shares"))
    broker = _f(h.get("broker_actual_shares") if h.get("broker_actual_shares") is not None else h.get("shares"))
    target = _f(new_shares if new_shares is not None else broker)
    if target <= 0:
        return {"ok": False, "error": "new share count must be positive"}
    impact = impact_preview(account, sym, target)
    px = _f(h.get("current_price") or h.get("price"))
    h["shares"] = target
    h["system_shares"] = target
    h["broker_actual_shares"] = broker if broker > 0 else target
    h["share_drift"] = round(_f(h["broker_actual_shares"]) - target, 6)
    h["share_drift_status"] = "aligned" if abs(h["share_drift"]) <= SHARE_DRIFT_TOL else "pending"
    h["last_reconciled_at"] = _now()
    h["last_reconciliation_source"] = source if source in SOURCES else "manual"
    if px > 0:
        h["market_value"] = round(target * px, 2)
    holdings[idx] = h
    port["holdings"] = holdings
    # recalc simple totals
    total = sum(_f(x.get("market_value")) for x in holdings)
    if isinstance(port.get("portfolio_totals"), dict):
        port["portfolio_totals"]["total_value"] = round(total, 2)
    from holdings_guard import protected_holdings_write
    wr = protected_holdings_write(port, source="share_reconciliation", account_key=account)
    if isinstance(wr, dict) and not wr.get("wrote", True):
        return {"ok": False, "error": wr.get("reason") or wr.get("status") or "holdings write blocked",
                "write": wr}

    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    ensure_tables(cur)
    cur.execute("""
        INSERT INTO position_reconciliation_log
            (account_key, symbol, previous_system_shares, new_system_shares, broker_shares_at_time,
             drift_amount, source, reconciled_by, notes, impact_json, drift_task_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
        RETURNING id
    """, (account, sym, old_sh, target, broker, round(target - old_sh, 6),
          source if source in SOURCES else "manual", reconciled_by, notes,
          json.dumps(impact, default=str), task_id))
    log_id = cur.fetchone()[0]
    if task_id:
        cur.execute("""
            UPDATE position_share_drift SET status='reconciled', updated_at=NOW(),
                system_shares=%s, broker_shares=%s, drift_amount=%s
            WHERE id=%s
        """, (target, broker, round(target - old_sh, 6), task_id))
    cur.execute("""
        UPDATE position_share_drift SET status='reconciled', updated_at=NOW()
        WHERE account_key=%s AND symbol=%s AND status IN ('open','snoozed')
    """, (account, sym))
    conn.commit()
    log.info("Position %s/%s reconciled %+g shares → %g (source=%s, log_id=%s)",
             account, sym, target - old_sh, target, source, log_id)
    return {
        "ok": True,
        "log_id": log_id,
        "symbol": sym,
        "account": account,
        "previous_system_shares": old_sh,
        "new_system_shares": target,
        "broker_shares": broker,
        "impact": impact,
        "message": f"Updated {sym} system shares {old_sh:g} → {target:g}",
    }


def snooze_drift(task_id: int, days: int = 1, notes: str | None = None) -> dict:
    ensure_tables()
    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    until = datetime.now(timezone.utc) + timedelta(days=max(1, min(int(days), 30)))
    cur.execute("""
        UPDATE position_share_drift SET status='snoozed', snooze_until=%s,
            notes=COALESCE(%s, notes), updated_at=NOW()
        WHERE id=%s AND status IN ('open','snoozed')
        RETURNING id, symbol, account_key
    """, (until, notes, task_id))
    r = cur.fetchone()
    conn.commit()
    if not r:
        return {"ok": False, "error": "task not found or not open"}
    return {"ok": True, "id": r[0], "symbol": r[1], "account": r[2],
            "snooze_until": until.isoformat(), "days": days}


def history(account: str | None = None, symbol: str | None = None, limit: int = 50) -> list[dict]:
    ensure_tables()
    from db_adapter import _get_conn
    cur = _get_conn().cursor()
    q = """SELECT id, account_key, symbol, previous_system_shares, new_system_shares,
                  broker_shares_at_time, drift_amount, source, reconciled_by, reconciled_at,
                  notes, impact_json
           FROM position_reconciliation_log WHERE 1=1"""
    args: list[Any] = []
    if account:
        q += " AND account_key=%s"
        args.append(account)
    if symbol:
        q += " AND upper(symbol)=%s"
        args.append(symbol.upper())
    q += " ORDER BY reconciled_at DESC LIMIT %s"
    args.append(min(max(int(limit), 1), 200))
    cur.execute(q, args)
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall() or []:
        d = dict(zip(cols, r))
        for k in ("previous_system_shares", "new_system_shares", "broker_shares_at_time", "drift_amount"):
            if d.get(k) is not None:
                d[k] = float(d[k])
        if d.get("reconciled_at") is not None:
            d["reconciled_at"] = d["reconciled_at"].isoformat()
        out.append(d)
    return out


def apply_share_policy_to_synced_positions(
    synced_by_account: dict[str, list[dict]],
    prior_holdings: list[dict],
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Post-process SnapTrade (or any broker) normalized positions with sticky DRIP policy.

    Returns (updated_synced_by_account, drift_events).
    """
    prior_by = {
        (str(h.get("symbol") or "").upper(), str(h.get("account") or "")): h
        for h in (prior_holdings or [])
        if not h.get("is_cash")
    }
    events: list[dict] = []
    out: dict[str, list[dict]] = {}
    for acct, positions in (synced_by_account or {}).items():
        fresh = []
        for p in positions:
            if p.get("is_cash") or str(p.get("symbol") or "").upper() == "CASH":
                fresh.append(p)
                continue
            sym = str(p.get("symbol") or "").upper()
            broker_qty = _f(p.get("shares") or p.get("qty"))
            if broker_qty <= 0:
                continue
            prior = prior_by.get((sym, acct))
            fields, ev = stamp_broker_qty(prior, broker_qty, account_key=acct, symbol=sym, name=p.get("name"))
            p = dict(p)
            p.update(fields)
            # re-scale MV if sticky shares
            px = _f(p.get("current_price") or p.get("price"))
            sys_sh = _f(p.get("shares"), broker_qty)
            if px > 0:
                p["market_value"] = round(sys_sh * px, 2)
            if ev:
                events.append(ev)
            fresh.append(p)
        out[acct] = fresh
    return out, events


def detect_from_holdings_file() -> dict:
    """Scan holdings.json for pending drift fields and upsert open tasks."""
    if not HOLDINGS_PATH.exists():
        return {"ok": False, "error": "no holdings"}
    port = json.loads(HOLDINGS_PATH.read_text())
    events = []
    for h in port.get("holdings") or []:
        if h.get("is_cash") or str(h.get("symbol") or "").upper() == "CASH":
            continue
        broker = h.get("broker_actual_shares")
        system = h.get("system_shares") if h.get("system_shares") is not None else h.get("shares")
        if broker is None or system is None:
            continue
        b, s = _f(broker), _f(system)
        if abs(b - s) <= SHARE_DRIFT_TOL:
            continue
        if h.get("share_drift_status") == "pending" or is_drip_like(s, b):
            events.append({
                "account_key": h.get("account"),
                "symbol": str(h.get("symbol") or "").upper(),
                "system_shares": s,
                "broker_shares": b,
                "drift_amount": round(b - s, 6),
                "source": h.get("share_drift_source") or classify_drift(s, b),
                "notes": "Detected from holdings.json scan",
            })
    n = process_sync_events(events)
    return {"ok": True, "events": len(events), "upserted": n, "open": list_open_drifts()}


def main(argv=None):
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [share-recon] %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--detect", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--history", action="store_true")
    ap.add_argument("--apply-id", type=int, default=None)
    ap.add_argument("--symbol", default=None)
    ap.add_argument("--account", default=None)
    args = ap.parse_args(argv)
    ensure_tables()
    if args.detect:
        print(json.dumps(detect_from_holdings_file(), indent=2, default=str))
        return 0
    if args.list:
        print(json.dumps({"open": list_open_drifts()}, indent=2, default=str))
        return 0
    if args.history:
        print(json.dumps({"history": history(args.account, args.symbol)}, indent=2, default=str))
        return 0
    if args.apply_id:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute("SELECT account_key, symbol, source FROM position_share_drift WHERE id=%s", (args.apply_id,))
        r = cur.fetchone()
        if not r:
            print(json.dumps({"ok": False, "error": "task not found"}))
            return 1
        res = apply_reconciliation(account=r[0], symbol=r[1], source=r[2] or "manual", task_id=args.apply_id)
        print(json.dumps(res, indent=2, default=str))
        return 0 if res.get("ok") else 1
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
