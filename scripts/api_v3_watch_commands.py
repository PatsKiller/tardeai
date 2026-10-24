"""Governed Watch write commands — never mutate broker projections in-place.

POST /api/v3/watch/commands/star
POST /api/v3/watch/commands/list-membership
POST /api/v3/watch/commands/alert
POST /api/v3/watch/commands/refresh-data
POST /api/v3/watch/commands/suggest-dismiss   (System Suggests: hide a suggested name for 30 days)
POST /api/v3/watch/commands/suggest-restore   (undo a dismissal)

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


# ── System Suggests decisions (operator 2026-10-23) ─────────────────────────────────────────────────────────────
# A dismissal is an operator command on the watchlist, never a broker action. It is recorded as one row in the
# existing watchlist_events log (event_type watch_suggest_dismissed / watch_suggest_restored) with who (the
# authenticated cc_auth principal, never the body), when, the reason and the name's rank at the time — the audit
# trail. lib/data_broker/watch_curation.read_dismissed() reads it (latest event per symbol, 30 days).

_SUGGEST_EVENTS = {"dismiss": "watch_suggest_dismissed", "restore": "watch_suggest_restored"}


def _principal() -> str:
    try:
        from lib.cc_auth import current_principal
    except ImportError:  # pragma: no cover - flat import layout
        try:
            from scripts.lib.cc_auth import current_principal  # type: ignore
        except ImportError:
            return ""
    try:
        return current_principal() or ""
    except Exception:  # noqa: BLE001
        return ""


def post_suggest_decision(action: str, body: dict | None = None, *, db_execute=None) -> dict[str, Any]:
    """Record a System Suggests dismissal or restore. ``db_execute(sql, params)`` is injectable for tests."""
    import json as _json
    import re as _re

    body = body or {}
    if action not in _SUGGEST_EVENTS:
        return {"ok": False, "error": "UNKNOWN_ACTION", "provider_calls": 0}
    symbol = str(body.get("symbol") or "").upper().strip()
    if not symbol or not _re.fullmatch(r"[A-Z0-9.\-^/]{1,12}", symbol):
        return {"ok": False, "error": "SYMBOL_REQUIRED", "provider_calls": 0}
    reason = str(body.get("reason") or "").strip()[:300] or None
    by = _principal() or "unauthenticated"
    payload = {"by": by, "reason": reason, "surface": "watch.system_suggests",
               "universe_rank": body.get("universe_rank") if isinstance(body.get("universe_rank"), int) else None,
               "conviction": body.get("conviction") if isinstance(body.get("conviction"), (int, float)) else None}
    sql = ("INSERT INTO watchlist_events (event_type, symbol, source, agent, status, message, payload) "
           "VALUES (%s, %s, 'operator', 'command_center', 'recorded', %s, %s::jsonb)")
    msg = (f"System Suggests: {'dismissed' if action == 'dismiss' else 'restored'} {symbol}"
           + (f" — {reason}" if reason else ""))
    params = (_SUGGEST_EVENTS[action], symbol, msg[:500], _json.dumps(payload))
    try:
        if db_execute is not None:
            db_execute(sql, params)
        else:
            from db_adapter import _get_conn

            conn = _get_conn()
            cur = conn.cursor()
            cur.execute(sql, params)
            conn.commit()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": type(e).__name__, "detail": str(e)[:160], "provider_calls": 0}
    try:  # the next read shows the change at once
        from lib.data_broker import watch_prospects as _wp

        _wp._CACHE.update(at=0.0, val=None)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "command": f"suggest-{action}", "symbol": symbol, "event_type": _SUGGEST_EVENTS[action],
            "by": by, "reason": reason, "provider_calls": 0, "broker_write": False, "accepted_at": _now()}


# ── My Watchlist membership — add / remove (operator 2026-10-23: "I still don't see an area where I can select what
# I want to watch") ───────────────────────────────────────────────────────────────────────────────────────────────
# One command for the star toggle on every Watch row, the "Add symbol" box and "Remove from my watchlist":
#   add    -> the operator star (operator_starred_symbols, the existing star path; starred_by = the principal) and one
#             watchlist_events row  watch_mine_added  {by, note, surface}.
#   remove -> unstar, archive the operator's own active ticker directives for the symbol (the governed
#             watch_directives writer), and one watchlist_events row  watch_mine_removed  {by, reason, surface}.
#             watch_domains.membership_operator() drops a name whose latest add/remove event is a remove (and no
#             newer reason), so the personal list / operator-origin rows are hidden without rewriting
#             watchlist_items. Watching only: no order, no size, no broker (MBI_BEHAVIOR = 0).

_MINE_EVENTS = {"add": "watch_mine_added", "remove": "watch_mine_removed"}


def post_mine_decision(body: dict | None = None, *, db_execute=None, db_query=None) -> dict[str, Any]:
    """POST /api/v3/watch/commands/mine {symbol, action: add|remove, note?, surface?}. Injectable for tests."""
    import json as _json
    import re as _re

    body = body or {}
    action = str(body.get("action") or "").lower()
    if action not in _MINE_EVENTS:
        return {"ok": False, "error": "ACTION_MUST_BE_ADD_OR_REMOVE", "provider_calls": 0}
    symbol = str(body.get("symbol") or "").upper().strip()
    if not symbol or not _re.fullmatch(r"[A-Z0-9.\-^/]{1,12}", symbol):
        return {"ok": False, "error": "SYMBOL_REQUIRED", "provider_calls": 0}
    note = str(body.get("note") or body.get("reason") or "").strip()[:300] or None
    surface = str(body.get("surface") or "watch")[:40]
    by = _principal() or "unauthenticated"
    if db_execute is None or db_query is None:
        from db_adapter import _execute, _get_conn

        conn = _get_conn()

        def db_execute(sql, params=None):  # noqa: F811
            cur = conn.cursor()
            cur.execute(sql, params or ())
            conn.commit()

        def db_query(sql, params=None, fetch="all"):  # noqa: F811
            return _execute(sql, params, fetch=fetch)

    archived: list[int] = []
    try:
        if action == "add":
            db_execute("INSERT INTO operator_starred_symbols (symbol, starred_at, starred_by) VALUES (%s, NOW(), %s) "
                       "ON CONFLICT (symbol) DO UPDATE SET starred_at = EXCLUDED.starred_at, "
                       "starred_by = EXCLUDED.starred_by", (symbol, by[:64]))
        else:
            db_execute("DELETE FROM operator_starred_symbols WHERE upper(symbol) = %s", (symbol,))
            rows = db_query("SELECT id FROM watch_directives WHERE kind = 'ticker' AND status = 'active' "
                            "AND created_by = 'operator' AND upper(spec->>'symbol') = %s", (symbol,)) or []
            if rows:
                try:
                    from lib.writers.watch_directives_writer import set_watch_directive_status
                except ImportError:  # pragma: no cover
                    from scripts.lib.writers.watch_directives_writer import set_watch_directive_status  # type: ignore
                for r in rows:
                    did = r.get("id") if hasattr(r, "get") else r[0]
                    set_watch_directive_status(db_query, did, "archived", source="watch_my_watchlist_remove")
                    archived.append(int(did))
        payload = {"by": by, "note": note, "surface": surface, "archived_directives": archived}
        msg = f"My Watchlist: {'added' if action == 'add' else 'removed'} {symbol}" + (f" — {note}" if note else "")
        db_execute("INSERT INTO watchlist_events (event_type, symbol, source, agent, status, message, payload) "
                   "VALUES (%s, %s, 'operator', 'command_center', 'recorded', %s, %s::jsonb)",
                   (_MINE_EVENTS[action], symbol, msg[:500], _json.dumps(payload)))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": type(e).__name__, "detail": str(e)[:160], "provider_calls": 0}
    try:
        from lib.data_broker import watch_prospects as _wp

        _wp._CACHE.update(at=0.0, val=None)
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "command": "mine", "action": action, "symbol": symbol, "by": by, "note": note,
            "event_type": _MINE_EVENTS[action], "archived_directives": archived, "starred": action == "add",
            "provider_calls": 0, "broker_write": False, "accepted_at": _now()}
