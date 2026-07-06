"""Stop monitoring health — diagnose + auto-remediate stop lifecycle / Fidelity manual-stop gaps.

Consumed by system_health_agent.py on every --apply cycle. Read-only on brokers — remediation runs
local sync scripts (SnapTrade holdings, lifecycle snapshot, protection advisor refresh, drift alerts).
"""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SCRIPTS = PROJECT_ROOT / "scripts"
_PY = PROJECT_ROOT / ".venv" / "bin" / "python"
_MAX_FIXES_PER_DAY = 8
_STALE_ADVISORY_HOURS = 36
_STALE_SNAPSHOT_MIN = 45
_EXEMPT_ACCOUNTS = frozenset({
    "fidelity_401k", "schwab_rollover_ira", "schwab_roth_ira", "schwab_roth", "schwab_taxable",
})


def _run(cmd: str, *, timeout: int = 180) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=timeout,
        )
        return {
            "ok": proc.returncode == 0,
            "exit": proc.returncode,
            "stdout": (proc.stdout or "")[-500:],
            "stderr": (proc.stderr or "")[-300:],
            "cmd": cmd[:200],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit": -1, "stderr": f"timeout after {timeout}s", "cmd": cmd[:200]}
    except Exception as e:
        return {"ok": False, "exit": -1, "stderr": str(e)[:200], "cmd": cmd[:200]}


def _holdings_rows() -> list[dict]:
    rows = []
    try:
        path = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
        if path.exists():
            data = json.loads(path.read_text())
            rows = [r for r in (data.get("holdings") or []) if isinstance(r, dict)]
    except Exception:
        pass
    if not rows:
        try:
            from api_v2 import portfolio_holdings
            rows = (portfolio_holdings() or {}).get("holdings") or []
        except Exception:
            pass
    return rows


def _is_stop_eligible(symbol: str, account: str) -> bool:
    acct = (account or "").lower()
    if acct in _EXEMPT_ACCOUNTS or "401k" in acct:
        return False
    try:
        from holding_family import is_unstoppable_fund
        if is_unstoppable_fund(symbol):
            return False
    except Exception:
        pass
    return acct.startswith(("schwab", "fidelity"))


def _active_stop_keys(scan: dict) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for r in scan.get("stops") or []:
        if r.get("lifecycle") in ("working", "near_trigger"):
            keys.add((str(r.get("account") or ""), str(r.get("symbol") or "").upper()))
    return keys


def diagnose(*, persist_scan: bool = True) -> dict[str, Any]:
    """Scan stop lifecycle + cross-check holdings/advisories. No broker writes."""
    import sys
    sys.path.insert(0, str(_SCRIPTS))
    issues: list[dict] = []
    try:
        import stop_lifecycle_monitor as slm
        scan = slm.scan(persist=persist_scan)
    except Exception as e:
        return {"ok": False, "error": f"lifecycle_scan_failed: {e}", "issues": [], "scan": {}}

    summary = scan.get("summary") or {}
    for sym_acct in summary.get("orphaned") or []:
        issues.append({
            "kind": "orphaned_stop",
            "severity": "alert",
            "detail": sym_acct,
            "fix": "snaptrade_sync_then_retire_or_resync",
        })
    for sym_acct in summary.get("oversized") or []:
        issues.append({
            "kind": "oversized_stop",
            "severity": "warn",
            "detail": sym_acct,
            "fix": "operator_review_qty",
        })
    for item in summary.get("near_trigger") or []:
        issues.append({
            "kind": "near_trigger",
            "severity": "warn",
            "detail": item,
            "fix": "monitor",
        })

    stop_keys = _active_stop_keys(scan)
    naked = []
    for h in _holdings_rows():
        sym = str(h.get("symbol") or "").upper()
        acct = str(h.get("account") or "")
        try:
            sh = float(h.get("shares") or 0)
        except (TypeError, ValueError):
            sh = 0
        if not sym or sh <= 0 or not _is_stop_eligible(sym, acct):
            continue
        if (acct, sym) not in stop_keys:
            naked.append(f"{sym}@{acct}")
    for n in naked:
        issues.append({
            "kind": "naked_position",
            "severity": "alert",
            "detail": n,
            "fix": "protection_advisor_refresh",
        })

    stale_adv = _stale_advisory_symbols()
    for sym in stale_adv:
        issues.append({
            "kind": "stale_protection_advisory",
            "severity": "warn",
            "detail": sym,
            "fix": "protection_advisor_refresh",
        })

    snap_age = _snapshot_age_minutes()
    if snap_age is not None and snap_age > _STALE_SNAPSHOT_MIN:
        issues.append({
            "kind": "stale_lifecycle_snapshot",
            "severity": "warn",
            "detail": f"{snap_age:.0f}m old",
            "fix": "lifecycle_rescan",
        })

    fidelity_orphans = [i for i in issues if i["kind"] == "orphaned_stop"
                        and "fidelity" in str(i.get("detail", "")).lower()]
    return {
        "ok": True,
        "scan_summary": summary,
        "issues": issues,
        "naked": naked,
        "fidelity_orphans": [i["detail"] for i in fidelity_orphans],
        "stale_advisories": stale_adv,
        "snapshot_age_min": snap_age,
        "generated_at": scan.get("generated_at"),
    }


def _stale_advisory_symbols() -> list[str]:
    held = {str(h.get("symbol") or "").upper() for h in _holdings_rows()
            if float(h.get("shares") or 0) > 0}
    if not held:
        return []
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """SELECT UPPER(symbol), MAX(created_at) AS last_at
               FROM hermes_research_intelligence
               WHERE research_type='protection_advisory' AND UPPER(symbol) = ANY(%s)
               GROUP BY UPPER(symbol)""",
            (list(held),),
        )
        stale = []
        now = datetime.now(timezone.utc)
        for sym, last_at in cur.fetchall():
            if not last_at:
                stale.append(sym)
                continue
            la = last_at if last_at.tzinfo else last_at.replace(tzinfo=timezone.utc)
            if (now - la).total_seconds() / 3600 > _STALE_ADVISORY_HOURS:
                stale.append(sym)
        return sorted(stale)
    except Exception:
        return []


