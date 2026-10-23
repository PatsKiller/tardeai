#!/usr/bin/env python3
"""Kill switches and circuit breakers — fail-closed, audited, operator-controlled.

Levels: global, broker, account, strategy, symbol, asset_class, options_only,
equities_only, llm_oversight, proposal_generation, live_submit.

CLI:
  python scripts/brokers/kill_switches.py --status
  python scripts/brokers/kill_switches.py --enable global --reason "..."
  python scripts/brokers/kill_switches.py --disable global --confirm "DISABLE GLOBAL KILL SWITCH YYYY-MM-DD"
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

LEVELS = (
    "global", "broker", "account", "strategy", "symbol", "asset_class",
    "options_only", "equities_only", "llm_oversight", "proposal_generation", "live_submit",
)

CIRCUIT_KEYS = (
    "max_proposals_per_scan", "max_approvals_per_day", "max_live_submits_per_day",
    "max_notional_per_day", "max_loss_per_day", "repeated_broker_rejects",
    "repeated_api_errors", "stale_data", "health_score_below", "queue_backlog_above",
)


def _conn():
    try:
        from db_adapter import _get_conn
        return _get_conn()
    except Exception:
        return None


def _ensure_table(cur) -> None:
    cur.execute("""CREATE TABLE IF NOT EXISTS kill_switch_state (
                     level TEXT NOT NULL,
                     scope TEXT NOT NULL DEFAULT '',
                     enabled BOOLEAN NOT NULL DEFAULT FALSE,
                     reason TEXT,
                     enabled_at TIMESTAMPTZ,
                     disabled_at TIMESTAMPTZ,
                     updated_at TIMESTAMPTZ DEFAULT NOW(),
                     PRIMARY KEY (level, scope))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS kill_switch_audit (
                     id SERIAL PRIMARY KEY,
                     action TEXT NOT NULL,
                     level TEXT NOT NULL,
                     scope TEXT,
                     reason TEXT,
                     confirm_phrase TEXT,
                     actor TEXT,
                     created_at TIMESTAMPTZ DEFAULT NOW())""")


def _audit(cur, action: str, level: str, scope: str, reason: str, *,
           confirm_phrase: str = "", actor: str = "operator") -> None:
    """One audit row, written on the caller's cursor so it commits (or rolls back) together with
    the state change. ``confirm_phrase`` lands in the ``kill_switch_audit.confirm_phrase`` column.

    2026-10-22: the parameter used to be ``confirm`` while ``disable()`` passed ``confirm_phrase=``,
    so every correctly-confirmed disable raised TypeError (present since the file was created
    2026-06-26; no test reached the success path). Keyword-only now, named after the column."""
    cur.execute(
        """INSERT INTO kill_switch_audit (action, level, scope, reason, confirm_phrase, actor)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (action, level, scope or "", reason or "", confirm_phrase or "", actor),
    )


def _rollback_quietly(conn) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


def expected_disable_phrase(level: str, today: dt.date | None = None) -> str:
    """The exact, date-bound phrase ``disable()`` requires. ``today`` is the host's local date."""
    day = (today or dt.date.today()).isoformat()
    return f"DISABLE {level.upper()} KILL SWITCH {day}"


