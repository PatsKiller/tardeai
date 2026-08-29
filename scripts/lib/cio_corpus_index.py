"""Read-only adapter over the institutional corpus that already exists.

Deliberately not a store. Every fact here is owned by another module
(`cio_research_library`, `cio_seasonality_analytics`, the earnings calendar);
this only *asks* them whether they close a question, so the free-first branch of
the research gate has something to consult before spending a model call.

See docs/ops/CIO_INSTITUTIONAL_CORPUS_MAP_2026-08-29.md for what is on disk.
The short version: 11 library facts over 7 families, and only `seasonality` has
real depth, so a corpus_hit outside seasonality is rare by construction rather
than by accident.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

CORPUS_INDEX_VERSION = "corpus_index_1.0.0"
AUTHORITY = "READ_ONLY_ADVISORY"

# A question dimension is only closable by a family that actually speaks to it.
# Without this a seasonality fact would "close" a bear-case question and the
# gate would skip research on a name it has never looked at.
# Only independently reproduced grades may close a gap. The registry's own
# wording: A/B "independently reproduced … risk-modifier only"; C "challenge-
# prompt / context only"; D "must not be treated as a Trade AI fact"; X
# "reproduction contradicts the source claim — do not apply."
CLOSING_GRADES = frozenset({"A", "B"})
CONTEXT_ONLY_GRADES = frozenset({"C", "D"})

DIMENSION_FAMILIES: dict[str, tuple[str, ...]] = {
    "seasonality": ("seasonality",),
    "calendar": ("seasonality",),
    "macro": ("macro",),
    "valuation": ("value",),
    "trend": ("trend", "breadth"),
    "risk": ("risk",),
    "tax": ("wealth_tax",),
}

# Dimensions no corpus fact may ever close: they are entity-specific and the
# library is entity-agnostic. Listing them is the point — it stops a future
# family from silently acquiring authority over a name-level question.
ENTITY_ONLY_DIMENSIONS = frozenset({
    "structural_drivers", "bear_case", "what_is_priced_in",
    "earnings_quality", "guidance", "competitive_position",
})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def library_facts() -> list[dict[str, Any]]:
    """The 11 structured facts. Empty list if the library cannot be imported."""
    try:
        from scripts.lib.cio_research_library import library_facts as _lf

        return list(_lf() or [])
    except Exception:
        return []


def seasonality_context(*, now: Optional[datetime] = None) -> dict[str, Any]:
    """Current month/cycle stats from the 1950- series, or {} if unavailable."""
    now = now or _utc_now()
    try:
        from scripts.lib import cio_seasonality_analytics as sa

        fn = "september_general" if now.month == 9 else "august_general"
        rec = getattr(sa, fn)() if hasattr(sa, fn) else {}
        return dict(rec or {})
    except Exception:
        return {}


def earnings_within(days: int, *, root: Path | str | None = None,
                    now: Optional[datetime] = None) -> dict[str, int]:
    """Symbols with a known earnings date within `days`. {} if no calendar.

    Event proximity is the one corpus signal that makes a job *more* eligible
    rather than less, so it is read here and fed to the cadence rule.
    """
    now = now or _utc_now()
    if root is None:
        return {}
    path = Path(root) / "data" / "portfolios" / "state" / "earnings_dates.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, int] = {}
    for sym, rec in (raw or {}).items():
        if not isinstance(rec, dict):
            continue
        d = rec.get("earnings_date")
        if not d:
            continue
        try:
            when = datetime.strptime(str(d)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        delta = (when - now).days
        if 0 <= delta <= days:
            out[str(sym).upper()] = delta
    return out


def consult(dimension: str, *, family_hint: str | None = None,
            now: Optional[datetime] = None) -> dict[str, Any]:
    """Ask the corpus whether it closes one question dimension.

    Returns a decision-shaped dict, never a bare bool, because the gate has to
    record *which* refs were consulted even when they do not close the gap.
    """
    dim = str(dimension or "").strip().lower()
    if not dim or dim in ENTITY_ONLY_DIMENSIONS:
        return {"closes": False, "reason": "entity_specific_dimension",
                "source_refs": [], "dimension": dim}

    families = DIMENSION_FAMILIES.get(dim)
    if not families and family_hint:
        families = (family_hint,)
    if not families:
        return {"closes": False, "reason": "no_family_for_dimension",
                "source_refs": [], "dimension": dim}

    hits = [f for f in library_facts()
            if str(f.get("family") or "").lower() in families]
    if not hits:
        return {"closes": False, "reason": "no_corpus_fact_for_family",
                "source_refs": [], "dimension": dim}

    refs = [{"source_id": f.get("source_id"),
             "family": f.get("family"),
             "evidence_grade": f.get("evidence_grade"),
             "max_influence_pct": f.get("max_influence_pct"),
             "applicability": f.get("current_applicability")}
            for f in hits]

    # The corpus carries its own application law in `evidence_grade`, and it is
    # stricter than "the almanac answered it":
    #
    #   A/B  independently reproduced — but "risk-modifier only", max 10%
    #        conviction adjustment, never a standalone sell
    #   C    "challenge-prompt / context only"
    #   D    "must not be treated as a Trade AI fact"
    #   X    reproduction contradicts the claim — do not apply
    #
    # So only A/B may close a gap, and only for a context-level dimension.
    # Letting C or D close one would launder an unreproduced citation into a
    # resolved question and skip the research that would have caught it.
    closing = [f for f in hits if str(f.get("evidence_grade") or "") in CLOSING_GRADES]
    contradicted = [f for f in hits if str(f.get("evidence_grade") or "") == "X"]
    if contradicted:
        return {"closes": False, "reason": "corpus_fact_contradicted_grade_x",
                "source_refs": refs, "dimension": dim}
    if not closing:
        grades = sorted({str(f.get("evidence_grade")) for f in hits})
        return {"closes": False,
                "reason": "corpus_fact_context_only_grade_" + "".join(grades).lower(),
                "source_refs": refs, "dimension": dim}
    refs = [r for r in refs if str(r.get("evidence_grade")) in CLOSING_GRADES]

    ctx = seasonality_context(now=now) if "seasonality" in families else {}
    # Carry the ceiling forward. A corpus_hit resolves the *research need*; it
    # never buys more authority than the fact itself has, and nothing
    # downstream may read it as a sell.
    ceiling = min([float(r.get("max_influence_pct") or 10.0) for r in refs] or [10.0])
    return {
        "closes": True,
        "reason": "corpus_fact_reproduced",
        "source_refs": refs,
        "dimension": dim,
        "seasonality": ctx or None,
        "max_influence_pct": ceiling,
        "standalone_sell": False,
        "creates_trim": False,
        "role": "risk_modifier_or_context",
        "corpus_index_version": CORPUS_INDEX_VERSION,
        "authority": AUTHORITY,
    }


def coverage() -> dict[str, Any]:
    """Family -> fact count. Used by the ops surface and the corpus map doc."""
    counts: dict[str, int] = {}
    for f in library_facts():
        fam = str(f.get("family") or "unknown")
        counts[fam] = counts.get(fam, 0) + 1
    return {
        "corpus_index_version": CORPUS_INDEX_VERSION,
        "authority": AUTHORITY,
        "families": counts,
        "total_facts": sum(counts.values()),
        "entity_only_dimensions": sorted(ENTITY_ONLY_DIMENSIONS),
        "note": ("Only seasonality has depth; other families hold a single "
                 "placeholder fact each, so corpus_hit is rare by construction."),
    }
