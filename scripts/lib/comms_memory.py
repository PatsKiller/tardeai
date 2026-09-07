#!/usr/bin/env python3
"""comms_memory.py — public Lane-A interface for same-subject communications history.

CampaignInterfaces@v1 §8: Lane A reads prior communications through this module.
Lane A never writes comms tables. This module opens no new tables — it wraps
``subject_memory.retrieve_subject_history`` and adds meaning-bearing helpers
(normalized_hash / already_said / attribution) brought to @v1 envelopes.

READ ONLY — no send, no delete, no wake writes.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

SCHEMA = "CommsMemoryRecall@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
INTERFACE_VERSION = "CampaignInterfaces@v1"

_SYMBOL_IN_KEY = re.compile(
    r"(?:^|:)(?:sym|symbol|ticker)[:=]([A-Z][A-Z0-9.\-]{0,9})",
    re.IGNORECASE,
)


def normalized_hash(text: str) -> str:
    """Hash of meaning-bearing text (markup stripped; numbers bucketed to int part)."""
    t = (text or "").lower()
    t = re.sub(r"(\d+)(?:[.,]\d+)?", r"#\1", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"[^a-z0-9#]+", " ", t).strip()
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def symbols_of(event: dict[str, Any]) -> set[str]:
    """Which securities an event is about. Empty set means UNATTRIBUTED, not none."""
    out: set[str] = set()
    refs = event.get("entity_refs")
    if isinstance(refs, str):
        try:
            refs = json.loads(refs)
        except Exception:
            refs = None
    if isinstance(refs, dict):
        refs = [refs]
    if isinstance(refs, list):
        for r in refs:
            if isinstance(r, dict) and r.get("symbol"):
                out.add(str(r["symbol"]).upper())
            elif isinstance(r, str) and r.strip():
                out.add(r.strip().upper())
    m = _SYMBOL_IN_KEY.search(str(event.get("subject_key") or ""))
    if m:
        out.add(m.group(1).upper())
    return out


@dataclass
class SubjectHistorySupply:
    """Exact record of what was supplied to a caller (Lane A audit surface)."""

    subject_key: str | None
    subject_guid: str | None
    event_ids: list[str] = field(default_factory=list)
    hit_count: int = 0
    eligible_only: bool = True
    limit: int = 50
    before: str | None = None
    schema: str = SCHEMA
    authority: str = AUTHORITY
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "authority": self.authority,
            "interface_version": INTERFACE_VERSION,
            "subject_key": self.subject_key,
            "subject_guid": self.subject_guid,
            "event_ids": list(self.event_ids),
            "hit_count": int(self.hit_count),
            "eligible_only": bool(self.eligible_only),
            "limit": int(self.limit),
            "before": self.before,
            "events": list(self.events),
        }


def _resolve_subject_key(
    *,
    subject_key: str | None = None,
    subject_guid: str | None = None,
) -> tuple[str | None, str | None]:
    sk = (subject_key or "").strip() or None
    sg = (subject_guid or "").strip() or None
    if sk:
        return sk, sg
    if sg:
        # Best-effort reverse: subject_memory may store guid on subject row.
        try:
            from scripts.lib.comms.subject_memory import memory_subject_snapshot

            snap = memory_subject_snapshot()
            subjects = snap.get("subjects") or {}
            for key, row in subjects.items():
                if str(row.get("subject_guid") or "") == sg:
                    return str(key), sg
        except Exception:
            pass
        # Fall back to using the guid string as a subject_key lookup (no match → empty).
        return sg, sg
    return None, None


def retrieve_same_subject_history(
    subject_key: str | None = None,
    *,
    subject_guid: str | None = None,
    limit: int = 50,
    before: datetime | str | None = None,
    eligible_only: bool = True,
) -> SubjectHistorySupply:
    """Public contract: same-subject history for Lane A (and curation).

    Excludes unrelated subjects. Wraps ``retrieve_subject_history``; opens no
    new tables. Returns the events list plus an exact supply record
    (event_ids, hit_count).
    """
    from scripts.lib.comms.subject_memory import retrieve_subject_history

    sk, sg = _resolve_subject_key(subject_key=subject_key, subject_guid=subject_guid)
    if not sk:
        return SubjectHistorySupply(
            subject_key=None,
            subject_guid=sg,
            limit=limit,
            eligible_only=eligible_only,
            before=str(before) if before is not None else None,
        )

    rows = retrieve_subject_history(
        sk, limit=max(1, int(limit)), eligible_only=bool(eligible_only)
    )

    # Exclude unrelated: only rows whose subject_key matches exactly.
    filtered: list[dict[str, Any]] = []
    before_dt: datetime | None = None
    if before is not None:
        if isinstance(before, datetime):
            before_dt = before if before.tzinfo else before.replace(tzinfo=timezone.utc)
        else:
            try:
                before_dt = datetime.fromisoformat(str(before).replace("Z", "+00:00"))
            except Exception:
                before_dt = None

    for r in rows:
        if str(r.get("subject_key") or sk) != sk:
            continue
        if before_dt is not None:
            ts = r.get("joined_at") or r.get("created_at") or r.get("observed_at")
            if isinstance(ts, datetime):
                cmp = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
                if cmp >= before_dt:
                    continue
            elif isinstance(ts, str):
                try:
                    cmp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if cmp >= before_dt:
                        continue
                except Exception:
                    pass
        filtered.append(r)

    event_ids = [str(r.get("event_id")) for r in filtered if r.get("event_id")]
    return SubjectHistorySupply(
        subject_key=sk,
        subject_guid=sg,
        event_ids=event_ids,
        hit_count=len(event_ids),
        eligible_only=bool(eligible_only),
        limit=int(limit),
        before=str(before) if before is not None else None,
        events=filtered,
    )


def already_said(
    subject_key: str,
    message: str,
    *,
    eligible_only: bool = False,
    limit: int = 50,
) -> tuple[bool, dict[str, Any]]:
    """Would sending this repeat something already supplied for this subject?"""
    supply = retrieve_same_subject_history(
        subject_key, limit=limit, eligible_only=eligible_only
    )
    want = normalized_hash(message)
    for prior in supply.events:
        summary = prior.get("short_summary") or prior.get("sanitized_body") or ""
        if summary and normalized_hash(str(summary)) == want:
            return True, {
                "reason": "same_normalized_content",
                "prior_event_id": str(prior.get("event_id")),
                "hit_count": supply.hit_count,
                "schema": SCHEMA,
            }
    return False, {
        "reason": "no_prior_match",
        "hit_count": supply.hit_count,
        "schema": SCHEMA,
    }
