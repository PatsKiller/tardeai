"""BrokerExecutionGuard (ADR-B3): fail-closed mode gating + audit. THE safety layer of this program.

Schwab default = BROKER_DISABLED. LIVE_ENABLED_FUTURE is defined but unreachable: it demands env flag + DB
control row + signed approval record, none of which exist, and the Schwab adapter raises unconditionally
anyway. Every decision (grant OR block) is audited with a correlation id.
"""
from __future__ import annotations

import os
from enum import Enum
from dataclasses import dataclass

from .order_intent import OrderIntent
from . import capabilities


class BrokerExecutionMode(str, Enum):
    SIMULATION = "SIMULATION"
    PAPER_TRAINING = "PAPER_TRAINING"        # Alpaca pipeline — never re-pointable to Schwab
    BROKER_DRY_RUN = "BROKER_DRY_RUN"        # local translate+validate+audit; ZERO order-endpoint HTTP
    BROKER_DISABLED = "BROKER_DISABLED"      # Schwab, this phase
    LIVE_ENABLED_FUTURE = "LIVE_ENABLED_FUTURE"


class ExecutionBlocked(Exception):
    """Raised whenever an execution path is reached without an explicit grant."""


@dataclass
class GuardDecision:
    allowed: bool
    mode: BrokerExecutionMode
    reason: str
    correlation_id: str


def mode_for(broker: str) -> BrokerExecutionMode:
    """Resolve the broker's execution mode — fail closed on anything unknown."""
    default = capabilities.get(broker).get("execution_mode_default", "BROKER_DISABLED")
    try:
        return BrokerExecutionMode(default)
    except ValueError:
        return BrokerExecutionMode.BROKER_DISABLED


def _live_future_unlocked() -> bool:
    """ALL three locks must exist; none do this phase. Any error => locked (fail closed)."""
    if os.getenv("BROKER_LIVE_ENABLED", "false").lower() != "true":
        return False
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute("SELECT value FROM system_controls WHERE key='broker_live_enabled'")
        r = cur.fetchone()
        if not r or str(r[0]).lower() != "true":
            return False
        cur.execute("SELECT count(*) FROM broker_live_approvals WHERE revoked_at IS NULL")
        return (cur.fetchone()[0] or 0) > 0
    except Exception:
        return False


_MUTATING_ACTIONS = ("submit", "replace")   # cancel stays allowed-in-principle: cancelling is the safe direction


def authorize(intent: OrderIntent, action: str = "submit") -> GuardDecision:
    """The single gate every adapter call must pass. Audited regardless of outcome."""
    mode = mode_for(intent.broker)
    # ── HARDCODED CANARY GATE (Stage 2a Part D, operator 2026-06-12) ──────────────────────────
    # Evaluated BEFORE the mode logic so no present-or-future allow branch can bypass it. Applies
    # to every mutating action on every broker EXCEPT the alpaca paper-training pipeline (Hard
    # Rule 7: paper gate untouched). The envelope lives in canary_gate.py — commit-only literals;
    # any gate failure (including import failure) denies. Redundant this phase by design.
    if action in _MUTATING_ACTIONS and intent.broker != "alpaca":
        try:
            from .canary_gate import evaluate as _canary_evaluate
            g = _canary_evaluate(intent)
            gate_reason = None if g.allowed else "; ".join(g.reasons)
        except Exception as e:
            gate_reason = f"canary gate unavailable ({str(e)[:60]}) — fail closed"
        if gate_reason:
            d = GuardDecision(False, mode, f"CANARY_GATE BLOCK: {gate_reason}", intent.correlation_id)
            try:
                from .audit import record_guard_decision
                record_guard_decision(intent, action, d)
            except Exception:
                pass
            return d
    if mode == BrokerExecutionMode.PAPER_TRAINING and intent.broker == "alpaca":
        d = GuardDecision(True, mode, "alpaca paper training path (existing pipeline)", intent.correlation_id)
    elif mode == BrokerExecutionMode.BROKER_DRY_RUN:
        d = GuardDecision(action in ("translate", "preview", "validate"), mode,
                          "dry-run: local translate/validate/audit only — order-endpoint I/O prohibited "
                          "(operator decision 2026-06-11)", intent.correlation_id)
    elif mode == BrokerExecutionMode.LIVE_ENABLED_FUTURE and _live_future_unlocked():
        # Stage 2b SB-1 (operator-approved 2026-06-12): the gated branch can now GRANT. Stack at this
        # point: canary gate already passed above (mutating actions) + 3 standing locks open. Remaining
        # per-order locks: pilot caps (account allowlist + cumulative 5-order cap) and per-trade
        # TWO-FACTOR approval (web typed-ticker AND telegram code, unexpired, single-use).
        # Cancel is the safe direction: allowed under open locks without 2FA (audited).
        if action == "cancel":
            d = GuardDecision(True, mode, "cancel granted (safe direction) under unlocked Stage 2b pilot",
                              intent.correlation_id)
        else:
            try:
                from .approval_service import is_fully_approved
                twofa = is_fully_approved(intent.intent_id)
            except Exception:
                twofa = False
            try:
                from .pilot_caps import evaluate as _pilot_eval
                pilot_ok, pilot_reasons = _pilot_eval(intent.account_key)
            except Exception as e:
                pilot_ok, pilot_reasons = False, [f"pilot caps unavailable ({str(e)[:60]}) — fail closed"]
            if not pilot_ok:
                d = GuardDecision(False, mode, "PILOT_CAPS BLOCK: " + "; ".join(pilot_reasons),
                                  intent.correlation_id)
            elif not twofa:
                d = GuardDecision(False, mode,
                                  "DENIED: per-trade two-factor approval missing/incomplete (web + telegram "
                                  "both required)", intent.correlation_id)
            else:
                d = GuardDecision(True, mode,
                                  "GRANTED (Stage 2b pilot): canary envelope + standing locks + pilot caps "
                                  "+ per-trade 2FA all green", intent.correlation_id)
    else:
        d = GuardDecision(False, BrokerExecutionMode.BROKER_DISABLED,
                          f"broker '{intent.broker}' execution disabled (fail-closed default)",
                          intent.correlation_id)
    try:
        from .audit import record_guard_decision
        record_guard_decision(intent, action, d)
    except Exception:
        pass  # audit failure must not grant/extend execution; decision already made
    return d


def require(intent: OrderIntent, action: str = "submit") -> None:
    d = authorize(intent, action)
    if not d.allowed:
        raise ExecutionBlocked(d.reason)
