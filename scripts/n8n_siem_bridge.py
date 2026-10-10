#!/usr/bin/env python3
"""n8n_siem_bridge.py — every n8n failure becomes a Command Center SIEM row (REMEDIATION_PLAN §5 L2).

Reads the coordination ledger ``runs`` table (sqlite mode=ro) and the incident fan-in receipt
(``data/runtime/n8n_incident_fanin_last.json``) and keeps one active ``system_health_events`` row per
(component ``n8n:<lane_id>``, event_type): insert when new, update in place when severity or detail changed, skip
when identical, resolve when the source says the lane recovered. Logic: ``scripts/lib/n8n_siem_bridge.py``.

    python3 scripts/n8n_siem_bridge.py --dry-run [--out report.json]   # read-only transaction, no INSERT/UPDATE
    python3 scripts/n8n_siem_bridge.py --apply

Receipt (apply only): $TRADEAI_STATE_ROOT/data/runtime/n8n_siem_bridge_last.json (N8nSiemBridge@v1), ``ok_at``
advances only on a fully successful run. Exit 0 = every source read and every write landed; 1 = a source was
unavailable or a write failed (the receipt says which); 2 = usage.

AUTHORITY: READ_ONLY_ADVISORY over the n8n stores; single writer of ``n8n:*`` rows in system_health_events.
No Telegram, no send of any kind: routing stays with the host SYSTEM chokepoint (AGENTS.md §9.1, §23.3).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import n8n_siem_bridge as B  # noqa: E402

SCHEMA = B.SCHEMA
NO_CONSUMER_REASON = B.NO_CONSUMER_REASON
RELEASE_LINK = Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT"

SELECT_OPEN = (
    "SELECT id, component, event_type, severity, message, lifecycle_state, created_at FROM system_health_events "
    "WHERE component LIKE 'n8n:%%' AND COALESCE(lifecycle_state,'active') IN ('active','acknowledged') "
    "ORDER BY id DESC"
)
SQL_INSERT = (
    "INSERT INTO system_health_events (component, event_type, severity, message, action_taken, success, "
    "lifecycle_state) VALUES (%s,%s,%s,%s,%s,FALSE,'active') RETURNING id"
)
SQL_UPDATE = (
    "UPDATE system_health_events SET severity=%s, message=%s, action_taken=%s "
    "WHERE id=%s AND component LIKE 'n8n:%%' AND COALESCE(lifecycle_state,'active') <> 'resolved'"
)
SQL_RESOLVE = (
    "UPDATE system_health_events SET lifecycle_state='resolved', resolved_at=NOW(), resolved_by=%s, success=TRUE, "
    "action_taken=%s WHERE id=%s AND component LIKE 'n8n:%%' AND COALESCE(lifecycle_state,'active') <> 'resolved'"
)


def state_root() -> Path:
    return Path(os.environ.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))


def ledger_path(root: Path) -> Path:
    explicit = os.environ.get("TRADEAI_N8N_COORDINATION_LEDGER")
    return Path(explicit) if explicit else root / B.LEDGER_REL


def load_registry(path: Path) -> dict[str, dict]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {str(r.get("lane_id")): r for r in doc.get("lanes") or [] if r.get("lane_id")}


def _load_json(path: Path) -> Optional[dict]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def connect():  # pragma: no cover - exercised against the live DB only
    from db_adapter import _get_conn

    conn = _get_conn()
    conn.rollback()
    return conn


def read_open_rows(conn) -> list[dict[str, Any]]:
    """The read-only side: one SELECT inside a READ ONLY transaction (a write here would raise)."""
    cur = conn.cursor()
    cur.execute("SET TRANSACTION READ ONLY")
    cur.execute(SELECT_OPEN)
    cols = [d[0] for d in cur.description]
    rows = [dict(zip(cols, r)) if not isinstance(r, dict) else dict(r) for r in cur.fetchall()]
    conn.rollback()  # end the read-only transaction before anything else happens on this connection
    return rows


def apply_plan(conn, plan: dict[str, list[dict]]) -> dict[str, Any]:
    """The only function that writes. Reached from main() after the dry-run branch has returned."""
    done = {"inserted": [], "updated": 0, "resolved": 0, "errors": []}
    cur = conn.cursor()
    try:
        for r in plan["insert"]:
            cur.execute(
                SQL_INSERT,
                (r["component"], r["event_type"], r["severity"], r["message"], f"{B.WRITER}: opened ({r['source']})"),
            )
            got = cur.fetchone()
            done["inserted"].append(got[0] if got and not isinstance(got, dict) else (got or {}).get("id"))
        for r in plan["update"]:
            cur.execute(
                SQL_UPDATE, (r["severity"], r["message"], f"{B.WRITER}: updated (was {r.get('was_severity')})", r["id"])
            )
            done["updated"] += 1
        for r in plan["resolve"]:
            cur.execute(SQL_RESOLVE, (B.WRITER, f"{B.WRITER}: resolved ({r['reason']})", r["id"]))
            done["resolved"] += 1
        conn.commit()
    except Exception as exc:  # noqa: BLE001 — one transaction: all or nothing, and the receipt says why
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        done = {"inserted": [], "updated": 0, "resolved": 0, "errors": [f"{type(exc).__name__}: {str(exc)[:300]}"]}
    return done


def build(now: datetime, root: Path, registry_path: Path, release_link: Path, conn) -> dict[str, Any]:
    """Read every source and compute the plan. Read-only end to end."""
    notes: dict[str, str] = {}
    try:
        registry = load_registry(registry_path)
        notes["registry"] = f"ok:{len(registry)}"
    except (OSError, ValueError) as exc:
        registry = {}
        notes["registry"] = f"unavailable:{type(exc).__name__}"
    ledger_ok = True
    try:
        latest = B.latest_runs(B.read_ledger_runs(ledger_path(root)))
        notes["ledger"] = f"ok:lanes={len(latest)}"
    except Exception as exc:  # noqa: BLE001
        latest, ledger_ok = {}, False
        notes["ledger"] = f"unavailable:{type(exc).__name__}:{str(exc)[:120]}"
    led, good = B.ledger_findings(latest, registry)
    fan, fanin_ok, notes["fanin"] = B.fanin_findings(_load_json(root / B.FANIN_RECEIPT_REL), now, registry, latest)
    findings = B.merge(led + fan)
    env = B.environment(release_link)
    db_ok = True
    try:
        open_rows = read_open_rows(conn) if conn is not None else []
        notes["db"] = f"ok:open_n8n_rows={len(open_rows)}" if conn is not None else "unavailable:no_connection"
        db_ok = conn is not None
    except Exception as exc:  # noqa: BLE001
        open_rows, db_ok = [], False
        notes["db"] = f"unavailable:{type(exc).__name__}:{str(exc)[:120]}"
    plan = B.plan(findings, open_rows, env=env, good_lanes=good, ledger_ok=ledger_ok, fanin_ok=fanin_ok)
    return {
        "plan": plan,
        "notes": notes,
        "env": env,
        "ledger_ok": ledger_ok,
        "fanin_ok": fanin_ok,
        "db_ok": db_ok,
        "sources_ok": ledger_ok and notes["fanin"] != "fanin:missing" and db_ok and bool(registry),
        "good_lanes": sorted(good),
    }


def main(
    argv: Optional[list[str]] = None,
    *,
    conn_factory=None,
    now: Optional[datetime] = None,
    release_link: Path = RELEASE_LINK,
    registry_path: Optional[Path] = None,
) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--out", default=None, help="write the full report (incl. would-write rows) to this path")
    args = ap.parse_args(argv)
    now = now or datetime.now(timezone.utc)
    root = state_root()
    try:
        conn = (conn_factory or connect)()
    except Exception as exc:  # noqa: BLE001
        print(f"[n8n-siem-bridge] DB unavailable: {type(exc).__name__}: {str(exc)[:200]}", file=sys.stderr)
        conn = None
    res = build(now, root, registry_path or (ROOT / "config" / "lane_registry.json"), release_link, conn)
    plan = res["plan"]
    report = {
        "schema": SCHEMA,
        "authority": "READ_ONLY_ADVISORY",
        "as_of": now.isoformat(),
        "mode": "dry-run" if args.dry_run else "apply",
        "env": res["env"],
        "source_notes": res["notes"],
        "counts": B.counts(plan),
        "fanin_ok": res["fanin_ok"],
        "ledger_ok": res["ledger_ok"],
    }
    if args.dry_run:
        report["would_write"] = {k: plan[k] for k in ("insert", "update", "resolve")}
        report["held"] = plan["hold"]
        report["ok"] = res["sources_ok"]
        if args.out:
            Path(args.out).write_text(json.dumps(report, indent=1, default=str) + "\n", encoding="utf-8")
        print(json.dumps({k: report[k] for k in ("mode", "env", "source_notes", "counts", "ok")}, default=str))
        return 0 if report["ok"] else 1
    # ---- apply: the only path that reaches a write
    if conn is None or not res["db_ok"]:
        done = {"inserted": [], "updated": 0, "resolved": 0, "errors": ["db_unavailable"]}
    else:
        done = apply_plan(conn, plan)
    ok = res["sources_ok"] and not done["errors"]
    out = root / B.RECEIPT_REL
    prev = _load_json(out) or {}
    receipt = {
        **report,
        "applied": {**done, "inserted": len(done["inserted"]), "inserted_ids": done["inserted"][:200]},
        "ok": ok,
        "ok_at": now.isoformat() if ok else prev.get("ok_at"),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(receipt, indent=1, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    if args.out:
        Path(args.out).write_text(json.dumps({**receipt, "plan": plan}, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: receipt[k] for k in ("mode", "env", "source_notes", "counts", "applied", "ok")}, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
