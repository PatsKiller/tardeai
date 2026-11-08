"""Confidence (§2.5): coverage × freshness × agreement × U_event × hit-rate, never a cosmetic number.

The five factors answer five different questions — did we measure it, is it fresh, do the categories agree, is a
catalyst ahead, and have we been right lately — and each one is printed with the record, so a low confidence is
always attributable rather than mysterious.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Sequence

from .categories import CategoryResult, freshness_weight


@dataclass
class Confidence:
    value: float
    band: str
    coverage: float
    freshness: float
    agreement: float
    u_event: float
    hitrate: float
    detractors: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute(
    categories: Sequence[CategoryResult],
    policy: dict[str, Any],
    now: datetime,
    *,
    u_event: float = 1.0,
    hitrate: float = 0.5,
    u_event_note: str = "",
) -> Confidence:
    cfg = policy["confidence"]
    measured = [c for c in categories if c.measured]
    coverage = sum(c.weight_prior for c in measured) / 100.0

    ages = []
    for c in measured:
        for ind in c.indicators:
            if ind.available:
                ages.append(freshness_weight(ind.as_of, now, policy))
    freshness = (sum(ages) / len(ages)) if ages else 0.0

    subs = [float(c.subscore) for c in measured if c.subscore is not None]
    if len(subs) >= 2:
        agreement = 1.0 - statistics.pstdev(subs) / float(cfg["agreement_scale"])
        agreement = max(float(cfg["agreement_floor"]), min(float(cfg["agreement_ceiling"]), agreement))
    elif subs:
        agreement = float(cfg["agreement_ceiling"])  # one measured category cannot disagree with itself
    else:
        agreement = 0.0

    value = coverage * freshness * agreement * float(u_event) * float(hitrate)
    bands = cfg["bands"]
    band = "HIGH" if value >= float(bands["high"]) else ("MODERATE" if value >= float(bands["moderate"]) else "LOW")

    parts = [
        {"factor": "coverage", "value": round(coverage, 3), "shortfall": 1.0 - coverage,
         "why": f"{len(measured)} of {len(categories)} categories measured"},
        {"factor": "freshness", "value": round(freshness, 3), "shortfall": 1.0 - freshness,
         "why": "mean indicator decay on the market clock"},
        {"factor": "agreement", "value": round(agreement, 3), "shortfall": 1.0 - agreement,
         "why": "1 - stdev(C_k)"},
        {"factor": "u_event", "value": round(float(u_event), 3), "shortfall": 1.0 - float(u_event),
         "why": u_event_note or "no HIGH event inside the horizon"},
        {"factor": "hitrate", "value": round(float(hitrate), 3), "shortfall": 1.0 - float(hitrate),
         "why": "trailing 12-week band hit rate (0.5 until 8 graded weeks exist)"},
    ]
    detractors = sorted(parts, key=lambda p: p["shortfall"], reverse=True)[:3]
    notes = []
    if band == "LOW":
        notes.append("LOW confidence: every action in the band template downgrades one notch toward NEUTRAL")
    zero = [c.key for c in categories if not c.measured]
    if zero:
        notes.append("UNKNOWN categories: " + ", ".join(zero))
    return Confidence(
        value=round(value, 4), band=band, coverage=round(coverage, 4), freshness=round(freshness, 4),
        agreement=round(agreement, 4), u_event=round(float(u_event), 4), hitrate=round(float(hitrate), 4),
        detractors=detractors, notes=notes,
    )


def hitrate_from_grades(grades: Sequence[dict[str, Any]], policy: dict[str, Any]) -> tuple[float, str]:
    """0.5 until ``hitrate_min_graded_weeks`` closed weeks exist; then 0.5 + 0.5·hit (§2.5)."""
    cfg = policy["confidence"]
    closed = [g for g in grades if g.get("status") == "graded" and g.get("band_hit") is not None]
    if len(closed) < int(cfg["hitrate_min_graded_weeks"]):
        return 0.5, f"{len(closed)} graded weeks, needs {cfg['hitrate_min_graded_weeks']}: hit rate held at 0.5"
    window = closed[-12:]
    hits = sum(1 for g in window if bool(g.get("band_hit")))
    hit = hits / len(window)
    return 0.5 + 0.5 * hit, f"{hits}/{len(window)} band hits over the trailing 12 weeks"


__all__ = ["Confidence", "compute", "hitrate_from_grades"]
