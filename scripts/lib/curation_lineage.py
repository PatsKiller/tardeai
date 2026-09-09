"""Curation lineage helpers — stable GUIDs + prior-grounding for Hermes external research rows.

Every new external curation row is versioned with:
  research_guid        a stable UUID for THIS curation row
  prior_research_guid  the research_guid of the immediately prior (symbol, lane) curation

and the prompt is grounded on the prior verdict so a new run is a linked RE-evaluation,
never a byte-identical repeat.
"""
from __future__ import annotations

import uuid
from typing import Any


def new_research_guid() -> str:
    return str(uuid.uuid4())


def prior_grounding_context(prior: dict[str, Any] | None) -> dict[str, Any] | None:
    """Build a redacted, prompt-safe grounding block from the prior (symbol, lane) curation."""
    if not prior:
        return None
    rec = str(prior.get("recommendation") or "").strip()
    if not rec:
        return None
    return {
        "guid": prior.get("research_guid"),
        "model": prior.get("model"),
        "at": str(prior.get("created_at") or ""),
        "recommendation_snip": rec[:1200],
        "instruction": (
            "A prior external curation exists for this symbol/lane (guid above). Do NOT repeat it "
            "verbatim. Independently re-evaluate against the NEW context and evidence, state explicitly "
            "what changed vs the prior verdict (confirm / strengthen / weaken / invalidate / no-new-info), "
            "and cite the prior guid in your reasoning."
        ),
    }


def grounding_instruction_text(block: dict[str, Any] | None) -> str:
    if not block:
        return ""
    return (
        f"\n[PRIOR CURATION — guid={block.get('guid')} model={block.get('model')} at={block.get('at')}]\n"
        f"prior recommendation: {block.get('recommendation_snip')}\n"
        f"{block.get('instruction')}"
    )
