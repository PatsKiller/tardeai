"""SourceLibrarian@v1 — a graded source has a SHELF LIFE, not just a grade.

The corpus already knows how good a fact is: `cio_research_registry` defines
evidence grades A/B/C/D/X and `cio_corpus_index.CLOSING_GRADES` lets A and B
close a research gap without spending a model call. What nothing knew is how
OLD that is allowed to be. A grade-B fact from eighteen months ago still read
as grade B, still closed the gap, and the desk answered a question about today
with a source nobody had looked at since.

This module adds the missing axis, and adds it to the store that already owns
freshness rather than to a second one:

    research_source_index row .extra += {grade, last_seen, stale_after_days}

`stale_after_days` defaults FROM the grade — a reproduced, out-of-sample-
supported A-fact keeps for a year; a bare source claim keeps for a fortnight —
and an operator may override it per source. Past that horizon the source is
dropped from `corpus_hit` eligibility. Not deleted, not downgraded: dropped
from the one decision where being old is disqualifying. If dropping the stale
sources leaves nothing that can close the gap, the corpus stops closing it and
the gate falls through to the ladder it would have used anyway.

**The librarian only demotes what it has metadata for.** A source with no grade
and no last_seen gets no opinion and behaves exactly as it did before this
module existed. That is deliberate: inventing a staleness verdict for a source
nobody graded would silently disable the corpus, and a corpus that quietly
stops closing gaps looks identical to a corpus that has nothing to say.

Discovery is NOT reimplemented here. `cio_source_discovery.discover()` already
caps proposals at 3 per entity per week, stamps them `CANDIDATE`, sets
`evidence_grade: None` and `is_fact: False`, and ingests nothing. This module
supplies the other half of that contract — `candidate_may_close()` — so an
ungraded CANDIDATE can never reach `corpus_hit` before an operator grades it.

READ_ONLY_ADVISORY. No network. No model call.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = "SourceLibrarian@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
FINANCIAL_ACTION = False

# Shelf life by evidence grade, in days. The letters are NOT redefined here —
# they are `cio_research_registry.EVIDENCE_GRADES`:
#   A robust (reproduced + out-of-sample)   B useful
#   C exploratory                            D bare source claim
#   X invalidated
# The spread follows the grade's own meaning: the better the evidence, the
# longer it stays true. X is 0 because an invalidated fact was never eligible.
STALE_AFTER_DAYS: dict[str, int] = {
    "A": 365,
    "B": 90,
    "C": 30,
    "D": 14,
    "X": 0,
}

# Only these grades can close a gap at all — the same law as
# cio_corpus_index.CLOSING_GRADES, imported at call time to avoid a cycle.
_FALLBACK_CLOSING_GRADES = frozenset({"A", "B"})

# A discovery proposal. Never a fact, never closes, until graded.
CANDIDATE_STATUS = "CANDIDATE"

META_FIELDS = ("grade", "last_seen", "stale_after_days")


def _now(now: Optional[datetime] = None) -> datetime:
    dt = now or datetime.now(timezone.utc)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse(ts: Any) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def normalize_grade(code: Any) -> str:
    """Canonical evidence letter, or "" — delegating to the registry that owns it."""
    try:
        from scripts.lib.cio_research_registry import normalize_grade as _ng
        return str(_ng(code) or "")
    except Exception:                                            # noqa: BLE001
        g = str(code or "").strip().upper()
        return g if g in STALE_AFTER_DAYS else ""


def closing_grades() -> frozenset:
    try:
        from scripts.lib.cio_corpus_index import CLOSING_GRADES
        return frozenset(CLOSING_GRADES)
    except Exception:                                            # noqa: BLE001
        return _FALLBACK_CLOSING_GRADES


def stale_after_days_for(grade: Any, *, override: Any = None) -> Optional[int]:
    """Shelf life in days. None means "no opinion" — an ungraded source."""
    if override is not None:
        try:
            return max(0, int(override))
        except (TypeError, ValueError):
            pass
    g = normalize_grade(grade)
    if not g:
        return None
    return STALE_AFTER_DAYS.get(g)


# ── persistence: the grade lives on the freshness row ──────────────────────

def set_grade(
    source_id: str,
    grade: Any,
    *,
    last_seen: Any = None,
    stale_after_days: Any = None,
    path: Path | None = None,
    root: Path | None = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Record an operator's grade for one source. Never resets its TTL."""
    now_dt = _now(now)
    from scripts.lib.research_source_index import upsert_meta
    g = normalize_grade(grade)
    meta = {
        "grade": g or None,
        "last_seen": (_parse(last_seen) or now_dt).isoformat(),
        "stale_after_days": stale_after_days_for(g, override=stale_after_days),
    }
    return upsert_meta(str(source_id), meta=meta, path=path, root=root, now=now_dt)


