"""DeepSeek curates the PRESENTATION of an advisory. It may not touch the facts.

The deterministic renderer produces correct but unreadable output: a wall of
sections, detector strings, and repeated blocks. Curation is a legitimate use of
a model — arranging what is already true — and an illegitimate one is letting it
restate the book.

So the contract is narrow and enforced in code, not in the prompt:

  * every numeric token in the output must already appear in the input.
    A model that invents, rounds, or "corrects" a figure is REJECTED.
  * the plan_id must survive, or the operator cannot act on the message.
  * no growth: curation compresses; a longer result means it added something.

Any violation, any exception, any empty response returns the DETERMINISTIC
message unchanged. Fail-open is right here and fail-closed is wrong: the input
is already correct and already sent-worthy, so the worst acceptable outcome is
the ugly version, never no version and never an invented one.

OFF unless CIO_ADVISORY_CURATOR=1. READ_ONLY_ADVISORY. MBI=0.
"""
from __future__ import annotations

import os
import re
from typing import Any, Optional

SCHEMA = "AdvisoryCuration@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
LANE = "agent_narrative"          # existing FAST lane; no new governance invented
MODEL = "deepseek-v4-flash"

# Digit runs, so 630,784.82 / 42.1pct / desk@v4 / 2026-08-30 all normalise.
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Words that assert a RELATION between facts rather than restating one. The
# first live curation produced "current weight exceeds max name threshold" —
# true, derived only from numbers already present, and still analysis the
# prompt forbids. A prompt rule is a request; this is a check. If the input
# never drew the comparison, the output may not draw it either.
_INFERENCE_MARKERS = (
    "exceeds", "exceeded", "breaches", "breach", "violates", "above the",
    "below the", "therefore", "implies", "implying", "suggests that",
    "indicates that", "means that", "as a result", "consequently",
    "which is higher", "which is lower", "outside the", "within the limit",
)

SYSTEM = (
    "You are the desk editor for a read-only investment advisory that is read "
    "on a phone, at a glance, by the operator who owns the book. You typeset "
    "and compress. You never analyse.\n"
    "\n"
    "HARD RULES — breaking any one voids your entire output:\n"
    "1. Copy every number, ticker, date and percentage EXACTLY as given. Never "
    "round, recompute, unit-convert or 'correct' one. 630,784.82 stays "
    "630,784.82; it never becomes 630,785 or $630.8k.\n"
    "2. Never state a relationship the input did not state. If the input says "
    "'weight 42.1%' and 'max_name 12.0%', you may print both — you may NOT "
    "write 'weight exceeds the max', 'breaches', 'therefore', or any other "
    "comparison. That is the analyst's job and it is not yours.\n"
    "3. Add no opinion, no recommendation, no caveat of your own.\n"
    "4. Reproduce the plan id, any links, and the READ_ONLY marker verbatim.\n"
    "\n"
    "SHAPE — follow this order:\n"
    "  1) One line: the decision facing the operator and the option the desk "
    "already recommends, in plain words.\n"
    "  2) 'Why' — at most four terse bullets of the evidence given.\n"
    "  3) 'Options' — one line each, only if the input lists them.\n"
    "  4) 'Risks' — one line each.\n"
    "  5) The footer: plan id, revisit date, links, READ_ONLY marker.\n"
    "\n"
    "STYLE: no marketing voice, no hedging, no restating the same fact in two "
    "sections. Drop machine noise (raw key=value dumps, null fields, internal "
    "flag names) once its meaning is carried in plain words. Target roughly "
    "half the input length. Shorter is better while no fact is lost.\n"
    "\n"
    "Return only the reformatted message."
)


def _user_prompt(text: str, plan: Any = None) -> str:
    """What the model sees: the message, plus named context for ORDERING only."""
    ctx = plan_context(plan)
    head = (
        "Reformat the advisory below for the operator's phone.\n"
        "Every fact must already appear in it. Draw no comparisons.\n"
    )
    if ctx:
        return f"{head}\n{ctx}\n\nADVISORY:\n{text}"
    return f"{head}\nADVISORY:\n{text}"


