"""admin_write_guard.py — the single guarded door for Tier-2/3 config/operational writes.

EVERY admin write MUST go through admin_write(). The chain, in order, cannot be skipped:
  1. ACCESS  — a single lightweight operator token. Sized for an AIR-GAPPED LAN: the network is
               the perimeter, so this is intentionally NOT hardened/multi-factor. If
               ADMIN_WRITE_TOKEN is unset, access is open (air-gapped default); if set, it must
               match.
  2. CONFIRM — two-step. Without an explicit confirm the call returns the exact diff
               (action, target, old -> new) for the UI to show; no one-click mutation. Guards
               MISCLICKS and BUGS, not attackers.
  3. APPLY   — runs the caller's apply_fn. The caller captures old_value BEFORE mutating
               (the IRON-RULE backup), and it is recorded in the audit row → reversible.
  4. AUDIT   — appends to admin_audit_log (append-only), even on failure/rejection. The
               independent record, separate from network security.

HARD EXCLUSION: this layer must NEVER arm live execution (ATM enable, risk wired to a LIVE
account, retry of any trading/execution/approval job). Those are Tier-1, handled separately.
"""
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _conn():
    from db_adapter import get_connection
    return get_connection()


def _append_audit(operator, action, target, old_value, new_value, result, detail=None):
    """Append one row to the append-only admin_audit_log. Returns the row id (or None)."""
    try:
        conn = _conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO admin_audit_log (operator, action, target, old_value, new_value, result, detail)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            [operator, action, target,
             json.dumps(old_value, default=str) if old_value is not None else None,
             json.dumps(new_value, default=str) if new_value is not None else None,
             result, detail],
        )
        aid = cur.fetchone()[0]
        conn.commit()
        return aid
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return None


def access_ok(token) -> bool:
    expected = os.environ.get("ADMIN_WRITE_TOKEN", "")
    return (not expected) or (token == expected)


def admin_write(*, action, target, old_value, new_value, apply_fn,
                operator="operator", confirmed=False, token=None):
    """The guarded write. Returns (status_code, response_dict). See module docstring for the chain.

    apply_fn() performs the actual mutation; old_value MUST be the true current value captured by
    the caller before calling this (it becomes the reversible audit record).
    """
    # 1. ACCESS
    if not access_ok(token):
        _append_audit(operator, action, target, old_value, new_value, "rejected", "access denied")
        return 403, {"ok": False, "error": "admin write access denied (operator token)"}

    # 2. CONFIRM (two-step) — no one-click mutation; show the exact change first
    if not confirmed:
        return 200, {"ok": True, "needs_confirm": True,
                     "preview": {"action": action, "target": target,
                                 "old_value": old_value, "new_value": new_value}}

    # 3. APPLY
    result, detail = "applied", None
    try:
        apply_fn()
    except Exception as e:
        result, detail = "failed", str(e)[:500]

    # 4. AUDIT (append-only, even on failure)
    audit_id = _append_audit(operator, action, target, old_value, new_value, result, detail)
    return (200 if result == "applied" else 500), {
        "ok": result == "applied", "result": result, "audit_id": audit_id,
        "action": action, "target": target,
        "old_value": old_value, "new_value": new_value, "detail": detail,
    }


def recent_audit(limit=50):
    try:
        conn = _conn()
        cur = conn.cursor()
        cur.execute(
            """SELECT id, ts, operator, action, target, old_value, new_value, result, detail
               FROM admin_audit_log ORDER BY ts DESC LIMIT %s""", [limit])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception:
        return []
