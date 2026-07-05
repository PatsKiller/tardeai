#!/usr/bin/env python3
"""Protective-stop canary lifecycle + broker read-back result recording.

One-V-canary discipline: broad Schwab stop placement stays blocked until a canary
records SUCCESS_READBACK_CONFIRMED from broker read-back truth.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

CANARY_LIFECYCLE_STATES = (
    "NOT_ARMED",
    "READY_FOR_OPERATOR",
    "READY_FOR_OPERATOR_NEXT_REGULAR_SESSION",
    "READY_FOR_OPERATOR_AFTER_HOURS_GTC",
    "SUBMIT_PENDING_2FA",
    "SUBMITTED_AWAITING_READBACK",
    "SUCCESS_READBACK_CONFIRMED",
    "FAILED_PRE_BROKER",
    "FAILED_BROKER_REJECTED",
    "FAILED_READBACK",
    "CANCELLED_BY_OPERATOR",
)

CANARY_RESULTS = (
    "SUCCESS_READBACK_CONFIRMED",
    "FAILED_PRE_BROKER",
    "FAILED_BROKER_REJECTED",
    "FAILED_READBACK",
    "CANCELLED_BY_OPERATOR",
)

DEFAULT_CANARY_ACCOUNT = "schwab_rollover_ira"
PREFERRED_CANARY_SYMBOL = "V"


def _conn():
    from db_adapter import _get_conn
    return _get_conn()


def ensure_table(cur) -> None:
    cur.execute("""CREATE TABLE IF NOT EXISTS protective_stop_canary_results (
                     id SERIAL PRIMARY KEY,
                     symbol TEXT NOT NULL,
                     account_key TEXT NOT NULL,
                     qty NUMERIC,
                     residual_qty NUMERIC,
                     order_kind TEXT,
                     trail_pct NUMERIC,
                     stop_price NUMERIC,
                     limit_price NUMERIC,
                     time_in_force TEXT,
                     broker_order_id TEXT,
                     broker_status TEXT,
                     submitted_at TIMESTAMPTZ,
                     readback_at TIMESTAMPTZ,
                     evidence_id TEXT,
                     order_spec_hash TEXT,
                     readiness_snapshot_hash TEXT,
                     quote_source TEXT,
                     quote_time_normalized TEXT,
                     quote_session TEXT,
                     operator_channel TEXT,
                     after_hours_ack BOOLEAN,
                     lifecycle_state TEXT NOT NULL,
                     result TEXT,
                     failure_reason TEXT,
                     readback_json JSONB,
                     created_at TIMESTAMPTZ DEFAULT NOW())""")


def record_canary_result(
    *,
    symbol: str,
    account_key: str,
    lifecycle_state: str,
    result: str | None = None,
    qty: float | None = None,
    residual_qty: float | None = None,
    order_kind: str | None = None,
    trail_pct: float | None = None,
    stop_price: float | None = None,
    limit_price: float | None = None,
    time_in_force: str | None = None,
    broker_order_id: str | None = None,
    broker_status: str | None = None,
    submitted_at: str | None = None,
    readback_at: str | None = None,
    evidence_id: str | None = None,
    order_spec_hash: str | None = None,
    readiness_snapshot_hash: str | None = None,
    quote_source: str | None = None,
    quote_time_normalized: str | None = None,
    quote_session: str | None = None,
    operator_channel: str | None = None,
    after_hours_ack: bool | None = None,
    failure_reason: str | None = None,
    readback: dict | None = None,
) -> dict:
    """Persist a canary lifecycle transition / broker read-back proof."""
    if lifecycle_state not in CANARY_LIFECYCLE_STATES:
        return {"ok": False, "error": f"invalid lifecycle_state: {lifecycle_state}"}
    conn = _conn()
    if not conn:
        return {"ok": False, "error": "db_unavailable"}
    cur = conn.cursor()
    ensure_table(cur)
    cur.execute(
        """INSERT INTO protective_stop_canary_results
           (symbol, account_key, qty, residual_qty, order_kind, trail_pct, stop_price, limit_price,
            time_in_force, broker_order_id, broker_status, submitted_at, readback_at, evidence_id,
            order_spec_hash, readiness_snapshot_hash, quote_source, quote_time_normalized,
            quote_session, operator_channel, after_hours_ack, lifecycle_state, result, failure_reason,
            readback_json)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
           RETURNING id""",
        (
            (symbol or "").upper(), account_key, qty, residual_qty, order_kind, trail_pct,
            stop_price, limit_price, time_in_force, broker_order_id, broker_status, submitted_at,
            readback_at, evidence_id, order_spec_hash, readiness_snapshot_hash, quote_source,
            quote_time_normalized, quote_session, operator_channel, after_hours_ack, lifecycle_state,
            result, (failure_reason or "")[:500] if failure_reason else None,
            json.dumps(readback or {}, default=str),
        ),
    )
    row_id = cur.fetchone()[0]
    conn.commit()
    return {"ok": True, "id": row_id, "lifecycle_state": lifecycle_state, "result": result}


def latest_canary_result(symbol: str | None = None, account_key: str | None = None) -> dict | None:
    conn = _conn()
    if not conn:
        return None
    cur = conn.cursor()
    ensure_table(cur)
    clauses, params = [], []
    if symbol:
        clauses.append("symbol=%s")
        params.append(symbol.upper())
    if account_key:
        clauses.append("account_key=%s")
        params.append(account_key)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    cur.execute(
        f"""SELECT id, symbol, account_key, lifecycle_state, result, broker_order_id, broker_status,
                   submitted_at, readback_at, order_spec_hash, failure_reason, created_at
            FROM protective_stop_canary_results{where}
            ORDER BY id DESC LIMIT 1""",
        tuple(params),
    )
    row = cur.fetchone()
    if not row:
        return None
    keys = ("id", "symbol", "account_key", "lifecycle_state", "result", "broker_order_id",
            "broker_status", "submitted_at", "readback_at", "order_spec_hash", "failure_reason", "created_at")
    return dict(zip(keys, row))


def has_success_readback(symbol: str | None = None) -> bool:
    conn = _conn()
    if not conn:
        return False
    cur = conn.cursor()
    ensure_table(cur)
    clauses, params = ["result=%s"], ["SUCCESS_READBACK_CONFIRMED"]
    if symbol:
        clauses.append("symbol=%s")
        params.append(symbol.upper())
    cur.execute(
        f"SELECT 1 FROM protective_stop_canary_results WHERE {' AND '.join(clauses)} LIMIT 1",
        tuple(params),
    )
    return cur.fetchone() is not None


def broad_stop_placement_blocked(symbol: str | None = PREFERRED_CANARY_SYMBOL) -> bool:
    """Broad Schwab stop placement remains blocked until canary SUCCESS_READBACK_CONFIRMED."""
    return not has_success_readback(symbol)


def build_canary_target(
    *,
    symbol: str,
    account: str,
    qty: int | float,
    residual_qty: float,
    order_kind: str,
    trail_pct: float | None = None,
    stop_price: float | None = None,
    limit_price: float | None = None,
    time_in_force: str = "GTC",
    quote_price: float | None = None,
    quote_timestamp_normalized: str | None = None,
    quote_source: str | None = None,
    quote_session: str | None = None,
) -> dict[str, Any]:
    return {
        "symbol": (symbol or "").upper(),
        "account": account,
        "qty": qty,
        "residual_qty": residual_qty,
        "order_kind": order_kind,
        "trail_pct": trail_pct,
        "stop_price": stop_price,
        "limit_price": limit_price,
        "time_in_force": time_in_force,
        "quote_price": quote_price,
        "quote_timestamp_normalized": quote_timestamp_normalized,
        "quote_source": quote_source,
        "quote_session": quote_session,
    }


def preferred_canary_targets() -> dict[str, dict]:
    return {
        "preferred": build_canary_target(
            symbol="V", account="schwab_rollover_ira", qty=201, residual_qty=0.4412,
            order_kind="TRAILING_STOP", trail_pct=8.7, time_in_force="GTC",
        ),
        "alternate": build_canary_target(
            symbol="V", account="schwab_roth_ira", qty=130, residual_qty=0.2689,
            order_kind="TRAILING_STOP", trail_pct=10.0, time_in_force="GTC",
        ),
    }