"""WakeResearchPersist@v1 — last cycle ("current") plus retained research hits.

The scheduled entrypoint used to `_p.write_text` a last-cycle-only document every
`*/5`. Idle cycles erased the cycle that closed the research/persist loop, so the
durable artifact could not prove M5 (see LITMUS_WAKE / CIO_M5_FIRST_FIRE).

Shape:

    {
      "schema": "WakeResearchPersist@v1",
      "current": { ...full last-cycle object... },
      "hits": [ {as_of, dispatched, research_called, persisted,
                 subjects[], decisions[], unattended}, ... ]
    }

Legacy last-cycle-only files load as ``current=<that object>, hits=[]``.
Hits cap at 20 (oldest dropped). Writes are atomic (tmp + replace).

Does not touch research-gate decision math or eligibility clocks.
This artifact carries no writer stamp field.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from scripts.lib.atomic_json_store import atomic_write_json

SCHEMA = "WakeResearchPersist@v1"
HITS_CAP = 20

# A cycle whose every research row is skip+cadence_not_due (and that did not
# call research / persist) is idle noise — do not retain it as a hit.
_SKIP = "skip"
_CADENCE_NOT_DUE = "cadence_not_due"


def is_hit(cycle: dict[str, Any]) -> bool:
    """Retain when research_called>0 OR persisted>0 OR a non-idle decision."""
    if int(cycle.get("research_called") or 0) > 0:
        return True
    if int(cycle.get("persisted") or 0) > 0:
        return True
    rows = cycle.get("research") or []
    if not rows:
        return False
    for row in rows:
        decision = str(row.get("decision") or "").strip().lower()
        reason = str(row.get("reason") or "").strip().lower()
        if decision != _SKIP:
            return True
        if reason != _CADENCE_NOT_DUE:
            return True
    # All rows are skip / cadence_not_due-only.
    return False


def hit_from_cycle(cycle: dict[str, Any]) -> dict[str, Any]:
    rows = cycle.get("research") or []
    subjects: list[Any] = []
    decisions: list[Any] = []
    for row in rows:
        sk = row.get("subject_key")
        if sk is not None and sk != "":
            subjects.append(sk)
        decisions.append(row.get("decision"))
    return {
        "as_of": cycle.get("as_of"),
        "dispatched": cycle.get("dispatched"),
        "research_called": int(cycle.get("research_called") or 0),
        "persisted": int(cycle.get("persisted") or 0),
        "subjects": subjects,
        "decisions": decisions,
        "unattended": bool(cycle.get("unattended", True)),
    }


DEFAULT_PATH = Path("data/cio/wake_research_persist.json")


def _hit_sort_key(hit: dict[str, Any]) -> str:
    """Newest last. `as_of` is an ISO string; a missing one sorts oldest."""
    return str(hit.get("as_of") or "")


def last_hit_for_subject(doc: dict[str, Any], subject_key: Any) -> Optional[dict[str, Any]]:
    """The most recent retained cycle in which THIS subject was researched.

    Returns None when no retained hit names the subject. That is a real
    negative -- we looked and it is not there -- and the caller must not
    confuse it with an unreadable document, which is a different thing.

    `decision` is best-effort. `hit_from_cycle` appends a decision for every
    research row but only appends a subject_key when it is non-empty, so the
    two lists are index-aligned ONLY while every row carries a subject. That
    holds today (the entrypoint appends a research row only inside
    `if subject_key:`) and it is not guaranteed by the shape, so the decision
    is read positionally only when the lengths agree and reported as None
    otherwise. Reading a decision off a misaligned index would attribute one
    subject's outcome to another.
    """
    if not subject_key:
        return None
    hits = doc.get("hits") or []
    if not isinstance(hits, list):
        return None
    best: Optional[dict[str, Any]] = None
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        subjects = hit.get("subjects") or []
        if not isinstance(subjects, list) or subject_key not in subjects:
            continue
        if best is None or _hit_sort_key(hit) >= _hit_sort_key(best):
            best = hit
    if best is None:
        return None
    decisions = best.get("decisions") or []
    subjects = best.get("subjects") or []
    decision = None
    if isinstance(decisions, list) and len(decisions) == len(subjects):
        # last occurrence: the most recent decision for the subject in that cycle
        idx = len(subjects) - 1 - subjects[::-1].index(subject_key)
        decision = decisions[idx]
    return {
        "as_of": best.get("as_of"),
        "decision": decision,
        "research_called": best.get("research_called"),
        "persisted": best.get("persisted"),
        "unattended": best.get("unattended"),
    }


def observe_last_hit(subject_key: Any, *, path: Path | str | None = None
                     ) -> dict[str, Any]:
    """Read-only consult. Never raises.

    `readable` distinguishes "the document could not be read" from "the
    document was read and holds no hit for this subject". Collapsing those two
    is how a monitor starts lying -- the same distinction `lane_registry`
    draws between UNVERIFIABLE and SILENT.
    """
    out: dict[str, Any] = {"readable": False, "hit": None, "detail": None}
    try:
        doc = load_document(path or DEFAULT_PATH)
    except Exception as exc:                       # named, never bare
        out["detail"] = f"{type(exc).__name__}: {exc}"
        return out
    out["readable"] = True
    out["hit"] = last_hit_for_subject(doc, subject_key)
    return out


def load_document(path: Path | str) -> dict[str, Any]:
    """Load new or legacy shape. Legacy → current=that, hits=[]. Never throws on missing."""
    path = Path(path)
    if not path.exists():
        return {"schema": SCHEMA, "current": None, "hits": []}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {"schema": SCHEMA, "current": None, "hits": []}
    # New shape: has an explicit current object (dict) at top level.
    if isinstance(raw.get("current"), dict):
        hits = raw.get("hits") or []
        if not isinstance(hits, list):
            hits = []
        return {
            "schema": SCHEMA,
            "current": raw["current"],
            "hits": list(hits),
        }
    # Legacy last-cycle-only (schema at top, no current key).
    return {"schema": SCHEMA, "current": raw, "hits": []}


def write_cycle(path: Path | str, cycle: dict[str, Any]) -> dict[str, Any]:
    """Set current to this cycle; append a hit when is_hit; cap hits; atomic write.

    ``cycle`` is the existing last-cycle object (schema/authority/as_of/…).
    Returns the document written.
    """
    path = Path(path)
    doc = load_document(path)
    hits = list(doc.get("hits") or [])
    if is_hit(cycle):
        hits.append(hit_from_cycle(cycle))
        if len(hits) > HITS_CAP:
            hits = hits[-HITS_CAP:]
    out = {
        "schema": SCHEMA,
        "current": cycle,
        "hits": hits,
    }
    atomic_write_json(path, out)
    return out
