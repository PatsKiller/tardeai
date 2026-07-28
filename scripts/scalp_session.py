#!/usr/bin/env python3
"""Momentum-scalp SESSION CLOCK — deterministic session phases and per-setup fire windows.

Replaces the engine's regular-hours-only assumption with explicit windows (arch-owner 2026-07-27):

    06:00-active_fire_start : collect + calculate context only (no alert/fire unless start configured 06:00)
    active_fire_start-09:29 : eligible PREMARKET setup detection (default 07:00)
    09:30-12:00             : eligible REGULAR setup detection (subject to each setup's own window)
    after 12:00             : no NEW FIRED state; existing positions managed/journaled

Phases: PREMARKET | REGULAR | POST_CUTOFF | CLOSED.
market_session (for the event contract + which denominators to use): PREMARKET | REGULAR.

Pure & testable: every function takes an explicit wall-clock `now` (America/New_York) so there is no
hidden clock. Premarket and regular denominators are NEVER mixed (see market_session()).
"""
from __future__ import annotations

from datetime import time as _time
from typing import Mapping

PREMARKET = "PREMARKET"
REGULAR = "REGULAR"
POST_CUTOFF = "POST_CUTOFF"
CLOSED = "CLOSED"


def _t(hhmm: str) -> _time:
    h, m = (int(x) for x in str(hhmm).split(":")[:2])
    return _time(h, m)


def session_config(cfg: Mapping) -> dict:
    """Normalize the session block into time objects, applying defaults if the additive keys are absent."""
    s = cfg.get("session", {}) if cfg else {}
    ctx = s.get("context_collection_start", "06:00")
    active = s.get("active_fire_start", "07:00")
    active_min = s.get("active_fire_start_min", "06:00")
    # active_fire_start may never be earlier than the configured minimum (fail-safe clamp)
    if _t(active) < _t(active_min):
        active = active_min
    return {
        "tz": s.get("tz", "America/New_York"),
        "context_collection_start": _t(ctx),
        "active_fire_start": _t(active),
        "active_fire_start_min": _t(active_min),
        "regular_open": _t(s.get("regular_open", "09:30")),
        "no_new_fire_after": _t(s.get("no_new_fire_after", "12:00")),
        "regular_close": _t(s.get("regular_close", "16:00")),
    }


def phase(now: _time, cfg: Mapping) -> str:
    """4-way session clock at wall-clock `now` (ET)."""
    sc = session_config(cfg)
    if now < sc["context_collection_start"] or now >= sc["regular_close"]:
        return CLOSED
    if now < sc["regular_open"]:
        return PREMARKET
    if now < sc["no_new_fire_after"]:
        return REGULAR
    return POST_CUTOFF


def market_session(now: _time, cfg: Mapping) -> str | None:
    """Which denominators/VWAP apply: PREMARKET (06:00-09:29) or REGULAR (09:30-16:00); None if CLOSED.
    NOTE: premarket and regular denominators must never be mixed — callers key their profile on this."""
    ph = phase(now, cfg)
    if ph == PREMARKET:
        return PREMARKET
    if ph in (REGULAR, POST_CUTOFF):
        return REGULAR
    return None


def new_fire_allowed(now: _time, cfg: Mapping) -> bool:
    """A NEW setup FIRED state is allowed only in [active_fire_start, no_new_fire_after).
    06:00-active_fire_start is context-only (unless the operator sets active_fire_start=06:00)."""
    sc = session_config(cfg)
    return sc["active_fire_start"] <= now < sc["no_new_fire_after"]


def window_contains(window_et: str, now: _time) -> bool:
    """Does 'HH:MM-HH:MM' (inclusive start, inclusive end minute) contain `now`?"""
    try:
        lo, hi = window_et.split("-")
    except (ValueError, AttributeError):
        return False
    return _t(lo) <= now <= _t(hi)


def setup_eligible(setup: Mapping, now: _time, cfg: Mapping) -> tuple[bool, str]:
    """Is a setup eligible to reach FIRED at `now`? Returns (ok, reason).
    Requires: global new-fire window open AND current market_session in the setup's supported_sessions
    AND (for REGULAR setups) the setup's static active_window_et contains `now`. This is a gate on the
    FIRED transition only — SCANNING/ARMED bookkeeping may continue outside it.

    PREMARKET setups do NOT use a static window lower bound: their effective window is
    [session.active_fire_start, regular_open), so the operator can move the active start (e.g. to 06:00)
    without a code or registry change (new_fire_allowed already enforces active_fire_start)."""
    if not new_fire_allowed(now, cfg):
        sc = session_config(cfg)
        if now >= sc["no_new_fire_after"]:
            return False, "OUTSIDE_WINDOW_POST_NOON_CUTOFF"
        return False, "OUTSIDE_WINDOW_BEFORE_ACTIVE_START"
    ms = market_session(now, cfg)
    if ms not in (setup.get("supported_sessions") or []):
        return False, f"SESSION_NOT_SUPPORTED_{ms}"
    if ms == REGULAR and not window_contains(setup.get("active_window_et", ""), now):
        return False, "OUTSIDE_SETUP_WINDOW"
    return True, "ELIGIBLE"
