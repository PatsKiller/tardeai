#!/usr/bin/env python3
"""finviz_admin_api.py — admin endpoints for the Finviz Screener Governance modal. Delegated from
api_v2.handle() (like inference_api). View + manage screener metadata/cadence/active/notes + run-now.

SAFETY: run-now performs a SOURCE FETCH ONLY (run_finviz_targeted_screeners, which has no broker path) —
it can NEVER place a trade or bypass any gate. Edits are audit-logged (operator/timestamp/before/after).
No broker writes; operator confirmation / 2FA untouched.

Routes:
  GET  /api/admin/finviz-screeners            → list (registry + DB merge, cadence, last/next run)
  GET  /api/admin/finviz-screeners/audit      → efficiency audit
  POST /api/admin/finviz-screeners/:id/update  {cadence_class?, notes?, sunset_candidate?}
  POST /api/admin/finviz-screeners/:id/enable
  POST /api/admin/finviz-screeners/:id/disable
  POST /api/admin/finviz-screeners/:id/run-now {chain?: false}
"""
from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
REGISTRY = ROOT / "config" / "finviz_screeners.yaml"
POLICY = ROOT / "config" / "finviz_screener_cadence_policy.yaml"


def _registry() -> dict:
    return yaml.safe_load(REGISTRY.read_text())


def _next_run_hint(cadence_class: str) -> str:
    try:
        pol = yaml.safe_load(POLICY.read_text())["cadence_classes"].get(cadence_class, {})
    except Exception:
        return "—"
    if pol.get("active") is False:
        return "disabled"
    if pol.get("default_windows"):
        w = pol["default_windows"][0]
        return f"every {w['every_minutes']}m {w['start']}-{w['end']} ET"
    if pol.get("default_times"):
        return "@ " + ",".join(pol["default_times"]) + (" " + ",".join(pol.get("default_days", [])) if pol.get("default_days") else "")
    return "—"


def _db_state() -> dict:
    try:
        from db_adapter import get_connection
        cur = get_connection().cursor()
        cur.execute("SELECT screener_id, active, last_run, results_count FROM finviz_screeners")
        return {r[0]: {"active": r[1], "last_run": str(r[2]) if r[2] else None, "results_count": r[3]}
                for r in cur.fetchall()}
    except Exception:
        return {}


def list_screeners() -> dict:
    reg = _registry()
    db = _db_state()
    rows = []
    for s in (list(reg.get("screeners", [])) + list(reg.get("db_screeners", []))):
        sid = s["screener_id"]
        dbm = db.get(sid, {})
        rows.append({
            "screener_id": sid, "preset_id": s.get("preset_id"), "name": s.get("name"),
            "strategy_family": s.get("strategy_family"), "time_sensitivity": s.get("time_sensitivity"),
            "cadence_class": s.get("cadence_class"),
            "active": dbm.get("active", s.get("active", True)),
            "url": s.get("url"),
            "last_run": dbm.get("last_run"), "next_run": _next_run_hint(s.get("cadence_class")),
            "rows_last_run": dbm.get("results_count"),
            "go_eligible_by_itself": s.get("go_eligible_by_itself", False),
            "classification_status": s.get("classification_status", "operator_preset"),
            "in_scalp_lane": sid in reg.get("scalp_lane_screener_ids", []),
        })
    return {"screeners": rows, "count": len(rows),
            "scalp_lane_screener_ids": reg.get("scalp_lane_screener_ids", []),
            "note": "Discovery only — no screener is GO-eligible by itself. run-now is source-fetch only."}


def _audit(operator, action, target, old, new, result, detail=None):
    try:
        from admin_write_guard import _append_audit
        _append_audit(operator or "operator", action, target, old, new, result, detail)
    except Exception:
        pass


