"""A refusal is not research — RESEARCH_REFUSAL_20261107.

Grok (and, less often, DeepSeek) answers a research prompt under the default Hermes profile by
declining it in prose: "I cannot provide the requested market verdict…", "This request conflicts
with the active default Hermes profile…". That answer used to be stored with ``status='sent'``, so
every consumer that reads sent rows treated a refusal as a completed piece of research:

- ``hermes_external_feedback_loop`` scored it for usefulness (measured 2026-11-07: id 69387, a
  refusal, scored 0.55), burning a model call per refusal and feeding noise into the per-lane
  usefulness average that routes work;
- ``hermes_outcome_grader`` parses a direction from every sent recommendation;
- the due-diligence reconciler and the CIO research routes count sent rows as answers.

One classifier, used at write time (:mod:`hermes_external_researcher`) and on the rows already
stored (the backfill's reclassification pass). A new status value — ``refused`` — is what excludes
a refusal: every reader already asks for ``status='sent'`` or
``status IN ('sent','ok','complete','success')``, so nothing else has to change.

Precision over recall: the check is anchored at the START of the text. The corpus (6,313 sent rows,
30 days, read 2026-11-07) shows refusals open by declining; rows that open with a symbol verdict and
only mention the profile limit in passing (e.g. "STIM evidence review only: the active default
Hermes profile cannot create a trade proposal…" followed by real analysis) are research, and are
kept. Losing a real finding is worse than scoring one refusal.
"""
from __future__ import annotations

import re

#: The status a refusal is stored with. ``hermes_external_research.status`` has no CHECK
#: constraint (verified 2026-11-07) and every reader already selects ``sent`` by name.
REFUSED_STATUS = "refused"

#: Why it was refused: the model's identity/profile forbids the task it was asked to do. The one
#: cause in the corpus; kept as a code so a second cause can be added without changing callers.
PROFILE_REFUSAL = "PROFILE_REFUSAL"

#: How much of the text is inspected. The opening sentence is the signal; a profile phrase that
#: appears deep inside an otherwise real analysis is not.
HEAD_CHARS = 240

_MARKUP = re.compile(r"[*_`#\[\]]+")
_WS = re.compile(r"\s+")

#: Anchored openings, from the stored corpus. Each is a sentence that declines the task.
_LEADING = re.compile(
    r"^(?:"
    r"i cannot\b|i can't\b|i won'?t\b|i will not\b|"
    r"i am (?:unable|operating under|hermes in)\b|i'm unable\b|"
    r"refused\b|refusal\b|decline\b|scope refusal\b|"
    r"no[.,]\s+(?:this|the)\s+(?:request|query|ask)\b|"
    r"(?:this|the)\s+request\b|"
    r"the active (?:hermes )?profile\b|default hermes profile\b|"
    r"under the active default\b|in the default hermes profile\b|"
    r"i do not\b"
    r")"
)


def _normalise(text) -> str:
    """Markdown stripped, whitespace collapsed, lower-cased — the shape the patterns expect.

    The typographic apostrophe is folded to ``'``: a model writes "I won’t …" as often as "I won't …",
    and that one character was the difference between a refusal and a piece of research.
    """
    s = str(text or "").replace("’", "'").replace("‘", "'")
    return _WS.sub(" ", _MARKUP.sub("", s)).strip().lower()


def classify_refusal(text) -> tuple[bool, str | None]:
    """``(is_refusal, reason_code)`` for a model answer's prose.

    ``text`` is what the writer stores as the recommendation (or the raw reply when a parse
    produced no recommendation). Unknown or empty text is not a refusal — this function never
    turns a missing answer into a confident one.
    """
    head = _normalise(text)[:HEAD_CHARS]
    if not head:
        return False, None
    if _LEADING.match(head):
        return True, PROFILE_REFUSAL
    return False, None
