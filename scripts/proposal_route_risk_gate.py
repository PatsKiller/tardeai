#!/usr/bin/env python3
"""proposal_route_risk_gate.py — Fail-closed risk gate for proposal approve/route paths."""
from __future__ import annotations


def check_proposal_risk(
    conn,
    *,
    symbol: str,
    strategy_id: str,
    trade_plan: dict,
    account: str,
    live_route: bool = False,
) -> dict:
    """Run risk_gate with broker_submit / approval_ready context; fail-closed on errors."""
    try:
        from risk_gate import RiskGate
        gate = RiskGate(conn)
        ctx = "broker_submit" if live_route else "approval_ready"
        mode = "live" if live_route else "paper"
        decision = gate.check(
            symbol=symbol,
            strategy_id=strategy_id,
            trade_plan=trade_plan or {},
            account=account,
            mode=mode,
            action_context=ctx,
        )
        approved = bool(decision.approved)
        if decision.result == "RISK_GATE_ERROR":
            approved = False
        return {
            "approved": approved,
            "result": decision.result,
            "reason_codes": list(decision.reason_codes or []),
            "action_context": ctx,
        }
    except Exception as e:
        return {
            "approved": False,
            "result": "RISK_GATE_ERROR",
            "reason_codes": [str(e)[:120]],
            "action_context": "broker_submit" if live_route else "approval_ready",
        }