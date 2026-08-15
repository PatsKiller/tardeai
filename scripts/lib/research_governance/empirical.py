"""R8 empirical factor / strategy families — fixture-first, whole-family only.

A 12-variant month-underweight family (underweight Jan..Dec). Each variant's
performance differential is ``-month_return`` on complete years only, so the
family is equal-length. Losers are recorded. No winner is anointed.

This is EMPIRICAL_STRATEGY / EMPIRICAL_FACTOR — not a trade.

READ_ONLY_ADVISORY. Never a standalone sell. Never creates TRIM.
Never claims OOS_SUPPORTED unless a real unused OOS window is registered
(this fixture runner does not register one).
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .almanac import MONTH_NAMES
from .almanac import load_monthly_fixture as _almanac_load_monthly_fixture
from .bootstrap_reality_check import calendar_family_reality_check
from .enums import EvidenceGrade, EvidenceType, InfluenceClass, ResearchStatus
from .models import ResearchEvidence, _stable_hash
from .multiple_testing import holm
from .trial_registry import TrialRegistry

AUTHORITY = "READ_ONLY_ADVISORY"
EMPIRICAL_VERSION = "r8_empirical_1.0.0"
MAX_INFLUENCE_PCT = 10.0
N_VARIANTS = 12
FAMILY_ID = "r8-month-underweight"
HYPOTHESIS_ID = "r8-empirical-month-underweight"
SOURCE_ID = "us_equity_monthly_sample"
INFLUENCE_CLASS = InfluenceClass.CONTEXT_MODIFIER

_PROTOCOL = {
    "family_id": FAMILY_ID,
    "hypothesis_id": HYPOTHESIS_ID,
    "rule": "month_underweight",
    "differential": "-month_return",
    "complete_years_only": True,
    "n_variants": N_VARIANTS,
    "fixture": "us_equity_monthly_sample.csv",
    "primary_metric": "mean_differential",
    "version": EMPIRICAL_VERSION,
}
PROTOCOL_HASH = _stable_hash(_PROTOCOL)
FAMILY_DEFINITION_HASH = _stable_hash({
    "protocol_hash": PROTOCOL_HASH,
    "planned_months": list(range(1, N_VARIANTS + 1)),
    "rule": "month_underweight",
})
DATASET_HASH = _stable_hash({
    "fixture": "us_equity_monthly_sample.csv",
    "kind": "monthly_equity",
})
CODE_SHA = _stable_hash({"module": "empirical", "version": EMPIRICAL_VERSION})

_CONTEXT_NOTE = (
    f"Context only. ≤{MAX_INFLUENCE_PCT:.0f}% conviction/sizing language. "
    "Never a standalone sell. Does not create TRIM. Whole family recorded; "
    "no winner-only promotion."
)


def load_monthly_fixture(path: Optional[Path] = None) -> list[dict[str, Any]]:
    """Reuse the Almanac US-equity monthly fixture."""
    return _almanac_load_monthly_fixture(path)


def _trial_id(month: int) -> str:
    return f"month_{int(month):02d}"


def _config_hash(month: int) -> str:
    return _stable_hash({"rule": "month_underweight", "month": int(month)})


def _planned_trials() -> list[tuple[str, str]]:
    return [(_trial_id(m), _config_hash(m)) for m in range(1, N_VARIANTS + 1)]


def variant_returns(month: int, rows: Optional[list[dict[str, Any]]] = None) -> list[float]:
    """Differential = -month_return for complete years only (equal length 12)."""
    m = int(month)
    if m < 1 or m > 12:
        raise ValueError(f"month must be in 1..12, got {month!r}")
    rows = rows if rows is not None else load_monthly_fixture()
    by_year: dict[int, dict[int, float]] = {}
    for r in rows:
        by_year.setdefault(int(r["year"]), {})[int(r["month"])] = float(r["return_pct"])
    out: list[float] = []
    for year in sorted(by_year):
        months = by_year[year]
        if any(k not in months for k in range(1, 13)):
            continue
        out.append(-float(months[m]))
    return out


def _betacf(a: float, b: float, x: float, *, max_iter: int = 200, eps: float = 3e-7) -> float:
    """Lentz continued fraction for the incomplete beta (Numerical Recipes)."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            return h
    return h


