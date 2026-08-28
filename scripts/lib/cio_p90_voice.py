"""P9.0 remaining voice labels.

T = template / f-string. D = derived filter or count. A = judgment.

Slice 10 stamps the leftover unlabeled voice fields. It does not rewrite
meaning. CASE_SUMMARY stays A-context (already labeled in 2B/2C).

READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

from typing import Any

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0

VOICE_T = "T"
VOICE_D = "D"
VOICE_A = "A"

NOTHING_REQUIRES_ACTION = "Nothing requires action today."
NOTHING_REQUIRES_ACTION_STAMPED = "[D] Nothing requires action today."

EXEC_SUMMARY_NOTE = (
    "the field name asserts synthesis; the value is an f-string over counts "
    "and filters (P9.0 #3)"
)
ACTION_NOW_NOTE = (
    "filter on urgency==NOW; includes urgent non-actions such as AVOID. "
    "Not DO_NOW. (P9.0 #6)"
)
NOTHING_NOTE = (
    "emitted when action_book.DO_NOW is empty; derived, not a considered "
    "all-clear judgment (P9.0 #2)"
)


def already_stamped(text: str) -> bool:
    t = str(text or "").lstrip()
    return t.startswith("[T] ") or t.startswith("[D] ") or t.startswith("[A] ")


def stamp_text(text: str, klass: str) -> str:
    """Prefix [T]/[D]/[A] once. Does not change the sentence."""
    t = str(text or "")
    if not t:
        return t
    if already_stamped(t):
        return t
    return f"[{klass}] {t}"


def stamp_nothing_requires_action(sentence: str | None = None) -> str:
    s = str(sentence or NOTHING_REQUIRES_ACTION).strip()
    if s in {NOTHING_REQUIRES_ACTION, NOTHING_REQUIRES_ACTION_STAMPED}:
        return NOTHING_REQUIRES_ACTION_STAMPED
    if NOTHING_REQUIRES_ACTION in s and "[D] Nothing requires action today." not in s:
        return s.replace(NOTHING_REQUIRES_ACTION, NOTHING_REQUIRES_ACTION_STAMPED, 1)
    return s


def voice_meta(klass: str, *, note: str) -> dict[str, Any]:
    return {
        "class": klass,
        "note": note,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
    }


def apply_operator_voice(product: dict[str, Any]) -> dict[str, Any]:
    """Additive T/D stamps on operator product. CASE_SUMMARY remains A."""
    out = dict(product or {})
    exec_s = str(out.get("executive_summary") or "")
    if exec_s:
        exec_s = stamp_nothing_requires_action(exec_s)
        out["executive_summary"] = stamp_text(exec_s, VOICE_T)
    out["executive_summary_class"] = VOICE_T
    out["executive_summary_voice"] = voice_meta(VOICE_T, note=EXEC_SUMMARY_NOTE)
    out["action_now_class"] = VOICE_D
    out["action_now_voice"] = voice_meta(VOICE_D, note=ACTION_NOW_NOTE)
    out["nothing_requires_action_class"] = VOICE_D
    out["nothing_requires_action_voice"] = voice_meta(VOICE_D, note=NOTHING_NOTE)
    cs = out.get("case_summaries")
    if isinstance(cs, dict):
        cs = dict(cs)
        cs.setdefault("class", VOICE_A)
        cs.setdefault("banner", "A-context · NON_AUTHORITATIVE · does not change action")
        out["case_summaries"] = cs
        if "research_cases" in out:
            out["research_cases"] = cs
    return out
