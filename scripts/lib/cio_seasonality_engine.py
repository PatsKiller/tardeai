"""cio_seasonality_engine.py — Phase 13 calendar / presidential-cycle context.

Mechanical labels only. No partisan hard-codes. Not an execution engine.

Weak/strong month buckets are filled AFTER independent reproduction
(see cio_seasonality_analytics). August is never hardcoded bearish.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

SEASONALITY_VERSION = "seasonality_engine_1.1.0"

MONTH_NAMES = (
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

# Literature-only fallback if reproduction is unavailable.
# September is the classic published hypothesis. August is NOT listed here —
# it may join the weak set only after Trade AI reproduces monthly returns.
LITERATURE_WEAK_MONTHS_UNVERIFIED = {9}
LITERATURE_STRONG_MONTHS_UNVERIFIED = {11, 12, 1, 4}


def weak_months_hypothesis() -> set[int]:
    """Weak months from reproduction; literature September only as fallback."""
    try:
        from scripts.lib.cio_seasonality_analytics import reproduced_weak_months

        reproduced = reproduced_weak_months()
        if reproduced:
            return set(reproduced)
    except Exception:
        pass
    return set(LITERATURE_WEAK_MONTHS_UNVERIFIED)


def strong_months_hypothesis() -> set[int]:
    try:
        from scripts.lib.cio_seasonality_analytics import reproduced_strong_months

        reproduced = reproduced_strong_months()
        if reproduced:
            return set(reproduced)
    except Exception:
        pass
    return set(LITERATURE_STRONG_MONTHS_UNVERIFIED)


def __getattr__(name: str) -> Any:
    # Backward-compatible module attributes, computed after reproduction.
    if name == "WEAK_MONTHS_HYPOTHESIS":
        return weak_months_hypothesis()
    if name == "STRONG_MONTHS_HYPOTHESIS":
        return strong_months_hypothesis()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def presidential_cycle_year(year: int) -> dict[str, Any]:
    """Mechanical US presidential market-cycle year class.

    Election years are years divisible such that (year - 1788) % 4 == 0 for
    US presidential elections starting 1788... actually elections are 1788+4k
    in years like 2020, 2024 → year % 4 == 0.
    """
    # US presidential elections: 2020, 2024, 2028 → year % 4 == 0
    rem = year % 4
    if rem == 0:
        label = "election_year"
        order = 4
    elif rem == 1:
        label = "post_election_year"
        order = 1
    elif rem == 2:
        label = "midterm_year"
        order = 2
    else:
        label = "pre_election_year"
        order = 3
    return {
        "year": year,
        "cycle_label": label,
        "cycle_order": order,
        "partisan_conclusion": None,  # hard rule: never fill
        "method": "year_mod_4_election_year_when_0",
    }


def month_context(month: int) -> dict[str, Any]:
    name = MONTH_NAMES[month] if 1 <= month <= 12 else "unknown"
    weak = weak_months_hypothesis()
    strong = strong_months_hypothesis()
    return {
        "month": month,
        "month_name": name,
        "hypothesis_bucket": (
            "historically_weaker_in_almanac_literature"
            if month in weak
            else (
                "historically_stronger_in_almanac_literature"
                if month in strong
                else "neutral_or_mixed_hypothesis"
            )
        ),
        "weak_months_reproduced": sorted(weak),
        "strong_months_reproduced": sorted(strong),
        "best_six_months_window": month in (11, 12, 1, 2, 3, 4),
        "worst_six_months_window": month in (5, 6, 7, 8, 9, 10),
    }


def calendar_effects(now: datetime) -> list[str]:
    """Lightweight calendar tags. Options expiration is 3rd Friday, not day 15–21."""
    tags: list[str] = []
    d = now.day
    if d <= 3:
        tags.append("turn_of_month_early")
    if d >= 28:
        tags.append("turn_of_month_late")
    if now.month in (3, 6, 9, 12) and d >= 25:
        tags.append("quarter_end_window")
    if now.month == 12 and d >= 20:
        tags.append("year_end_window")
    if now.month == 12 or (now.month == 1 and d <= 15):
        tags.append("tax_loss_adjacent_window")
    try:
        from scripts.lib.cio_market_calendar import (
            is_options_expiration,
            is_options_expiration_week,
        )

        if is_options_expiration(now):
            tags.append("options_expiration")
        if is_options_expiration_week(now):
            tags.append("options_expiration_week")
    except Exception:
        pass
    return tags


def build_seasonality_context(now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    m = month_context(now.month)
    cycle = presidential_cycle_year(now.year)
    effects = calendar_effects(now)
    narrative = [
        f"Calendar: {m['month_name']} {now.year} · cycle={cycle['cycle_label']} "
        f"(mechanical, non-partisan).",
        f"Month hypothesis bucket: {m['hypothesis_bucket']} "
        f"(source-claim context only until Trade AI reproduces).",
        f"Six-month window: "
        f"{'best_six_months_hypothesis' if m['best_six_months_window'] else 'worst_six_months_hypothesis'}.",
    ]
    if effects:
        narrative.append("Calendar tags: " + ", ".join(effects))
    narrative.append(
        "Use as risk modifier / challenge context only — never a standalone trade rule."
    )
    return {
        "version": SEASONALITY_VERSION,
        "as_of": now.isoformat(),
        "month": m,
        "presidential_cycle": cycle,
        "calendar_effects": effects,
        "narrative_lines": narrative,
        "authority": "READ_ONLY_ADVISORY",
        "execution_engine": False,
    }
