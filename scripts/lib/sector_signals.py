"""CIO sector signal semantics shared by the writer and read projections.

RS is the sector return minus SPY's return, in percentage points, over exactly
5/20/60 benchmark sessions. The 20- and 60-session signs determine posture;
one-day quotes and the five-session context never determine it. No allocation,
proposal, execution or provider access is performed here.
"""
from __future__ import annotations

import math
from typing import Any


def number(value: Any) -> float | None:
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def sector_posture(rs20: Any, rs60: Any) -> dict[str, Any]:
    """One definition for the Sectors, CIO and Defense sector labels."""
    mid, long = number(rs20), number(rs60)
    if mid is None or long is None:
        state, momentum, trend, posture = None, "missing", "Not measured", "Not measured"
        gap = "Both 20- and 60-session relative strength are required"
    elif mid == 0 and long == 0:
        state, momentum, trend, posture, gap = None, "neutral", "Flat", "Neutral", None
    elif mid >= 0 and long >= 0:
        state, momentum, trend, posture, gap = "LEADING", "leading", "Strengthening", "Favoured", None
    elif mid < 0 and long < 0:
        state, momentum, trend, posture, gap = "LAGGING", "lagging", "Weakening", "Review", None
    elif mid >= 0:
        state, momentum, trend, posture, gap = "IMPROVING", "improving", "Recovering", "Research watch", None
    else:
        state, momentum, trend, posture, gap = "WEAKENING", "weakening", "Cooling", "Neutral", None
    return {"state": state, "momentum": momentum, "trend": trend,
            "cio_posture": posture, "posture_basis": "20d_60d_vs_spy", "gap": gap}


def relative_strength(sector_closes, benchmark_closes, *, offset: int = 0) -> dict[str, Any]:
    """Use SPY session anchors, never shorten a horizon to fill missing history.

    A missing intermediate close makes that horizon incomplete. An ETF ending
    before SPY's latest session is a gap, rather than an apparently current row.
    Duplicate dates must already have been resolved by the owning price query.
    """
    sector = {str(d): number(p) for d, p in sector_closes}
    benchmark = {str(d): number(p) for d, p in benchmark_closes}
    dates = sorted(d for d, p in benchmark.items() if p is not None and p > 0)
    i = len(dates) - 1 - offset
    end = dates[i] if 0 <= i < len(dates) else None
    result: dict[str, Any] = {"as_of": end, "rs5": None, "rs20": None, "rs60": None}
    gaps = []
    for window in (5, 20, 60):
        if end is None or i < window:
            gaps.append(f"{window} sessions: insufficient history")
            continue
        covered = dates[i-window:i+1]
        if any(sector.get(d) is None or sector[d] <= 0 for d in covered):
            gaps.append(f"{window} sessions: sector closes missing")
            continue
        start = covered[0]
        result[f"rs{window}"] = round(
            ((sector[end] / sector[start] - 1) - (benchmark[end] / benchmark[start] - 1)) * 100, 2
        )
    result.update(sector_posture(result["rs20"], result["rs60"]))
    result["coverage_gaps"] = gaps
    if result["gap"] and gaps:
        result["gap"] += ": " + "; ".join(gaps)
    return result


def normalize_signal_row(row: dict[str, Any]) -> dict[str, Any]:
    """Reclassify legacy snapshots without allowing their old state to win."""
    return {**row, **sector_posture(row.get("rs20"), row.get("rs60"))}
