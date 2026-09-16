"""The reader that `research_contradiction` never had.

`research_contradiction.persist_candidates` has appended
`ResearchContradictionCandidate@v1` rows to
`data/cio/research_contradiction_candidates.jsonl` on every accepted research
result since it shipped -- 31,762 rows measured 2026-09-16, growing daily. A
repo-wide search for a consumer finds the writer, the module that calls the
writer, its own tests, and one baseline reporter that counts the file's LINES
and annotates `"consumer count is measured by grep, not here"`.

**Nothing has ever read a contradiction candidate.** A contradiction is the one
signal in the research engine that says an existing belief may be wrong, and it
has been written to disk and never opened. That is the loudest dormant signal
in the repository.

This module is the consumer. It is deliberately NOT an auto-resolver: a
contradiction between two research artifacts is exactly the case where a
machine choosing between two candidate truths can destroy one (AGENTS.md §17,
escalate-never-resolve). So it does three things and stops:

  1. **Groups** candidates by subject, so 31,762 rows become a short list of
     subjects that hold an unresolved internal disagreement.
  2. **Ranks** them by how contested and how fresh the disagreement is, so the
     operator sees the live ones rather than the 2026-07 backlog.
  3. **Refuses to self-validate**, reusing `research_contradiction.assess_candidate`,
     which already raises `self_validation_forbidden` when the assessor is one
     of the artifact producers. This module never assesses on its own authority;
     it prepares the assessment an independent assessor would record.

Nothing here rewrites a thesis, resolves a candidate, or mutates any source
artifact. Reading 31,762 rows and reporting that 40 subjects disagree with
themselves changes no belief by itself -- it makes the disagreement visible,
which is the step that was missing.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. FINANCIAL_ACTION = False.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from scripts.lib.research_contradiction import (
    ASSESSMENT_SCHEMA,
    SCHEMA as CANDIDATE_SCHEMA,
    assess_candidate,
)

SCHEMA = "ResearchContradictionDigest@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0
FINANCIAL_ACTION = False

CANDIDATES_RELPATH = ("data", "cio", "research_contradiction_candidates.jsonl")

# A disagreement older than this is backlog, not news. It is still reported in
# the totals -- it is simply not what the operator is shown first.
FRESH_WINDOW = timedelta(days=14)


def candidates_path(root: Path | str | None = None) -> Path:
    """Resolve the candidate store from an EXPLICIT root, never from the CWD."""
    base = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    return base.joinpath(*CANDIDATES_RELPATH)


def _parse_ts(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def load_candidates(
    path: Path | str | None = None,
    *,
    root: Path | str | None = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Read candidate rows. A missing store is an empty list, not an exception.

    Malformed lines are skipped rather than fatal: this store is append-only and
    a single truncated write must not make the whole backlog unreadable.
    """
    target = Path(path) if path is not None else candidates_path(root)
    out: list[dict[str, Any]] = []
    if not target.is_file():
        return out
    with open(target, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("schema") == CANDIDATE_SCHEMA:
                out.append(row)
                if limit is not None and len(out) >= limit:
                    break
    return out


def _subject_of(candidate: dict[str, Any]) -> str:
    """The thing the two artifacts disagree ABOUT.

    Candidates carry the shared context that made them a contradiction in the
    first place (`shared_context`, e.g. `factual.sector:Energy`). Falling back
    to the symbol keeps single-name disagreements grouped rather than scattered.
    """
    for key in ("subject_key", "subject_guid", "symbol"):
        value = candidate.get(key)
        if value:
            return str(value)
    shared = candidate.get("shared_context")
    if isinstance(shared, (list, tuple)) and shared:
        return str(shared[0])
    return "UNATTRIBUTED"


def _producers(candidate: dict[str, Any]) -> list[str]:
    """Every agent/provider that produced one of the contradicting artifacts.

    This is what makes an assessor's independence checkable: an assessor in this
    set is self-validating and `assess_candidate` refuses it.
    """
    out: list[str] = []
    for key in ("left_producer", "right_producer", "producer", "producers",
                "left_provider", "right_provider"):
        value = candidate.get(key)
        if isinstance(value, str) and value:
            out.append(value)
        elif isinstance(value, (list, tuple)):
            out.extend(str(v) for v in value if v)
    return sorted(set(out))


def digest(
    candidates: Iterable[dict[str, Any]],
    *,
    now: Optional[datetime] = None,
    top_n: int = 20,
) -> dict[str, Any]:
    """Group, rank and report. Resolves nothing and rewrites nothing."""
    moment = now or datetime.now(timezone.utc)
    rows = [c for c in candidates if isinstance(c, dict)]

    by_subject: dict[str, dict[str, Any]] = {}
    undated = 0
    for candidate in rows:
        subject = _subject_of(candidate)
        bucket = by_subject.setdefault(subject, {
            "subject": subject,
            "candidate_count": 0,
            "fresh_count": 0,
            "latest_ts": None,
            "producers": set(),
            "candidate_ids": [],
        })
        bucket["candidate_count"] += 1
        bucket["producers"].update(_producers(candidate))
        cid = candidate.get("candidate_id")
        if cid and len(bucket["candidate_ids"]) < 10:
            bucket["candidate_ids"].append(str(cid))
        ts = _parse_ts(candidate.get("detected_at") or candidate.get("created_at")
                       or candidate.get("ts"))
        if ts is None:
            undated += 1
            continue
        if (moment - ts) <= FRESH_WINDOW:
            bucket["fresh_count"] += 1
        current = bucket["latest_ts"]
        if current is None or ts > current:
            bucket["latest_ts"] = ts

    subjects = []
    for bucket in by_subject.values():
        latest = bucket["latest_ts"]
        subjects.append({
            "subject": bucket["subject"],
            "candidate_count": bucket["candidate_count"],
            "fresh_count": bucket["fresh_count"],
            "latest_ts": latest.isoformat() if latest else None,
            "producers": sorted(bucket["producers"]),
            "independent_assessor_required": True,
            "candidate_ids": bucket["candidate_ids"],
        })
    # Fresh disagreements first, then the most contested, then newest. A large
    # stale pile must not outrank a small live one.
    subjects.sort(key=lambda s: (-s["fresh_count"], -s["candidate_count"],
                                 s["latest_ts"] or "", s["subject"]))

    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "financial_action": FINANCIAL_ACTION,
        "memory_behavior_influence": MBI_BEHAVIOR,
        "as_of": moment.isoformat(),
        "candidates_read": len(rows),
        "subjects_in_conflict": len(subjects),
        "candidates_without_timestamp": undated,
        "fresh_window_days": FRESH_WINDOW.days,
        "top_subjects": subjects[:top_n],
        "resolution_policy": (
            "ESCALATE, NEVER RESOLVE. A contradiction is two candidate truths; "
            "a machine picking one can destroy the other (AGENTS.md §17). This "
            "digest reports; an independent assessor records the assessment."
        ),
        "note": (
            "subjects_in_conflict = 0 with candidates_read > 0 would mean the "
            "grouping key is wrong, not that the book agrees with itself."
        ),
    }


def prepare_assessment(
    candidate: dict[str, Any],
    *,
    assessor_id: str,
    assessor_provider: str,
    assessment: str,
    evidence_refs: list[str],
) -> dict[str, Any]:
    """Build an independent assessment, refusing self-validation.

    Delegates the independence check to `research_contradiction.assess_candidate`
    rather than re-implementing it: two copies of one rule drift apart, and the
    drift is invisible until someone diffs them by hand. Raises
    `self_validation_forbidden` when the assessor produced either artifact.
    """
    return assess_candidate(
        candidate,
        assessor_id=assessor_id,
        assessor_provider=assessor_provider,
        artifact_producers=_producers(candidate),
        assessment=assessment,
        evidence_refs=evidence_refs,
    )


__all__ = [
    "ASSESSMENT_SCHEMA",
    "CANDIDATE_SCHEMA",
    "SCHEMA",
    "candidates_path",
    "digest",
    "load_candidates",
    "prepare_assessment",
]
