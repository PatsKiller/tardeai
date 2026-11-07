"""Shared detector for LLM refusals that arrive as successful generations (LQ-20261107-407).

A model that declines the persona/prompt ("I cannot perform investment synthesis...", "**Refusal**",
"I am operating in the default Hermes profile...") returns text, not an error. Writers must store it
as refused (never a narrative, never a consensus vote) and readers must not display it.
"""
from __future__ import annotations

import re

_LEAD_STRIP = "*#_>` \t\r\n\"'-"

_REFUSAL_PREFIXES = (
    "i cannot", "i can't", "i can not", "i won't", "i will not", "i'm unable", "i am unable",
    "i'm not able", "i am not able", "i must decline", "i have to decline", "sorry, i cannot",
    "sorry, i can't", "i apologize, but i cannot", "i'm sorry, but i can",
    "i am operating in", "i'm operating in", "hermes default profile", "hermes review",
    "as an ai", "unable to comply", "unable to fulfill",
)
_REFUSAL_MARKERS = (
    "**refusal**", "requires the active profile to switch", "default hermes profile",
    "hermes default profile active", "cannot perform investment synthesis",
    "cannot fulfill this request", "can't fulfill this request",
)
_PREFIX_RE = re.compile(r"^\[multi-consensus\][^.]*\.\s*")


def is_refusal(text) -> bool:
    """True when `text` is a model refusal rather than analysis. Conservative: a leading
    first-person refusal phrase or a known refusal marker in the first 400 chars."""
    if not text:
        return False
    head = str(text).lstrip(_LEAD_STRIP).lower()
    head = _PREFIX_RE.sub("", head, count=1) if head.startswith("[multi-consensus]") else head
    head = head.lstrip(_LEAD_STRIP)[:400]
    if head.startswith(_REFUSAL_PREFIXES):
        return True
    return any(m in head for m in _REFUSAL_MARKERS)