def update_screener(sid: str, body: dict, operator: str = "operator") -> dict:
    """Edit cadence_class / notes / sunset_candidate in the registry (metadata only, audited)."""
    reg = _registry()
    found = None
    for grp in ("screeners", "db_screeners"):
        for s in reg.get(grp, []):
            if s["screener_id"] == sid:
                found = s; break
        if found:
            break
    if not found:
        return {"ok": False, "error": f"unknown screener {sid}"}
    before = {k: found.get(k) for k in ("cadence_class", "notes", "sunset_candidate")}
    for k in ("cadence_class", "notes", "sunset_candidate"):
        if k in (body or {}):
            found[k] = body[k]
    REGISTRY.write_text(yaml.safe_dump(reg, sort_keys=False, default_flow_style=False, width=200))
    after = {k: found.get(k) for k in ("cadence_class", "notes", "sunset_candidate")}
    _audit(operator, "finviz_screener_update", sid, before, after, "applied")
    return {"ok": True, "screener_id": sid, "before": before, "after": after}


def set_active(sid: str, active: bool, operator: str = "operator") -> dict:
    """Enable/disable a DB screener (active flag), audited. Registry presets are metadata-only."""
    try:
        from db_adapter import get_connection
        conn = get_connection(); cur = conn.cursor()
        cur.execute("SELECT active FROM finviz_screeners WHERE screener_id=%s", (sid,))
        row = cur.fetchone()
        if row is None:
            return {"ok": False, "error": f"screener {sid} not in DB (registry preset — metadata only)"}
        old = row[0]
        cur.execute("UPDATE finviz_screeners SET active=%s, updated_at=NOW() WHERE screener_id=%s", (active, sid))
        conn.commit()
        _audit(operator, "finviz_screener_active", sid, old, active, "applied")
        return {"ok": True, "screener_id": sid, "active": active, "was": old}
    except Exception as e:
        return {"ok": False, "error": str(e).splitlines()[0][:100]}


def run_now(sid: str, operator: str = "operator") -> dict:
    """SOURCE FETCH ONLY — run this one screener's Finviz fetch. NEVER places a trade or bypasses a gate.
    Respects the global Finviz throttle (via run_finviz_targeted_screeners → finviz_screener_runner fetch)."""
    try:
        from run_finviz_targeted_screeners import run as _run
        r = _run([sid], dry_run=False)
        _audit(operator, "finviz_screener_run_now", sid, None, r.get("unique_symbols"), "source_fetch_only")
        return {"ok": True, "screener_id": sid, "unique_symbols": r.get("unique_symbols"),
                "uses_broad_runner": r.get("uses_broad_runner"),
                "safety": "source fetch only — no trade, no gate bypass, no broker write"}
    except Exception as e:
        return {"ok": False, "error": str(e).splitlines()[0][:100]}


def audit_report() -> dict:
    try:
        from finviz_screener_efficiency_audit import build
        return build(30)
    except Exception as e:
        return {"ok": False, "error": str(e).splitlines()[0][:100]}


def handle_finviz_admin(base_path: str, method: str, body: dict = None, query: dict = None):
    """Returns (status, dict) or None if not a finviz-admin route."""
    if not base_path.startswith("/api/admin/finviz-screeners"):
        return None
    body = body or {}
    operator = body.get("operator") or "operator"

    if method == "GET":
        if base_path == "/api/admin/finviz-screeners":
            return 200, {"ok": True, **list_screeners()}
        if base_path == "/api/admin/finviz-screeners/audit":
            return 200, {"ok": True, "audit": audit_report()}
        return 404, {"ok": False, "error": "unknown finviz-admin GET route"}

    if method == "POST":
        m = re.match(r"^/api/admin/finviz-screeners/([^/]+)/(update|enable|disable|run-now)$", base_path)
        if not m:
            return 404, {"ok": False, "error": "unknown finviz-admin POST route"}
        sid, action = m.group(1), m.group(2)
        if action == "update":
            return 200, update_screener(sid, body, operator)
        if action == "enable":
            return 200, set_active(sid, True, operator)
        if action == "disable":
            return 200, set_active(sid, False, operator)
        if action == "run-now":
            return 200, run_now(sid, operator)
    return 405, {"ok": False, "error": "method not allowed"}