def _numbers(text: str) -> set[str]:
    return {m.group(0).replace(",", "").rstrip(".") for m in _NUM_RE.finditer(text or "")}


def enabled() -> bool:
    return os.environ.get("CIO_ADVISORY_CURATOR", "").strip().lower() in (
        "1", "true", "yes", "on")


def validate(original: str, curated: str, *, plan_id: str | None = None) -> Optional[str]:
    """Return a rejection reason, or None when the curation is safe to send."""
    if not curated or not curated.strip():
        return "empty"
    invented = _numbers(curated) - _numbers(original)
    if invented:
        return "invented_numbers:" + ",".join(sorted(invented)[:5])
    if plan_id and plan_id not in curated:
        return "dropped_plan_id"
    # The authority marker is the whole basis on which the operator reads this
    # as advice and not instruction. The first live curation quietly dropped it.
    if "READ_ONLY" in (original or "") and "READ_ONLY" not in curated:
        return "dropped_authority_marker"
    # Semantic violations are reported before the length one: "it reasoned"
    # tells the operator something "it grew" does not.
    lo_o, lo_c = (original or "").lower(), curated.lower()
    added = [m for m in _INFERENCE_MARKERS if m in lo_c and m not in lo_o]
    if added:
        return "added_inference:" + ",".join(added[:3])
    if len(curated) > len(original):
        return "grew"
    return None


def plan_context(plan: Any) -> str:
    """The facts the model must lead with, named rather than buried in prose.

    Curating flat text alone made the model conservative — the first live run
    returned the input nearly unchanged, because it could not tell which line
    was the decision. Naming the decision, the subject and the posture is what
    lets it put the answer first without inventing one.
    """
    if not isinstance(plan, dict):
        return ""
    bits = []
    def _add(label, val):
        if val not in (None, "", [], {}):
            bits.append(f"{label}: {val}")
    _add("Situation", str(plan.get("situation_type") or "").replace("_", " "))
    _add("Subject", ", ".join(plan.get("symbols") or []))
    _add("Desk stance", plan.get("thesis_stance") or plan.get("stance"))
    _add("Recommended option", plan.get("option_id") or plan.get("recommendation_option"))
    _add("Actionability", plan.get("actionability"))
    _add("Revisit", plan.get("revisit_at"))
    if not bits:
        return ""
    return ("CONTEXT (already true — use to decide ordering only, never to add "
            "claims):\n" + "\n".join("- " + b for b in bits))


def curate(
    text: str,
    *,
    plan_id: str | None = None,
    plan: Any = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Return {"text": ..., "curated": bool, "reason": ...}. Never raises."""
    out = {"schema": SCHEMA, "authority": AUTHORITY, "text": text,
           "curated": False, "reason": None, "model": MODEL}
    if not enabled():
        out["reason"] = "disabled"
        return out
    if not text or not text.strip():
        out["reason"] = "empty_input"
        return out
    try:
        try:
            from scripts.lib.deepseek_client import chat
        except Exception:
            from lib.deepseek_client import chat          # type: ignore
        resp = chat(
            model_id=MODEL,
            prompt=text,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": _user_prompt(text, plan)}],
            max_tokens=1400,
            temperature=0.2,
            timeout=timeout,
            source_service="cio",
            source_process="cio_advisory_curator",
            source_lane=LANE,
            agent="maria",
        )
        content = ""
        for attr in ("content", "text", "message"):
            v = getattr(resp, attr, None)
            if isinstance(v, str) and v.strip():
                content = v
                break
        if not content and isinstance(resp, dict):
            content = str(resp.get("content") or "")
        reason = validate(text, content, plan_id=plan_id)
        if reason:
            out["reason"] = "rejected:" + reason
            return out
        out["text"] = content.strip()
        out["curated"] = True
        out["reason"] = "ok"
        return out
    except Exception as exc:                                    # noqa: BLE001
        out["reason"] = "error:" + exc.__class__.__name__
        return out
