"""Curated per-gate prompt templates. Versioned, not free-form.

"Go research this stock" is how a research system ends up with four models
writing four different opinions in operator voice. Each gate here gets a fixed
skeleton with a fixed job:

    FLASH   classify the gap, list missing evidence, ask 3-5 questions.
            Never answers, never recommends.
    PRO     answers exactly those question_ids, citations/ids only.
    OPENAI  residual only — the questions Pro left open, JSON schema out.
    GROK    critiques an artifact: complete? contradictory? execution-tainted?
            attachable? Verdict VALID | PARTIAL | REJECT.

Carried across every hop: question_ids, artifact_id, prior outcome, corpus
refs, prior critique. That carry is what makes the ladder cumulative instead of
four independent guesses at the same question.
"""
from __future__ import annotations

import json
from typing import Any, Optional

TEMPLATES_VERSION = "research_templates_1.0.0"
AUTHORITY = "READ_ONLY_ADVISORY"

GATES = ("flash", "pro", "openai", "grok_critique")

# Stated in every system prompt. This is belt-and-braces next to the output
# lint — the model is told, and the artifact is still checked.
_FORBIDDEN_CLAUSE = (
    "Never write an instruction to act: no buy, sell, trim, flatten, "
    "liquidate, place, submit or execute directed at the reader. "
    "Never present a price as an established fact to be stored as memory. "
    "Never write notification or alert copy. "
    "You are producing analysis for an advisory record, not an order."
)

_SHARED_SYSTEM = (
    "You are a research analyst for a READ_ONLY_ADVISORY investment record. "
    "Your output is stored as evidence and may be attached to a plan only after "
    "an independent critique passes. " + _FORBIDDEN_CLAUSE
)

_SYSTEM: dict[str, str] = {
    "flash": _SHARED_SYSTEM + (
        " TASK: classify the research gap only. Identify what evidence is "
        "missing and ask 3 to 5 specific, answerable questions. "
        "Do NOT answer them. Do NOT offer a view, rating, or recommendation."
    ),
    "pro": _SHARED_SYSTEM + (
        " TASK: answer the supplied question_ids and nothing else. Every claim "
        "carries a citation or a source id. If a question cannot be answered "
        "from available evidence, mark it unresolved rather than speculating."
    ),
    "openai": _SHARED_SYSTEM + (
        " TASK: address only the question_ids still unresolved after the prior "
        "pass. Return the given JSON schema exactly. Long-form reasoning is "
        "acceptable inside fields; prose outside the schema is not."
    ),
    "grok_critique": _SHARED_SYSTEM + (
        " TASK: critique the supplied artifact. Is it complete against its "
        "question_ids? Internally contradictory? Execution-tainted (does it "
        "instruct the reader to act)? Attachable to a plan as evidence? "
        "Return verdict VALID, PARTIAL or REJECT with reasons. "
        "Do not rewrite the artifact and do not perform the research yourself."
    ),
}

_OUTPUT_SCHEMA: dict[str, dict[str, Any]] = {
    "flash": {"gap_class": "str", "missing_evidence": ["str"],
              "questions": [{"question_id": "str", "dim": "str", "q": "str"}]},
    "pro": {"answers": [{"question_id": "str", "answer": "str",
                         "citations": ["str"], "resolved": "bool"}]},
    "openai": {"answers": [{"question_id": "str", "answer": "str",
                            "citations": ["str"], "resolved": "bool"}],
               "still_unresolved": ["str"]},
    "grok_critique": {"verdict": "VALID|PARTIAL|REJECT", "reasons": ["str"],
                      "execution_tainted": "bool", "attachable": "bool"},
}


def forbidden_clause() -> str:
    return _FORBIDDEN_CLAUSE


def output_schema(gate: str) -> dict[str, Any]:
    return dict(_OUTPUT_SCHEMA.get(gate) or {})


def build(gate: str, *, symbol: str | None = None,
          question_ids: Optional[list[str]] = None,
          questions: Optional[list[dict[str, Any]]] = None,
          artifact: Any = None,
          artifact_id: str | None = None,
          prior_outcome: str | None = None,
          prior_critique: Any = None,
          corpus_refs: Optional[list[dict[str, Any]]] = None,
          research_id: str | None = None) -> dict[str, Any]:
    """Render one gate's system+user pair plus the carry block.

    Raises ValueError on an unknown gate rather than silently producing an
    unlabelled prompt — an unrouted model call is exactly what this module is
    meant to prevent.
    """
    g = str(gate or "").lower()
    if g not in GATES:
        raise ValueError(f"unknown research gate: {gate!r}")

    carry = {
        "research_id": research_id,
        "artifact_id": artifact_id,
        "question_ids": list(question_ids or []),
        "prior_outcome": prior_outcome,
        "prior_critique": prior_critique,
        "corpus_refs": list(corpus_refs or []),
    }

    parts: list[str] = []
    if symbol:
        parts.append(f"ENTITY: {symbol}")
    if carry["question_ids"]:
        parts.append("QUESTION_IDS: " + ", ".join(carry["question_ids"]))
    if questions:
        parts.append("QUESTIONS:\n" + json.dumps(questions, indent=1, default=str))
    if corpus_refs:
        # Corpus refs travel as context with their grade attached, so the model
        # cannot promote a grade-D citation into a settled fact.
        parts.append("CORPUS CONTEXT (context/risk-modifier only, never a "
                     "standalone conclusion):\n"
                     + json.dumps(corpus_refs, indent=1, default=str))
    if prior_outcome:
        parts.append(f"PRIOR OUTCOME: {prior_outcome}")
    if prior_critique:
        parts.append("PRIOR CRITIQUE:\n" + json.dumps(prior_critique, indent=1, default=str))
    if artifact is not None:
        parts.append("ARTIFACT UNDER REVIEW:\n" + (
            artifact if isinstance(artifact, str)
            else json.dumps(artifact, indent=1, default=str)))
    parts.append("RETURN JSON MATCHING:\n" + json.dumps(output_schema(g), indent=1))

    return {
        "templates_version": TEMPLATES_VERSION,
        "gate": g,
        "system": _SYSTEM[g],
        "user": "\n\n".join(parts),
        "carry": carry,
        "output_schema": output_schema(g),
        "authority": AUTHORITY,
        "financial_action": False,
    }