def list_active(*, broker: str | None = None, account_key: str | None = None,
                strategy: str | None = None, symbol: str | None = None,
                asset_class: str | None = None) -> list[dict]:
    """Return active kill switches matching context. Fail-closed: DB error => treat global as active."""
    conn = _conn()
    if not conn:
        return [{"level": "global", "scope": "", "reason": "kill_switch_db_unavailable", "fail_closed": True}]
    cur = conn.cursor()
    _ensure_table(cur)
    cur.execute("SELECT level, scope, reason, enabled_at FROM kill_switch_state WHERE enabled=TRUE")
    active = []
    for level, scope, reason, enabled_at in cur.fetchall() or []:
        scope = scope or ""
        if level == "global":
            active.append({"level": level, "scope": scope, "reason": reason, "enabled_at": str(enabled_at)})
        elif level == "broker" and broker and scope == broker:
            active.append({"level": level, "scope": scope, "reason": reason, "enabled_at": str(enabled_at)})
        elif level == "account" and account_key and scope == account_key:
            active.append({"level": level, "scope": scope, "reason": reason, "enabled_at": str(enabled_at)})
        elif level == "strategy" and strategy and scope == strategy:
            active.append({"level": level, "scope": scope, "reason": reason, "enabled_at": str(enabled_at)})
        elif level == "symbol" and symbol and scope.upper() == symbol.upper():
            active.append({"level": level, "scope": scope, "reason": reason, "enabled_at": str(enabled_at)})
        elif level == "asset_class" and asset_class and scope == asset_class:
            active.append({"level": level, "scope": scope, "reason": reason, "enabled_at": str(enabled_at)})
        elif level in ("options_only", "equities_only", "llm_oversight", "proposal_generation", "live_submit"):
            active.append({"level": level, "scope": scope, "reason": reason, "enabled_at": str(enabled_at)})
    return active


def is_blocked(*, broker: str | None = None, account_key: str | None = None,
               strategy: str | None = None, symbol: str | None = None,
               asset_class: str | None = None, live_submit: bool = False) -> tuple[bool, list[str]]:
    """True if any applicable kill switch blocks the path. The READ-ONLY trading lock (incident SPCX
    2026-10-14) counts as an always-on global switch while engaged (Alpaca paper exempt)."""
    try:
        from lib.trading_lock import is_trading_locked
        _locked = is_trading_locked(broker=broker,
                                    environment="paper" if (broker or "").lower() == "alpaca" else None)
    except Exception:
        _locked = True
    if _locked:
        return True, ["trading_lock:locked (read-only toward brokers; operator unlock required)"]
    active = list_active(broker=broker, account_key=account_key, strategy=strategy,
                         symbol=symbol, asset_class=asset_class)
    reasons = []
    for row in active:
        lvl = row["level"]
        if lvl == "global" or (lvl == "live_submit" and live_submit):
            reasons.append(f"kill_switch:{lvl}:{row.get('reason') or 'active'}")
        elif lvl == "broker" and broker:
            reasons.append(f"kill_switch:broker:{broker}")
        elif lvl == "account" and account_key:
            reasons.append(f"kill_switch:account:{account_key}")
        elif lvl == "strategy" and strategy:
            reasons.append(f"kill_switch:strategy:{strategy}")
        elif lvl == "symbol" and symbol:
            reasons.append(f"kill_switch:symbol:{symbol}")
        elif lvl == "asset_class" and asset_class:
            reasons.append(f"kill_switch:asset_class:{asset_class}")
        elif lvl == "options_only" and asset_class == "option":
            reasons.append("kill_switch:options_only")
        elif lvl == "equities_only" and asset_class == "equity":
            reasons.append("kill_switch:equities_only")
    if any(r.get("fail_closed") for r in active):
        return True, ["kill_switch:db_unavailable_fail_closed"]
    return bool(reasons), reasons


def status() -> dict:
    conn = _conn()
    out: dict[str, Any] = {"ok": conn is not None, "levels": list(LEVELS), "active": [], "audit_tail": []}
    if not conn:
        out["error"] = "db_unavailable"
        return out
    cur = conn.cursor()
    _ensure_table(cur)
    cur.execute("SELECT level, scope, enabled, reason, enabled_at, disabled_at FROM kill_switch_state ORDER BY level, scope")
    out["switches"] = [
        {"level": a, "scope": b or "", "enabled": bool(c), "reason": d,
         "enabled_at": str(e) if e else None, "disabled_at": str(f) if f else None}
        for a, b, c, d, e, f in (cur.fetchall() or [])
    ]
    out["active"] = [s for s in out["switches"] if s["enabled"]]
    cur.execute("SELECT action, level, scope, reason, actor, created_at FROM kill_switch_audit ORDER BY id DESC LIMIT 20")
    out["audit_tail"] = [
        {"action": a, "level": b, "scope": c or "", "reason": d, "actor": e, "created_at": str(f)}
        for a, b, c, d, e, f in (cur.fetchall() or [])
    ]
    return out


