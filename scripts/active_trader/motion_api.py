"""Read-only aggregate Active Trader motion endpoint body.

``motion_snapshot()`` reads the LATEST line of the persistent shadow observation
journal, freshness-gates it, and returns the ``active-trader-motion-snapshot-v1``
envelope. It is a PURE READ: it never appends to the journal, never touches a broker,
session, credential, order path, or LLM. ``EXIT_SIGNAL`` present in the payload is
EVIDENCE ONLY — this endpoint exposes it and never acts on it.

Honest failure posture:
* journal absent / empty  -> an "unavailable" envelope (a DISTINCT contract string so
  the UI's ``contractOk`` is false and it fails closed to MOTION API UNAVAILABLE); no
  fabricated leases/positions/signals.
* journal present but stale -> the last-good motion snapshot returned verbatim (its old
  ``generated_at`` preserved so the UI computes staleness itself) plus an explicit
  ``stale: true`` / ``last_update_age_s`` marker.
* journal present + fresh  -> the last-good snapshot with ``stale: false`` + age.
"""
from __future__ import annotations

import math
import os
import time
from typing import Any, Optional

from .motion_journal import latest_snapshot

MOTION_CONTRACT = "active-trader-motion-snapshot-v1"
MOTION_UNAVAILABLE_CONTRACT = "active-trader-motion-unavailable-v1"

# Operating defaults surfaced even in the unavailable envelope (documentary, not live).
_OPERATING_CAP = 2
_PROVIDER_HARD_CAP = 8
_MAX_PULL_FALLBACKS_PER_MINUTE = 2

# A snapshot older than this (seconds) is treated as stale. Roughly 2x the idle refresh
# hint (30s). Env-overridable for calibration; never negative.
_DEFAULT_MAX_AGE_S = 60.0

_ZERO_AUTHORITY = {
    "mutation": False,
    "order": False,
    "session_authorize": False,
    "canary": False,
    "financial_action": False,
}


def _max_age_s(override: Optional[float]) -> float:
    if override is not None:
        return max(0.0, float(override))
    env = os.environ.get("ACTIVE_TRADER_MOTION_MAX_AGE_S", "").strip()
    if env:
        try:
            return max(0.0, float(env))
        except ValueError:
            pass
    return _DEFAULT_MAX_AGE_S


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    return v if math.isfinite(v) else None


def _unavailable_envelope(now: float, detail: str) -> dict[str, Any]:
    """Honest 'never got a good snapshot' envelope. Distinct contract -> contractOk
    false in the UI. Empty motion collections -> nothing fabricated."""
    return {
        "contract": MOTION_UNAVAILABLE_CONTRACT,
        "available": False,
        "stale": True,
        "data_state": "MOTION_API_UNAVAILABLE",
        "detail": detail,
        "generated_at": float(now),
        "last_update_age_s": None,
        "ui_refresh_after_s": 30,
        "push_primary": True,
        "max_pull_fallbacks_per_minute": _MAX_PULL_FALLBACKS_PER_MINUTE,
        "t2": {
            "operating_cap": _OPERATING_CAP,
            "provider_hard_cap": _PROVIDER_HARD_CAP,
            "leases": [],
            "decisions": [],
        },
        "positions": [],
        "exit_signals": [],
        "read_only": True,
        "write": False,
        "authority": dict(_ZERO_AUTHORITY),
    }


def _finalize(snapshot: dict[str, Any], *, stale: bool, age: Optional[float]) -> dict[str, Any]:
    """Return the journal snapshot with the read-only envelope guarantees re-asserted.
    We never trust the persisted authority block — it is forced closed here."""
    body = dict(snapshot)
    body["read_only"] = True
    body["write"] = False
    body["authority"] = dict(_ZERO_AUTHORITY)
    body["stale"] = bool(stale)
    body["last_update_age_s"] = age
    body["data_state"] = "DATA_STALE" if stale else "LIVE_DATA"
    return body


def motion_snapshot(
    *,
    now: Optional[float] = None,
    max_age_s: Optional[float] = None,
    path: Any = None,
) -> dict[str, Any]:
    """Return the aggregate motion snapshot envelope. PURE READ — never writes the
    journal, never touches broker/session/order/LLM. Fail-closed and honest."""
    current = time.time() if now is None else float(now)

    latest = latest_snapshot(path=path)
    if not isinstance(latest, dict) or not latest:
        return _unavailable_envelope(
            current,
            "motion journal empty or absent; shadow producer has not run yet",
        )

    if latest.get("contract") != MOTION_CONTRACT:
        # The journal held something, but not a recognized motion snapshot: do not
        # surface it as live. Fail closed to unavailable.
        return _unavailable_envelope(
            current, "latest journal entry did not declare the motion contract"
        )

    gen = _finite(latest.get("generated_at"))
    age = None if gen is None else max(0.0, current - gen)

    limit = _max_age_s(max_age_s)
    if age is None or age > limit:
        return _finalize(latest, stale=True, age=age)

    return _finalize(latest, stale=False, age=age)
