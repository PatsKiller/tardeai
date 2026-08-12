"""Catalyst severity thresholds — single source of truth for desk behavior.

Severity turns a calendar fact into revisit timing, Hermes priority,
invalidation, and Telegram elevation — never into orders.

READ_ONLY_ADVISORY / defensive_observe: defaults are conservative.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional


# ── severity rank ────────────────────────────────────────────────────────────

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
SEVERITIES = frozenset(SEVERITY_RANK)

# Default severity by controlled event kind
KIND_DEFAULT_SEVERITY = {
    "ex_div": "low",
    "distribution": "low",
    "earnings": "high",
    "guidance": "medium",
    "index_rebalance": "medium",
    "macro": "medium",
    "regulatory": "high",
    "product": "medium",
    "other": "low",
    # aliases / broker types
    "analyst_upgrade": "medium",
    "analyst_downgrade": "medium",
    "contract_win": "medium",
    "mna": "high",
    "fda": "high",
    "dividend": "low",
}

CONTROLLED_KINDS = frozenset(KIND_DEFAULT_SEVERITY)

# ── horizon windows (calendar / trading-day approximation) ───────────────────

HORIZON_TELEGRAM_ELEVATE = 5
HORIZON_REVISIT_TIGHTEN = 5
HORIZON_HERMES_WARM = 5
HORIZON_HERMES_RESEARCH_GAP = 10
HORIZON_INVALIDATE_ON_ADD = 15
HORIZON_PACK_FILTER = 15  # max days kept in LLM/evidence pack

# ── minimum severity to trigger each action ──────────────────────────────────

MIN_SEV_TELEGRAM_ELEVATE = "medium"   # mention in summary line
MIN_SEV_REVISIT_TIGHTEN = "medium"
MIN_SEV_HERMES_WARM = "medium"
MIN_SEV_RESEARCH_GAP = "medium"       # force research-gap emit on material plans
MIN_SEV_INVALIDATE_CACHE = "medium"
MIN_SEV_MATERIALITY_BUMP = "high"     # can mark situation more urgent

# Priority mapping for Hermes jobs
SEV_TO_HERMES_PRIORITY = {
    "low": "low",
    "medium": "normal",
    "high": "high",
    "critical": "critical",
}

PRIORITY_RANK = {"low": 0, "normal": 1, "high": 2, "critical": 3}

# Modifiers
EXPECTED_MOVE_STEP_PCT = 5.0  # ≥ this → +1 severity step (clamped)


def clamp_severity(s: str | None) -> str:
    """Unknown / missing → low (never invent high)."""
    if not s:
        return "low"
    key = str(s).strip().lower()
    return key if key in SEVERITY_RANK else "low"


def max_severity(a: str | None, b: str | None) -> str:
    ca, cb = clamp_severity(a), clamp_severity(b)
    return ca if SEVERITY_RANK[ca] >= SEVERITY_RANK[cb] else cb


def sev_at_least(sev: str | None, minimum: str | None) -> bool:
    return SEVERITY_RANK[clamp_severity(sev)] >= SEVERITY_RANK[clamp_severity(minimum)]


def step_up_severity(sev: str | None, steps: int = 1) -> str:
    """Raise severity by N steps (clamped at critical)."""
    rank = SEVERITY_RANK[clamp_severity(sev)] + max(0, steps)
    for name, r in SEVERITY_RANK.items():
        if r == min(rank, 3):
            return name
    return "critical"


def step_down_severity(sev: str | None, steps: int = 1) -> str:
    rank = SEVERITY_RANK[clamp_severity(sev)] - max(0, steps)
    for name, r in SEVERITY_RANK.items():
        if r == max(rank, 0):
            return name
    return "low"


def clamp_priority(p: str | None) -> str:
    key = (p or "normal").strip().lower()
    return key if key in PRIORITY_RANK else "normal"


def max_priority(a: str | None, b: str | None) -> str:
    ca, cb = clamp_priority(a), clamp_priority(b)
    return ca if PRIORITY_RANK[ca] >= PRIORITY_RANK[cb] else cb


def hermes_priority_for_severity(sev: str | None) -> str:
    return SEV_TO_HERMES_PRIORITY[clamp_severity(sev)]


def next_relevant_event(
    events: Iterable[dict[str, Any]] | None,
    *,
    max_days: int,
    min_sev: str,
) -> Optional[dict[str, Any]]:
    """Soonest event within horizon meeting min severity (tie-break: higher sev)."""
    upcoming: list[dict[str, Any]] = []
    for e in events or []:
        if not isinstance(e, dict):
            continue
        hd = e.get("horizon_days")
        if hd is None:
            continue
        try:
            days = float(hd)
        except (TypeError, ValueError):
            continue
        if 0 <= days <= max_days and sev_at_least(e.get("severity", "low"), min_sev):
            upcoming.append(e)
    if not upcoming:
        return None
    upcoming.sort(
        key=lambda e: (
            float(e.get("horizon_days") or 0),
            -SEVERITY_RANK[clamp_severity(e.get("severity", "low"))],
        )
    )
    return upcoming[0]


def effective_research_priority(
    sev: str | None,
    *,
    weight_pct: float | None = None,
    fire_pct: float | None = None,
    dd_pct: float | None = None,
    deep_dd_pct: float | None = None,
) -> str:
    """Compound severity with concentration / drawdown posture (still READ_ONLY)."""
    base = hermes_priority_for_severity(sev)
    if fire_pct is not None and weight_pct is not None and fire_pct > 0:
        if weight_pct >= 0.95 * fire_pct:
            base = max_priority(base, "high")
    if deep_dd_pct is not None and dd_pct is not None and deep_dd_pct > 0:
        if dd_pct >= 0.8 * deep_dd_pct:
            base = max_priority(base, "high")
    return base
