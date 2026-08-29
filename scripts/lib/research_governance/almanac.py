"""R3 Stock Almanac reproduction — governed, fixture-first, citation-only.

Three layers are never collapsed:
  SOURCE CLAIM  →  TRADE AI REPRODUCTION  →  CURRENT APPLICATION

Public STA investor-alert citations are title/URL/date only. No book pages,
no newsletter body, no partisan presidential conclusions.

Calendar claims are challenged as a FAMILY (STW / White Reality Check),
never as a lone winner.

READ_ONLY_ADVISORY. Never a standalone sell. Never creates TRIM.
"""
from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Optional

from .bootstrap_reality_check import calendar_family_reality_check
from .enums import EvidenceGrade, EvidenceType, InfluenceClass, ResearchStatus
from .models import ResearchEvidence

AUTHORITY = "READ_ONLY_ADVISORY"
ALMANAC_VERSION = "r3_almanac_1.0.0"
MAX_INFLUENCE_PCT = 10.0
OOS_START_YEAR = 2000
SOURCE_ID_BOOK = "stock_traders_almanac"

_REPO = Path(__file__).resolve().parents[3]
# Wave 3A: relocated out of tests/. Single resolver, see cio_library_paths.
from scripts.lib.cio_library_paths import us_equity_monthly_path

DEFAULT_FIXTURE = us_equity_monthly_path()

# Public STA *alerts* — citation only.
STA_PUBLIC_ALERTS: dict[str, dict[str, str]] = {
    "august_general": {
        "title": "August Almanac & Vital Stats: Stronger in Election Years",
        "url": "https://www.stocktradersalmanac.com/Alert/20240718_2.aspx",
        "date": "2024-07-18",
        "month": "8",
        "claim_direction": "negative",
    },
    "august_midterm": {
        "title": "August Almanac & Vital Stats: No Reprieve in Midterm Years",
        "url": "https://www.stocktradersalmanac.com/Alert/20260716_1.aspx",
        "date": "2026-07-16",
        "month": "8",
        "claim_direction": "negative",
    },
    "september_general": {
        "title": "September Almanac & Vital Stats: Worst Month of the Year 1950-2023",
        "url": "https://www.stocktradersalmanac.com/Alert/20240815_1.aspx",
        "date": "2024-08-15",
        "month": "9",
        "claim_direction": "negative",
    },
    "september_midterm": {
        "title": "September Almanac: Worst Month Modestly Better in Midterm Years",
        "url": "https://www.stocktradersalmanac.com/Alert/20220818_1.aspx",
        "date": "2022-08-18",
        "month": "9",
        "claim_direction": "negative",
    },
}

_SUMMARIES = {
    "august_general": (
        "Operator-structured summary of a public STA investor alert (citation only): "
        "August is described as among the weaker modern-sample months. Not a book extract."
    ),
    "august_midterm": (
        "Operator-structured summary of a public STA investor alert (citation only): "
        "midterm-year Augusts are described as offering no seasonal reprieve. Not a book extract."
    ),
    "september_general": (
        "Operator-structured summary of a public STA investor alert (citation only): "
        "September is described as the worst-performing calendar month in long samples since 1950. "
        "Not a book extract."
    ),
    "september_midterm": (
        "Operator-structured summary of a public STA investor alert (citation only): "
        "midterm-year Septembers are described as modestly better in rank than September overall. "
        "Not a book extract."
    ),
}

MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}


def presidential_cycle_label(year: int) -> str:
    """Mechanical cycle only. year % 4 == 2 → midterm_year. No partisan read."""
    r = int(year) % 4
    return {
        0: "election_year",
        1: "post_election_year",
        2: "midterm_year",
        3: "pre_election_year",
    }[r]


def is_midterm_year(year: int) -> bool:
    return presidential_cycle_label(year) == "midterm_year"


def load_monthly_fixture(path: Optional[Path] = None) -> list[dict[str, Any]]:
    p = path or DEFAULT_FIXTURE
    if not p.is_file():
        raise FileNotFoundError(f"almanac fixture missing: {p}")
    rows: list[dict[str, Any]] = []
    with p.open(encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            year = int(rec["year"])
            month = int(rec["month"])
            rows.append({
                "date": rec["date"],
                "year": year,
                "month": month,
                "return_pct": float(rec["return_pct"]),
                "cycle_label": rec.get("cycle_label") or presidential_cycle_label(year),
                "source": "fixture",
            })
    return rows


def _filter(
    rows: list[dict[str, Any]],
    *,
    month: Optional[int] = None,
    cycle_label: Optional[str] = None,
    year_min: Optional[int] = None,
    year_max: Optional[int] = None,
) -> list[float]:
    out: list[float] = []
    for r in rows:
        if month is not None and int(r["month"]) != int(month):
            continue
        if cycle_label and r.get("cycle_label") != cycle_label:
            continue
        y = int(r["year"])
        if year_min is not None and y < year_min:
            continue
        if year_max is not None and y > year_max:
            continue
        out.append(float(r["return_pct"]))
    return out


def summarize(values: list[float]) -> dict[str, Any]:
    n = len(values)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "win_rate": None, "std": None}
    return {
        "n": n,
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "win_rate": sum(1 for v in values if v > 0) / n,
        "std": statistics.pstdev(values) if n > 1 else 0.0,
    }


