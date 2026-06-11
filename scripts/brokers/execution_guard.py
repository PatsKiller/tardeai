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


def authorize(intent: OrderIntent, action: str = "submit") -> GuardDecision:
    """The single gate every adapter call must pass. Audited regardless of outcome."""
    mode = mode_for(intent.broker)
    if mode == BrokerExecutionMode.PAPER_TRAINING and intent.broker == "alpaca":
        d = GuardDecision(True, mode, "alpaca paper training path (existing pipeline)", intent.correlation_id)
    elif mode == BrokerExecutionMode.BROKER_DRY_RUN:
        d = GuardDecision(action in ("translate", "preview", "validate"), mode,
                          "dry-run: local translate/validate/audit only — order-endpoint I/O prohibited "
                          "(operator decision 2026-06-11)", intent.correlation_id)
    elif mode == BrokerExecutionMode.LIVE_ENABLED_FUTURE and _live_future_unlocked():
        # 4th lock (operator requirement 2026-06-11): per-trade TWO-FACTOR approval — web popup AND
        # telegram code, both confirmed, unexpired, single-use. Even with all standing locks open,
        # an unapproved intent is denied. (And this phase's adapter still blocks unconditionally.)
        try:
            from .approval_service import is_fully_approved
            twofa = is_fully_approved(intent.intent_id)
        except Exception:
            twofa = False
        d = GuardDecision(False, mode,
                          ("2FA approved but LIVE execution is out of scope this phase (adapter blocks "
                           "unconditionally)" if twofa else
                           "DENIED: per-trade two-factor approval missing/incomplete (web + telegram both "
                           "required)"), intent.correlation_id)
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
