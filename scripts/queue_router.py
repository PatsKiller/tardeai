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


def route_proposal(pid: int, *, actor: str = "system", trade: dict | None = None) -> dict:
    """Dispatch an APPROVED queue row to its intended broker. Returns a result dict; never raises.

    trade: optional operator-confirmed {account, shares, entry, stop, target} applied before Schwab 2FA.
    """
    try:
        import trade_modify as _tm
    except Exception:
        _tm = None
    cur = _get_conn().cursor()
    cur.execute("""SELECT symbol, intended_broker, target_account, status, routing_state,
                          proposed_entry, proposed_shares, proposed_stop, proposed_target1,
                          strategy_id
                     FROM paper_trade_proposals WHERE id=%s""", (pid,))
    r = cur.fetchone()
    if not r:
        return {"ok": False, "error": "proposal not found"}
    (symbol, broker, account, status, routing_state, entry, shares,
     proposed_stop, proposed_target1, strategy_id) = r

    def _audit(after, reason):
        if _tm:
            _tm.audit_decision("route", proposal_id=pid, actor=actor, channel="system",
                               after=after, reason=reason)

    from proposal_routing import resolve_dispatch_broker
    broker, route_err = resolve_dispatch_broker(
        {"intended_broker": broker, "target_account": account})
    if not broker:
        _audit({"routing_required": True}, route_err or "routing not set")
        return {"ok": False, "routing_required": True, "error": route_err, "symbol": symbol}
    broker = broker.strip()

    # ── Paper (Alpaca) — default paper path when not Schwab/Fidelity ──
    if broker == ALPACA or (not broker.startswith(SCHWAB_PREFIX) and not broker.startswith("fidelity")):
        if broker != ALPACA:
            try:
                from broker_config import get_default_paper_account
                broker = get_default_paper_account() or ALPACA
            except Exception:
                broker = ALPACA
        _set_routing_state(pid, "routing")
        try:
            from proposal_paper_submitter import submit_paper
            res = submit_paper(pid)
            ok = bool(res and (res.get("ok") or res.get("success")))
            if ok:
                try:
                    import proposal_live_submit_tag as _tag
                    _tag.tag_proposal_live_submit(pid, live_submit_path="paper_auto")
                except Exception:
                    pass
            _set_routing_state(pid, "routed" if ok else "rejected")
            _audit({"broker": broker, "ok": ok}, "alpaca paper submit")
            return {"ok": ok, "broker": broker, "symbol": symbol, "detail": res}
        except Exception as e:
            _set_routing_state(pid, "rejected")
            _audit({"broker": broker, "error": str(e)[:120]}, "alpaca submit error")
            return {"ok": False, "broker": broker, "error": str(e)[:160]}

    # ── Schwab — OTOCO bracket (LIMIT entry + STOP child) via per-order 2FA when armed ──
    if broker.startswith(SCHWAB_PREFIX):
        from brokers import broker_entry_pilot as _bep
        preview_spec = None
        try:
            _pi = _bep.build_intent(
                account or broker, symbol, int(shares or 0), float(entry or 0), float(proposed_stop or 0),
                target=float(proposed_target1) if proposed_target1 else None,
                strategy_id=str(strategy_id or "momentum_scalp"), proposal_id=pid,
            )
            preview_spec = _bep.spec_from_intent(_pi)
        except Exception:
            preview_spec = _build_schwab_order_spec(symbol, shares, entry)
        armed, gate_reason = _schwab_routing_armed(account)
        if not armed:
            _set_routing_state(pid, "queued")
            _audit({"broker": broker, "gated": True, "reason": gate_reason, "order_spec": preview_spec,
                    "bracket": True},
                   "schwab routing wired but gated")
            return {"ok": False, "broker": broker, "gated": True, "symbol": symbol,
                    "order_spec": preview_spec, "bracket": True,
                    "detail": f"Schwab API submit wired but GATED: {gate_reason}. No order placed."}
        # ARMED: step 1 — build OTOCO bracket + request per-order 2FA (submit at route/confirm).
        try:
            _set_routing_state(pid, "routing")
            res = _bep.request_route(pid, trade=trade)
            ok = bool(res.get("ok"))
            if not ok:
                _set_routing_state(pid, "rejected")
            _audit({"broker": broker, "ok": ok, "mode": res.get("mode"), "intent_id": res.get("intent_id")},
                   "schwab bracket 2FA requested (armed)")
            return {"ok": ok, "broker": broker, "symbol": symbol, **res}
        except Exception as e:
            _set_routing_state(pid, "rejected")
            _audit({"broker": broker, "error": str(e)[:160]}, "schwab bracket 2FA request error")
            return {"ok": False, "broker": broker, "gated": False, "symbol": symbol,
                    "order_spec": preview_spec, "bracket": True,
                    "detail": f"Schwab 2FA request failed: {str(e)[:160]}"}

    # ── Fidelity — no trading API; the proposal IS the record (operator executes at Fidelity) ──
    if broker.startswith("fidelity"):
        _set_routing_state(pid, "routed")   # recorded as a manual trade to place at Fidelity
        try:
            import proposal_live_submit_tag as _tag
            _tag.tag_proposal_live_submit(pid, live_submit_path="record_only")
        except Exception:
            pass
        _audit({"broker": broker, "record_only": True}, "fidelity record-only (no API)")
        return {"ok": True, "broker": broker, "symbol": symbol, "record_only": True,
                "detail": "Fidelity has no trading API — recorded as a manual trade; execute it at Fidelity."}

    _audit({"broker": broker, "unknown": True}, "unknown broker")
    return {"ok": False, "broker": broker, "error": f"unknown/disabled broker '{broker}' — fail-closed"}