def _snapshot_age_minutes() -> float | None:
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT MAX(snapshot_at) FROM stop_lifecycle")
        row = cur.fetchone()
        if not row or not row[0]:
            return None
        ts = row[0] if row[0].tzinfo else row[0].replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - ts).total_seconds() / 60.0
    except Exception:
        return None


def _fixes_today(conn, component: str = "stop_monitoring") -> int:
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT COUNT(*) FROM system_health_events
               WHERE component=%s AND event_type='STOP_FIX' AND created_at > NOW() - INTERVAL '24 hours'""",
            (component,),
        )
        return int(cur.fetchone()[0] or 0)
    except Exception:
        return 0


def _log_fix(conn, msg: str, *, success: bool, action: str) -> None:
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO system_health_events
               (component, event_type, severity, message, action_taken, success)
               VALUES ('stop_monitoring', 'STOP_FIX', %s, %s, %s, %s)""",
            ("INFO" if success else "WARN", msg[:500], action[:200], success),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def remediate(diagnosis: dict[str, Any], conn, *, apply: bool = True) -> dict[str, Any]:
    """Auto-fix safe stop-monitoring gaps. Never places broker orders."""
    if not apply:
        return {"applied": False, "planned": [i.get("fix") for i in diagnosis.get("issues") or []]}

    if _fixes_today(conn) >= _MAX_FIXES_PER_DAY:
        return {"applied": False, "reason": "max_fixes_per_day", "limit": _MAX_FIXES_PER_DAY}

    actions: list[dict] = []
    issues = diagnosis.get("issues") or []
    kinds = {i["kind"] for i in issues}

    def _do(name: str, cmd: str, timeout: int = 180):
        res = _run(cmd, timeout=timeout)
        actions.append({"action": name, **res})
        _log_fix(conn, f"{name}: exit={res.get('exit')}", success=res.get("ok", False), action=cmd[:200])
        return res.get("ok")

    py = str(_PY)

    # 1) Fidelity holdings stale → orphan false positives (e.g. DXCM pending fill)
    if diagnosis.get("fidelity_orphans") or "orphaned_stop" in kinds:
        _do("snaptrade_sync", f"{py} scripts/snaptrade_sync.py --apply", timeout=240)

    # 2) Refresh lifecycle after holdings sync
    if kinds or diagnosis.get("snapshot_age_min"):
        _do("stop_lifecycle_rescan", f"{py} scripts/stop_lifecycle_monitor.py", timeout=120)

    # 3) Re-diagnose orphans; retire closed-position manual stops
    try:
        import sys
        sys.path.insert(0, str(_SCRIPTS))
        import stop_lifecycle_monitor as slm
        from db_adapter import _get_conn as gdb
        scan2 = slm.scan(persist=True)
        orphans = set(scan2.get("summary", {}).get("orphaned") or [])
        hmap = slm._holdings_map()
        gconn = gdb()
        gcur = gconn.cursor()
        for tag in orphans:
            if "@" not in tag:
                continue
            sym, acct = tag.split("@", 1)
            sym = sym.upper()
            held = hmap.get((acct, sym)) or {}
            try:
                held_sh = float(held.get("shares") or 0)
            except (TypeError, ValueError):
                held_sh = 0
            if held_sh <= 0 and acct.startswith("fidelity"):
                gcur.execute(
                    """UPDATE manual_broker_stops SET active=FALSE, status='closed_position',
                       updated_at=NOW() WHERE UPPER(symbol)=%s AND account=%s AND active=TRUE""",
                    (sym, acct),
                )
                gconn.commit()
                actions.append({"action": "retire_orphan_manual_stop", "ok": True, "detail": tag})
                _log_fix(conn, f"retired orphan manual stop {tag}", success=True,
                         action="deactivate manual_broker_stops")
        gconn.close()
    except Exception as e:
        actions.append({"action": "orphan_cleanup", "ok": False, "stderr": str(e)[:200]})

    # 4) Stale protection advisories + naked positions → targeted advisor refresh (cap 6 symbols)
    refresh_syms = sorted(set(diagnosis.get("stale_advisories") or [])
                          | {i["detail"].split("@")[0] for i in issues if i["kind"] == "naked_position"})
    refresh_syms = [s for s in refresh_syms if s][:6]
    if refresh_syms:
        sym_arg = ",".join(refresh_syms)
        _do("protection_advisor", f"{py} scripts/holding_protection_advisor.py --symbols {sym_arg}",
            timeout=600)

    # 5) Drift / lock-in pass (advisory Telegram — no broker writes)
    if _is_market_hours_et():
        _do("stop_drift_alert", f"{py} scripts/stop_drift_alert.py --send", timeout=90)

    return {"applied": True, "actions": actions, "refreshed_symbols": refresh_syms}


def _is_market_hours_et() -> bool:
    try:
        import pytz
        now = datetime.now(pytz.timezone("US/Eastern"))
        if now.weekday() >= 5:
            return False
        mins = now.hour * 60 + now.minute
        return 570 <= mins <= 960
    except Exception:
        return False


def run_stop_monitoring_health(conn, *, apply: bool = False) -> dict[str, Any]:
    """Entry point for system_health_agent."""
    diag = diagnose(persist_scan=True)
    fixes = remediate(diag, conn, apply=apply) if apply else {"applied": False}
    alerts = []
    for i in diag.get("issues") or []:
        sev = i.get("severity", "warn")
        icon = "🚨" if sev == "alert" else "⚠️"
        alerts.append(f"{icon} Stop monitor: {i['kind']} — {i.get('detail')}")
    if fixes.get("actions"):
        fixed = sum(1 for a in fixes["actions"] if a.get("ok"))
        alerts.append(f"🔧 Stop auto-fix: {fixed}/{len(fixes['actions'])} actions OK")
    return {"diagnosis": diag, "remediation": fixes, "alerts": alerts}