def source_meta(
    source_id: str,
    *,
    path: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Read back {grade, last_seen, stale_after_days, present} for one source.

    `last_seen` falls back to the index's own `last_researched_at` /
    `last_modified_at`: the moment the index last fetched a source IS the last
    time anyone saw it, and requiring a second hand-maintained timestamp would
    guarantee the two disagree.
    """
    try:
        from scripts.lib.research_source_index import get_row
        row = get_row(str(source_id), path=path, root=root)
    except Exception:                                            # noqa: BLE001
        row = None
    if not isinstance(row, dict):
        return {"source_id": str(source_id), "present": False,
                "grade": "", "last_seen": None, "stale_after_days": None}
    extra = row.get("extra") or {}
    last_seen = (extra.get("last_seen") or row.get("last_researched_at")
                 or row.get("last_modified_at"))
    grade = normalize_grade(extra.get("grade"))
    return {
        "source_id": str(source_id),
        "present": True,
        "grade": grade,
        "last_seen": last_seen,
        "stale_after_days": stale_after_days_for(
            grade, override=extra.get("stale_after_days")),
    }


# ── the eligibility verdict ────────────────────────────────────────────────

def _ref_fields(ref: Any) -> tuple[str, dict[str, Any]]:
    if isinstance(ref, dict):
        sid = str(ref.get("source_id") or ref.get("id") or ref.get("title") or "")
        return sid, ref
    return str(ref or ""), {}


def staleness(
    ref: Any,
    *,
    now: Optional[datetime] = None,
    path: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Resolve one source_ref's grade/last_seen/shelf-life and judge it.

    Resolution order: the ref's own fields first (a corpus fact carries its
    `evidence_grade` inline), then the index row, then no opinion.
    """
    now_dt = _now(now)
    sid, fields = _ref_fields(ref)
    meta = source_meta(sid, path=path, root=root) if sid else {
        "grade": "", "last_seen": None, "stale_after_days": None, "present": False}

    grade = normalize_grade(fields.get("evidence_grade")
                            or fields.get("grade")) or meta.get("grade") or ""
    last_seen = _parse(fields.get("last_seen") or fields.get("as_of")
                       or meta.get("last_seen"))
    shelf = stale_after_days_for(
        grade, override=(fields.get("stale_after_days")
                         if fields.get("stale_after_days") is not None
                         else meta.get("stale_after_days")))

    out = {
        "source_id": sid,
        "grade": grade,
        "last_seen": last_seen.isoformat() if last_seen else None,
        "stale_after_days": shelf,
        "age_days": (round((now_dt - last_seen).total_seconds() / 86400.0, 2)
                     if last_seen else None),
        "known": bool(last_seen is not None and shelf is not None),
        "stale": False,
        "reason": "no_opinion",
    }
    if str(fields.get("status") or "").strip().upper() == CANDIDATE_STATUS:
        out["reason"] = "candidate_not_graded"
        out["stale"] = True
        return out
    if grade == "X":
        out["reason"] = "grade_x_invalidated"
        out["stale"] = True
        return out
    if not out["known"]:
        return out
    horizon = last_seen + timedelta(days=int(shelf))
    if now_dt >= horizon:
        out["stale"] = True
        out["reason"] = f"stale_grade_{grade or 'ungraded'}_after_{shelf}d"
    else:
        out["reason"] = "fresh"
    return out


def corpus_eligible(
    ref: Any,
    *,
    now: Optional[datetime] = None,
    path: Path | None = None,
    root: Path | None = None,
) -> tuple[bool, dict[str, Any]]:
    """May this source close a gap right now? Returns (ok, staleness_detail)."""
    detail = staleness(ref, now=now, path=path, root=root)
    return (not detail["stale"]), detail


def candidate_may_close(candidate: dict[str, Any]) -> bool:
    """A discovery CANDIDATE never closes a gap until an operator grades it.

    The other half of `cio_source_discovery`'s contract: that module refuses to
    ingest, this one refuses to let an un-ingested proposal act like a fact.
    """
    if not isinstance(candidate, dict):
        return False
    if str(candidate.get("status") or "").strip().upper() == CANDIDATE_STATUS:
        return False
    if candidate.get("is_fact") is False:
        return False
    return normalize_grade(candidate.get("evidence_grade")) in closing_grades()


def filter_corpus(
    corpus: Optional[dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    path: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Drop stale sources from a corpus verdict; un-close it if none survive.

    Returns a NEW dict. When the corpus was not closing anything, or carries no
    source_refs the librarian has an opinion about, this is a faithful copy —
    the librarian is not allowed to make the corpus quieter than it was.
    """
    if not isinstance(corpus, dict) or not corpus:
        return dict(corpus or {})
    out = dict(corpus)
    refs = list(out.get("source_refs") or [])
    if not refs:
        return out

    kept: list[Any] = []
    dropped: list[dict[str, Any]] = []
    for ref in refs:
        ok, detail = corpus_eligible(ref, now=now, path=path, root=root)
        (kept if ok else dropped).append(ref if ok else detail)

    if not dropped:
        return out

    out["source_refs"] = kept
    out["librarian_dropped"] = dropped
    out["librarian_schema"] = SCHEMA
    if out.get("closes") and not kept:
        out["closes"] = False
        out["reason"] = "librarian_all_closing_sources_stale"
    return out


def audit(
    source_ids: Iterable[str],
    *,
    now: Optional[datetime] = None,
    path: Path | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Read-only shelf report over named sources. Ops, not notify."""
    now_dt = _now(now)
    rows = [staleness(sid, now=now_dt, path=path, root=root)
            for sid in (source_ids or [])]
    by_grade: dict[str, int] = {}
    for r in rows:
        g = r.get("grade") or "ungraded"
        by_grade[g] = by_grade.get(g, 0) + 1
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "financial_action": FINANCIAL_ACTION,
        "as_of": now_dt.isoformat(),
        "considered": len(rows),
        "graded": sum(1 for r in rows if r.get("grade")),
        "stale": sum(1 for r in rows if r.get("stale")),
        "no_opinion": sum(1 for r in rows if r.get("reason") == "no_opinion"),
        "by_grade": dict(sorted(by_grade.items())),
        "rows": rows,
        "stale_after_days": dict(STALE_AFTER_DAYS),
        "note": ("a source with no grade and no last_seen gets NO opinion and "
                 "behaves exactly as it did before the librarian existed"),
    }
