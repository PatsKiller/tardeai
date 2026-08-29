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
    # A contradicted fact is dropped, not fatal to the dimension. "Do not
    # apply" is a instruction about *that fact*; August failing to reproduce
    # says nothing about September. Blocking the whole dimension on one X
    # would make an honest re-grade look like a corpus outage.
    if contradicted and not closing:
        return {"closes": False, "reason": "corpus_fact_contradicted_grade_x",
                "source_refs": refs, "dimension": dim,
                "contradicted": [f.get("source_id") for f in contradicted]}
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


# ---------------------------------------------------------------- registry
#
# Wave 3A. The 20-30 publications were not missing — they were catalogued in
# `config/cio_research_source_catalog.json` all along, which the previous
# corpus sweep missed by searching data/ dirs and filename globs rather than
# config/. The catalog is honest about itself: all 34 entries carry
# full_text_status=NOT_FOUND_IN_FILE_LIBRARY, claim_status=
# SOURCE_CLAIM_INCOMPLETE and license_class=COPYRIGHT.
#
# So the registry below is one index over two populations:
#   - 11 library facts   (reproducible, graded, may close a context gap)
#   - 34 catalogued works (citation only, no lawful full text -> grade D)
#
# Grade D "must not be treated as a Trade AI fact", so no catalogue entry can
# ever corpus_hit. They are listed so the gate can cite them as context and so
# a census question has one answer instead of a search.

CATALOG_RELPATH = ("config", "cio_research_source_catalog.json")
CATALOG_GRADE = "D"          # no lawful full text -> not reproducible -> D


def _catalog_path() -> Path:
    return Path(__file__).resolve().parents[2].joinpath(*CATALOG_RELPATH)


def catalog_entries() -> list[dict[str, Any]]:
    """The 34 catalogued works, normalised into registry shape."""
    try:
        raw = json.loads(_catalog_path().read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for s in (raw.get("sources") or []):
        if not isinstance(s, dict):
            continue
        full_text = str(s.get("full_text_status") or "")
        on_disk = full_text not in {"", "NOT_FOUND_IN_FILE_LIBRARY"}
        out.append({
            "source_id": s.get("source_id"),
            "family": "context",
            "title": s.get("title"),
            "authors": s.get("authors"),
            "path": None if not on_disk else s.get("path"),
            "content_hash": None,
            "as_of": None,
            "evidence_grade": CATALOG_GRADE,
            "application_law": ("citation only — no lawful full text on disk; "
                                "grade D must not be treated as a Trade AI fact"),
            "dimension_scope": "context",
            "source_type": s.get("source_type"),
            "canon_class": s.get("canon_class"),
            "license_class": s.get("license_class"),
            "full_text_status": full_text,
            "claim_status": s.get("claim_status"),
            "on_disk": on_disk,
            "can_corpus_hit": False,
        })
    return out


def registry() -> dict[str, Any]:
    """One index over both populations. Reads only; ingests nothing."""
    facts = []
    for f in library_facts():
        grade = str(f.get("evidence_grade") or "")
        facts.append({
            "source_id": f.get("source_id"),
            "family": f.get("family"),
            "title": f.get("title"),
            "path": None,
            "content_hash": None,
            "as_of": None,
            "evidence_grade": grade,
            "application_law": f.get("current_applicability"),
            "dimension_scope": "context",
            "on_disk": False,
            "can_corpus_hit": grade in CLOSING_GRADES,
        })
    cat = catalog_entries()

    # Wave 3A.2 seed: Family A-G sources, plus calendar effects reproduced
    # against the Ken French monthly series. Same index, no second store.
    seed: list[dict[str, Any]] = []
    calendar: list[dict[str, Any]] = []
    try:
        from scripts.lib.cio_library_seed import (
            fred_series_rows, seed_rows, wave3a3_series_rows,
        )

        from scripts.lib.cio_library_seed import edgar_row

        seed = (list(seed_rows()) + list(fred_series_rows())
                + list(wave3a3_series_rows()) + [edgar_row()])
    except Exception:
        seed = []
    try:
        from scripts.lib.cio_calendar_facts import build_calendar_facts

        calendar = list(build_calendar_facts())
    except Exception:
        calendar = []
    regime: list[dict[str, Any]] = []
    try:
        from scripts.lib.cio_regime_facts import build_regime_facts

        regime = list(build_regime_facts())
    except Exception:
        regime = []
    for row in regime:
        row["can_corpus_hit"] = (
            str(row.get("evidence_grade")) in CLOSING_GRADES
            and row.get("dimension_scope") == "context")
    for row in seed:
        row["can_corpus_hit"] = (
            str(row.get("evidence_grade")) in CLOSING_GRADES
            and row.get("dimension_scope") == "context")
    for row in calendar:
        row["can_corpus_hit"] = (
            str(row.get("evidence_grade")) in CLOSING_GRADES
            and row.get("dimension_scope") == "context")

    return {
        "corpus_index_version": CORPUS_INDEX_VERSION,
        "authority": AUTHORITY,
        "library_facts": facts,
        "catalog": cat,
        "seed": seed,
        "calendar_facts": calendar,
        "regime_facts": regime,
        "counts": {
            "library_facts": len(facts),
            "catalog": len(cat),
            "catalog_on_disk": sum(1 for c in cat if c["on_disk"]),
            "can_corpus_hit": sum(1 for f in facts if f["can_corpus_hit"]),
            "seed": len(seed),
            "seed_on_disk": sum(1 for s in seed if s.get("status") == "FOUND_ON_DISK"),
            "calendar_facts": len(calendar),
            "calendar_reproduced": sum(1 for c in calendar if c.get("reproduced")),
            "regime_facts": len(regime),
        },
        "freshness_law": "research_source_index.decide() — this module keeps none",
        "note": ("Catalogued works are citation-only until lawful full text "
                 "exists; grade D can never close a research gap."),
    }
