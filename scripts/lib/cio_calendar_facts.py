"""Calendar effects, reproduced against real market data. Deterministic, no network.

Wave 3A.2. The named almanac effects (January Barometer, Santa Claus rally,
best six months, …) are registered as structured rows, each carrying whether
*we* reproduced it and on which series — never as prose, and never as an
instruction.

**Why the series matters.** Wave 3A.1 established that
`us_equity_monthly_synthetic_1950_2024.csv` is synthetic: 1987-10 reads +3.27%
where the market fell about 21.5%, and no month in 75 years is worse than
-7.88%. Reproducing a calendar claim against that file proves the pipeline is
deterministic; it says nothing about markets. Grades derived from it cannot
mean "independently reproduced".

So reproduction runs against the Ken French Data Library monthly market series
(1926-07 onward, 1200 months, public and redistributable), where 1987-10 reads
-23.19% and the worst month is -28.74%. `REAL_SERIES` is the grading series;
the synthetic file is kept only for the determinism check it was always doing.

Nothing here emits an action. "Sell in May" is stored as
`halloween_nov_apr` / `worst_six_months_may_oct` calendar_context and never as
a verb — the shared imperative matcher governs output either way.
"""
from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

CALENDAR_FACTS_VERSION = "calendar_facts_1.0.0"
AUTHORITY = "READ_ONLY_ADVISORY"

_LIB = Path(__file__).resolve().parents[2] / "reference" / "library"
REAL_SERIES = _LIB / "series" / "ff_research_data_factors_monthly.csv"
SYNTHETIC_SERIES = _LIB / "us_equity_monthly_synthetic_1950_2024.csv"

# Minimum sample before a reproduction may carry a reproduced grade. Below
# this the effect is recorded with reproduced=False and stays context-only.
MIN_SAMPLE_N = 20

# Every calendar fact is context. None of them may close an entity question.
DIMENSION_SCOPE = "context"
APPLICATION_LAW = (
    "calendar_context only — risk-modifier or context, max 10% conviction "
    "language, never a standalone sell, never creates TRIM"
)


@dataclass(frozen=True)
class MonthlyPoint:
    year: int
    month: int
    ret_pct: float


def load_french(path: Path | None = None) -> list[MonthlyPoint]:
    """Ken French monthly market return (Mkt-RF + RF = total market return)."""
    p = path or REAL_SERIES
    out: list[MonthlyPoint] = []
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) != 5 or len(parts[0]) != 6 or not parts[0].isdigit():
            continue
        try:
            mkt, rf = float(parts[1]), float(parts[4])
        except ValueError:
            continue
        if mkt <= -99.0:          # French's missing-value sentinel
            continue
        out.append(MonthlyPoint(int(parts[0][:4]), int(parts[0][4:]), mkt + rf))
    return out


def load_synthetic(path: Path | None = None) -> list[MonthlyPoint]:
    p = path or SYNTHETIC_SERIES
    out: list[MonthlyPoint] = []
    if not p.exists():
        return out
    for row in csv.DictReader(p.open(encoding="utf-8")):
        try:
            out.append(MonthlyPoint(int(row["year"]), int(row["month"]),
                                    float(row["return_pct"])))
        except (KeyError, ValueError):
            continue
    return out


def _stats(vals: Iterable[float]) -> dict[str, Any]:
    v = [x for x in vals]
    if not v:
        return {"n": 0, "mean": None, "median": None, "win_rate": None, "stdev": None}
    return {
        "n": len(v),
        "mean": round(statistics.mean(v), 4),
        "median": round(statistics.median(v), 4),
        "win_rate": round(sum(1 for x in v if x > 0) / len(v), 4),
        "stdev": round(statistics.stdev(v), 4) if len(v) > 1 else None,
    }


def _cycle_year(year: int) -> str:
    """Mechanical US presidential cycle label. No partisan content, ever."""
    r = year % 4
    return {0: "election_year", 1: "post_election_year",
            2: "midterm_year", 3: "pre_election_year"}[r]


def _window(points: list[MonthlyPoint], months: set[int]) -> list[float]:
    return [p.ret_pct for p in points if p.month in months]


def _compound_window(points: list[MonthlyPoint], months: list[int]) -> list[float]:
    """Compound a contiguous seasonal window per occurrence, not per month."""
    by_year: dict[int, list[float]] = {}
    for p in points:
        if p.month in months:
            by_year.setdefault(p.year, []).append(p.ret_pct)
    out = []
    for _year, vals in sorted(by_year.items()):
        if len(vals) != len(months):
            continue                      # partial window — drop, do not pad
        acc = 1.0
        for v in vals:
            acc *= (1.0 + v / 100.0)
        out.append((acc - 1.0) * 100.0)
    return out


