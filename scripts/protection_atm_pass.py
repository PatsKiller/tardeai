#!/usr/bin/env python3
"""protection_atm_pass.py — ATM auto-apply pass for protection adjustments.

Couples the protection-advisory stream to ATM so it is governed the same way as entries:
  • PAPER account positions → ATM AUTO-APPLIES the adjustment (only the hard-guarded stop-UP actions
    that apply_paper_protection_adjustment allows: MOVE_STOP_TO_PROFIT_LOCK / MOVE_STOP_TO_BREAKEVEN,
    via Alpaca REPLACE so the stop is never absent and risk can only decrease).
  • REAL (Schwab/Fidelity) account positions → left PROPOSED for operator approval (+ 2FA downstream).
Nothing is applied without a proposal row in paper_protection_adjustment_proposals (the record), so
there is no ATM-to-paper action that bypasses the proposals system.

Advisory/no-bypass by construction: it only ever calls the existing guarded apply() with confirm.
"""
from __future__ import annotations

import os

def _is_paper_account(acct: str) -> bool:
    from automated_account import is_automated_account
    return is_automated_account(acct)
# Auto-apply is limited to stop-UP actions (Alpaca REPLACE → the stop is never absent and risk can only
# decrease), per this module's design. ADD_FIXED_TAKE_PROFIT is intentionally NOT here: it is a NEW sell
# order (POST), not a stop replace, and the proposals are only generated for already-stopped positions whose
# shares are fully held_for_orders — so Alpaca 403s the standalone limit and the proposal re-fired every pass
# (the AGNC loop). It stays ADVISORY; an operator places it as an OCO. KEEP_CURRENT_STOP also stays advisory.
AUTO_APPLY_ACTIONS = {
    "MOVE_STOP_TO_PROFIT_LOCK", "MOVE_STOP_TO_BREAKEVEN",
    "CONVERT_TO_TRAILING_STOP",
}


def _auto_apply_enabled() -> bool:
    # Operator choice: paper auto-applies; flip to 0 to make paper operator-approved too.
    return os.getenv("PROTECTION_ATM_AUTO_APPLY_PAPER", "1") == "1"


def _load_env() -> None:
    from pathlib import Path
    p = Path(__file__).resolve().parent.parent / ".env"
    if not p.exists():
        return
    try:
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))
    except Exception:
        pass


def release_read_transaction(conn) -> None:
    """End the open read transaction before slow non-database work.

    rollback, not commit: this pass only SELECTed. commit() would publish
    writes the caller had not yet committed on the shared connection.
    """
    conn.rollback()


def _db_connection_closed(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "connection already closed" in text or "cursor already closed" in text


def _connection_for_pass(conn):
    """Use the passed handle when it is open; otherwise the thread-local one."""
    from db_adapter import _get_conn, ensure_conn

    if conn is None:
        return _get_conn()
    if getattr(conn, "closed", 0):
        return ensure_conn()
    return conn


def _load_proposed_rows(conn) -> list:
    cur = conn.cursor()
    cur.execute("""
        SELECT a.id, a.symbol, a.action, a.proposed_stop, a.trade_id,
               t.account AS acct, t.status AS trade_status
        FROM paper_protection_adjustment_proposals a
        JOIN paper_trades t ON t.id = a.trade_id
        WHERE a.status = 'PROPOSED' AND t.status = 'open'
        ORDER BY a.id
    """)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def run_protection_pass(conn=None, *, mode: str = "active", dry_run: bool = False) -> dict:
    """Process PROPOSED protection adjustments. mode='active' applies on paper; 'dry' previews only."""
    _load_env()  # ensure ALPACA_MODE present (apply() also asserts paper)
    conn = _connection_for_pass(conn)
    try:
        rows = _load_proposed_rows(conn)
    except Exception as exc:
        if not _db_connection_closed(exc):
            raise
        from db_adapter import ensure_conn
        conn = ensure_conn()
        rows = _load_proposed_rows(conn)
    # Rows are already in memory. apply() does quote lookups and broker HTTP;
    # leaving this connection inside the SELECT transaction holds it
    # idle-in-transaction for that whole call.
    release_read_transaction(conn)

    out = {"considered": len(rows), "auto_applied": 0, "operator_pending": 0,
           "skipped_action": 0, "failed": 0, "dry_run": dry_run, "details": []}
    auto_ok = _auto_apply_enabled() and mode == "active" and not dry_run
    paper_mode = os.environ.get("ALPACA_MODE") == "paper"

    for r in rows:
        acct = str(r.get("acct") or "")
        is_paper = _is_paper_account(acct)
        action = (r.get("action") or "").upper()
        # REAL accounts: never auto-apply — leave for operator (+2FA).
        if not is_paper:
            out["operator_pending"] += 1
            out["details"].append({"id": r["id"], "symbol": r["symbol"], "decision": "operator_review", "account": acct})
            continue
        # PAPER, but action not in the auto-apply allowlist → stays advisory.
        if action not in AUTO_APPLY_ACTIONS:
            out["skipped_action"] += 1
            out["details"].append({"id": r["id"], "symbol": r["symbol"], "decision": "advisory_action", "action": action})
            continue
        if not (auto_ok and paper_mode):
            out["operator_pending"] += 1
            out["details"].append({"id": r["id"], "symbol": r["symbol"], "decision": "auto_apply_disabled_or_preview"})
            continue
        # Apply via the hard-guarded engine (paper-only, stop-up-only, REPLACE).
        try:
            import apply_paper_protection_adjustment as ap
            res = ap.apply(r["id"], operator="ATM_auto",
                           reason=f"ATM auto-apply (paper) {action}", confirm=True)
            ok = bool(res.get("ok") or res.get("applied") or res.get("status") == "applied")
            if ok:
                out["auto_applied"] += 1
                out["details"].append({"id": r["id"], "symbol": r["symbol"], "decision": "auto_applied", "action": action})
            elif str(res.get("status") or "").upper() == "NOT_APPLICABLE":
                # Structurally not placeable (e.g. shares fully held by the existing stop) — marked terminal by
                # the engine, NOT retried. Count as skipped, not failed, so the summary stays honest.
                out["skipped_action"] += 1
                out["details"].append({"id": r["id"], "symbol": r["symbol"], "decision": "not_applicable",
                                       "action": action, "reason": str(res.get("block_reason") or "")[:120]})
            else:
                out["failed"] += 1
                out["details"].append({"id": r["id"], "symbol": r["symbol"], "decision": "apply_failed",
                                       "reason": str(res)[:120]})
        except Exception as e:
            out["failed"] += 1
            out["details"].append({"id": r["id"], "symbol": r["symbol"], "decision": "apply_error", "error": str(e)[:120]})
    return out


def main():
    import argparse, json
    ap = argparse.ArgumentParser(description="ATM protection auto-apply pass")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    print(json.dumps(run_protection_pass(mode="dry" if a.dry_run else "active", dry_run=a.dry_run), indent=2, default=str))


if __name__ == "__main__":
    main()
