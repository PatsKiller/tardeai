#!/usr/bin/env python3
"""Say something only when there is something new to say — and then say it.

The operator's complaint, verbatim: "It seems like I'm seeing the same text day
after day with the same subject matter." The measurement agreed with the feeling
but not with the obvious explanation. Outbound text was only 0-14% literally
duplicated; what repeated was the SHAPE:

    "Material change — N name(s) worth a look"
    "⚡ Watchpool: XXX | NEAR TRIGGER | Score: 63"

Same template, new ticker, every hour. A notification format, never a finding.
Meanwhile 49,094 research rows existed, all carrying subject_guid, and none of
their content ever reached the operator.

Two failures, and they need different fixes:

  1. THE DESK SPEAKS WHEN NOTHING CHANGED. A wake fires on a schedule, so it
     produces something every hour whether or not the world moved. `assess()` is
     the gate: a subject is worth speaking about only if there is evidence the
     last thing we said did not already cite, or if the thesis itself moved.
     Silence is a legitimate, recorded outcome -- not a failure to produce.

  2. WHEN IT DOES SPEAK, IT DOES NOT NARRATE. `compose()` turns the actual
     research into sentences that cite it, so "AES — worth a look" becomes what
     was found and where.

WHY THE GATE IS EVIDENCE-BASED AND NOT TIME-BASED. A cooldown ("don't repeat
within N hours") suppresses the urgent case along with the boring one, and stays
silent through a genuine change simply because it spoke recently. Comparing cited
evidence answers the actual question -- do we know something we did not know last
time -- and it is measurable after the fact.

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR=0. Composition may change what the
desk SAYS. It may never change what the desk DOES.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "CioComposedNarrative@v1"

# Why the desk is speaking, or why it is not. Recorded on every assessment so a
# silent hour is auditable rather than indistinguishable from a broken one.
SPEAK_NEW_EVIDENCE = "new_evidence"
SPEAK_THESIS_CHANGED = "thesis_changed"
SPEAK_FIRST_VIEW = "first_view"
SILENT_NO_CHANGE = "no_change"
SILENT_NO_EVIDENCE = "no_evidence"

SPEAK_REASONS = (SPEAK_NEW_EVIDENCE, SPEAK_THESIS_CHANGED, SPEAK_FIRST_VIEW)


def _evidence_id(item: Mapping[str, Any]) -> str | None:
    """The stable id of one piece of evidence.

    Prefers content_hash over row id: the same article arriving twice through two
    feeds is one fact, and counting it as two would let a duplicate re-open a
    subject the desk has already spoken about.
    """
    for key in ("content_hash", "research_id", "id", "source_url"):
        v = item.get(key)
        if v:
            return f"{key}:{v}"
    return None


def prior_cited(prior_narratives: Iterable[Mapping[str, Any]]) -> set[str]:
    """Everything the desk has already cited about this subject."""
    out: set[str] = set()
    for n in prior_narratives or []:
        for c in (n.get("cited_ids") or []):
            out.add(str(c))
        for s in (n.get("sentences") or []):
            for c in (s.get("cites") or []):
                out.add(str(c))
    return out


def assess(
    *,
    research: Sequence[Mapping[str, Any]],
    prior_narratives: Sequence[Mapping[str, Any]] = (),
    prior_thesis: str | None = None,
    new_thesis: str | None = None,
) -> dict[str, Any]:
    """Decide whether this subject is worth speaking about at all.

    Returns a decision with its reason and the evidence that justifies it, so
    both speaking and staying silent are explainable after the fact.
    """
    seen = prior_cited(prior_narratives)
    new_ids: list[str] = []
    for item in research or []:
        eid = _evidence_id(item)
        if eid and eid not in seen and eid not in new_ids:
            new_ids.append(eid)

    thesis_moved = bool(
        prior_thesis and new_thesis
        and str(prior_thesis).strip().lower() != str(new_thesis).strip().lower()
    )

    if thesis_moved:
        # A changed conclusion is worth saying even on evidence already cited --
        # the operator's stake is in the conclusion, not the footnotes.
        reason = SPEAK_THESIS_CHANGED
    elif not research:
        reason = SILENT_NO_EVIDENCE
    elif not prior_narratives and new_ids:
        reason = SPEAK_FIRST_VIEW
    elif new_ids:
        reason = SPEAK_NEW_EVIDENCE
    else:
        reason = SILENT_NO_CHANGE

    return {
        "schema": SCHEMA,
        "speak": reason in SPEAK_REASONS,
        "reason": reason,
        "new_evidence_ids": new_ids,
        "prior_cited_count": len(seen),
        "research_count": len(research or []),
        "thesis_moved": thesis_moved,
        "authority": AUTHORITY,
    }


def compose(
    *,
    subject_label: str,
    research: Sequence[Mapping[str, Any]],
    assessment: Mapping[str, Any],
    prior_thesis: str | None = None,
    new_thesis: str | None = None,
    model_narrator: Any = None,
) -> dict[str, Any]:
    """Turn research into cited sentences. Deterministic unless a narrator is given.

    The deterministic path states what was found and where, and cites every
    claim. It is not analysis and does not pretend to be -- but "3 new sources on
    Energy, led by <title> (reuters.com)" is a finding, where "worth a look" is
    not, and it costs nothing and cannot hallucinate.

    `model_narrator` is optional and injected, never constructed here: model
    calls are governed by the existing lane policy and its budget, and a
    composition path that silently reaches a paid provider is exactly what §12
    forbids. When supplied it must return sentences in the same
    {sentence, cites} shape; anything it cites that is not in the dossier is
    dropped by the caller's grounding step.
    """
    new_ids = set(assessment.get("new_evidence_ids") or [])
    fresh = [r for r in research if _evidence_id(r) in new_ids] or list(research)

    if model_narrator is not None:
        try:
            sentences = model_narrator(subject_label=subject_label, research=fresh,
                                       prior_thesis=prior_thesis, new_thesis=new_thesis)
            if sentences:
                return {"schema": SCHEMA, "narrated_by": "model",
                        "sentences": list(sentences), "authority": AUTHORITY}
        except Exception:
            pass  # fall through to deterministic; never fail to speak at all

    sentences: list[dict[str, Any]] = []
    if assessment.get("reason") == SPEAK_THESIS_CHANGED and prior_thesis and new_thesis:
        sentences.append({
            "sentence": f"{subject_label}: view changed from {prior_thesis} to {new_thesis}.",
            "cites": [i for i in list(new_ids)[:3]] or [],
        })

    lead = fresh[0] if fresh else None
    if lead is not None:
        title = str(lead.get("title") or "").strip()
        src = str(lead.get("source_url") or "")
        domain = src.split("/")[2] if "://" in src and len(src.split("/")) > 2 else ""
        n = len(fresh)
        what = f"{n} new source{'s' if n != 1 else ''} on {subject_label}"
        if title:
            what += f", led by “{title[:120]}”"
        if domain:
            what += f" ({domain})"
        sentences.append({"sentence": what + ".",
                          "cites": [i for i in (_evidence_id(r) for r in fresh[:5]) if i]})

    return {"schema": SCHEMA, "narrated_by": "deterministic",
            "sentences": sentences, "authority": AUTHORITY}


__all__ = ["SCHEMA", "AUTHORITY", "MBI", "SPEAK_REASONS",
           "SPEAK_NEW_EVIDENCE", "SPEAK_THESIS_CHANGED", "SPEAK_FIRST_VIEW",
           "SILENT_NO_CHANGE", "SILENT_NO_EVIDENCE",
           "prior_cited", "assess", "compose"]