def enable(level: str, *, scope: str = "", reason: str = "", actor: str = "operator") -> dict:
    if level not in LEVELS:
        return {"ok": False, "error": f"unknown level {level!r}"}
    conn = _conn()
    if not conn:
        return {"ok": False, "error": "db_unavailable"}
    # State change + audit row are one transaction: both commit, or neither does.
    try:
        cur = conn.cursor()
        _ensure_table(cur)
        now = dt.datetime.now(dt.timezone.utc)
        cur.execute(
            """INSERT INTO kill_switch_state (level, scope, enabled, reason, enabled_at, updated_at)
               VALUES (%s,%s,TRUE,%s,%s,NOW())
               ON CONFLICT (level, scope) DO UPDATE SET enabled=TRUE, reason=EXCLUDED.reason,
                 enabled_at=EXCLUDED.enabled_at, updated_at=NOW()""",
            (level, scope or "", reason or "operator_enabled", now),
        )
        _audit(cur, "enable", level, scope, reason, actor=actor)
        conn.commit()
    except Exception as exc:
        _rollback_quietly(conn)
        return {"ok": False, "error": f"enable_failed_rolled_back: {type(exc).__name__}: {exc}"}
    try:
        from audit_ledger import record_event
        record_event("kill_switch_change", decision="enabled", reason=reason,
                     component="kill_switches", actor=actor,
                     snapshot={"level": level, "scope": scope})
    except Exception:
        pass
    return {"ok": True, "level": level, "scope": scope, "status": status()}


def disable(level: str, *, scope: str = "", confirm: str = "", actor: str = "operator") -> dict:
    if level not in LEVELS:
        return {"ok": False, "error": f"unknown level {level!r}"}
    want = expected_disable_phrase(level)
    if confirm != want:
        return {"ok": False, "error": f"must be exactly: {want!r}"}
    conn = _conn()
    if not conn:
        return {"ok": False, "error": "db_unavailable"}
    # State change + audit row are one transaction: both commit, or neither does. The connection
    # is db_adapter's thread-local one (autocommit off), so without the rollback a failure here
    # would leave the UPDATE pending for the next unrelated commit on this thread to persist —
    # a disable with no audit row.
    try:
        cur = conn.cursor()
        _ensure_table(cur)
        cur.execute(
            """UPDATE kill_switch_state SET enabled=FALSE, disabled_at=NOW(), updated_at=NOW()
               WHERE level=%s AND scope=%s""",
            (level, scope or ""),
        )
        rows = getattr(cur, "rowcount", None)
        _audit(cur, "disable", level, scope, "operator_disabled", confirm_phrase=confirm, actor=actor)
        conn.commit()
    except Exception as exc:
        _rollback_quietly(conn)
        return {"ok": False, "error": f"disable_failed_rolled_back: {type(exc).__name__}: {exc}"}
    try:
        from audit_ledger import record_event
        record_event("kill_switch_change", decision="disabled", reason=confirm,
                     component="kill_switches", actor=actor,
                     snapshot={"level": level, "scope": scope})
    except Exception:
        pass
    return {"ok": True, "level": level, "scope": scope, "rows_updated": rows, "status": status()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--enable", metavar="LEVEL")
    ap.add_argument("--disable", metavar="LEVEL")
    ap.add_argument("--scope", default="")
    ap.add_argument("--reason", default="")
    ap.add_argument("--confirm", default="")
    args = ap.parse_args()
    if args.enable or args.disable:
        if args.enable:
            res = enable(args.enable, scope=args.scope, reason=args.reason)
        else:
            res = disable(args.disable, scope=args.scope, confirm=args.confirm)
        print(json.dumps(res, indent=2, default=str))
        # A refused or failed change exits non-zero: callers (ops_controls) read rc 0 as APPLIED.
        return 0 if res.get("ok") else 1
    print(json.dumps(status(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())