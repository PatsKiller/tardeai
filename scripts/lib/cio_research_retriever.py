"""cio_research_retriever.py — Phases 11–16 retrieve-before-synthesis.

Compact research facts are assembled BEFORE any CIO synthesis or capital-plan
attachment. Output is a risk modifier / context note only.

Influence cap: 10% conviction or sizing *language*. Never a standalone sell.
Never creates TRIM from August (or any month). Never autonomous execution.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from scripts.lib.cio_market_calendar import describe_calendar
from scripts.lib.cio_research_library import facts_for_family, library_facts
from scripts.lib.cio_seasonality_analytics import (
    MAX_INFLUENCE_PCT,
    august_general,
    august_midterm,
    month_headline,
    reproduced_weak_months,
    september_general,
    september_midterm,
)
from scripts.lib.cio_seasonality_engine import (
    MONTH_NAMES,
    build_seasonality_context,
    presidential_cycle_year,
)

RETRIEVER_VERSION = "research_retriever_1.0.0"
AUTHORITY = "READ_ONLY_ADVISORY"
ROLE = "risk_modifier_or_context"

_FORBIDDEN = (
    "standalone_sell",
    "create_trim_from_seasonality",
    "hard_coded_partisan_presidency_conclusions",
    "fulltext_book_republication",
)


def _compact_fact(f: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": f.get("source_id"),
        "family": f.get("family"),
        "title": f.get("title"),
        "evidence_grade": f.get("evidence_grade"),
        "n": f.get("n"),
        "mean": f.get("mean"),
        "win_rate": f.get("win_rate"),
        "layers": f.get("layers"),
        "citation": f.get("citation"),
        "current_applicability": f.get("current_applicability"),
    }


def _almanac_for_month(month: int, cycle_label: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if month == 8:
        out.append(august_general())
        if cycle_label == "midterm_year":
            out.append(august_midterm())
    elif month == 9:
        out.append(september_general())
        if cycle_label == "midterm_year":
            out.append(september_midterm())
    return out


def _modifier_note(month: int, cycle_label: str, weak: set[int], grades: list[str]) -> str:
    name = MONTH_NAMES[month] if 1 <= month <= 12 else "this month"
    grade_s = ",".join(grades) if grades else "n/a"
    if month in weak:
        return (
            f"{name} ({cycle_label}) appears in the *reproduced* weak-month set. "
            f"Treat as a ≤{MAX_INFLUENCE_PCT:.0f}% conviction/sizing language "
            f"modifier (grades {grade_s}). Never a standalone sell. Do not create TRIM."
        )
    return (
        f"{name} ({cycle_label}) is calendar context only. Any influence is capped "
        f"at {MAX_INFLUENCE_PCT:.0f}% language and is never a standalone buy/sell."
    )


def retrieve_for_decision(
    *,
    now: Optional[datetime] = None,
    symbols: Optional[Sequence[str]] = None,
    decision_id: Optional[str] = None,
) -> dict[str, Any]:
    """Retrieve compact facts before synthesis. No execution payload."""
    now = now or datetime.now(timezone.utc)
    cycle = presidential_cycle_year(now.year)
    season = build_seasonality_context(now)
    weak = reproduced_weak_months()
    almanac = _almanac_for_month(now.month, cycle["cycle_label"])
    facts = [_compact_fact(f) for f in library_facts()]
    month_facts = [
        f
        for f in facts
        if f.get("family") == "seasonality"
        or (now.month == 8 and "august" in str(f.get("source_id") or "").lower())
        or (now.month == 9 and "september" in str(f.get("source_id") or "").lower())
    ]
    grades = [str(a.get("evidence_grade")) for a in almanac if a.get("evidence_grade")]
    note = _modifier_note(now.month, cycle["cycle_label"], weak, grades)
    headlines = [month_headline(a) for a in almanac]
    syms = [str(s).upper() for s in (symbols or []) if s][:24]
    return {
        "version": RETRIEVER_VERSION,
        "as_of": now.isoformat(),
        "authority": AUTHORITY,
        "role": ROLE,
        "execution_engine": False,
        "decision_id": decision_id,
        "symbols": syms,
        "presidential_cycle": cycle,
        "seasonality": {
            "month": now.month,
            "month_name": MONTH_NAMES[now.month],
            "weak_months_reproduced": sorted(weak),
            "in_reproduced_weak_set": now.month in weak,
            "narrative_lines": season.get("narrative_lines") or [],
        },
        "calendar": describe_calendar(now),
        "almanac": almanac,
        "almanac_headlines": headlines,
        "facts": facts,
        "relevant_facts": month_facts[:8],
        "modifier_note": note,
        "influence": {
            "max_conviction_sizing_modifier_pct": MAX_INFLUENCE_PCT,
            "standalone_sell": False,
            "creates_trim": False,
            "role": ROLE,
        },
        "forbidden": list(_FORBIDDEN),
        "disclaimer": (
            "Research context is retrieved before synthesis and does not instruct "
            "trades. SOURCE CLAIM ≠ TRADE AI REPRODUCTION ≠ CURRENT APPLICATION."
        ),
    }


def retrieve_research_context(
    now: Optional[datetime] = None,
    symbols: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    """Hook used by compose_strategy_context / capital plan (modifier note only)."""
    payload = retrieve_for_decision(now=now, symbols=symbols)
    # Surface a stable, compact context object for the plan envelope.
    return {
        "version": RETRIEVER_VERSION,
        "as_of": payload["as_of"],
        "authority": AUTHORITY,
        "role": ROLE,
        "execution_engine": False,
        "modifier_note": payload["modifier_note"],
        "influence": payload["influence"],
        "presidential_cycle": payload["presidential_cycle"],
        "seasonality": payload["seasonality"],
        "almanac_headlines": payload["almanac_headlines"],
        "relevant_facts": payload["relevant_facts"],
        "calendar": payload["calendar"],
        "forbidden": payload["forbidden"],
        "disclaimer": payload["disclaimer"],
        "symbols": payload["symbols"],
    }
