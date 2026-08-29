"""Bounded search-for-new-sources. Proposes candidates; never ingests truth.

The corpus is thin (11 facts, 7 families, only seasonality with depth), so
proposing new sources is legitimate. Doing it unbounded is not: an auto-ingest
loop would fill the research library with unreviewed claims that then read as
Trade AI facts.

Rules, enforced here rather than by convention:
  - dry by default; `apply=True` stores CANDIDATE refs only
  - a candidate is never a fact and never gets an evidence grade
  - cap 3 proposals per entity per week
  - no download, no scrape, no new dependency
  - a candidate becomes a fact only after Grok critique ACCEPTs it, which is a
    separate pass this module does not perform
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

DISCOVERY_VERSION = "source_discovery_1.0.0"
AUTHORITY = "READ_ONLY_ADVISORY"
MAX_PROPOSALS_PER_ENTITY_PER_WEEK = 3
CANDIDATE_STATUS = "CANDIDATE"


def _utc(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def _store_path(root: Path | str) -> Path:
    return Path(root) / "data" / "cio" / "cio_source_candidates.jsonl"


def _recent(root: Path | str, entity: str, now: datetime) -> list[dict[str, Any]]:
    path = _store_path(root)
    if not path.exists():
        return []
    cutoff = now - timedelta(days=7)
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if str(rec.get("entity") or "").upper() != entity.upper():
            continue
        try:
            ts = datetime.fromisoformat(str(rec.get("proposed_at")).replace("Z", "+00:00"))
        except Exception:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= cutoff:
            out.append(rec)
    return out


def existing_source_ids() -> set[str]:
    try:
        from scripts.lib.cio_research_library import library_facts

        return {str(f.get("source_id")) for f in library_facts() if f.get("source_id")}
    except Exception:
        return set()


def discover(entity: str, *, proposals: Optional[list[dict[str, Any]]] = None,
             root: Path | str | None = None, apply: bool = False,
             now: Optional[datetime] = None) -> dict[str, Any]:
    """Propose new candidate sources for `entity`.

    `proposals` is supplied by the caller (an operator note, or a critiqued
    model pass). This function does not invent sources itself — it enforces the
    caps, dedupes against the existing library, and records CANDIDATE refs.
    """
    now = _utc(now)
    ent = str(entity or "").upper()
    if not ent:
        return {"discovery_version": DISCOVERY_VERSION, "entity": None,
                "accepted": [], "rejected": [], "reason": "no_entity",
                "authority": AUTHORITY}

    known = existing_source_ids()
    already = _recent(root or ".", ent, now) if root else []
    budget = max(0, MAX_PROPOSALS_PER_ENTITY_PER_WEEK - len(already))

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for p in (proposals or []):
        sid = str(p.get("source_id") or p.get("title") or "").strip()
        if not sid:
            rejected.append({"proposal": p, "reason": "no_source_id_or_title"})
            continue
        if sid in known:
            rejected.append({"proposal": p, "reason": "already_in_library"})
            continue
        if len(accepted) >= budget:
            rejected.append({"proposal": p, "reason": "weekly_cap_reached"})
            continue
        accepted.append({
            "entity": ent,
            "source_id": sid,
            "title": p.get("title"),
            "url": p.get("url"),
            "why": p.get("why"),
            "status": CANDIDATE_STATUS,
            "evidence_grade": None,      # a candidate has no grade, by design
            "is_fact": False,
            "proposed_at": now.isoformat(),
            "discovery_version": DISCOVERY_VERSION,
            "authority": AUTHORITY,
        })

    wrote = None
    if apply and accepted and root:
        path = _store_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            for rec in accepted:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        wrote = str(path)

    return {
        "discovery_version": DISCOVERY_VERSION,
        "entity": ent,
        "accepted": accepted,
        "rejected": rejected,
        "used_this_week": len(already),
        "weekly_cap": MAX_PROPOSALS_PER_ENTITY_PER_WEEK,
        "remaining_budget": max(0, budget - len(accepted)),
        "applied": bool(apply and accepted and root),
        "wrote": wrote,
        "authority": AUTHORITY,
        "note": "CANDIDATE refs are not facts and carry no evidence grade.",
    }