def _reg_inc_beta(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_beta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    if x < (a + 1.0) / (a + b + 2.0):
        front = math.exp(a * math.log(x) + b * math.log(1.0 - x) - ln_beta)
        return front * _betacf(a, b, x) / a
    front = math.exp(b * math.log(1.0 - x) + a * math.log(x) - ln_beta)
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _student_t_sf(t: float, df: float) -> float:
    """P(T_df > t). Symmetric Student-t survival via regularized incomplete beta."""
    x = df / (df + t * t)
    half = 0.5 * _reg_inc_beta(df / 2.0, 0.5, x)
    if t >= 0.0:
        return half
    return 1.0 - half


def _one_sided_mean_gt_zero_pvalue(xs: list[float]) -> float:
    """One-sided t-test H1: mean > 0. Fail-closed to p=1 on degenerate samples."""
    n = len(xs)
    if n < 2:
        return 1.0
    mean = statistics.fmean(xs)
    sd = statistics.stdev(xs)
    if not math.isfinite(mean) or not math.isfinite(sd):
        raise ValueError("non-finite mean/sd in variant series")
    if sd == 0.0:
        return 0.0 if mean > 0.0 else 1.0
    t_stat = mean / (sd / math.sqrt(n))
    if not math.isfinite(t_stat):
        raise ValueError("non-finite t-statistic")
    p = _student_t_sf(t_stat, float(n - 1))
    if not math.isfinite(p):
        raise ValueError("non-finite p-value")
    return min(1.0, max(0.0, float(p)))


def _grade_for_fixture(n: int) -> EvidenceGrade:
    """Grade C at best on the fixture — never A/B, never an OOS upgrade."""
    if n >= 15:
        return EvidenceGrade.C
    return EvidenceGrade.D


def _status_for_fixture(n: int) -> ResearchStatus:
    if n >= 15:
        return ResearchStatus.IN_SAMPLE_REPRODUCED
    if n > 0:
        return ResearchStatus.HYPOTHESIS_REGISTERED
    return ResearchStatus.SOURCE_CLAIM


def run_family(
    *,
    confirmatory: bool = False,
    family_definition_hash: Optional[str] = None,
) -> dict[str, Any]:
    """Freeze, record all 12 planned variants, multiple-test, and family-challenge.

    ``selected_winner`` remains None. ``oos_claimed`` is False: this runner does
    not register an OOS window. Confirmatory freeze requires
    ``family_definition_hash`` (registry-enforced; we also require it here).
    """
    if confirmatory and not (family_definition_hash or "").strip():
        raise ValueError("family_definition_hash is required for a confirmatory family")

    rows = load_monthly_fixture()
    series_by_month = {m: variant_returns(m, rows=rows) for m in range(1, 13)}
    lengths = {len(series_by_month[m]) for m in range(1, 13)}
    if len(lengths) != 1:
        raise ValueError(f"variant series have unequal lengths: {sorted(lengths)}")

    planned = _planned_trials()
    registry = TrialRegistry()
    registry.freeze_family(
        FAMILY_ID,
        HYPOTHESIS_ID,
        protocol_hash=PROTOCOL_HASH,
        planned_trials=planned,
        family_definition_hash=family_definition_hash if confirmatory else None,
        confirmatory=confirmatory,
    )

    now = datetime.now(timezone.utc).isoformat()
    trials: list[dict[str, Any]] = []
    pvalues: list[float] = []
    series: list[list[float]] = []

    for month in range(1, 13):
        xs = series_by_month[month]
        n = len(xs)
        mean = statistics.fmean(xs) if n else None
        p = _one_sided_mean_gt_zero_pvalue(xs)
        payload = {"month": month, "n": n, "mean": mean}
        rec_kwargs: dict[str, Any] = {
            "result_payload": payload,
        }
        if confirmatory:
            rec_kwargs.update(
                code_sha=CODE_SHA,
                dataset_hash=DATASET_HASH,
                started_at=now,
                completed_at=now,
            )
        rec = registry.record_trial(
            FAMILY_ID,
            _trial_id(month),
            config_hash=_config_hash(month),
            **rec_kwargs,
        )
        trial = {
            "trial_id": _trial_id(month),
            "month": month,
            "month_name": MONTH_NAMES[month],
            "n": n,
            "mean": mean,
            "pvalue": p,
            "config_hash": rec.config_hash,
            "result_hash": rec.result_hash,
            "terminal_status": rec.terminal_status,
        }
        trials.append(trial)
        pvalues.append(p)
        series.append(xs)

    # Fail-closed: malformed p-values raise ValueError from multiple_testing.
    mt = holm(pvalues, alpha=0.05)
    multiple = {
        "method": mt["method"],
        "adjusted": mt["adjusted"],
        "rejected": mt["rejected"],
        "alpha": mt["alpha"],
        "raw_pvalues": pvalues,
        "n": len(pvalues),
    }

    rc = calendar_family_reality_check(
        FAMILY_ID,
        series,
        n_bootstrap=200,
        seed=7,
        family_definition_hash=family_definition_hash if confirmatory else None,
        trial_family_id=FAMILY_ID,
        confirmatory=confirmatory,
    )
    family_challenge = {
        **{k: rc[k] for k in rc if k != "resamples"},
        "winner_only": False,
        "whole_family": True,
        "authority": AUTHORITY,
        "pvalue": rc.get("bootstrap_pvalue"),
        "statistic": rc.get("observed_statistic"),
    }

    completeness = registry.completeness_report(FAMILY_ID)
    family_complete = bool(completeness.get("complete")) and len(trials) == N_VARIANTS

    return {
        "authority": AUTHORITY,
        "version": EMPIRICAL_VERSION,
        "winner_only": False,
        "whole_family": True,
        "standalone_sell": False,
        "creates_trim": False,
        "family_complete": family_complete,
        "n_variants": N_VARIANTS,
        "trials": trials,
        "multiple_testing": multiple,
        "family_challenge": family_challenge,
        "selected_winner": None,
        "influence_class": INFLUENCE_CLASS.value,
        "max_influence_pct": MAX_INFLUENCE_PCT,
        "oos_claimed": False,
        "research_status": _status_for_fixture(
            min((int(t["n"]) for t in trials), default=0)
        ).value,
        "family_id": FAMILY_ID,
        "hypothesis_id": HYPOTHESIS_ID,
        "protocol_hash": PROTOCOL_HASH,
        "family_definition_hash": family_definition_hash if confirmatory else None,
        "confirmatory": confirmatory,
        "completeness": completeness,
    }


def attempt_winner_only(pack: dict[str, Any]) -> None:
    """Refuse winner-only promotion.

    Raises ValueError if the family is incomplete, if losers were not recorded,
    or if a caller tries to anoint ``selected_winner``.
    """
    if not isinstance(pack, dict):
        raise ValueError("attempt_winner_only requires a family pack dict")
    trials = list(pack.get("trials") or [])
    n_variants = int(pack.get("n_variants") or N_VARIANTS)
    complete = bool(pack.get("family_complete")) and len(trials) >= n_variants
    if not complete:
        raise ValueError("cannot select a winner from an incomplete family")
    losers = [
        t for t in trials
        if t.get("mean") is not None and float(t["mean"]) <= 0.0
    ]
    if not losers:
        raise ValueError("cannot select a winner without recording losers")
    raise ValueError(
        "winner-only selection is forbidden; selected_winner must remain None"
    )


def as_research_evidence(pack: dict[str, Any]) -> list[ResearchEvidence]:
    """EMPIRICAL_STRATEGY, grade C at best on fixture, CONTEXT_MODIFIER."""
    if not isinstance(pack, dict):
        raise ValueError("as_research_evidence requires a family pack dict")
    trials = list(pack.get("trials") or [])
    ns = [int(t["n"]) for t in trials if t.get("n") is not None]
    n_min = min(ns) if ns else 0
    grade = _grade_for_fixture(n_min)
    status = _status_for_fixture(n_min)
    # Hard invariant: fixture family never claims OOS_SUPPORTED.
    if status is ResearchStatus.OOS_SUPPORTED:
        status = ResearchStatus.IN_SAMPLE_REPRODUCED
    if grade in {EvidenceGrade.A, EvidenceGrade.B}:
        grade = EvidenceGrade.C

    evidence: list[ResearchEvidence] = [
        ResearchEvidence(
            fact_id="empirical:month_underweight:family",
            fact=(
                f"Month-underweight empirical family: n_variants={pack.get('n_variants')} "
                f"family_complete={pack.get('family_complete')} "
                f"selected_winner={pack.get('selected_winner')}"
            ),
            source_id=SOURCE_ID,
            evidence_type=EvidenceType.EMPIRICAL_STRATEGY,
            research_status=status,
            evidence_grade=grade,
            influence_class=INFLUENCE_CLASS,
            reproduction_ids=[FAMILY_ID],
            sample_n=n_min or None,
            period="monthly",
            current_applicability=_CONTEXT_NOTE,
            caveat=(
                "Fixture family; not a vendor print. Context only. "
                "Whole family recorded; no winner-only promotion. OOS not claimed."
            ),
            role_in_decision="risk_modifier_or_context",
        )
    ]
    for t in trials:
        n = int(t["n"]) if t.get("n") is not None else 0
        month = int(t["month"])
        evidence.append(
            ResearchEvidence(
                fact_id=f"empirical:month_underweight:{month:02d}",
                fact=(
                    f"{t.get('month_name') or MONTH_NAMES.get(month, month)} "
                    f"underweight: n={n} mean={t.get('mean')}"
                ),
                source_id=SOURCE_ID,
                evidence_type=EvidenceType.EMPIRICAL_STRATEGY,
                research_status=_status_for_fixture(n),
                evidence_grade=_grade_for_fixture(n),
                influence_class=INFLUENCE_CLASS,
                reproduction_ids=[f"{FAMILY_ID}:{_trial_id(month)}"],
                sample_n=n or None,
                period="monthly",
                current_applicability=_CONTEXT_NOTE,
                caveat="Fixture variant in a complete searched family. Context only.",
                role_in_decision="risk_modifier_or_context",
            )
        )
    return evidence