# --- the named effects -------------------------------------------------------

def january_barometer(points: list[MonthlyPoint]) -> dict[str, Any]:
    """Does a positive January coincide with a positive Feb-Dec?"""
    jan = {p.year: p.ret_pct for p in points if p.month == 1}
    rest = _compound_window(points, list(range(2, 13)))
    rest_by_year: dict[int, float] = {}
    by_year: dict[int, list[float]] = {}
    for p in points:
        if p.month >= 2:
            by_year.setdefault(p.year, []).append(p.ret_pct)
    for y, vals in by_year.items():
        if len(vals) == 11:
            acc = 1.0
            for v in vals:
                acc *= (1.0 + v / 100.0)
            rest_by_year[y] = (acc - 1.0) * 100.0
    pairs = [(jan[y], rest_by_year[y]) for y in sorted(jan) if y in rest_by_year]
    agree = [1 for j, r in pairs if (j > 0) == (r > 0)]
    return {"n": len(pairs),
            "agreement_rate": round(len(agree) / len(pairs), 4) if pairs else None,
            "rest_of_year": _stats([r for _, r in pairs]),
            "note": "sign agreement between January and Feb-Dec compounded",
            "_unused_rest": len(rest)}


def santa_claus_rally(points: list[MonthlyPoint]) -> dict[str, Any]:
    """December as a monthly proxy.

    The classic definition is the last 5 trading days plus the first 2 of
    January. A monthly series cannot express that, so this is December only and
    says so — an approximation labelled as one, not a silent substitution.
    """
    s = _stats(_window(points, {12}))
    s["note"] = ("December monthly proxy; true definition is last 5 + first 2 "
                 "trading days and needs a daily series")
    s["is_approximation"] = True
    return s


def best_six_months(points: list[MonthlyPoint]) -> dict[str, Any]:
    return _stats(_compound_window(points, [11, 12, 1, 2, 3, 4]))


def worst_six_months(points: list[MonthlyPoint]) -> dict[str, Any]:
    return _stats(_compound_window(points, [5, 6, 7, 8, 9, 10]))


def september_weakness(points: list[MonthlyPoint]) -> dict[str, Any]:
    return _stats(_window(points, {9}))


def month_of_year(points: list[MonthlyPoint], month: int) -> dict[str, Any]:
    return _stats(_window(points, {month}))


def cycle_pattern(points: list[MonthlyPoint], label: str) -> dict[str, Any]:
    return _stats([p.ret_pct for p in points if _cycle_year(p.year) == label])


def turn_of_month(points: list[MonthlyPoint]) -> dict[str, Any]:
    return {"n": 0, "reproduced": False,
            "reason": "requires a daily series; monthly data cannot express it"}


def pre_holiday(points: list[MonthlyPoint]) -> dict[str, Any]:
    return {"n": 0, "reproduced": False,
            "reason": "requires a daily series; monthly data cannot express it"}


def midterm_bottom_picker(points: list[MonthlyPoint]) -> dict[str, Any]:
    """Midterm Q2-Q3 weakness vs Q4 sweet spot."""
    mid = [p for p in points if _cycle_year(p.year) == "midterm_year"]
    q23 = _stats([p.ret_pct for p in mid if 4 <= p.month <= 9])
    q4 = _stats([p.ret_pct for p in mid if p.month >= 10])
    # Expose a top-level n so the composite grades on its own sample rather
    # than falling to D for lacking a scalar the grader looks for.
    return {"q2_q3": q23, "q4": q4,
            "n": min(q23.get("n") or 0, q4.get("n") or 0),
            "spread_mean": (None if q23.get("mean") is None or q4.get("mean") is None
                            else round(q4["mean"] - q23["mean"], 4))}


# --- graded registry rows ----------------------------------------------------

# source_ids these effects are claimed by, for citation on each row.
CLAIM_SOURCES = {
    "january_barometer": ["hirsch_stock_traders_almanac_2026"],
    "santa_claus_rally": ["hirsch_stock_traders_almanac_2026"],
    "best_six_months": ["bouman_jacobsen_2002_halloween",
                        "hirsch_stock_traders_almanac_2026"],
    "halloween_nov_apr": ["bouman_jacobsen_2002_halloween"],
    "worst_six_months_may_oct": ["bouman_jacobsen_2002_halloween"],
    "september_weakness": ["hirsch_stock_traders_almanac_2026"],
    "turn_of_month": ["hirsch_stock_traders_almanac_2026"],
    "pre_holiday": ["hirsch_stock_traders_almanac_2026"],
    "midterm_year_pattern": ["hirsch_stock_traders_almanac_2026"],
    "post_election_year": ["hirsch_stock_traders_almanac_2026"],
    "presidential_4yr_cycle": ["hirsch_stock_traders_almanac_2026"],
    "midterm_bottom_picker": ["hirsch_stock_traders_almanac_2026"],
}


