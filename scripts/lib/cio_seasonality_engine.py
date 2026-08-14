"""cio_seasonality_engine.py — Phase 13 calendar / presidential-cycle context.

Mechanical labels only. No partisan hard-codes. Not an execution engine.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

SEASONALITY_VERSION = "seasonality_engine_1.0.0"

MONTH_NAMES = (
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

# Weak/strong month *hypotheses* for context (not automatic portfolio rules)
# Literature-cited tendencies as SOURCE CONTEXT only.
WEAK_MONTHS_HYPOTHESIS = {9}  # September
STRONG_MONTHS_HYPOTHESIS = {11, 12, 1, 4}  # best-six-months adjacent


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
    return {
        "month": month,
        "month_name": name,
        "hypothesis_bucket": (
            "historically_weaker_in_almanac_literature"
            if month in WEAK_MONTHS_HYPOTHESIS
            else (
                "historically_stronger_in_almanac_literature"
                if month in STRONG_MONTHS_HYPOTHESIS
                else "neutral_or_mixed_hypothesis"
            )
        ),
        "best_six_months_window": month in (11, 12, 1, 2, 3, 4),
        "worst_six_months_window": month in (5, 6, 7, 8, 9, 10),
    }


def calendar_effects(now: datetime) -> list[str]:
    """Lightweight calendar tags (not full market calendar)."""
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
    # Options expiration week approximation: 3rd Friday week
    if 15 <= d <= 21:
        tags.append("mid_month_options_window_approx")
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
