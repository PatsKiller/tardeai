"""Shared detector for LLM refusals that arrive as successful generations (LQ-20261107-407, -512;
anchor SYNTHESIS_REFUSAL_LQ512).

A model that declines the persona/prompt ("I cannot perform investment synthesis...", "**Refusal**",
"I am operating in the default Hermes profile...", "**Declined.** This request requires...") returns
text, not an error. Writers must store it as refused (never a narrative, never a consensus vote) and
readers must not display it.

LQ-512 widened the shapes after measuring all 967 live watchlist_final_synthesis rows: the 407
predicate caught 94 refusals and missed more ("**Refusal:**" after a [MULTI-CONSENSUS] prefix lost
its asterisks to the strip; "Declined.", "This request is outside the active profile", "I am the
default Hermes assistant", "The active Hermes profile is `default`"). The shapes all name the model's
own profile/identity boundary; real analysis never does. A real narrative that mentions Hermes as a
DATA source ("0.37% Hermes yield") or says "I cannot ignore valuation" stays real.
"""
from __future__ import annotations

import re

_LEAD_STRIP = "*#_>` \t\r\n\"'-:."

# A leading first-person refusal, or a refusal heading, at the start of the text (after any
# [MULTI-CONSENSUS] prefix and markdown). Matched against the lowercased, stripped head.
_REFUSAL_PREFIXES = (
    "i cannot", "i can't", "i can not", "i won't", "i will not", "i'm unable", "i am unable",
    "i'm not able", "i am not able", "i must decline", "i have to decline", "sorry, i cannot",
    "sorry, i can't", "i apologize, but i cannot", "i'm sorry, but i can",
    "i am operating in", "i'm operating in", "hermes default profile", "hermes review",
    "as an ai", "unable to comply", "unable to fulfill",
    # LQ-512 headings
    "refusal", "refused", "declined", "request declined", "i decline",
    "boundary note", "boundary clarification", "profile boundary",
    "request outside", "this request is outside", "this request violates",
    "i am the default hermes", "i am hermes",
)
# Phrases that name the model's own profile/identity boundary. Searched anywhere in the head.
_REFUSAL_MARKERS = (
    "**refusal**", "requires the active profile to switch", "default hermes profile",
    "hermes default profile", "cannot perform investment synthesis",
    "cannot fulfill this request", "can't fulfill this request",
    # LQ-512
    "default hermes assistant", "default general-purpose hermes", "non-trading profile",
    "trade ai advisory identity", "trade ai advisory profile",
    "active hermes profile", "hermes profile is", "hermes profile authority",
    "the active profile is", "the current active profile is", "the current profile is",
    "outside the active profile", "active profile's authority",
    "violates my operating boundar", "per my operating boundaries",
    "i do not perform investment synthesis", "i do not create, approve, or promote",
    "default profile scope", "this profile is the default",
)
# "This request requires/asks ... trade recommendation" — a refusal opener that never names Hermes.
_REQUEST_OPENER = re.compile(
    r"^this (request|query) (requires|asks|requests|attempts)\b[^.]{0,260}"
    r"\b(trade|trading|portfolio|investment|advisory|cio|chief investment)\b"
)
_PREFIX_RE = re.compile(r"^\[multi-consensus\][^.]*\.\s*")
_HEAD_CHARS = 500


def _head(text) -> str:
    head = str(text).lstrip(_LEAD_STRIP).lower()
    if head.startswith("[multi-consensus]"):
        head = _PREFIX_RE.sub("", head, count=1)
    return head[:_HEAD_CHARS]


def is_refusal(text) -> bool:
    """True when `text` is a model refusal rather than analysis.

    Conservative: a leading first-person refusal phrase or refusal heading, a "This request requires
    ... trade/portfolio ..." opener, or a profile/identity-boundary marker in the first 500 chars.
    Markers are checked on the unstripped head too, so "**Refusal**" survives the markdown strip."""
    if not text:
        return False
    raw_head = _head(text)
    head = raw_head.lstrip(_LEAD_STRIP)
    if head.startswith(_REFUSAL_PREFIXES):
        return True
    if _REQUEST_OPENER.match(head):
        return True
    return any(m in raw_head or m in head for m in _REFUSAL_MARKERS)


# Fields a reader must blank when the stored narrative is a refusal: everything derived from the
# refusing run. The recommendation was voted from refusal text (LQ-407), so it is not a decision.
REFUSAL_DERIVED_FIELDS = (
    "synthesis_narrative", "synthesis_narrative_snip", "synthesis_recommendation",
    "synthesis_confidence", "grok_recommendation", "chatgpt_recommendation", "models_agree",
    "synthesis_actionable", "conflicts", "unresolved", "synthesis_conflicts_snip",
    "synthesis_evidence", "synthesis_data_i_doubt", "dual_consensus_json", "decision_safety",
)


def scrub_refused_synthesis(item: dict, narrative_key: str = "synthesis_narrative") -> dict:
    """Reader guard (LQ-512): if `item[narrative_key]` is a refusal, blank every field derived from
    that run and set `synthesis_refused: True`. Mutates and returns `item`. A non-refusal item gets
    `synthesis_refused: False` and is otherwise unchanged."""
    refused = is_refusal(item.get(narrative_key))
    item["synthesis_refused"] = refused
    if refused:
        for k in (*REFUSAL_DERIVED_FIELDS, narrative_key):
            if k in item:
                item[k] = None
    return item
