"""Conflict domain profiles; security rules follow the binding exceptions matrix."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Optional
import math

from ..engine import COMPATIBLE, OPPOSITE, SAME, UNKNOWN, Finding, Input, Subject, side


from .rulebook import RULEBOOK


def _n(v: Any) -> str:
    return str(v or "").strip().upper().replace("-", "_").replace(" ", "_")


# ── 1. security stance (Watch, Home, CIO Desk, Advisory, Telegram escalations, Ask the CIO) ────────────────────────
BUY, HOLD, ASIDE, REDUCE = "buy", "hold", "stand_aside", "reduce"
_SEC = RULEBOOK["security_stance"]
_UNI = RULEBOOK["universal"]
_FAM = {value: family for family, values in _SEC["families"].items() for value in values}


def stance_action(v: Any, held: bool) -> Optional[str]:
    f = _FAM.get(_n(v))
    if f is None:
        return None
    if not held and f in (REDUCE, HOLD):
        return ASIDE                    # can't trim what you don't own; "hold" a non-position = stay out
    if held and f == ASIDE:
        return HOLD if _n(v) in _SEC["held_keep"] else REDUCE
    return f


# ── 2. numeric fact that several pages compute (portfolio total, day P&L, cash, position count) ──────────────────
@dataclass
class NumericFactProfile:
    name: str = "numeric_fact"
    canonical_source: str = "the canonical aggregate"
    canonical_max_age: timedelta = timedelta(hours=RULEBOOK["numeric_fact"]["canonical_max_age_hours"])
    flap_limit: int = _UNI["flap_limit"]
    flap_window: timedelta = timedelta(days=_UNI["flap_window_days"])
    abs_tolerance: float = RULEBOOK["numeric_fact"]["abs_tolerance"]          # dollars (or units) — rounding noise only
    rel_tolerance: float = RULEBOOK["numeric_fact"]["rel_tolerance"]          # money shown on two pages must match to the dollar; a metric that is
                                        # legitimately approximate (e.g. a model estimate) sets its own tolerance
    unit: str = RULEBOOK["numeric_fact"]["unit"]

    def compare(self, a: Any, b: Any, s: Subject) -> str:
        try:
            x, y = float(a), float(b)
        except (TypeError, ValueError):
            return UNKNOWN
        if not math.isfinite(x) or not math.isfinite(y):
            return UNKNOWN
        d = abs(x - y)
        if d <= self.abs_tolerance:
            return SAME
        if d <= abs(x) * self.rel_tolerance:
            return COMPATIBLE
        return OPPOSITE                 # a real mismatch: two pages would show different numbers

    def supersede_after(self, source: str) -> timedelta:
        return timedelta(days=RULEBOOK["numeric_fact"]["supersede_days"])

    def gate_blocks(self, g, canonical, s) -> bool:
        return False

    def protection_finding(self, i, s, canonical) -> Optional[Finding]:
        return None

    def describe(self, v: Any) -> str:
        try:
            return f"{self.unit}{float(v):,.2f}"
        except (TypeError, ValueError):
            return str(v)

    def owner_review_action(self) -> str:
        return "notify_operator"        # a number mismatch is a data defect: fix the reader, never "decide"


# ── 3. schedule state (lane registry vs crontab vs n8n vs last successful run) ───────────────────────────────────
@dataclass
class ScheduleStateProfile:
    name: str = "schedule_state"
    canonical_source: str = "the lane registry"
    canonical_max_age: timedelta = timedelta(days=RULEBOOK["schedule_state"]["canonical_max_age_days"])
    flap_limit: int = _UNI["flap_limit"]
    flap_window: timedelta = timedelta(days=_UNI["flap_window_days"])
    _runs = RULEBOOK["schedule_state"]["runs"]

    def compare(self, a: Any, b: Any, s: Subject) -> str:
        x, y = self._runs.get(_n(a)), self._runs.get(_n(b))
        if x is None or y is None:
            return UNKNOWN
        return SAME if x == y else OPPOSITE

    def supersede_after(self, source: str) -> timedelta:
        return timedelta(days=RULEBOOK["schedule_state"]["supersede_days"])     # a crontab line is never "too old" to matter

    def gate_blocks(self, g, canonical, s) -> bool:
        return False

    def protection_finding(self, i, s, canonical) -> Optional[Finding]:
        return None

    def describe(self, v: Any) -> str:
        return _n(v).replace("_", " ").lower() or "—"

    def owner_review_action(self) -> str:
        return "notify_operator"        # schedule truth is an operator/coordinator decision (registry is §17-governed)


from .security import SecurityStanceProfile
from .vocabulary import posture

PROFILES = {p.name: p for p in (SecurityStanceProfile(), NumericFactProfile(), ScheduleStateProfile())}
