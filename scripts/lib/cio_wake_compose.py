#!/usr/bin/env python3
"""The wake's decide hook, composing a real finding instead of a template claim.

Before this, every organic wake produced the same shape of claim:

    "selection:unconsumed_research:f92f7e0b... warrants review"

An id and the words "warrants review" — the machine-readable equivalent of the
Telegram alerts the operator described as "the same text day after day". The
research that justified the wake was never read, never summarised, and never
reached the claim.

This wraps `default_decide` rather than replacing it. Every existing guarantee is
preserved verbatim: MEMORY_SALIENCE when memory is present, SELECTION_OBSERVATION
otherwise, the ORIGINAL selection source_id never reminted, allow_empty_memory,
and MBI_BEHAVIOR=0. What is added is the claim's TEXT when — and only when —
there is something new to say.

THE GATE COMES FIRST, AND IT IS WHY THIS IS AFFORDABLE. `assess()` compares the
research behind this wake against what the desk has already cited about the
subject. No new evidence and no thesis move means no model call at all. A wake
still happens, still commits, still receipts — it simply does not narrate a
subject it has nothing new to say about. Without that gate this would be a model
call per subject per hour, forever.

Bounded twice more: `CIO_NARRATIVE_COMPOSITION_ENABLED` must be on (default OFF),
and `CIO_NARRATIVE_MAX_PER_WAKE` caps compositions per process so a bad feed day
cannot become an unbounded bill.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR=0.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "CioWakeComposition@v1"

FEATURE_FLAG = "CIO_NARRATIVE_COMPOSITION_ENABLED"
MAX_ENV = "CIO_NARRATIVE_MAX_PER_WAKE"
RESEARCH_ENV = "TRADEAI_WAKE_RESEARCH_OBJECTS_PATH"

_composed_this_process = 0


def enabled(env: Mapping[str, str] | None = None) -> bool:
    src = env if env is not None else os.environ
    return str(src.get(FEATURE_FLAG, "")).strip().lower() in {"1", "true", "yes", "on"}


def _max_per_wake(env: Mapping[str, str] | None = None) -> int:
    src = env if env is not None else os.environ
    try:
        return max(0, int(str(src.get(MAX_ENV, "") or 5)))
    except ValueError:
        return 5


def research_for_subject(subject_guid: str, env: Mapping[str, str] | None = None) -> list[dict]:
    """The research rows the selector drew this subject from.

    Read from the same feed the selector reads, so the narrative is grounded in
    exactly what caused the wake -- not a fresh query that might return something
    the selection never saw.
    """
    src = env if env is not None else os.environ
    raw = str(src.get(RESEARCH_ENV, "") or "").strip()
    if not raw:
        return []
    p = Path(raw)
    if not p.is_file():
        return []
    out: list[dict] = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if str(row.get("subject_guid")) == str(subject_guid):
                out.append(row)
    except Exception:
        return []
    return out


def _prior_narratives(context: Mapping[str, Any]) -> list[dict]:
    """What the desk has already said about this subject.

    Memory facts and prior comm events both count as "already said" -- a finding
    the operator was messaged an hour ago is not new just because it is not in
    the memory store.
    """
    prior: list[dict] = []
    for f in context.get("memory_facts") or []:
        content = f.get("content")
        if isinstance(content, dict) and content.get("cited_ids"):
            prior.append({"cited_ids": content["cited_ids"]})
        elif isinstance(content, str) and content:
            prior.append({"cited_ids": [content]})
    for ev in context.get("comm_events") or []:
        cited = ev.get("cited_ids")
        if cited:
            prior.append({"cited_ids": cited})
    return prior


def composing_decide(context: dict, *, env: Mapping[str, str] | None = None,
                     narrator: Any = None) -> dict:
    """default_decide, plus a narrated claim when there is something new to say."""
    global _composed_this_process
    from scripts.lib.persistent_agent_wake import _normalize_claim, default_decide

    base = default_decide(context)
    if not enabled(env) or not base.get("act"):
        return base

    subject_guid = context.get("subject_guid")
    research = research_for_subject(subject_guid, env)
    if not research:
        return base

    from scripts.lib.cio_narrative_compose import assess, compose

    a = assess(research=research, prior_narratives=_prior_narratives(context))
    base["composition_reason"] = a["reason"]
    if not a["speak"]:
        # Not a failure. The desk had nothing new about this subject, and said so
        # in the record rather than repeating itself to the operator.
        return base

    if _composed_this_process >= _max_per_wake(env):
        base["composition_reason"] = "capped"
        return base

    label = str((research[0].get("symbol") or subject_guid or "")).upper()
    if narrator is None and enabled(env):
        from scripts.lib.cio_narrative_narrator import narrate as narrator  # noqa: PLC0415

    out = compose(subject_label=label, research=research, assessment=a,
                  model_narrator=narrator)
    sentences = out.get("sentences") or []
    if not sentences:
        return base

    _composed_this_process += 1
    text = " ".join(s.get("sentence", "") for s in sentences).strip()
    cites = sorted({c for s in sentences for c in (s.get("cites") or [])})

    # The claim BECOMES the finding. Same commitment shape, same source id, same
    # rails -- only the text changes from an id-and-a-template to what was found.
    commitment = dict(base.get("commitment") or {})
    commitment["claim"] = text[:2000]
    commitment["normalized_claim"] = _normalize_claim(text[:2000])
    commitment["cited_ids"] = cites
    commitment["narrated_by"] = out.get("narrated_by")
    base["commitment"] = commitment
    base["narrative"] = {"schema": SCHEMA, "sentences": sentences,
                         "cited_ids": cites, "narrated_by": out.get("narrated_by"),
                         "subject_label": label, "authority": AUTHORITY}
    return base


__all__ = ["SCHEMA", "AUTHORITY", "MBI", "FEATURE_FLAG", "MAX_ENV",
           "enabled", "research_for_subject", "composing_decide"]
