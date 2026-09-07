#!/usr/bin/env python3
"""agent_view.py — AgentView@v2 (wake-side). Lane A creates; Lane D settles commitments.

Advisory only. No broker authority. Confidence is computed from evidence the wake
actually read — never asserted by an LLM.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from scripts.lib.persistent_wake_interfaces import (
    VIEW_SCHEMA,
    envelope,
    mint_view_id,
)
from scripts.lib.persistent_wake_store import JsonlStore

AUTHORITY = "READ_ONLY_ADVISORY"
STANCES = ("UNEXPLAINED_MOVE", "EXPLAINED_MOVE", "QUIET", "UNKNOWN")


def confidence_for(*, corroborated: bool, dossier_size: int, magnitude: float,
                   catalyst_weight: float = 0.0) -> tuple[float, dict]:
    basis: dict[str, Any] = {
        "corroborated": bool(corroborated),
        "dossier_size": int(dossier_size),
        "magnitude": round(float(magnitude), 3),
        "catalyst_weight": round(float(catalyst_weight), 3),
    }
    c = 0.55 if corroborated else 0.25
    c += min(dossier_size, 40) / 40.0 * 0.15
    c += min(max(magnitude - 1.0, 0.0), 4.0) / 4.0 * 0.10
    c += min(max(catalyst_weight, 0.0), 1.0) * 0.10
    c = round(min(max(c, 0.01), 0.95), 3)
    basis["confidence"] = c
    return c, basis


def stance_for(*, has_change: bool, open_questions: int, narrative_sentences: int
               ) -> tuple[str, str]:
    if not has_change:
        return "QUIET", "no material change observed"
    if open_questions > 0 and narrative_sentences < 2:
        return "UNEXPLAINED_MOVE", "move without adequate narrative"
    if narrative_sentences >= 2:
        return "EXPLAINED_MOVE", "move accompanied by narrative"
    return "UNKNOWN", "insufficient evidence"


def create_view(
    store: JsonlStore,
    *,
    agent_id: str,
    subject_guid: str,
    wake_id: str,
    stance: str,
    summary: str,
    source_sha: str,
    correlation_id: str,
    influence_source_ids: list[str] | None = None,
    producer: str = "test",
) -> dict:
    if stance not in STANCES:
        raise ValueError(f"illegal stance {stance!r}")
    vid = mint_view_id(agent_id, subject_guid, wake_id)
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    rec = {
        "view_id": vid,
        "wake_id": wake_id,
        "agent_id": agent_id,
        "subject_guid": subject_guid,
        "stance": stance,
        "summary": summary,
        "authority": AUTHORITY,
        **envelope(
            schema_version=VIEW_SCHEMA,
            source_sha=source_sha,
            produced_at=now,
            correlation_id=correlation_id,
            idempotency_key=vid,
            lifecycle_state="OPEN",
            parent_id=wake_id,
            parent_kind="wake",
            provenance={
                "producer": producer,
                "inputs": [{"kind": "wake", "id": wake_id}],
                "policy_decisions": [],
                "llm": None,
                "influence_source_ids": list(influence_source_ids or []),
            },
        ),
    }
    _, rec = store.append_unique("views", "view_id", rec)
    return rec