def _grade(rec: dict[str, Any], *, reproduced: bool) -> str:
    """A/B need reproduction on the real series with adequate N.

    Nothing here returns A: A additionally requires out-of-sample directional
    support, which is a separate check, so B is the ceiling for a single
    in-sample reproduction.
    """
    if not reproduced:
        return "C"
    n = rec.get("n") or 0
    if n < MIN_SAMPLE_N:
        return "D"
    return "B"


def build_calendar_facts(*, real: Optional[list[MonthlyPoint]] = None,
                         synthetic: Optional[list[MonthlyPoint]] = None
                         ) -> list[dict[str, Any]]:
    """Every named effect as a graded row. Reproduction runs on the REAL series."""
    r = real if real is not None else load_french()
    s = synthetic if synthetic is not None else load_synthetic()
    has_real = bool(r)

    def row(fact_id: str, rec: dict[str, Any], *, reproduced: bool,
            synth: dict[str, Any] | None = None,
            note: str = "") -> dict[str, Any]:
        reproduced = reproduced and has_real
        return {
            "source_id": "calendar_fact_" + fact_id,
            "fact_id": fact_id,
            "family": "seasonality",
            "title": fact_id.replace("_", " "),
            "claimed_by": CLAIM_SOURCES.get(fact_id, []),
            "reproduced": reproduced,
            "reproduced_on": ("ken_french_monthly_1926" if reproduced else None),
            "result": rec,
            "synthetic_result": synth,
            "evidence_grade": _grade(rec, reproduced=reproduced),
            "application_law": APPLICATION_LAW,
            "dimension_scope": DIMENSION_SCOPE,
            "refresh": "static",
            "max_influence_pct": 10.0,
            "standalone_sell": False,
            "creates_trim": False,
            "notes": note,
            "calendar_facts_version": CALENDAR_FACTS_VERSION,
            "authority": AUTHORITY,
        }

    bsm, wsm = best_six_months(r), worst_six_months(r)
    facts = [
        row("january_barometer", january_barometer(r), reproduced=True,
            synth=january_barometer(s) if s else None,
            note="sign agreement, not a return forecast"),
        row("santa_claus_rally", santa_claus_rally(r), reproduced=False,
            note="December monthly proxy only; true window needs daily data"),
        row("best_six_months", bsm, reproduced=True,
            synth=best_six_months(s) if s else None),
        row("halloween_nov_apr", bsm, reproduced=True,
            note="same window as best_six_months; Bouman & Jacobsen framing"),
        row("worst_six_months_may_oct", wsm, reproduced=True,
            synth=worst_six_months(s) if s else None,
            note=("still positive on the real series — the effect is a "
                  "differential, not a negative half-year")),
        row("september_weakness", september_weakness(r), reproduced=True,
            synth=september_weakness(s) if s else None),
        row("turn_of_month", turn_of_month(r), reproduced=False,
            note="monthly series cannot express it"),
        row("pre_holiday", pre_holiday(r), reproduced=False,
            note="monthly series cannot express it"),
        row("midterm_year_pattern", cycle_pattern(r, "midterm_year"),
            reproduced=True, synth=cycle_pattern(s, "midterm_year") if s else None),
        row("post_election_year", cycle_pattern(r, "post_election_year"),
            reproduced=True),
        row("presidential_4yr_cycle",
            {"by_label": {lbl: cycle_pattern(r, lbl) for lbl in
                          ("election_year", "post_election_year",
                           "midterm_year", "pre_election_year")},
             "n": len(r)},
            reproduced=True, note="mechanical year%4 labels; no partisan content"),
        row("midterm_bottom_picker", midterm_bottom_picker(r), reproduced=True,
            note="Q2-Q3 vs Q4 within midterm years"),
    ]
    return facts


def divergence_report(*, real: Optional[list[MonthlyPoint]] = None,
                      synthetic: Optional[list[MonthlyPoint]] = None
                      ) -> list[dict[str, Any]]:
    """Where the synthetic series disagrees with the real one. Evidence, not a fix."""
    out = []
    for f in build_calendar_facts(real=real, synthetic=synthetic):
        syn = f.get("synthetic_result")
        res = f.get("result") or {}
        if not syn or res.get("mean") is None or syn.get("mean") is None:
            continue
        out.append({
            "fact_id": f["fact_id"],
            "real_mean": res["mean"], "real_n": res["n"],
            "synthetic_mean": syn["mean"], "synthetic_n": syn["n"],
            "abs_delta": round(abs(res["mean"] - syn["mean"]), 4),
        })
    return sorted(out, key=lambda d: -d["abs_delta"])
