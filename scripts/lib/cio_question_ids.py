"""Stable question ids derived from meaning, not position.

The bug this fixes is not that ids look wrong — it is that they are
**positional**. `cio_hermes_research` assigns `q{i+1}` when a question carries
no explicit id, so `q2` means "whatever was second in the list that day". Change
the question order and a carried-forward answer keyed on `q2` silently attaches
to a different question. Nothing errors; the mapping is just wrong.

That matters because the whole research ladder is built on the carry: Flash
asks question_ids, Pro answers *those* ids, OpenAI takes the residual, and the
critique judges completeness against them. A live Grok critique on 2026-08-29
flagged exactly this on SPCX, and a scan of all 471 stored results found the
same shape book-wide — `q1/q2/q3` (337/191/191) and `q_cat_1..3` (134 each),
never a semantic id.

Every question already carried a stable semantic field. Two of them, in fact:

    cio_hermes_research.default_questions_for_plan  ->  intent
    research_need_decision.decide                   ->  dim

Two vocabularies for one concept is how the earlier drift bugs in this codebase
started (two total_cash writers, two freshness laws), so both resolve through
this single function.

Ids are derived, never stored-and-diverged: the same intent always yields the
same id, on every pass and every provider.
"""
from __future__ import annotations

import re
from typing import Any, Optional

QUESTION_ID_VERSION = "question_ids_1.0.0"
PREFIX = "q_"

# `dim` (v1 gate) -> `intent` (research vocabulary). One concept, one id.
DIM_TO_INTENT = {
    "structural_drivers": "structural_drivers",
    "bear_case": "bear_case",
    "what_is_priced_in": "priced_in",
}

# The intents in use today. Listing them makes an unknown intent visible rather
# than silently producing a new id nobody expects.
KNOWN_INTENTS = frozenset({
    "drift_attribution", "catalyst_map", "invalidation", "thesis_check",
    "deployment_candidates", "regime", "liquidity",
    "structural_drivers", "bear_case", "priced_in",
})

_SLUG = re.compile(r"[^a-z0-9]+")


def slug(text: Any) -> str:
    s = _SLUG.sub("_", str(text or "").strip().lower()).strip("_")
    return s[:48]


def question_id_for(question: dict[str, Any], *,
                    index: Optional[int] = None) -> str:
    """Stable id for one question.

    Order of resolution:
      1. an explicit `question_id` / `id` — callers that already thought about
         this keep their contract
      2. `intent`, then `dim` — the semantic anchor
      3. positional `q{n}` as a LAST resort, so a malformed question still gets
         an id rather than crashing the enqueue
    """
    explicit = question.get("question_id") or question.get("id")
    if explicit:
        return str(explicit)
    intent = str(question.get("intent") or "").strip().lower()
    if not intent:
        dim = str(question.get("dim") or "").strip().lower()
        intent = DIM_TO_INTENT.get(dim, dim)
    if intent:
        return PREFIX + slug(intent)
    return f"q{(index or 0) + 1}"


def assign_ids(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return questions with stable ids, de-duplicated deterministically.

    Two questions sharing an intent would otherwise collide onto one id and the
    second answer would overwrite the first. They get `_2`, `_3` suffixes in
    list order — still stable for a given question set, and visible.
    """
    out: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for i, q in enumerate(questions or []):
        if not isinstance(q, dict):
            continue
        qid = question_id_for(q, index=i)
        seen[qid] = seen.get(qid, 0) + 1
        if seen[qid] > 1:
            qid = f"{qid}_{seen[qid]}"
        row = dict(q)
        row["question_id"] = qid
        out.append(row)
    return out


def is_positional(question_id: Any) -> bool:
    """True for the legacy `q1` / `q_cat_1` shapes this replaces."""
    s = str(question_id or "")
    return bool(re.fullmatch(r"q\d+", s) or re.fullmatch(r"q_cat_\d+", s))


def unknown_intents(questions: list[dict[str, Any]]) -> list[str]:
    """Intents not in KNOWN_INTENTS. Reported, never blocked."""
    out = []
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        intent = str(q.get("intent") or "").strip().lower()
        if intent and intent not in KNOWN_INTENTS:
            out.append(intent)
    return sorted(set(out))


# Semantic question id -> the thesis field its answer feeds. One map, shared by
# the options lifecycle (short display answers) and the symbol-thesis bridge
# (full text), so the two cannot drift onto different ids.
ANSWER_MAP = {
    "q_thesis_check": "thesis",
    "q_catalyst_map": "catalysts",
    "q_invalidation": "invalidation",
    "q_bear_case": "bear_case",
}
FOLLOWUP_PREFIX = "q_cio_followup_"


def answer_text(answer: dict[str, Any]) -> str:
    """summary + detail, joined; the full text, never truncated here."""
    parts = (str(answer.get("summary") or "").strip(), str(answer.get("detail") or "").strip())
    return " ".join(x for x in parts if x)


def structured_answers(result: Optional[dict[str, Any]]) -> dict[str, str]:
    """Per-question answers keyed by meaning (thesis, catalysts, invalidation,
    bear_case, cio_followup_N). An answer whose status is 'unanswered' is
    skipped: its text says why nothing was found, which is not a finding.
    """
    out: dict[str, str] = {}
    for a in (result or {}).get("answers") or []:
        if not isinstance(a, dict):
            continue
        qid = str(a.get("question_id") or "")
        key = ANSWER_MAP.get(qid)
        if not key and qid.startswith(FOLLOWUP_PREFIX):
            key = qid[len(PREFIX):]
        if not key or str(a.get("status") or "").lower() == "unanswered":
            continue
        text = answer_text(a)
        if text:
            out[key] = text
    return out
