"""HermesRuntimeStatus@v1 — oneshot / event-driven queue taxonomy.

READ_ONLY_ADVISORY. This module classifies Hermes runtime for the control plane.
It never sends messages, never starts workers, and never mutates financial truth.

Invariant: a Type=oneshot (no long-lived daemon) worker with an empty queue is
EXPECTED_IDLE — not FAILED, not BROKEN. NO_DAEMON is a valid architecture.
"""
from __future__ import annotations

from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "HermesRuntimeStatus@v1"
MEMORY_BEHAVIOR_INFLUENCE = 0

# Exact state strings (Lane C / R20 data-plane V2 contract).
ON_DEMAND_READY = "ON_DEMAND_READY"
ON_DEMAND_RUNNING = "ON_DEMAND_RUNNING"
EVENT_DRIVEN_IDLE = "EVENT_DRIVEN_IDLE"
QUEUE_WAITING = "QUEUE_WAITING"
QUEUE_ACTIVE = "QUEUE_ACTIVE"
SCHEDULED = "SCHEDULED"
EXPECTED_IDLE = "EXPECTED_IDLE"
DEGRADED = "DEGRADED"
FAILED = "FAILED"
DISABLED = "DISABLED"
UNKNOWN = "UNKNOWN"

STATES = (
    ON_DEMAND_READY,
    ON_DEMAND_RUNNING,
    EVENT_DRIVEN_IDLE,
    QUEUE_WAITING,
    QUEUE_ACTIVE,
    SCHEDULED,
    EXPECTED_IDLE,
    DEGRADED,
    FAILED,
    DISABLED,
    UNKNOWN,
)

# Architecture families. Hermes CIO worker is systemd Type=oneshot.
_ON_DEMAND = frozenset({"oneshot", "on_demand", "ondemand", "on-demand"})
_EVENT = frozenset({"event", "event_driven", "eventdriven", "event-driven"})
_QUEUE = frozenset({"queue", "event_driven_queue", "event-driven-queue"})
_SCHED = frozenset({"scheduled", "schedule", "timer"})
_UNKNOWN_ARCH = frozenset({"unknown", "unspecified"})

