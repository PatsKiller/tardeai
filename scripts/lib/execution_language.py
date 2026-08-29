"""One imperative matcher, shared by every execution-language gate.

Two gates used to enforce "research may not instruct" with **different**
vocabularies — `hermes_research_schema.EXEC_LINT` and
`research_quality.critique` — so each covered the other's blind spot by
accident and `execute the buy` passed both. Expanding two substring lists is
what let that happen; this module exists so there is one definition.

**The rule is grammatical, not lexical.** The banned thing is an *imperative,
operator-directed clause*, not the words `trim` / `sell` / `half`. Analysis
uses those words constantly and must keep attaching:

    rejected                       admitted
    ------------------------------ ------------------------------------------
    trim the position              a trim would reduce concentration
    sell half                      sold half in 2021
    execute the buy                after the 2018 trim
    place an order                 management will execute its buyback plan
    buy now                        the order book was thin

So a match requires a verb in **base form** followed by a size-or-object, and
is disqualified when the verb is preceded by a determiner (making it a noun),
a modal (making it conditional), or an infinitive/past-tense marker (making it
narration).

Structured operator recommendations (`option_id` = `trim_if`,
`hold_with_thesis`, …) are **not** this gate. They are a product surface with
its own governance; running research rules over them would reject the
operator's own vocabulary.

READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "ExecutionLanguageMatch@v1"

# Base-form verbs only. Past tense (sold/trimmed/placed/executed) is narration
# and is excluded by construction — it simply is not in this set.
_VERB = r"(?:buy|sell|trim|flatten|liquidate|submit|place|execute|exit|short|cover)"

# What makes the clause operator-directed: a size, a position, or an order object.
_OBJECT = (
    r"(?:"
    r"half|all|everything|"
    r"(?:the|this|that|your|our|my)\s+(?:position|stake|holding|shares?|lot|book)|"
    r"(?:some|part|most|any)\s+of\s+(?:the|this|your)\s+(?:position|stake|shares?)|"
    r"(?:a|an|the)\s+(?:order|stop|trade|buy|sell|fill)|"
    # bare objects: "execute trade" / "place stop" were caught before the
    # rewrite and must stay caught — an article is optional, not required.
    r"order|stop|trade|fill|shares?|now|"
    r"\d+\s*(?:%|percent|shares?)"
    r")"
)

# Words immediately before the verb that mean it is NOT an instruction:
#   a/an/the  -> noun      ("a trim", "the sell")
#   modals    -> hypothesis ("would trim", "could sell")
#   to        -> infinitive ("decided to trim", "plan to sell")
#   not/never -> negation   ("do not sell")
_DISQUALIFIER = (
    r"(?:a|an|the|any|no|"
    r"would|could|should|may|might|will|can|must|shall|"
    r"to|not|never|"
    r"of|for|after|before|since|when|if|whether)"
)

_CLAUSE_RE = re.compile(
    rf"(?<!\w)(?P<verb>{_VERB})\s+(?P<obj>{_OBJECT})(?!\w)",
    re.I,
)

# Phrases that are unambiguously execution instructions regardless of object.
_ALWAYS_RE = re.compile(
    r"(?<!\w)("
    r"market\s+order|limit\s+order|force\s+fill|enter\s+(?:long|short)|"
    r"(?:buy|sell)\s+now|flatten(?:\s+(?:it|out))?|liquidate"
    r")(?!\w)",
    re.I,
)


def _preceding_word(text: str, start: int) -> str:
    before = text[:start].rstrip()
    if not before:
        return ""
    m = re.search(r"([A-Za-z']+)$", before)
    return m.group(1).lower() if m else ""


def _as_text(blob: Any) -> str:
    if isinstance(blob, str):
        return blob
    try:
        return json.dumps(blob, default=str)
    except Exception:
        return str(blob)


def find_imperative(blob: Any) -> Optional[str]:
    """Return the offending clause, or None. One definition for every gate."""
    text = _as_text(blob)
    if not text:
        return None

    for m in _CLAUSE_RE.finditer(text):
        prev = _preceding_word(text, m.start())
        if prev and re.fullmatch(_DISQUALIFIER, prev, re.I):
            continue           # noun, conditional, infinitive or negation
        return m.group(0)

    m = _ALWAYS_RE.search(text)
    return m.group(0) if m else None


def is_imperative(blob: Any) -> bool:
    return find_imperative(blob) is not None


def describe(blob: Any) -> dict[str, Any]:
    """Match plus why, for a receipt that explains itself."""
    hit = find_imperative(blob)
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "imperative": hit is not None,
        "match": hit,
        "rule": "base-form verb + size/object, not preceded by determiner, modal, infinitive or negation",
        "not_this_gate": "operator product option_id recommendations",
    }
