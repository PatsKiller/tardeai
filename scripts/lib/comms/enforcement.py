"""Runtime enforcement helpers for the communications gateway.

Phase 2: fail closed when a transport path is invoked without an event_id.
Full network egress confinement remains an ops/runtime concern; this module is
the in-process contract gate.
"""
from __future__ import annotations


class MissingCommunicationEventId(RuntimeError):
    """Raised when a provider adapter is asked to send without a ledger event_id."""


def require_event_id(event_id: str | None, *, adapter: str = "transport") -> str:
    """Reject provider sends that are not bound to a CommunicationEvent.

    Phase 1/2 compatibility: callers that have not yet migrated will fail here
    once wired. Until wired, legacy paths still bypass this gate — tracked by
    the static chokepoint ratchets.
    """
    if not event_id or not str(event_id).strip():
        raise MissingCommunicationEventId(
            f"{adapter}: provider call forbidden without communication event_id"
        )
    return str(event_id).strip()


def assert_delivery_not_owned_in_off_or_shadow(gateway_mode: str, *, delivery_owned: bool) -> None:
    """Invariant: OFF/SHADOW must never claim delivery ownership."""
    mode = (gateway_mode or "OFF").upper()
    if mode in ("OFF", "SHADOW") and delivery_owned:
        raise RuntimeError(
            f"delivery_owned=True illegal while COMMS_GATEWAY_MODE={mode}"
        )
