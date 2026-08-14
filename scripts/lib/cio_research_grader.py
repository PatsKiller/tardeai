"""cio_research_grader.py — Phases 11–16 evidence grader.

A robust / B useful / C exploratory / D source claim / X invalidated.

Honest grades only. A reproduction on a fixture is never silently labeled A
without N, effect, and OOS support. READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from scripts.lib.cio_research_registry import (
    EVIDENCE_GRADES,
    GRADE_CODES,
    grade_record,
    normalize_grade,
)

GRADER_VERSION = "research_grader_1.0.0"
AUTHORITY = "READ_ONLY_ADVISORY"


def t_stat(mean: Optional[float], std: Optional[float], n: Optional[int]) -> Optional[float]:
    if mean is None or std is None or not n or n < 2:
        return None
    se = float(std) / math.sqrt(int(n))
    if se == 0:
        return None
    return float(mean) / se


def grade_evidence(
    *,
    reproduced: bool = False,
    n: Optional[int] = None,
    mean: Optional[float] = None,
    win_rate: Optional[float] = None,
    std: Optional[float] = None,
    oos_mean: Optional[float] = None,
    oos_win_rate: Optional[float] = None,
    oos_n: Optional[int] = None,
    claim_direction: Optional[str] = None,
    invalidated: bool = False,
) -> dict[str, Any]:
    """Grade a single research claim against an optional independent reproduction.

    claim_direction: 'negative' / 'positive' / 'weak' / 'strong' / None
    """
    reasons: list[str] = []
    nn = int(n or 0)
    direction = (claim_direction or "").strip().lower()

    if invalidated:
        rec = grade_record("X")
        rec.update(
            {
                "version": GRADER_VERSION,
                "authority": AUTHORITY,
                "evidence_grade": "X",
                "reasons": ["explicitly invalidated"],
                "t_stat": t_stat(mean, std, n),
            }
        )
        return rec

    if not reproduced or nn <= 0 or mean is None:
        rec = grade_record("D")
        rec.update(
            {
                "version": GRADER_VERSION,
                "authority": AUTHORITY,
                "evidence_grade": "D",
                "reasons": ["no independent Trade AI reproduction"],
                "t_stat": None,
            }
        )
        return rec

    wr = win_rate
    t = t_stat(mean, std, n)
    mean_neg = mean < 0
    mean_pos = mean > 0
    wr_neg = wr is not None and wr < 0.5
    wr_pos = wr is not None and wr > 0.5

    claim_wants_weak = direction in ("negative", "weak", "below_average", "bearish")
    claim_wants_strong = direction in ("positive", "strong", "above_average", "bullish")

    contradicted = False
    if claim_wants_weak and mean_pos and (wr is None or wr_pos) and mean > 0.25 and (wr is None or wr > 0.55):
        contradicted = True
        reasons.append("source claim is weak/negative but reproduction is clearly positive")
    if claim_wants_strong and mean_neg and (wr is None or wr_neg) and mean < -0.25 and (wr is None or wr < 0.45):
        contradicted = True
        reasons.append("source claim is strong/positive but reproduction is clearly negative")

    if contradicted:
        rec = grade_record("X")
        rec.update(
            {
                "version": GRADER_VERSION,
                "authority": AUTHORITY,
                "evidence_grade": "X",
                "reasons": reasons,
                "t_stat": t,
            }
        )
        return rec

    oos_conflict = False
    if oos_mean is not None and nn >= 8:
        if mean_neg and oos_mean > 0.15:
            oos_conflict = True
        if mean_pos and oos_mean < -0.15:
            oos_conflict = True
        if oos_conflict:
            reasons.append("out-of-sample mean conflicts with in-sample direction")

    directional = (mean_neg and (wr is None or wr_neg or abs((wr or 0.5) - 0.5) < 0.03)) or (
        mean_pos and (wr is None or wr_pos or abs((wr or 0.5) - 0.5) < 0.03)
    )
    if mean_neg and wr_neg:
        reasons.append("mean < 0 and win_rate < 50%")
        directional = True
    elif mean_pos and wr_pos:
        reasons.append("mean > 0 and win_rate > 50%")
        directional = True
    elif mean != 0:
        reasons.append("mean and win_rate only weakly aligned")

    abs_t = abs(t) if t is not None else 0.0
    oos_ok = oos_mean is not None and not oos_conflict and (
        (mean_neg and oos_mean <= 0) or (mean_pos and oos_mean >= 0)
    )
    if oos_ok:
        reasons.append("OOS mean agrees on sign")

    if nn < 20:
        grade = "C"
        reasons.append(f"small sample n={nn}")
    elif oos_conflict or not directional:
        grade = "C"
        if not directional:
            reasons.append("mixed directional signals")
    elif nn >= 40 and abs_t >= 2.0 and oos_ok:
        grade = "A"
        reasons.append(f"n={nn}, |t|={abs_t:.2f}, OOS agrees")
    else:
        grade = "B"
        reasons.append(f"usable n={nn}; effect modest or OOS incomplete (|t|={abs_t:.2f})")
        if abs_t < 1.0:
            # Large N but tiny effect stays useful-as-context, not robust.
            reasons.append("small effect size — context only")

    rec = grade_record(grade)
    rec.update(
        {
            "version": GRADER_VERSION,
            "authority": AUTHORITY,
            "evidence_grade": grade,
            "reasons": reasons,
            "t_stat": t,
            "n": nn,
            "mean": mean,
            "win_rate": wr,
            "oos_mean": oos_mean,
            "oos_win_rate": oos_win_rate,
            "oos_n": oos_n,
        }
    )
    return rec


def fact_counts_by_grade(facts: list[dict[str, Any]]) -> dict[str, int]:
    counts = {g: 0 for g in ("A", "B", "C", "D", "X")}
    for f in facts or []:
        g = normalize_grade(f.get("evidence_grade") or f.get("internal_validation_status"))
        if not g:
            # map validation statuses that are not letter grades
            status = str(f.get("internal_validation_status") or "").lower()
            if status in ("reproduced_oos",) or status == "reproduced":
                g = "B"
            elif status == "partially_reproduced":
                g = "C"
            elif status == "failed_reproduction":
                g = "X"
            else:
                g = "D"
        counts[g] = counts.get(g, 0) + 1
    return counts


__all__ = [
    "AUTHORITY",
    "EVIDENCE_GRADES",
    "GRADE_CODES",
    "GRADER_VERSION",
    "fact_counts_by_grade",
    "grade_evidence",
    "t_stat",
]
