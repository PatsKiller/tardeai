"""Helpers to publish symbol_* theses into CIOThesisStore (advisory only).

Default notify=False for bulk. Never writes broker/risk state.
Production backfill must be explicitly enabled by operator after integration.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from scripts.lib.cio_theses import CIOThesisStore
from scripts.lib.symbol_thesis_coverage import symbol_thesis_id


def publish_symbol_thesis(
    symbol: str,
    *,
    summary: str,
    stance: str = "",
    portfolio_role: str = "UNKNOWN",
    universe_memberships: Optional[list[str]] = None,
    why_owned_or_watched: str = "",
    why_exited: str = "",
    what_changed_since_exit: str = "",
    evidence_for: Optional[list[str]] = None,
    counter_evidence: Optional[list[str]] = None,
    invalidation_conditions: Optional[list[str]] = None,
    research_gaps: Optional[list[str]] = None,
    what_changes_my_mind: Optional[list[str]] = None,
    catalysts: Optional[list[dict[str, Any]]] = None,
    evidence_text: Optional[dict[str, str]] = None,
    owner_agent: str = "alex",
    change_note: str = "",
    store: CIOThesisStore | None = None,
    notify: bool = False,
    actor_id: str = "symbol_thesis_publish",
    provenance: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    store = store or CIOThesisStore()
    tid = symbol_thesis_id(symbol)
    previous = store.get_current(tid)
    supplied = dict(provenance or {})
    write_provenance = {
        "writer": supplied.get("writer") or actor_id,
        "writer_version": supplied.get("writer_version") or "symbol_thesis_publish@v1",
        "source_research_ids": list(supplied.get("source_research_ids") or []),
        "delta_id": supplied.get("delta_id"),
        "trigger": supplied.get("trigger") or "unspecified",
        "run_id": supplied.get("run_id"),
        "source_sha": supplied.get("source_sha") or os.getenv("TRADEAI_SOURCE_SHA") or os.getenv("SOURCE_SHA"),
        "previous_version": (previous or {}).get("thesis_version"),
        "reason_for_change": supplied.get("reason_for_change") or change_note or f"symbol thesis for {symbol.upper()}",
    }
    # Optional provenance keys: present only when the caller supplied them, so a
    # version written without them keeps the exact prior shape.
    for key in ("scope", "source_result_id"):
        if supplied.get(key):
            write_provenance[key] = supplied.get(key)
    bullets = []
    if why_owned_or_watched:
        bullets.append(f"Why owned/watched: {why_owned_or_watched}")
    if why_exited:
        bullets.append(f"Why exited: {why_exited}")
    if what_changed_since_exit:
        bullets.append(f"Since exit: {what_changed_since_exit}")
    extra = {
        "kind": "symbol",
        "symbol": symbol.upper(),
        "portfolio_role": portfolio_role,
        "universe_memberships": list(universe_memberships or []),
        "why_owned_or_watched": why_owned_or_watched,
        "why_exited": why_exited,
        "what_changed_since_exit": what_changed_since_exit,
        "evidence_for": list(evidence_for or []),
        "counter_evidence": list(counter_evidence or []),
        "invalidation_conditions": list(invalidation_conditions or []),
        "research_gaps": list(research_gaps or []),
        "what_changes_my_mind": list(what_changes_my_mind or []),
        "write_provenance": write_provenance,
    }
    # catalysts: [{text, as_of, source_research_id, event_date?}];
    # evidence_text: {ev_id: text} for evidence ids minted from answer text.
    # Stored only when supplied (CIOThesisStore copies extra keys onto the record).
    if catalysts is not None:
        extra["catalysts"] = [dict(c) for c in catalysts if isinstance(c, dict)]
    if evidence_text is not None:
        extra["evidence_text"] = {str(k): str(v) for k, v in evidence_text.items()}
    return store.publish(
        summary,
        thesis_id=tid,
        stance=stance,
        bullets=bullets,
        linked_symbols=[symbol.upper()],
        owner_agent=owner_agent,
        change_note=change_note or f"symbol thesis for {symbol.upper()}",
        actor_id=actor_id,
        extra=extra,
        notify=notify,
    )
