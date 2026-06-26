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


def _audit(cur, action: str, level: str, scope: str, reason: str, confirm: str = "", actor: str = "operator") -> None:
    cur.execute(
        """INSERT INTO kill_switch_audit (action, level, scope, reason, confirm_phrase, actor)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (action, level, scope or "", reason or "", confirm or "", actor),
    )


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
    """True if any applicable kill switch blocks the path."""
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
    today = dt.date.today().isoformat()
    want = f"DISABLE {level.upper()} KILL SWITCH {today}"
    if level == "global":
        want = f"DISABLE GLOBAL KILL SWITCH {today}"
    if confirm != want:
        return {"ok": False, "error": f"must be exactly: {want!r}"}
    conn = _conn()
    if not conn:
        return {"ok": False, "error": "db_unavailable"}
    cur = conn.cursor()
    _ensure_table(cur)
    cur.execute(
        """UPDATE kill_switch_state SET enabled=FALSE, disabled_at=NOW(), updated_at=NOW()
           WHERE level=%s AND scope=%s""",
        (level, scope or ""),
    )
    _audit(cur, "disable", level, scope, "operator_disabled", confirm_phrase=confirm, actor=actor)
    conn.commit()
    try:
        from audit_ledger import record_event
        record_event("kill_switch_change", decision="disabled", reason=confirm,
                     component="kill_switches", actor=actor,
                     snapshot={"level": level, "scope": scope})
    except Exception:
        pass
    return {"ok": True, "level": level, "scope": scope, "status": status()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--enable", metavar="LEVEL")
    ap.add_argument("--disable", metavar="LEVEL")
    ap.add_argument("--scope", default="")
    ap.add_argument("--reason", default="")
    ap.add_argument("--confirm", default="")
    args = ap.parse_args()
    if args.enable:
        print(json.dumps(enable(args.enable, scope=args.scope, reason=args.reason), indent=2, default=str))
    elif args.disable:
        print(json.dumps(disable(args.disable, scope=args.scope, confirm=args.confirm), indent=2, default=str))
    else:
        print(json.dumps(status(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())