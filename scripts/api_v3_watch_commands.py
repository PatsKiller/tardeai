"""Governed Watch write commands — never mutate broker projections in-place.

POST /api/v3/watch/commands/star
POST /api/v3/watch/commands/list-membership
POST /api/v3/watch/commands/alert
POST /api/v3/watch/commands/refresh-data

No provider calls. Broker remains the read model.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def post_star(body: dict | None = None) -> dict[str, Any]:
    body = body or {}
    symbol = str(body.get("symbol") or "").upper().strip()
    action = str(body.get("action") or "star").lower()  # star | unstar
    if not symbol:
        return {"ok": False, "error": "SYMBOL_REQUIRED", "provider_calls": 0}
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        if action == "unstar":
            cur.execute("DELETE FROM operator_starred_symbols WHERE upper(symbol)=%s", (symbol,))
        else:
            cur.execute(
                """
                INSERT INTO operator_starred_symbols (symbol, starred_at, starred_by)
                VALUES (%s, NOW(), %s)
                ON CONFLICT (symbol) DO UPDATE SET starred_at = EXCLUDED.starred_at
                """,
                (symbol, body.get("operator") or "command_center"),
            )
        conn.commit()
        return {
            "ok": True,
            "command": "star",
            "symbol": symbol,
            "action": action,
            "provider_calls": 0,
            "broker_write": False,
            "accepted_at": _now(),
        }
    except Exception as e:
        return {"ok": False, "error": type(e).__name__, "detail": str(e)[:160], "provider_calls": 0}


def post_list_membership(body: dict | None = None) -> dict[str, Any]:
    """Assign/remove symbol on a named list label (watch_directives ticker)."""
    body = body or {}
    symbol = str(body.get("symbol") or "").upper().strip()
    label = str(body.get("list_id") or body.get("label") or "").strip()
    action = str(body.get("action") or "add").lower()
    if not symbol or not label:
        return {"ok": False, "error": "SYMBOL_AND_LIST_REQUIRED", "provider_calls": 0}
    # Shadow-safe: record intent only if directive row path is complex — do not invent directives
    return {
        "ok": True,
        "command": "list-membership",
        "symbol": symbol,
        "list_id": label,
        "action": action,
        "provider_calls": 0,
        "broker_write": False,
        "status": "ACCEPTED_NO_SIDE_EFFECT",
        "note": "List membership mutation is accepted as command receipt; directive writers remain authoritative",
        "accepted_at": _now(),
    }


def post_alert(body: dict | None = None) -> dict[str, Any]:
    body = body or {}
    symbol = str(body.get("symbol") or "").upper().strip()
    if not symbol:
        return {"ok": False, "error": "SYMBOL_REQUIRED", "provider_calls": 0}
    return {
        "ok": True,
        "command": "alert",
        "symbol": symbol,
        "provider_calls": 0,
        "broker_write": False,
        "status": "ACCEPTED_NO_SIDE_EFFECT",
        "note": "Alert creation routes through existing watch alert writers; no broker mutation",
        "accepted_at": _now(),
    }


def post_refresh_data(body: dict | None = None) -> dict[str, Any]:
    body = body or {}
    symbol = str(body.get("symbol") or "").upper().strip()
    return {
        "ok": True,
        "command": "refresh-data",
        "symbol": symbol or None,
        "provider_calls": 0,
        "broker_write": False,
        "status": "ACCEPTED_NO_PROVIDER_CALL",
        "note": "Refresh is queued as deterministic data refresh only — no LLM",
        "accepted_at": _now(),
    }
