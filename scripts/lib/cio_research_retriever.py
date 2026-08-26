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


def _attach_governed_audit(
    ctx: dict[str, Any],
    *,
    now: datetime,
    decision_id: Optional[str] = None,
) -> dict[str, Any]:
    """Attach R3/R4 governed Almanac + HMAC decision-use audit.

    Fail-soft: compact CIO context still returns if governance import/fixture
    is unavailable. Never creates TRIM. Never a standalone sell.
    Does not call ``cio_retriever_adapter.retrieve_for_decision`` (that adapter
    imports this module — recursion is forbidden).
    """
    try:
        from scripts.lib.research_governance.almanac import as_research_evidence, bundle
        from scripts.lib.research_governance.decision_use_audit import DecisionUseLedger
        from scripts.lib.research_governance.degradation import evaluate_fact

        pack = bundle(as_of_year=int(now.year))
        evidence = []
        for sl in (pack.get("slices") or {}).values():
            ev = as_research_evidence(sl)
            if ev.evidence_grade.value != "X":
                evidence.append(ev)
        did = (decision_id or "").strip() or f"cio_research_{now.strftime('%Y%m%dT%H%M%SZ')}"
        rec = DecisionUseLedger().record(
            decision_id=did,
            query={"hook": "cio_research_retriever", "month": int(now.month)},
            evidence=evidence,
            influence_cap_pct=float(pack.get("max_influence_pct") or MAX_INFLUENCE_PCT),
            as_of=now.isoformat(),
        )
        deg = evaluate_fact(evidence[0]) if evidence else None
        ctx["governed_audit"] = {
            "status": "OK",
            "decision_id": rec.decision_id,
            "record_digest": rec.record_digest,
            "signature_ok": rec.verify(),
            "influence_cap_pct": rec.influence_cap_pct,
            "forbidden_actions": list(rec.forbidden_actions),
            "fact_ids": list(rec.fact_ids),
            "degradation": (
                {"action": deg.action, "reason": deg.reason} if deg is not None else None
            ),
            "authority": AUTHORITY,
            "creates_trim": False,
            "standalone_sell": False,
            "partisan_conclusion": pack.get("partisan_conclusion"),
            "august_hardcoded_bearish": bool(pack.get("august_hardcoded_bearish")),
        }
        ctx["governed_almanac"] = {
            "version": pack.get("version"),
            "cycle_label": pack.get("cycle_label"),
            "weak_months": pack.get("reproduced_weak_months"),
            "max_influence_pct": pack.get("max_influence_pct"),
            "standalone_sell": False,
            "creates_trim": False,
            "slices": {
                k: {
                    "n": sl.get("n"),
                    "mean": sl.get("mean"),
                    "evidence_grade": sl.get("evidence_grade"),
                    "layers": sl.get("layers"),
                }
                for k, sl in (pack.get("slices") or {}).items()
            },
        }
    except Exception as exc:  # noqa: BLE001 — fail-soft; compact context still usable
        ctx["governed_audit"] = {
            "status": "UNAVAILABLE",
            "reason": str(exc)[:240],
            "authority": AUTHORITY,
            "creates_trim": False,
            "standalone_sell": False,
        }
    return ctx


def retrieve_research_context(
    now: Optional[datetime] = None,
    symbols: Optional[Sequence[str]] = None,
    decision_id: Optional[str] = None,
) -> dict[str, Any]:
    """Hook used by compose_strategy_context / capital plan (modifier note only)."""
    now = now or datetime.now(timezone.utc)
    payload = retrieve_for_decision(now=now, symbols=symbols, decision_id=decision_id)
    # Surface a stable, compact context object for the plan envelope.
    ctx = {
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
    return _attach_governed_audit(
        ctx,
        now=now,
        decision_id=decision_id or payload.get("decision_id"),
    )
