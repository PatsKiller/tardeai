"""Communications Gateway — canonical CommunicationEvent client (Phase 1).

Public API:
  - CommunicationEvent
  - publish_communication
  - new_event_id / idempotency_key_for
  - get_gateway_mode / MODE_*

Phase 1 does NOT own provider delivery. Modes default to OFF.
"""
from __future__ import annotations

from scripts.lib.comms.client import PublishResult, publish_communication
from scripts.lib.comms.event import CommunicationEvent, required_missing
from scripts.lib.comms.identity import idempotency_key_for, new_event_id
from scripts.lib.comms.mode import (
    MODE_ACTIVE,
    MODE_CANARY,
    MODE_OFF,
    MODE_SHADOW,
    VALID_MODES,
    get_gateway_mode,
    mode_diagnostics,
)

__all__ = [
    "CommunicationEvent",
    "PublishResult",
    "publish_communication",
    "new_event_id",
    "idempotency_key_for",
    "required_missing",
    "MODE_OFF",
    "MODE_SHADOW",
    "MODE_CANARY",
    "MODE_ACTIVE",
    "VALID_MODES",
    "get_gateway_mode",
    "mode_diagnostics",
]
