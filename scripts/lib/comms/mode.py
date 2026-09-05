"""Communications gateway runtime mode (product vocabulary).

OFF     Ledger may record; gateway does not own delivery.
SHADOW  Ledger + decision compare; no delivery ownership.
CANARY  Limited channels/recipients/classes (later phases).
ACTIVE  Gateway owns delivery for activated classes (later phases).

Fail-closed: unrecognized values resolve to OFF.
"""
from __future__ import annotations

import os
import threading
from typing import Any

MODE_OFF = "OFF"
MODE_SHADOW = "SHADOW"
MODE_CANARY = "CANARY"
MODE_ACTIVE = "ACTIVE"
VALID_MODES = (MODE_OFF, MODE_SHADOW, MODE_CANARY, MODE_ACTIVE)

ENV_VAR = "COMMS_GATEWAY_MODE"

_lock = threading.Lock()
_cache: dict[str, Any] = {"mode": None, "why": None}


def resolve_mode(*, refresh: bool = False) -> tuple[str, str]:
    with _lock:
        if not refresh and _cache["mode"] is not None:
            return _cache["mode"], _cache["why"]
        raw = (os.getenv(ENV_VAR) or "").strip().upper()
        if not raw:
            mode, why = MODE_OFF, "default_off"
        elif raw in VALID_MODES:
            mode, why = raw, f"env:{ENV_VAR}"
        else:
            mode, why = MODE_OFF, f"env_invalid_value:{raw[:24]}"
        _cache["mode"], _cache["why"] = mode, why
        return mode, why


def get_gateway_mode(*, refresh: bool = False) -> str:
    return resolve_mode(refresh=refresh)[0]


def mode_diagnostics(*, refresh: bool = False) -> dict[str, Any]:
    mode, why = resolve_mode(refresh=refresh)
    return {
        "mode": mode,
        "reason": why,
        "default": MODE_OFF,
        "env_var": ENV_VAR,
        "valid_modes": list(VALID_MODES),
        "delivery_owner": (
            "legacy_or_none"
            if mode in (MODE_OFF, MODE_SHADOW)
            else "gateway_canary_or_active"
        ),
        "phase1_note": "Phase 1 never performs provider calls from publish_communication.",
    }
