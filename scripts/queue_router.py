#!/usr/bin/env python3
"""queue_router.py — one approval queue, broker-aware dispatch (operator 2026-06-19).

Every queue row (paper_trade_proposals) — whether it originated from the automated pipeline (origin=
'auto') or a manual web/Telegram submission (origin='manual_*') — flows through ONE approval queue and
is dispatched here by `intended_broker`:

  • alpaca_paper → the existing paper submit path (proposal_paper_submitter) — LIVE today, paper-only.
  • schwab_*     → PREPARED but GATED. Schwab live routing reuses the protective-stop transport + the
                   live-trading interlock; until the operator explicitly arms it this returns 'gated'
                   and places NOTHING. This is the drop-in lane for future Charles Schwab routing.

Routing is audited (queue_decision_audit, action='route'). Fail-closed: an unknown/disabled broker
never places an order.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db_adapter import _get_conn

ALPACA = "alpaca_paper"
SCHWAB_PREFIX = "schwab"


def _set_routing_state(pid: int, state: str) -> None:
    try:
        conn = _get_conn(); cur = conn.cursor()
        cur.execute("UPDATE paper_trade_proposals SET routing_state=%s WHERE id=%s", (state, pid))
        conn.commit()
    except Exception:
        try:
            _get_conn().rollback()
        except Exception:
            pass


def route_proposal(pid: int, *, actor: str = "system") -> dict:
    """Dispatch an APPROVED queue row to its intended broker. Returns a result dict; never raises."""
    try:
        import trade_modify as _tm
    except Exception:
        _tm = None
    cur = _get_conn().cursor()
    cur.execute("""SELECT symbol, intended_broker, target_account, status, routing_state
                     FROM paper_trade_proposals WHERE id=%s""", (pid,))
    r = cur.fetchone()
    if not r:
        return {"ok": False, "error": "proposal not found"}
    symbol, broker, account, status, routing_state = r
    broker = (broker or ALPACA).strip()

    def _audit(after, reason):
        if _tm:
            _tm.audit_decision("route", proposal_id=pid, actor=actor, channel="system",
                               after=after, reason=reason)

    # ── Alpaca paper — the live path today (paper-only) ──
    if broker == ALPACA:
        _set_routing_state(pid, "routing")
        try:
            from proposal_paper_submitter import submit_paper
            res = submit_paper(pid)
            ok = bool(res and (res.get("ok") or res.get("success")))
            _set_routing_state(pid, "routed" if ok else "rejected")
            _audit({"broker": broker, "ok": ok}, "alpaca paper submit")
            return {"ok": ok, "broker": broker, "symbol": symbol, "detail": res}
        except Exception as e:
            _set_routing_state(pid, "rejected")
            _audit({"broker": broker, "error": str(e)[:120]}, "alpaca submit error")
            return {"ok": False, "broker": broker, "error": str(e)[:160]}

    # ── Schwab — PREPARED but GATED (no live order until explicitly armed) ──
    if broker.startswith(SCHWAB_PREFIX):
        gated_reason = _schwab_gate_reason(account)
        _set_routing_state(pid, "queued")  # stays queued; nothing placed
        _audit({"broker": broker, "gated": True, "reason": gated_reason}, "schwab routing gated")
        return {"ok": False, "broker": broker, "gated": True, "symbol": symbol,
                "detail": f"Schwab routing prepared but gated: {gated_reason}. No order placed."}

    # ── Fidelity — no trading API; the proposal IS the record (operator executes at Fidelity) ──
    if broker.startswith("fidelity"):
        _set_routing_state(pid, "routed")   # recorded as a manual trade to place at Fidelity
        _audit({"broker": broker, "record_only": True}, "fidelity record-only (no API)")
        return {"ok": True, "broker": broker, "symbol": symbol, "record_only": True,
                "detail": "Fidelity has no trading API — recorded as a manual trade; execute it at Fidelity."}

    _audit({"broker": broker, "unknown": True}, "unknown broker")
    return {"ok": False, "broker": broker, "error": f"unknown/disabled broker '{broker}' — fail-closed"}


def _schwab_gate_reason(account_key: str | None) -> str:
    """Why Schwab routing is currently gated. Reuses the live-trading interlock (fail-closed)."""
    try:
        from live_trading_interlock import assert_writable, InterlockRefused, _conn as _il_conn
        try:
            assert_writable(_il_conn(), account_key or "", action="write")
            return "interlock open but Schwab queue-routing not yet armed (operator step pending)"
        except InterlockRefused as e:
            return f"live-trading interlock closed ({str(e)[:80]})"
    except Exception as e:
        return f"interlock unavailable ({str(e)[:60]}) — fail-closed"


if __name__ == "__main__":
    import json
    pid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    print(json.dumps(route_proposal(pid), indent=2, default=str))