_FALSEY_ERROR = frozenset({"", "none", "false", "0", "ok", "null"})


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _first(kwargs: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in kwargs:
            return kwargs[key]
    return default


def _as_int(value: Any, *, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is True or value is False:
        return value
    if value is None:
        return default
    token = str(value).strip().lower()
    if token in {"1", "true", "yes", "on"}:
        return True
    if token in {"0", "false", "no", "off"}:
        return False
    return default


def _explicit_error(value: Any) -> Optional[str]:
    """FAILED is reserved for an explicit error object/string. Never inferred."""
    if value is None or value is False:
        return None
    if value is True:
        return "error"
    if isinstance(value, BaseException):
        return f"{type(value).__name__}: {value}"
    token = str(value).strip()
    if not token or token.lower() in _FALSEY_ERROR:
        return None
    return token


def _mode_for(architecture: str) -> str:
    if architecture in _ON_DEMAND:
        return "ON_DEMAND"
    if architecture in _EVENT:
        return "EVENT_DRIVEN"
    if architecture in _SCHED:
        return "SCHEDULED"
    if architecture in _QUEUE:
        return "QUEUE"
    if architecture in _UNKNOWN_ARCH:
        return "UNKNOWN"
    return "ON_DEMAND"


def _result(*, mode: str, state: str, pending: int, reason: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "mode": mode,
        "state": state,
        "pending": int(pending),
        "reason": reason,
        "authority": AUTHORITY,
        "memory_behavior_influence": MEMORY_BEHAVIOR_INFLUENCE,
    }


def classify(**kwargs: Any) -> dict[str, Any]:
    """Classify Hermes runtime from advisory inputs.

    Expected kwargs (all optional; extra keys ignored):

    * pending / queue_pending / pending_count
    * worker_running / running / worker_alive
    * enabled
    * error / exception
    * architecture / mode / architecture_mode
      (oneshot, event_driven, scheduled, queue, unknown)
    * drain / oneshot_drain / draining
    * ready
    * degraded / stale
    * no_daemon
    * reason

    Rules:
    - oneshot / event-driven architecture is valid
    - pending==0 and worker not running → EXPECTED_IDLE (not FAILED, not BROKEN)
    - pending>0 and worker not running → QUEUE_WAITING
    - worker running and pending>0 (queue architecture) → QUEUE_ACTIVE
    - worker running oneshot drain → ON_DEMAND_RUNNING
    - DISABLED if enabled=False
    - FAILED only on explicit error
    - NO_DAEMON != BROKEN
    """
    enabled = _as_bool(_first(kwargs, "enabled", default=True), default=True)
    pending = _as_int(
        _first(kwargs, "pending", "queue_pending", "pending_count", default=0),
        default=0,
    )
    worker_running = _as_bool(
        _first(kwargs, "worker_running", "running", "worker_alive", default=False),
        default=False,
    )
    architecture = _norm(
        _first(kwargs, "architecture", "architecture_mode", default="oneshot")
    )
    # `mode` is an architecture alias only when it is not already a runtime state.
    mode_kw = _norm(_first(kwargs, "mode"))
    if not architecture or architecture == "oneshot":
        if mode_kw in _ON_DEMAND | _EVENT | _QUEUE | _SCHED | _UNKNOWN_ARCH:
            architecture = mode_kw
    if not architecture:
        architecture = "oneshot"

    drain = _as_bool(
        _first(kwargs, "drain", "oneshot_drain", "draining", default=False),
        default=False,
    )
    ready = _as_bool(_first(kwargs, "ready", default=False), default=False)
    degraded = _as_bool(
        _first(kwargs, "degraded", "stale", default=False),
        default=False,
    )
    given_reason = _first(kwargs, "reason")
    if given_reason is not None:
        given_reason = str(given_reason).strip() or None

    oneshot = architecture in _ON_DEMAND or drain
    evented = architecture in _EVENT
    queued = architecture in _QUEUE
    scheduled = architecture in _SCHED
    mode = _mode_for(architecture if not drain or architecture in _ON_DEMAND else "oneshot")
    if drain and mode not in {"ON_DEMAND", "QUEUE"}:
        mode = "ON_DEMAND"

    if enabled is False:
        return _result(
            mode=mode,
            state=DISABLED,
            pending=pending,
            reason=given_reason or "enabled=false",
        )

    explicit_error = _explicit_error(_first(kwargs, "error", "exception"))
    if explicit_error:
        return _result(
            mode=mode,
            state=FAILED,
            pending=pending,
            reason=given_reason or explicit_error,
        )

    if degraded:
        return _result(
            mode=mode,
            state=DEGRADED,
            pending=pending,
            reason=given_reason or "degraded",
        )

    if architecture in _UNKNOWN_ARCH and not worker_running and pending == 0 and not drain:
        return _result(
            mode=UNKNOWN,
            state=UNKNOWN,
            pending=pending,
            reason=given_reason or "architecture unknown",
        )

    if worker_running:
        if oneshot or drain:
            return _result(
                mode="ON_DEMAND" if oneshot or drain else mode,
                state=ON_DEMAND_RUNNING,
                pending=pending,
                reason=given_reason or "oneshot drain running",
            )
        if pending > 0 or queued:
            return _result(
                mode=mode if mode != "UNKNOWN" else "QUEUE",
                state=QUEUE_ACTIVE,
                pending=pending,
                reason=given_reason or "worker running with pending work",
            )
        if scheduled:
            return _result(
                mode="SCHEDULED",
                state=SCHEDULED,
                pending=pending,
                reason=given_reason or "scheduled worker running",
            )
        return _result(
            mode=mode,
            state=QUEUE_ACTIVE,
            pending=pending,
            reason=given_reason or "worker running",
        )

    # Worker not running. An empty queue on a oneshot / event-driven worker is
    # healthy idle — never BROKEN, never FAILED merely because there is no daemon.
    if pending > 0:
        return _result(
            mode=mode if mode != "UNKNOWN" else "QUEUE",
            state=QUEUE_WAITING,
            pending=pending,
            reason=given_reason or "pending>0 worker not running",
        )

    if scheduled:
        return _result(
            mode="SCHEDULED",
            state=SCHEDULED,
            pending=pending,
            reason=given_reason or "scheduled waiting for next fire",
        )
    if evented:
        return _result(
            mode="EVENT_DRIVEN",
            state=EVENT_DRIVEN_IDLE,
            pending=pending,
            reason=given_reason or "event-driven idle",
        )
    if oneshot and ready:
        return _result(
            mode="ON_DEMAND",
            state=ON_DEMAND_READY,
            pending=pending,
            reason=given_reason or "on-demand ready",
        )
    return _result(
        mode="ON_DEMAND" if oneshot or mode == "UNKNOWN" else mode,
        state=EXPECTED_IDLE,
        pending=pending,
        reason=given_reason or "oneshot idle; no daemon",
    )
