"""Shared detector for LLM refusals that arrive as successful generations (LQ-20261107-407, -512;
anchor SYNTHESIS_REFUSAL_LQ512).

A model that declines the persona/prompt ("I cannot perform investment synthesis...", "**Refusal**",
"I am operating in the default Hermes profile...", "**Declined.** This request requires...") returns
text, not an error. Writers must store it as refused (never a narrative, never a consensus vote) and
readers must not display it.

LQ-512 widened the shapes after measuring all 967 live watchlist_final_synthesis rows: the 407
predicate caught 94 refusals and missed more ("**Refusal:**" after a [MULTI-CONSENSUS] prefix lost
its asterisks to the strip; "Declined.", "This request is outside the active profile", "I am the
default Hermes assistant", "The active Hermes profile is `default`").

Every rule is BOUNDED (LQ-522 review), because a verdict here fails the run and blanks the card:
  * a heading word ("Refusal", "Declined", "Boundary note", ...) counts only as a heading, followed by
    punctuation, markup or a newline -- never "Declined 12% since the print" or "Refused-tender risk";
  * a first-person opener ("I cannot", "I won't", ...) counts only when its first sentence names what
    is declined (perform / act as / the request / the CIO role / synthesis / a recommendation / a
    profile) -- never "I cannot see a catalyst" or "I cannot ignore the margin compression";
  * "As an AI" counts only as "as an AI[ assistant|model|language model]" plus a comma or period;
  * "the current/active profile is" counts only when it names `default` or `non-trading`.
Real analysis that mentions Hermes as a DATA source ("0.37% Hermes yield"), a risk "profile", or a
lane vote label stays real. tests/test_llm_refusal_guard_20261107.py pins the must-stay-real lines.
"""

from __future__ import annotations

import re

_LEAD_STRIP = "*#_>` \t\r\n\"'-:."

# A refusal heading: the word(s), then punctuation, markup or a newline.
_HEADING = re.compile(
    r"^(refusal|refused|declined|request declined|i decline|hermes review|boundary note"
    r"|boundary clarification|profile boundary)\s*[.:*!\n]"
)
# A first-person opener; it counts only with a declined object in its first sentence.
_FIRST_PERSON = re.compile(
    r"^(i cannot|i can't|i can not|i won't|i will not|i'm unable|i am unable|i'm not able|i am not able"
    r"|i must decline|i have to decline|i decline|sorry, i can|i apologize, but i cannot|i'm sorry, but i can)\b"
)
_DECLINED_OBJECT = re.compile(
    r"\b(perform|adopt|assume|act as|acting as|fulfill|comply|generate|produce"
    r"|(provide|give|issue|make|offer)( an?| any)?( investment| trade| trading| portfolio| buy/sell)?"
    r" (recommendation|advice|verdict|decision|allocation|proposal)s?"
    r"|cio|chief investment|synthesis|persona"
    r"|(default|active|hermes|current|trading|advisory) profile"
    r"|this request|that request|the request|this task|that role|this role)\b"
)
_AS_AN_AI = re.compile(r"^as an ai( language model| assistant| model)?[,.]")
# Openers that only a refusal uses; matched as plain prefixes.
_STRICT_PREFIXES = (
    "i am operating in",
    "i'm operating in",
    "hermes default profile",
    "unable to comply",
    "unable to fulfill",
    "this request is outside",
    "this request violates",
    "i am the default hermes",
    "i am hermes",
)
_REQUEST_OUTSIDE = re.compile(r"^request outside (the |my |this )?(active |default )?(profile|scope|boundar)")
# "The active/current [Hermes] profile is `default`" -- only when it names the default/non-trading profile.
_PROFILE_IS_DEFAULT = re.compile(
    r"\b(active|current)( active)?( hermes)? profile is\W{0,4}(the )?(default|non-trading)\b"
)
# Phrases that name the model's own profile/identity boundary. Searched anywhere in the head.
_REFUSAL_MARKERS = (
    "**refusal**",
    "requires the active profile to switch",
    "default hermes profile",
    "hermes default profile",
    "cannot perform investment synthesis",
    "cannot fulfill this request",
    "can't fulfill this request",
    # LQ-512
    "default hermes assistant",
    "default general-purpose hermes",
    "non-trading profile",
    "trade ai advisory identity",
    "trade ai advisory profile",
    "active hermes profile",
    "hermes profile authority",
    "outside the active profile",
    "active profile's authority",
    "violates my operating boundar",
    "per my operating boundaries",
    "i do not perform investment synthesis",
    "i do not create, approve, or promote",
    "default profile scope",
    "this profile is the default",
)
# "This request requires/asks ... trade recommendation" -- a refusal opener that never names Hermes.
_REQUEST_OPENER = re.compile(
    r"^this (request|query) (requires|asks|requests|attempts)\b[^.]{0,260}"
    r"\b(trade|trading|portfolio|investment|advisory|cio|chief investment)\b"
)
_PREFIX_RE = re.compile(r"^\[multi-consensus\][^.]*\.\s*")
_FIRST_SENTENCE = re.compile(r"(?<=[.!?])\s|\n")
_HEAD_CHARS = 500


def _head(text) -> str:
    head = str(text).lstrip(_LEAD_STRIP).lower()
    if head.startswith("[multi-consensus]"):
        head = _PREFIX_RE.sub("", head, count=1)
    return head[:_HEAD_CHARS]


def is_refusal(text) -> bool:
    """True when `text` is a model refusal rather than analysis.

    Bounded (see the module docstring): a refusal heading, a refusal-only opener, a first-person opener
    whose first sentence names what is declined, a "This request requires ... trade/portfolio ..."
    opener, or a profile/identity-boundary marker in the first 500 chars. Markers are checked on the
    unstripped head too, so "**Refusal**" survives the markdown strip."""
    if not text:
        return False
    raw_head = _head(text)
    head = raw_head.lstrip(_LEAD_STRIP)
    if (
        _HEADING.match(head)
        or _AS_AN_AI.match(head)
        or _REQUEST_OUTSIDE.match(head)
        or head.startswith(_STRICT_PREFIXES)
        or _REQUEST_OPENER.match(head)
    ):
        return True
    if _FIRST_PERSON.match(head) and _DECLINED_OBJECT.search(_FIRST_SENTENCE.split(head, maxsplit=1)[0]):
        return True
    if _PROFILE_IS_DEFAULT.search(raw_head) or _PROFILE_IS_DEFAULT.search(head):
        return True
    return any(m in raw_head or m in head for m in _REFUSAL_MARKERS)


# Fields a reader must blank when the stored narrative is a refusal: everything derived from the
# refusing run. The recommendation was voted from refusal text (LQ-407), so it is not a decision.
REFUSAL_DERIVED_FIELDS = (
    "synthesis_narrative",
    "synthesis_narrative_snip",
    "synthesis_recommendation",
    "synthesis_confidence",
    "grok_recommendation",
    "chatgpt_recommendation",
    "models_agree",
    "synthesis_actionable",
    "conflicts",
    "unresolved",
    "synthesis_conflicts_snip",
    "synthesis_evidence",
    "synthesis_data_i_doubt",
    "dual_consensus_json",
    "decision_safety",
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
