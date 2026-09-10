#!/usr/bin/env python3
"""Model narration for a composed narrative — on the SAME governed ladder.

`cio_narrative_compose.compose()` takes an injected `model_narrator` and stays
deterministic without one, because a composition path that silently reaches a
paid provider is what AGENTS.md §12 forbids. This module is that narrator, and
the injection stays explicit: importing it does not arm anything.

ONE LADDER, NOT TWO. The lane order is not re-implemented here — the functions
are imported from `due_diligence_questions`, which owns the operator-set order
(flash FIRST, set 2026-09-06):

    1. deepseek flash        DDQ_CURATION_MODEL
    2. free OAuth            DDQ_OAUTH_ORDER = chatgpt,grok
    3. deepseek pro          DDQ_CURATION_MODEL_PRO
    4. run_with_escalation -> EscalationStopped, the hard stop

A second ladder would drift from the first, and the cheaper one would quietly
stop being tried first. A lane that refuses (cap, circuit breaker, rate limit) is
skipped, never retried — that behaviour comes free by reusing them.

WHAT HAPPENS AT THE HARD STOP. `EscalationStopped` notifies the operator and
raises. `compose()` catches any narrator failure and falls back to deterministic
narration, so the desk still says what was found and where — it simply stops
short of interpreting it. Degrading from analysis to fact is the right direction:
the alternative is silence on a subject that just cleared a novelty gate, and the
operator has already been notified by the escalation itself.

GROUNDING IS ENFORCED IN CODE, NOT ASKED FOR IN THE PROMPT. The comment in
due_diligence_questions.ground() is exact and applies here unchanged: "A model
told not to invent will still occasionally invent, and an ungrounded question is
indistinguishable from a real one to the person reading it."

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR=0 — the prompt forbids any sizing,
ordering, stop or weight language, and `cio_narrative_write` refuses a behaviour
field regardless of what a model returns.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "CioModelNarration@v1"

PROMPT = """You are the CIO desk writing one short note for the operator about {subject}.

You are given ONLY the evidence below. Write 1-3 sentences saying what is new and
what it means for this subject. Every sentence MUST cite at least one evidence id
from the list, verbatim.

Rules:
- Cite only ids that appear below. Never invent an id, a number, or a source.
- If the evidence does not support a claim, do not make it.
- Advisory only. Never mention position size, share count, weight, stop, limit,
  order, or any instruction to buy or sell.
- Plain sentences. No preamble, no markdown, no bullet characters.
{thesis_line}
EVIDENCE:
{evidence}

Return ONLY JSON:
{{"sentences": [{{"sentence": "...", "cites": ["id", ...]}}]}}
"""


def _evidence_block(research: Sequence[Mapping[str, Any]]) -> tuple[str, set[str]]:
    """Render the dossier and return the id set grounding will be checked against."""
    lines: list[str] = []
    ids: set[str] = set()
    for r in research:
        rid = (r.get("content_hash") and f"content_hash:{r['content_hash']}") \
            or (r.get("research_id") and f"research_id:{r['research_id']}") \
            or (r.get("id") and f"id:{r['id']}")
        if not rid:
            continue
        ids.add(rid)
        title = str(r.get("title") or "").strip()[:180]
        url = str(r.get("source_url") or "")
        domain = url.split("/")[2] if "://" in url and len(url.split("/")) > 2 else ""
        lines.append(f"  {rid}  {title}" + (f"  ({domain})" if domain else ""))
    return "\n".join(lines), ids


def narrate(*, subject_label: str, research: Sequence[Mapping[str, Any]],
            prior_thesis: str | None = None, new_thesis: str | None = None,
            asker: Any = None) -> list[dict[str, Any]]:
    """Return grounded {sentence, cites} rows, or [] to fall back to deterministic.

    `asker` is injectable for tests so no control ever reaches a provider.
    """
    evidence, valid_ids = _evidence_block(research)
    if not valid_ids:
        return []

    thesis_line = ""
    if prior_thesis and new_thesis and prior_thesis != new_thesis:
        thesis_line = (f"- The desk's view moved from {prior_thesis} to {new_thesis}; "
                       f"say why, citing evidence.\n")

    prompt = PROMPT.format(subject=subject_label, evidence=evidence,
                           thesis_line=thesis_line)

    res = asker(prompt) if asker is not None else _ask_governed(prompt)
    if not res:
        return []

    text = (res.get("text") or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1].lstrip("json").strip()
    try:
        parsed = json.loads(text)
    except Exception:
        return []

    out: list[dict[str, Any]] = []
    for s in (parsed.get("sentences") or []):
        sentence = str(s.get("sentence") or "").strip()
        cites = [c for c in (s.get("cites") or []) if c in valid_ids]
        # Ungrounded sentence is dropped, not repaired. A sentence whose citation
        # does not resolve is indistinguishable from an invention.
        if sentence and cites:
            out.append({"sentence": sentence, "cites": sorted(set(cites)),
                        "lane": res.get("lane"), "model": res.get("model")})
    return out


def _ask_governed(prompt: str) -> dict[str, Any] | None:
    """The operator-set ladder, imported rather than reproduced."""
    try:
        try:
            from scripts.due_diligence_questions import (
                CURATION_MODEL, CURATION_MODEL_PRO, _curate_via_deepseek, _curate_via_oauth)
        except ImportError:
            from due_diligence_questions import (  # type: ignore
                CURATION_MODEL, CURATION_MODEL_PRO, _curate_via_deepseek, _curate_via_oauth)
    except Exception:
        return None

    res = (_curate_via_deepseek(prompt, CURATION_MODEL)
           or _curate_via_oauth(prompt)
           or _curate_via_deepseek(prompt, CURATION_MODEL_PRO))
    if res is None:
        # Every lane above has already been tried once. run_with_escalation
        # notifies the operator and raises EscalationStopped; compose() catches
        # it and narrates deterministically rather than going silent.
        from lib.llm_escalation import run_with_escalation

        res = run_with_escalation(
            prompt, purpose="CIO narrative composition (flash, OAuth and pro all unavailable)")
    if res is not None and not res.get("model"):
        # lane/model drift, observed 2026-09-10: `model` was NULL on all 153 live
        # subject_state_narratives rows because neither deepseek nor oauth sets
        # it. Record the lane as the model rather than losing attribution.
        res = {**res, "model": res.get("lane")}
    return res


__all__ = ["SCHEMA", "AUTHORITY", "MBI", "PROMPT", "narrate"]