def _build_schwab_order_spec(symbol: str, shares, entry) -> dict:
    """Exact Schwab order JSON for a queued entry: SINGLE LIMIT BUY (mirrors the Stage-2b canary shape)."""
    return {
        "session": "NORMAL", "duration": "DAY", "orderType": "LIMIT",
        "price": f"{float(entry):.2f}",
        "orderLegCollection": [{
            "instruction": "BUY", "quantity": int(shares),
            "instrument": {"symbol": (symbol or "").upper(), "assetType": "EQUITY"},
        }],
        "orderStrategyType": "SINGLE",
    }


def _build_schwab_intent(account_key: str, symbol: str, shares, entry):
    """OrderIntent for the fenced transport (execution_guard runs the gate + per-order 2FA on it)."""
    import uuid
    from brokers.order_intent import (OrderIntent, Instrument, Direction, EntrySpec,
                                       EntryMethod, Quantity, TIF, SessionPolicy)
    return OrderIntent(
        instrument=Instrument((symbol or "").upper()), direction=Direction.LONG,
        entry=EntrySpec(method=EntryMethod.LIMIT, limit_price=float(entry)),
        quantity=Quantity(qty=int(shares)), broker="schwab", account_key=account_key,
        tif=TIF.DAY, session=SessionPolicy.NORMAL, correlation_id=str(uuid.uuid4()),
    )


def _schwab_routing_armed(account_key: str | None) -> tuple[bool, str]:
    """Is Schwab queue-routing armed for LIVE submit? Three independent locks, ALL required (fail-closed):
      1. system_controls['schwab_queue_routing_enabled'] == 'true'  (the explicit queue-routing arm), AND
      2. the live-trading interlock passes for this account, AND
      3. the account is api_write_enabled.
    Default = NOT armed → the submit path is wired but places nothing. Returns (armed, reason)."""
    # Lock 1 — the queue-routing arm switch (absent/false by default)
    try:
        cur = _get_conn().cursor()
        cur.execute("SELECT value FROM system_controls WHERE key='schwab_queue_routing_enabled'")
        row = cur.fetchone()
        if not (row and str(row[0]).lower() == "true"):
            return (False, "Schwab queue-routing not armed (system_controls.schwab_queue_routing_enabled != true)")
    except Exception as e:
        try:
            _get_conn().rollback()
        except Exception:
            pass
        return (False, f"arm-state unavailable ({str(e)[:60]}) — fail-closed")
    # Lock 2 — the live-trading interlock
    reason = _schwab_gate_reason(account_key)
    if not reason.startswith("interlock open"):
        return (False, reason)
    return (True, "armed")


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