def grade_reproduction(
    *,
    n: int,
    mean: Optional[float],
    oos_mean: Optional[float],
    oos_n: int,
    claim_direction: str,
) -> EvidenceGrade:
    if n <= 0 or mean is None:
        return EvidenceGrade.D
    direction = claim_direction.lower()
    contradicted = (
        (direction == "negative" and mean > 0.5)
        or (direction == "positive" and mean < -0.5)
    )
    if contradicted and oos_n >= 10 and oos_mean is not None and (
        (direction == "negative" and oos_mean > 0.5)
        or (direction == "positive" and oos_mean < -0.5)
    ):
        return EvidenceGrade.X
    oos_agrees = False
    if oos_n >= 8 and oos_mean is not None and mean is not None:
        oos_agrees = (mean < 0 and oos_mean < 0) or (mean > 0 and oos_mean > 0)
    if n >= 40 and oos_agrees and abs(mean) >= 0.05:
        return EvidenceGrade.B
    if n >= 15:
        return EvidenceGrade.C
    return EvidenceGrade.D


def reproduce_slice(
    key: str,
    *,
    rows: Optional[list[dict[str, Any]]] = None,
    as_of_year: int = 2026,
) -> dict[str, Any]:
    if key not in STA_PUBLIC_ALERTS:
        raise ValueError(f"unknown almanac slice {key!r}")
    meta = STA_PUBLIC_ALERTS[key]
    rows = rows if rows is not None else load_monthly_fixture()
    month = int(meta["month"])
    cycle = "midterm_year" if "midterm" in key else None
    full = summarize(_filter(rows, month=month, cycle_label=cycle))
    ins = summarize(_filter(rows, month=month, cycle_label=cycle, year_max=OOS_START_YEAR - 1))
    oos = summarize(_filter(rows, month=month, cycle_label=cycle, year_min=OOS_START_YEAR))
    grade = grade_reproduction(
        n=int(full["n"] or 0),
        mean=full["mean"],
        oos_mean=oos["mean"],
        oos_n=int(oos["n"] or 0),
        claim_direction=meta["claim_direction"],
    )
    status = ResearchStatus.SOURCE_CLAIM
    if grade in {EvidenceGrade.B, EvidenceGrade.C} and full["n"]:
        status = ResearchStatus.IN_SAMPLE_REPRODUCED
        if oos["n"] and oos["mean"] is not None and full["mean"] is not None:
            if (full["mean"] < 0 and oos["mean"] < 0) or (full["mean"] > 0 and oos["mean"] > 0):
                if grade == EvidenceGrade.B:
                    status = ResearchStatus.OOS_SUPPORTED
    if grade == EvidenceGrade.X:
        status = ResearchStatus.FAILED_REPRODUCTION
    layers = {
        "source_claim": {
            "source_id": SOURCE_ID_BOOK,
            "alert_id": key,
            "title": meta["title"],
            "url": meta["url"],
            "date": meta["date"],
            "summary": _SUMMARIES[key],
            "citation_only": True,
            "fulltext": False,
            "claim_status": "SOURCE_CLAIM_INCOMPLETE",
        },
        "trade_ai_reproduction": {
            "n": full["n"],
            "mean": full["mean"],
            "median": full["median"],
            "win_rate": full["win_rate"],
            "std": full["std"],
            "in_sample": ins,
            "oos": oos,
            "fixture": str(DEFAULT_FIXTURE.name),
            "not_vendor_print": True,
        },
        "current_application": {
            "role": "risk_modifier_or_context",
            "max_influence_pct": MAX_INFLUENCE_PCT,
            "standalone_sell": False,
            "creates_trim": False,
            "partisan_conclusion": None,
            "as_of_year": as_of_year,
            "cycle_label": presidential_cycle_label(as_of_year),
            "note": (
                f"Context only. ≤{MAX_INFLUENCE_PCT:.0f}% conviction/sizing language. "
                "Never a standalone sell. Does not create TRIM."
            ),
        },
    }
    return {
        "slice": key,
        "month": month,
        "month_name": MONTH_NAMES[month],
        "cycle_label": cycle,
        "evidence_grade": grade.value,
        "research_status": status.value,
        "layers": layers,
        "n": full["n"],
        "mean": full["mean"],
        "win_rate": full["win_rate"],
        "authority": AUTHORITY,
        "version": ALMANAC_VERSION,
        "partisan_conclusion": None,
    }


