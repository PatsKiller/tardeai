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

# --- position-directive verbs (2026-08-29) --------------------------------
#
# A live Grok critique rejected an artifact this matcher had passed as clean:
#
#     "Maintain small tracking position with hard invalidation;
#      do not add until price action confirms forward-looking signals."
#
# It failed on BOTH halves of the main clause pattern. `maintain` is not in
# `_VERB`, and `position` is not one of the bare `_OBJECT` nouns (only
# order/stop/trade/fill/shares/now are). Telling the operator what size to hold
# is an instruction as surely as telling them to sell.
#
# Kept as a SEPARATE pattern rather than widened into _VERB/_OBJECT, because
# adding `position` as a bare object would also pair it with buy/sell/trim and
# balloon the blast radius across the whole corpus. Scoped this way it newly
# catches 46 of 471 stored artifacts (9.8%) — every sampled one a real
# instruction ("do not add" x38, "maintain current position" x15).
#
# Nothing is retro-detached: `research_quality.IMPERATIVE_GATE_EFFECTIVE`
# grandfathers 468 of those 471, per the operator's Decision 1 ("Do NOT
# retro-detach the 466").
#
# `keep` is included alongside the requested `maintain`/`add` because
# "keep the position" is indistinguishable in kind from "maintain the
# position"; leaving it out would ship a guard with a hole the same shape as
# the one being closed. It is one token in _POSITION_VERB if that is unwanted.
_POSITION_VERB = r"(?:maintain|add(?:\s+to)?|keep)"

# Up to three adjectives may sit between verb and noun — the live miss was
# "maintain SMALL TRACKING position", which an adjacent-only pattern skips.
_POSITION_OBJECT = (
    r"(?:(?:\w+\s+){0,3}"
    r"(?:position|stake|holding|exposure|weight|shares?)"
    r")"
)

_POSITION_RE = re.compile(
    rf"(?<!\w)(?P<verb>{_POSITION_VERB})\s+(?P<obj>{_POSITION_OBJECT})(?!\w)",
    re.I,
)

# NOT IMPLEMENTED: "do not add" as a directive.
#
# The live critique also flagged "do not add until price action confirms", and
# a prohibition is arguably an order. A `do not <verb>` rule was written, and
# removed again: it breaks a pinned legacy case,
#
#     "do not sell shares before the ex-date"
#
# which `test_legacy_admitted` requires to pass, because it is ex-dividend
# context rather than an instruction. The two are grammatically identical —
# `do not <verb>` in both — so no rule separates them without reading intent.
#
# Decision 1 governs: ban the instruction, never the word, and do not torch the
# 466. Between losing 38 "do not add" catches and breaking a pinned admitted
# case, the pin wins. The position-directive clause below still catches the
# artifact that started this ("Maintain small tracking position"), which was
# the actual miss.

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

    for m in _POSITION_RE.finditer(text):
        prev = _preceding_word(text, m.start())
        if prev and re.fullmatch(_DISQUALIFIER, prev, re.I):
            continue           # "would maintain", "decided to add", "the position"
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


# ── field-scoped lint ────────────────────────────────────────────────────────
#
# Some fields are instruction-shaped by construction. `desk_implications.notes`
# and `recommendation` exist to tell the operator what the desk thinks should
# happen; free prose in a summary does not.
#
# That distinction is what makes a stricter rule safe here. `do not <verb>`
# cannot be banned globally, because the pinned legacy case
# "do not sell shares before the ex-date" is ex-dividend CONTEXT and must stay
# admitted — and it is grammatically identical to "do not add". No rule
# separates them by shape.
#
# It separates by LOCATION. Measured across 471 stored artifacts: 57 carry a
# `do not <verb>` inside these fields (56 of them "do not add"), and **zero**
# of those also mention ex-date/ex-dividend. The ambiguous case does not occur
# where instructions live.
#
#     "do not add, do not average down, and either exit or demand a verifiable…"
#     "Do not add to position; treat as speculative lottery ticket or exit."
#
# Free-prose entry points (`find_imperative`, `lint_execution_language`) are
# unchanged, so the pin still passes.

INSTRUCTION_FIELDS = (
    ("desk_implications", ("notes", "note")),
    ("recommendation", None),
)

_DIRECTIVE_NEGATION_RE = re.compile(
    r"(?<!\w)do\s+not\s+"
    r"(?:add|buy|sell|trim|flatten|liquidate|maintain|keep|exit|short|cover)"
    r"(?!\w)",
    re.I,
)


def instruction_field_text(artifact: Any) -> dict[str, str]:
    """Pull the instruction-shaped fields out of an artifact. Never raises."""
    out: dict[str, str] = {}
    if not isinstance(artifact, dict):
        return out
    for field, subkeys in INSTRUCTION_FIELDS:
        v = artifact.get(field)
        if v in (None, "", [], {}):
            continue
        if subkeys and isinstance(v, dict):
            for sk in subkeys:
                s = v.get(sk)
                if s:
                    out[f"{field}.{sk}"] = _as_text(s)
        else:
            out[field] = _as_text(v)
    return out


def find_field_directive(artifact: Any) -> Optional[dict[str, str]]:
    """Stricter lint for instruction-shaped fields only.

    Returns {field, match, rule} or None. Applies the ordinary matcher AND the
    `do not <verb>` rule that free prose is exempt from.
    """
    for field, text in instruction_field_text(artifact).items():
        hit = find_imperative(text)
        if hit:
            return {"field": field, "match": hit, "rule": "imperative_clause"}
        m = _DIRECTIVE_NEGATION_RE.search(text)
        if m:
            return {"field": field, "match": m.group(0),
                    "rule": "directive_negation"}
    return None


def describe_field_directive(artifact: Any) -> dict[str, Any]:
    """Receipt shape, so a rejection says which field and which rule."""
    hit = find_field_directive(artifact)
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "instruction_in_field": hit is not None,
        "field": (hit or {}).get("field"),
        "match": (hit or {}).get("match"),
        "rule": (hit or {}).get("rule"),
        "fields_checked": sorted(instruction_field_text(artifact)),
        "note": ("Stricter than free prose: these fields exist to direct the "
                 "operator, so `do not <verb>` counts here and does not "
                 "elsewhere."),
    }