def reproduced_weak_months(rows: Optional[list[dict[str, Any]]] = None, *, min_n: int = 20) -> set[int]:
    rows = rows if rows is not None else load_monthly_fixture()
    usable: dict[int, float] = {}
    for m in range(1, 13):
        s = summarize(_filter(rows, month=m))
        if (s["n"] or 0) >= min_n and s["mean"] is not None:
            usable[m] = float(s["mean"])
    if not usable:
        return set()
    ranked = sorted(usable, key=lambda m: usable[m])
    return set(ranked[:3]) | {m for m, v in usable.items() if v < 0}


def calendar_family_differentials(rows: Optional[list[dict[str, Any]]] = None) -> dict[str, list[float]]:
    """12 equal-length month-underweight rules (complete years only).

    Differential = -(month return): a 'avoid that month' rule vs staying invested.
    Evaluated as a FAMILY — never winner-only.
    """
    rows = rows if rows is not None else load_monthly_fixture()
    by_year: dict[int, dict[int, float]] = {}
    for r in rows:
        by_year.setdefault(int(r["year"]), {})[int(r["month"])] = float(r["return_pct"])
    family = {MONTH_NAMES[m]: [] for m in range(1, 13)}
    for year in sorted(by_year):
        months = by_year[year]
        if any(m not in months for m in range(1, 13)):
            continue
        for m in range(1, 13):
            family[MONTH_NAMES[m]].append(-float(months[m]))
    return family


def challenge_calendar_family(
    rows: Optional[list[dict[str, Any]]] = None,
    *,
    seed: int = 7,
    n_resamples: int = 200,
) -> dict[str, Any]:
    family = calendar_family_differentials(rows)
    names = [k for k, v in family.items() if len(v) >= 8]
    series = [family[k] for k in names]
    if len(series) < 2:
        return {
            "status": "UNAVAILABLE",
            "reason": "calendar family needs >= 2 rules with adequate N",
            "family": names,
            "authority": AUTHORITY,
        }
    rc = calendar_family_reality_check(
        "sta_calendar_month_underweight",
        series,
        n_bootstrap=n_resamples,
        seed=seed,
        family_definition_hash="r3-calendar-12-month-underweight",
        trial_family_id="r3-calendar-family",
        confirmatory=False,
    )
    return {
        "status": rc.get("status") or "OK",
        "family": names,
        "n_rules": rc.get("n_rules") or len(series),
        "pvalue": rc.get("bootstrap_pvalue"),
        "statistic": rc.get("observed_statistic"),
        "whole_family": True,
        "winner_only": False,
        "source": "sullivan_timmermann_white_calendar_effects_2001",
        "authority": AUTHORITY,
        "note": "Challenges the searched calendar family; does not anoint a winner.",
        "raw": {k: rc[k] for k in rc if k != "resamples"},
    }


def as_research_evidence(slice_result: dict[str, Any]) -> ResearchEvidence:
    grade = EvidenceGrade(slice_result["evidence_grade"])
    status = ResearchStatus(slice_result["research_status"])
    return ResearchEvidence(
        fact_id=f"almanac:{slice_result['slice']}",
        fact=(
            f"{slice_result['month_name']} seasonality ({slice_result['slice']}): "
            f"n={slice_result['n']} mean={slice_result['mean']}"
        ),
        source_id=SOURCE_ID_BOOK,
        source_date=slice_result["layers"]["source_claim"]["date"],
        evidence_type=EvidenceType.SEASONALITY,
        research_status=status,
        evidence_grade=grade,
        influence_class=InfluenceClass.CONTEXT_MODIFIER,
        reproduction_ids=[f"r3-{slice_result['slice']}"] if slice_result["n"] else [],
        sample_n=slice_result["n"],
        period="monthly",
        current_applicability=slice_result["layers"]["current_application"]["note"],
        caveat="Fixture reproduction; not a vendor print. Context only.",
        role_in_decision="risk_modifier_or_context",
    )


def bundle(*, as_of_year: int = 2026) -> dict[str, Any]:
    rows = load_monthly_fixture()
    slices = {k: reproduce_slice(k, rows=rows, as_of_year=as_of_year) for k in STA_PUBLIC_ALERTS}
    weak = reproduced_weak_months(rows)
    challenge = challenge_calendar_family(rows)
    return {
        "authority": AUTHORITY,
        "version": ALMANAC_VERSION,
        "as_of_year": as_of_year,
        "cycle_label": presidential_cycle_label(as_of_year),
        "partisan_conclusion": None,
        "slices": slices,
        "reproduced_weak_months": sorted(weak),
        "august_hardcoded_bearish": False,
        "august_in_weak_set": 8 in weak,
        "calendar_family_challenge": challenge,
        "max_influence_pct": MAX_INFLUENCE_PCT,
        "standalone_sell": False,
        "creates_trim": False,
        "fulltext": False,
    }
